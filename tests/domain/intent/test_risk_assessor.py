# tests/domain/intent/test_risk_assessor.py
"""
Comprehensive tests for domain/intent/risk_assessor.py.
Covers RiskCategory, RiskLevel, RiskAssessmentStatus (including helper methods),
RiskFactor, RiskAssessment, RiskAssessor (including private assessment methods),
and the singleton accessor.
Uses fixtures, parameterized tests, and strong assertions.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from domain.intent.risk_assessor import (
    RiskAssessment,
    RiskAssessmentStatus,
    RiskAssessor,
    RiskCategory,
    RiskFactor,
    RiskLevel,
    get_risk_assessor,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_intent_data():
    """Sample intent data for testing risk assessment."""
    return {
        "amount": Decimal("500000000"),
        "is_international": True,
        "payment_method": "BANK_TRANSFER",
        "is_shell_company": False,
        "transaction_type": "CROSS_BORDER",
        "source_document_ref": "PO-001",
        "is_intercompany": False,
        "is_related_party": False,
        "requires_regulatory_approval": False,
        "customer_id": "CUST-001",
        "customer_credit_limit": Decimal("1000000000"),
        "customer_current_balance": Decimal("300000000"),
        "has_overdue_payments": False,
        "customer_payment_rating": "GOOD",
        "tax_avoidance_indicator": False,
        "tax_id": "123456789012345",
        "tax_jurisdiction": "IDN",
        "is_rush": False,
        "is_duplicate_suspected": False,
        "unusual_pattern": False,
        "beneficiary_mismatch": False,
    }


@pytest.fixture
def sample_intent():
    """Mock immutable intent record."""
    intent = MagicMock()
    intent.intent_id = uuid4()
    intent.intent_type = MagicMock()
    intent.intent_type.name = "CREATE_INVOICE"
    intent.data = {}
    return intent


@pytest.fixture
def sample_risk_factor():
    """Sample risk factor for testing."""
    return RiskFactor(
        category=RiskCategory.AML,
        description="Large transaction amount (>100M)",
        score=30.0,
        weight=1.5,
        version=1,
    )


@pytest.fixture
def sample_risk_assessment():
    """Sample risk assessment for testing."""
    return RiskAssessment(
        assessment_id=uuid4(),
        intent_id=uuid4(),
        assessed_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
        assessed_by="test_user",
        overall_risk=RiskLevel.MEDIUM,
        risk_score=45.5,
        factors=[],
        recommendations=["Standard review required"],
        status=RiskAssessmentStatus.ASSESSED,
        requires_approval=False,
        requires_dual_control=False,
        notes="Test assessment",
        version=1,
    )


# ============================================================================
# Enum Tests (including helper methods)
# ============================================================================

class TestRiskCategory:
    def test_members(self):
        assert RiskCategory.AML.value == "aml"
        assert RiskCategory.FRAUD.value == "fraud"
        assert RiskCategory.COMPLIANCE.value == "compliance"
        assert RiskCategory.CREDIT.value == "credit"
        assert RiskCategory.OPERATIONAL.value == "operational"
        assert RiskCategory.REPUTATIONAL.value == "reputational"
        assert RiskCategory.TAX.value == "tax"

    def test_from_string(self):
        assert RiskCategory.from_string("aml") == RiskCategory.AML
        assert RiskCategory.from_string("FRAUD") == RiskCategory.FRAUD
        assert RiskCategory.from_string("credit") == RiskCategory.CREDIT
        assert RiskCategory.from_string("CREDIT") == RiskCategory.CREDIT

    def test_from_string_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown RiskCategory"):
            RiskCategory.from_string("unknown")


class TestRiskLevel:
    def test_members(self):
        assert RiskLevel.LOW.value == 1
        assert RiskLevel.MEDIUM.value == 2
        assert RiskLevel.HIGH.value == 3
        assert RiskLevel.CRITICAL.value == 4

    def test_from_int(self):
        assert RiskLevel.from_int(1) == RiskLevel.LOW
        assert RiskLevel.from_int(2) == RiskLevel.MEDIUM
        assert RiskLevel.from_int(3) == RiskLevel.HIGH
        assert RiskLevel.from_int(4) == RiskLevel.CRITICAL
        assert RiskLevel.from_int(5) == RiskLevel.LOW  # Default fallback

    def test_requires_approval(self):
        assert RiskLevel.LOW.requires_approval() is False
        assert RiskLevel.MEDIUM.requires_approval() is False
        assert RiskLevel.HIGH.requires_approval() is True
        assert RiskLevel.CRITICAL.requires_approval() is True

    def test_requires_dual_control(self):
        assert RiskLevel.LOW.requires_dual_control() is False
        assert RiskLevel.MEDIUM.requires_dual_control() is False
        assert RiskLevel.HIGH.requires_dual_control() is False
        assert RiskLevel.CRITICAL.requires_dual_control() is True


class TestRiskAssessmentStatus:
    def test_members(self):
        # Values are auto() so we test existence
        assert RiskAssessmentStatus.PENDING is not None
        assert RiskAssessmentStatus.ASSESSED is not None
        assert RiskAssessmentStatus.NEEDS_REVIEW is not None
        assert RiskAssessmentStatus.ESCALATED is not None
        assert RiskAssessmentStatus.APPROVED is not None
        assert RiskAssessmentStatus.REJECTED is not None

    def test_from_string(self):
        assert RiskAssessmentStatus.from_string("PENDING") == RiskAssessmentStatus.PENDING
        assert RiskAssessmentStatus.from_string("assessed") == RiskAssessmentStatus.ASSESSED
        assert RiskAssessmentStatus.from_string("NEEDS_REVIEW") == RiskAssessmentStatus.NEEDS_REVIEW

    def test_from_string_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown RiskAssessmentStatus"):
            RiskAssessmentStatus.from_string("unknown")


# ============================================================================
# RiskFactor Tests
# ============================================================================

class TestRiskFactor:
    def test_construction(self):
        factor = RiskFactor(
            category=RiskCategory.AML,
            description="Test factor",
            score=50.0,
            weight=1.5,
            version=1,
        )
        assert factor.category == RiskCategory.AML
        assert factor.description == "Test factor"
        assert factor.score == 50.0
        assert factor.weight == 1.5
        assert factor.version == 1

    def test_validate_invalid_category(self):
        with pytest.raises(ValueError, match="category must be RiskCategory"):
            RiskFactor(
                category="AML",  # type: ignore
                description="test",
                score=50.0,
                weight=1.0,
            )

    def test_validate_empty_description(self):
        with pytest.raises(ValueError, match="description cannot be empty"):
            RiskFactor(
                category=RiskCategory.AML,
                description="",
                score=50.0,
                weight=1.0,
            )

    def test_validate_score_too_low(self):
        with pytest.raises(ValueError, match="score must be between 0 and 100"):
            RiskFactor(
                category=RiskCategory.AML,
                description="test",
                score=-1.0,
                weight=1.0,
            )

    def test_validate_score_too_high(self):
        with pytest.raises(ValueError, match="score must be between 0 and 100"):
            RiskFactor(
                category=RiskCategory.AML,
                description="test",
                score=101.0,
                weight=1.0,
            )

    def test_validate_zero_weight(self):
        with pytest.raises(ValueError, match="weight must be positive"):
            RiskFactor(
                category=RiskCategory.AML,
                description="test",
                score=50.0,
                weight=0.0,
            )

    def test_validate_negative_weight(self):
        with pytest.raises(ValueError, match="weight must be positive"):
            RiskFactor(
                category=RiskCategory.AML,
                description="test",
                score=50.0,
                weight=-1.0,
            )

    def test_validate_version_zero(self):
        with pytest.raises(ValueError, match="version must be >= 1"):
            RiskFactor(
                category=RiskCategory.AML,
                description="test",
                score=50.0,
                weight=1.0,
                version=0,
            )

    def test_create(self, sample_risk_factor):
        result = sample_risk_factor.create("creator")
        assert result is sample_risk_factor
        assert len(sample_risk_factor._audit_trail) >= 2  # __post_init__ + create

    def test_update(self, sample_risk_factor):
        updated = sample_risk_factor.update("updater", description="Updated desc", score=75.0)
        assert updated.description == "Updated desc"
        assert updated.score == 75.0
        assert updated.version == sample_risk_factor.version + 1
        assert len(updated._audit_trail) >= 3

    def test_update_does_not_change_version_field(self):
        factor = RiskFactor(
            category=RiskCategory.AML,
            description="test",
            score=50.0,
            weight=1.0,
            version=5,
        )
        updated = factor.update("updater", version=999)
        assert updated.version == 6  # Incremented, not set to 999

    def test_delete(self, sample_risk_factor):
        deleted = sample_risk_factor.delete("deleter", "reason")
        assert deleted is sample_risk_factor
        assert len(sample_risk_factor._audit_trail) >= 2

    def test_restore(self, sample_risk_factor):
        restored = sample_risk_factor.restore("restorer")
        assert restored is sample_risk_factor

    def test_activate(self, sample_risk_factor):
        activated = sample_risk_factor.activate("activator")
        assert activated is sample_risk_factor

    def test_deactivate(self, sample_risk_factor):
        deactivated = sample_risk_factor.deactivate("deactivator", "reason")
        assert deactivated is sample_risk_factor

    def test_lock(self, sample_risk_factor):
        locked = sample_risk_factor.lock("locker", "reason")
        assert locked is sample_risk_factor

    def test_unlock(self, sample_risk_factor):
        unlocked = sample_risk_factor.unlock("unlocker")
        assert unlocked is sample_risk_factor

    def test_validate_returns_valid(self, sample_risk_factor):
        result = sample_risk_factor.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert result["version"] == sample_risk_factor.version

    def test_validate_returns_errors(self, sample_risk_factor):
        # Force invalid state
        sample_risk_factor.score = -10
        result = sample_risk_factor.validate()
        assert result["is_valid"] is False
        assert "score must be between 0 and 100" in result["errors"]

    def test_to_dict(self, sample_risk_factor):
        d = sample_risk_factor.to_dict()
        assert d["category"] == "aml"
        assert d["description"] == "Large transaction amount (>100M)"
        assert d["score"] == 30.0
        assert d["weight"] == 1.5
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "category": "aml",
            "description": "Test from dict",
            "score": 75.5,
            "weight": 2.0,
            "version": 3,
        }
        factor = RiskFactor.from_dict(data)
        assert factor.category == RiskCategory.AML
        assert factor.description == "Test from dict"
        assert factor.score == 75.5
        assert factor.weight == 2.0
        assert factor.version == 3

    def test_from_dict_defaults(self):
        data = {
            "category": "fraud",
            "description": "Test",
            "score": 50.0,
        }
        factor = RiskFactor.from_dict(data)
        assert factor.weight == 1.0
        assert factor.version == 1

    def test_clone(self, sample_risk_factor):
        cloned = sample_risk_factor.clone()
        assert cloned is not sample_risk_factor
        assert cloned.category == sample_risk_factor.category
        assert cloned.description == sample_risk_factor.description
        assert cloned.score == sample_risk_factor.score
        assert cloned.weight == sample_risk_factor.weight
        assert cloned.version == 1

    def test_snapshot(self, sample_risk_factor):
        snap = sample_risk_factor.snapshot()
        assert snap["version"] == sample_risk_factor.version
        assert snap["category"] == sample_risk_factor.category.value
        assert snap["score"] == sample_risk_factor.score
        assert "timestamp" in snap

    def test_get_version(self, sample_risk_factor):
        assert sample_risk_factor.get_version() == 1

    def test_audit_trail(self, sample_risk_factor):
        trail = sample_risk_factor.audit_trail()
        assert len(trail) >= 1
        sample_risk_factor.touch("toucher")
        trail2 = sample_risk_factor.audit_trail()
        assert len(trail2) >= 2
        assert trail2[-1]["action"] == "TOUCH"

    def test_touch(self, sample_risk_factor):
        touched = sample_risk_factor.touch("toucher")
        assert touched.version == sample_risk_factor.version + 1
        assert len(touched._audit_trail) >= 2

    def test_weighted_score(self, sample_risk_factor):
        assert sample_risk_factor.weighted_score() == 30.0 * 1.5  # 45.0


# ============================================================================
# RiskAssessment Tests
# ============================================================================

class TestRiskAssessment:
    def test_construction(self):
        assessment = RiskAssessment(
            assessment_id=uuid4(),
            intent_id=uuid4(),
            assessed_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
            assessed_by="test_user",
            overall_risk=RiskLevel.HIGH,
            risk_score=75.5,
            factors=[],
            recommendations=["Recommendation 1"],
            status=RiskAssessmentStatus.ASSESSED,
            requires_approval=True,
            requires_dual_control=False,
            notes="Test",
            version=1,
        )
        assert assessment.overall_risk == RiskLevel.HIGH
        assert assessment.risk_score == 75.5
        assert assessment.status == RiskAssessmentStatus.ASSESSED
        assert assessment.requires_approval is True
        assert assessment.cryptographic_hash != ""

    def test_validate_invalid_assessment_id(self):
        with pytest.raises(ValueError, match="assessment_id must be UUID"):
            RiskAssessment(
                assessment_id="not-uuid",  # type: ignore
                intent_id=uuid4(),
                assessed_at=datetime.now(UTC),
                assessed_by="test",
                overall_risk=RiskLevel.LOW,
                risk_score=10.0,
                factors=[],
                recommendations=[],
                status=RiskAssessmentStatus.PENDING,
                requires_approval=False,
                requires_dual_control=False,
            )

    def test_validate_invalid_intent_id(self):
        with pytest.raises(ValueError, match="intent_id must be UUID"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id="not-uuid",  # type: ignore
                assessed_at=datetime.now(UTC),
                assessed_by="test",
                overall_risk=RiskLevel.LOW,
                risk_score=10.0,
                factors=[],
                recommendations=[],
                status=RiskAssessmentStatus.PENDING,
                requires_approval=False,
                requires_dual_control=False,
            )

    def test_validate_empty_assessed_by(self):
        with pytest.raises(ValueError, match="assessed_by cannot be empty"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id=uuid4(),
                assessed_at=datetime.now(UTC),
                assessed_by="",
                overall_risk=RiskLevel.LOW,
                risk_score=10.0,
                factors=[],
                recommendations=[],
                status=RiskAssessmentStatus.PENDING,
                requires_approval=False,
                requires_dual_control=False,
            )

    def test_validate_invalid_overall_risk(self):
        with pytest.raises(ValueError, match="overall_risk must be RiskLevel"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id=uuid4(),
                assessed_at=datetime.now(UTC),
                assessed_by="test",
                overall_risk="LOW",  # type: ignore
                risk_score=10.0,
                factors=[],
                recommendations=[],
                status=RiskAssessmentStatus.PENDING,
                requires_approval=False,
                requires_dual_control=False,
            )

    def test_validate_risk_score_out_of_range_low(self):
        with pytest.raises(ValueError, match="risk_score must be between 0 and 100"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id=uuid4(),
                assessed_at=datetime.now(UTC),
                assessed_by="test",
                overall_risk=RiskLevel.LOW,
                risk_score=-1.0,
                factors=[],
                recommendations=[],
                status=RiskAssessmentStatus.PENDING,
                requires_approval=False,
                requires_dual_control=False,
            )

    def test_validate_risk_score_out_of_range_high(self):
        with pytest.raises(ValueError, match="risk_score must be between 0 and 100"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id=uuid4(),
                assessed_at=datetime.now(UTC),
                assessed_by="test",
                overall_risk=RiskLevel.LOW,
                risk_score=101.0,
                factors=[],
                recommendations=[],
                status=RiskAssessmentStatus.PENDING,
                requires_approval=False,
                requires_dual_control=False,
            )

    def test_validate_invalid_factors_type(self):
        with pytest.raises(ValueError, match="factors must be list"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id=uuid4(),
                assessed_at=datetime.now(UTC),
                assessed_by="test",
                overall_risk=RiskLevel.LOW,
                risk_score=10.0,
                factors="not-list",  # type: ignore
                recommendations=[],
                status=RiskAssessmentStatus.PENDING,
                requires_approval=False,
                requires_dual_control=False,
            )

    def test_validate_invalid_recommendations_type(self):
        with pytest.raises(ValueError, match="recommendations must be list"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id=uuid4(),
                assessed_at=datetime.now(UTC),
                assessed_by="test",
                overall_risk=RiskLevel.LOW,
                risk_score=10.0,
                factors=[],
                recommendations="not-list",  # type: ignore
                status=RiskAssessmentStatus.PENDING,
                requires_approval=False,
                requires_dual_control=False,
            )

    def test_validate_invalid_status(self):
        with pytest.raises(ValueError, match="status must be RiskAssessmentStatus"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id=uuid4(),
                assessed_at=datetime.now(UTC),
                assessed_by="test",
                overall_risk=RiskLevel.LOW,
                risk_score=10.0,
                factors=[],
                recommendations=[],
                status="PENDING",  # type: ignore
                requires_approval=False,
                requires_dual_control=False,
            )

    def test_validate_invalid_requires_approval(self):
        with pytest.raises(ValueError, match="requires_approval must be bool"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id=uuid4(),
                assessed_at=datetime.now(UTC),
                assessed_by="test",
                overall_risk=RiskLevel.LOW,
                risk_score=10.0,
                factors=[],
                recommendations=[],
                status=RiskAssessmentStatus.PENDING,
                requires_approval="True",  # type: ignore
                requires_dual_control=False,
            )

    def test_validate_invalid_requires_dual_control(self):
        with pytest.raises(ValueError, match="requires_dual_control must be bool"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id=uuid4(),
                assessed_at=datetime.now(UTC),
                assessed_by="test",
                overall_risk=RiskLevel.LOW,
                risk_score=10.0,
                factors=[],
                recommendations=[],
                status=RiskAssessmentStatus.PENDING,
                requires_approval=False,
                requires_dual_control="False",  # type: ignore
            )

    def test_validate_version_zero(self):
        with pytest.raises(ValueError, match="version must be >= 1"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id=uuid4(),
                assessed_at=datetime.now(UTC),
                assessed_by="test",
                overall_risk=RiskLevel.LOW,
                risk_score=10.0,
                factors=[],
                recommendations=[],
                status=RiskAssessmentStatus.PENDING,
                requires_approval=False,
                requires_dual_control=False,
                version=0,
            )

    def test_compute_hash(self, sample_risk_assessment):
        hash_val = sample_risk_assessment.compute_hash()
        assert len(hash_val) == 64
        # Same data should produce same hash
        hash2 = sample_risk_assessment.compute_hash()
        assert hash_val == hash2

    def test_create(self, sample_risk_assessment):
        result = sample_risk_assessment.create("creator")
        assert result is sample_risk_assessment

    def test_update_status(self, sample_risk_assessment):
        updated = sample_risk_assessment.update(
            "updater",
            status=RiskAssessmentStatus.APPROVED,
            notes="Approved by manager"
        )
        assert updated.status == RiskAssessmentStatus.APPROVED
        assert updated.notes == "Approved by manager"
        assert updated.version == sample_risk_assessment.version + 1

    def test_update_only_status_and_notes(self):
        assessment = RiskAssessment(
            assessment_id=uuid4(),
            intent_id=uuid4(),
            assessed_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
            assessed_by="test",
            overall_risk=RiskLevel.MEDIUM,
            risk_score=45.0,
            factors=[],
            recommendations=["Old rec"],
            status=RiskAssessmentStatus.ASSESSED,
            requires_approval=False,
            requires_dual_control=False,
            notes="Old note",
            version=1,
        )
        updated = assessment.update(
            "updater",
            status=RiskAssessmentStatus.APPROVED,
            notes="New note",
            overall_risk=RiskLevel.HIGH,  # Should be ignored
            risk_score=99.0,  # Should be ignored
        )
        assert updated.status == RiskAssessmentStatus.APPROVED
        assert updated.notes == "New note"
        assert updated.overall_risk == RiskLevel.MEDIUM  # Unchanged
        assert updated.risk_score == 45.0  # Unchanged

    def test_delete_raises(self, sample_risk_assessment):
        with pytest.raises(AttributeError, match="cannot be deleted"):
            sample_risk_assessment.delete("deleter")

    def test_restore_raises(self, sample_risk_assessment):
        with pytest.raises(AttributeError, match="cannot be restored"):
            sample_risk_assessment.restore("restorer")

    def test_activate_from_pending(self, sample_risk_assessment):
        sample_risk_assessment.status = RiskAssessmentStatus.PENDING
        activated = sample_risk_assessment.activate("activator")
        assert activated.status == RiskAssessmentStatus.ASSESSED
        assert activated.version == sample_risk_assessment.version + 1

    def test_activate_from_assessed(self, sample_risk_assessment):
        sample_risk_assessment.status = RiskAssessmentStatus.ASSESSED
        activated = sample_risk_assessment.activate("activator")
        assert activated is sample_risk_assessment  # No change

    def test_deactivate_from_assessed(self, sample_risk_assessment):
        sample_risk_assessment.status = RiskAssessmentStatus.ASSESSED
        deactivated = sample_risk_assessment.deactivate("deactivator", "reason")
        assert deactivated.status == RiskAssessmentStatus.NEEDS_REVIEW
        assert deactivated.version == sample_risk_assessment.version + 1

    def test_deactivate_from_pending(self, sample_risk_assessment):
        sample_risk_assessment.status = RiskAssessmentStatus.PENDING
        deactivated = sample_risk_assessment.deactivate("deactivator", "reason")
        assert deactivated is sample_risk_assessment  # No change

    def test_lock(self, sample_risk_assessment):
        locked = sample_risk_assessment.lock("locker", "reason")
        assert locked is sample_risk_assessment

    def test_unlock(self, sample_risk_assessment):
        unlocked = sample_risk_assessment.unlock("unlocker")
        assert unlocked is sample_risk_assessment

    def test_validate_returns_valid(self, sample_risk_assessment):
        result = sample_risk_assessment.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_returns_hash_mismatch(self, sample_risk_assessment):
        object.__setattr__(sample_risk_assessment, "cryptographic_hash", "fake")
        result = sample_risk_assessment.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_to_dict(self, sample_risk_assessment):
        d = sample_risk_assessment.to_dict()
        assert d["overall_risk"] == "MEDIUM"
        assert d["risk_score"] == 45.5
        assert d["status"] == "ASSESSED"
        assert d["requires_approval"] is False
        assert "assessment_id" in d
        assert "cryptographic_hash" in d

    def test_from_dict(self):
        assessment_id = uuid4()
        intent_id = uuid4()
        data = {
            "assessment_id": str(assessment_id),
            "intent_id": str(intent_id),
            "assessed_at": "2026-01-15T12:00:00+00:00",
            "assessed_by": "test",
            "overall_risk": "HIGH",
            "risk_score": 80.0,
            "factors": [
                {
                    "category": "aml",
                    "description": "Test factor",
                    "score": 50.0,
                    "weight": 1.5,
                    "version": 1,
                }
            ],
            "recommendations": ["Rec 1"],
            "status": "NEEDS_REVIEW",
            "requires_approval": True,
            "requires_dual_control": False,
            "notes": "Test notes",
            "version": 2,
            "cryptographic_hash": "",
        }
        assessment = RiskAssessment.from_dict(data)
        assert assessment.assessment_id == assessment_id
        assert assessment.intent_id == intent_id
        assert assessment.overall_risk == RiskLevel.HIGH
        assert assessment.risk_score == 80.0
        assert assessment.status == RiskAssessmentStatus.NEEDS_REVIEW
        assert assessment.requires_approval is True
        assert len(assessment.factors) == 1
        assert assessment.factors[0].category == RiskCategory.AML

    def test_from_dict_defaults(self):
        assessment_id = uuid4()
        intent_id = uuid4()
        data = {
            "assessment_id": str(assessment_id),
            "intent_id": str(intent_id),
            "assessed_at": "2026-01-15T12:00:00+00:00",
            "assessed_by": "test",
            "overall_risk": "LOW",
            "risk_score": 10.0,
            "factors": [],
            "requires_approval": False,
            "requires_dual_control": False,
        }
        assessment = RiskAssessment.from_dict(data)
        assert assessment.recommendations == []
        assert assessment.notes == ""
        assert assessment.version == 1
        assert assessment.cryptographic_hash == ""

    def test_clone(self, sample_risk_assessment):
        cloned = sample_risk_assessment.clone()
        assert cloned.assessment_id != sample_risk_assessment.assessment_id
        assert cloned.intent_id == sample_risk_assessment.intent_id
        assert cloned.overall_risk == sample_risk_assessment.overall_risk
        assert cloned.status == RiskAssessmentStatus.PENDING
        assert cloned.version == 1
        assert cloned.factors == sample_risk_assessment.factors

    def test_snapshot(self, sample_risk_assessment):
        snap = sample_risk_assessment.snapshot()
        assert snap["assessment_id"] == str(sample_risk_assessment.assessment_id)
        assert snap["intent_id"] == str(sample_risk_assessment.intent_id)
        assert snap["overall_risk"] == "MEDIUM"

    def test_get_version(self, sample_risk_assessment):
        assert sample_risk_assessment.get_version() == 1

    def test_audit_trail(self, sample_risk_assessment):
        trail = sample_risk_assessment.audit_trail()
        assert len(trail) >= 1
        sample_risk_assessment.touch("toucher")
        trail2 = sample_risk_assessment.audit_trail()
        assert len(trail2) >= 2
        assert trail2[-1]["action"] == "TOUCH"

    def test_touch(self, sample_risk_assessment):
        touched = sample_risk_assessment.touch("toucher")
        assert touched is sample_risk_assessment
        assert len(sample_risk_assessment._audit_trail) >= 2

    def test_is_actionable(self, sample_risk_assessment):
        sample_risk_assessment.status = RiskAssessmentStatus.ASSESSED
        assert sample_risk_assessment.is_actionable() is True
        sample_risk_assessment.status = RiskAssessmentStatus.PENDING
        assert sample_risk_assessment.is_actionable() is False
        sample_risk_assessment.status = RiskAssessmentStatus.NEEDS_REVIEW
        assert sample_risk_assessment.is_actionable() is False


# ============================================================================
# RiskAssessor Tests
# ============================================================================

class TestRiskAssessor:
    def test_singleton(self):
        assessor1 = RiskAssessor()
        assessor2 = RiskAssessor()
        assert assessor1 is assessor2

    @pytest.fixture
    def assessor(self):
        return RiskAssessor()

    @pytest.fixture
    def mock_record_service(self):
        with patch("domain.intent.risk_assessor.get_immutable_intent_record_service") as mock:
            service = MagicMock()
            mock.return_value = service
            yield service

    # ---- Private assessment methods ----
    def test_assess_aml_risk_large_amount(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {"amount": Decimal("1500000000")}
        factor = assessor._assess_aml_risk(intent)
        assert factor is not None
        assert factor.category == RiskCategory.AML
        assert factor.score == 50.0  # Very large
        assert "Very large transaction amount" in factor.description

    def test_assess_aml_risk_large_amount_not_decimal(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {"amount": "1500000000"}
        factor = assessor._assess_aml_risk(intent)
        assert factor is not None
        assert factor.score == 50.0

    def test_assess_aml_risk_medium_amount(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {"amount": Decimal("200000000")}
        factor = assessor._assess_aml_risk(intent)
        assert factor is not None
        assert factor.category == RiskCategory.AML
        assert factor.score == 30.0
        assert "Large transaction amount" in factor.description

    def test_assess_aml_risk_small_amount(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {"amount": Decimal("1000000")}
        factor = assessor._assess_aml_risk(intent)
        assert factor is None  # No factor for small amount

    def test_assess_aml_risk_international(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {
            "amount": Decimal("1000000"),
            "is_international": True,
        }
        factor = assessor._assess_aml_risk(intent)
        assert factor is not None
        assert factor.score == 20.0
        assert "International transaction" in factor.description

    def test_assess_aml_risk_cash(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {
            "amount": Decimal("1000000"),
            "payment_method": "CASH",
        }
        factor = assessor._assess_aml_risk(intent)
        assert factor is not None
        assert factor.score == 35.0
        assert "Cash transaction" in factor.description

    def test_assess_aml_risk_shell_company(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {
            "amount": Decimal("1000000"),
            "is_shell_company": True,
        }
        factor = assessor._assess_aml_risk(intent)
        assert factor is not None
        assert factor.score == 40.0
        assert "Shell company" in factor.description

    def test_assess_aml_risk_combined(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {
            "amount": Decimal("1500000000"),
            "is_international": True,
            "payment_method": "CASH",
            "is_shell_company": True,
        }
        factor = assessor._assess_aml_risk(intent)
        assert factor is not None
        assert factor.score == 100.0  # Capped at 100
        descriptions = factor.description.split("; ")
        assert len(descriptions) == 4

    def test_assess_fraud_risk_round_number(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {"amount": Decimal("15000000")}  # >10M and divisible by 1M
        factor = assessor._assess_fraud_risk(intent)
        assert factor is not None
        assert factor.category == RiskCategory.FRAUD
        assert factor.score == 15.0
        assert "Round number amount" in factor.description

    def test_assess_fraud_risk_round_number_small(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {"amount": Decimal("5000000")}  # <10M
        factor = assessor._assess_fraud_risk(intent)
        assert factor is None

    def test_assess_fraud_risk_round_number_not_divisible(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {"amount": Decimal("15000001")}  # Not divisible by 1M
        factor = assessor._assess_fraud_risk(intent)
        assert factor is None

    def test_assess_fraud_risk_rush(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {
            "amount": Decimal("1000000"),
            "is_rush": True,
        }
        factor = assessor._assess_fraud_risk(intent)
        assert factor is not None
        assert factor.score == 15.0
        assert "Rush" in factor.description

    def test_assess_fraud_risk_duplicate(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {
            "amount": Decimal("1000000"),
            "is_duplicate_suspected": True,
        }
        factor = assessor._assess_fraud_risk(intent)
        assert factor is not None
        assert factor.score == 25.0
        assert "duplicate" in factor.description

    def test_assess_fraud_risk_beneficiary_mismatch(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {
            "amount": Decimal("1000000"),
            "beneficiary_mismatch": True,
        }
        factor = assessor._assess_fraud_risk(intent)
        assert factor is not None
        assert factor.score == 30.0
        assert "Beneficiary mismatch" in factor.description

    def test_assess_fraud_risk_combined(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {
            "amount": Decimal("15000000"),
            "is_rush": True,
            "is_duplicate_suspected": True,
            "beneficiary_mismatch": True,
        }
        factor = assessor._assess_fraud_risk(intent)
        assert factor is not None
        expected = 15 + 15 + 25 + 30  # 85
        assert factor.score == 85.0

    def test_assess_compliance_risk_regulated(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {
            "transaction_type": "FOREIGN_EXCHANGE",
            "source_document_ref": "PO-001",
        }
        factor = assessor._assess_compliance_risk(intent)
        assert factor is not None
        assert factor.category == RiskCategory.COMPLIANCE
        assert factor.score == 25.0
        assert "Regulated transaction" in factor.description

    def test_assess_compliance_risk_missing_ref(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {
            "transaction_type": "PURCHASE",
            "source_document_ref": None,
        }
        factor = assessor._assess_compliance_risk(intent)
        assert factor is not None
        assert factor.score == 20.0
        assert "Missing source document" in factor.description

    def test_assess_compliance_risk_intercompany(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {
            "transaction_type": "PURCHASE",
            "source_document_ref": "PO-001",
            "is_intercompany": True,
        }
        factor = assessor._assess_compliance_risk(intent)
        assert factor is not None
        assert factor.score == 15.0
        assert "Intercompany" in factor.description

    def test_assess_compliance_risk_related_party(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {
            "transaction_type": "PURCHASE",
            "source_document_ref": "PO-001",
            "is_related_party": True,
        }
        factor = assessor._assess_compliance_risk(intent)
        assert factor is not None
        assert factor.score == 20.0
        assert "Related party" in factor.description

    def test_assess_compliance_risk_regulatory_approval(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {
            "transaction_type": "PURCHASE",
            "source_document_ref": "PO-001",
            "requires_regulatory_approval": True,
        }
        factor = assessor._assess_compliance_risk(intent)
        assert factor is not None
        assert factor.score == 30.0
        assert "regulatory approval" in factor.description

    def test_assess_compliance_risk_no_factors(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {
            "transaction_type": "PURCHASE",
            "source_document_ref": "PO-001",
            "is_intercompany": False,
            "is_related_party": False,
            "requires_regulatory_approval": False,
        }
        factor = assessor._assess_compliance_risk(intent)
        assert factor is None

    def test_assess_credit_risk_not_applicable(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.intent_type.name = "OTHER"
        intent.data = {}
        factor = assessor._assess_credit_risk(intent)
        assert factor is None

    def test_assess_credit_risk_no_customer(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.intent_type.name = "CREATE_INVOICE"
        intent.data = {"customer_id": None}
        factor = assessor._assess_credit_risk(intent)
        assert factor is None

    def test_assess_credit_risk_high_utilization(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.intent_type.name = "CREATE_INVOICE"
        intent.data = {
            "customer_id": "CUST-001",
            "amount": Decimal("500000000"),
            "customer_credit_limit": Decimal("600000000"),
            "customer_current_balance": Decimal("100000000"),
            "has_overdue_payments": False,
            "customer_payment_rating": "GOOD",
        }
        factor = assessor._assess_credit_risk(intent)
        assert factor is not None
        assert factor.category == RiskCategory.CREDIT
        # utilization = (100M + 500M) / 600M = 1.0 = 100%
        assert factor.score >= 30.0
        assert "exhausted" in factor.description

    def test_assess_credit_risk_medium_utilization(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.intent_type.name = "CREATE_INVOICE"
        intent.data = {
            "customer_id": "CUST-001",
            "amount": Decimal("300000000"),
            "customer_credit_limit": Decimal("1000000000"),
            "customer_current_balance": Decimal("400000000"),
            "has_overdue_payments": False,
            "customer_payment_rating": "GOOD",
        }
        factor = assessor._assess_credit_risk(intent)
        assert factor is not None
        # utilization = (400M + 300M) / 1000M = 70%
        assert factor.score == 15.0
        assert "High credit utilization" in factor.description

    def test_assess_credit_risk_overdue_payments(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.intent_type.name = "CREATE_INVOICE"
        intent.data = {
            "customer_id": "CUST-001",
            "amount": Decimal("1000000"),
            "customer_credit_limit": Decimal("1000000000"),
            "customer_current_balance": Decimal("0"),
            "has_overdue_payments": True,
            "customer_payment_rating": "GOOD",
        }
        factor = assessor._assess_credit_risk(intent)
        assert factor is not None
        assert factor.score == 25.0
        assert "overdue payments" in factor.description

    def test_assess_credit_risk_poor_payment_rating(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.intent_type.name = "CREATE_INVOICE"
        intent.data = {
            "customer_id": "CUST-001",
            "amount": Decimal("1000000"),
            "customer_credit_limit": Decimal("1000000000"),
            "customer_current_balance": Decimal("0"),
            "has_overdue_payments": False,
            "customer_payment_rating": "POOR",
        }
        factor = assessor._assess_credit_risk(intent)
        assert factor is not None
        assert factor.score == 30.0
        assert "Poor payment history" in factor.description

    def test_assess_tax_risk_avoidance(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {
            "tax_avoidance_indicator": True,
            "tax_id": "123456789012345",
            "tax_jurisdiction": "IDN",
        }
        factor = assessor._assess_tax_risk(intent)
        assert factor is not None
        assert factor.category == RiskCategory.TAX
        assert factor.score == 40.0
        assert "tax avoidance" in factor.description

    def test_assess_tax_risk_missing_tax_id(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {
            "tax_avoidance_indicator": False,
            "tax_id": None,
            "tax_jurisdiction": "IDN",
        }
        factor = assessor._assess_tax_risk(intent)
        assert factor is not None
        assert factor.score == 20.0
        assert "Missing tax identification" in factor.description

    def test_assess_tax_risk_foreign_jurisdiction(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {
            "tax_avoidance_indicator": False,
            "tax_id": "123456789012345",
            "tax_jurisdiction": "USA",
        }
        factor = assessor._assess_tax_risk(intent)
        assert factor is not None
        assert factor.score == 15.0
        assert "Foreign tax jurisdiction" in factor.description

    def test_assess_tax_risk_intercompany_high_value(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {
            "tax_avoidance_indicator": False,
            "tax_id": "123456789012345",
            "tax_jurisdiction": "IDN",
            "is_intercompany": True,
            "amount": Decimal("1500000000"),
        }
        factor = assessor._assess_tax_risk(intent)
        assert factor is not None
        assert factor.score == 35.0
        assert "transfer pricing" in factor.description

    def test_assess_tax_risk_intercompany_low_value(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {
            "tax_avoidance_indicator": False,
            "tax_id": "123456789012345",
            "tax_jurisdiction": "IDN",
            "is_intercompany": True,
            "amount": Decimal("500000000"),
        }
        factor = assessor._assess_tax_risk(intent)
        assert factor is None  # No factor because amount < 1B

    def test_assess_tax_risk_no_factors(self):
        assessor = RiskAssessor()
        intent = MagicMock()
        intent.data = {
            "tax_avoidance_indicator": False,
            "tax_id": "123456789012345",
            "tax_jurisdiction": "IDN",
            "is_intercompany": False,
        }
        factor = assessor._assess_tax_risk(intent)
        assert factor is None

    def test_generate_recommendations_critical(self):
        assessor = RiskAssessor()
        factors = [
            RiskFactor(category=RiskCategory.AML, description="High AML", score=80.0, weight=1.0)
        ]
        recommendations = assessor._generate_recommendations(factors, RiskLevel.CRITICAL)
        assert len(recommendations) >= 4
        assert "Escalate to compliance committee" in recommendations[0]
        assert "dual control" in recommendations[1]
        assert "enhanced due diligence" in recommendations[2]
        assert "board-level approval" in recommendations[3]

    def test_generate_recommendations_high(self):
        assessor = RiskAssessor()
        factors = []
        recommendations = assessor._generate_recommendations(factors, RiskLevel.HIGH)
        assert len(recommendations) >= 3
        assert "managerial approval" in recommendations[0]
        assert "Document justification" in recommendations[1]
        assert "additional verification" in recommendations[2]

    def test_generate_recommendations_medium(self):
        assessor = RiskAssessor()
        factors = []
        recommendations = assessor._generate_recommendations(factors, RiskLevel.MEDIUM)
        assert len(recommendations) >= 2
        assert "Standard review" in recommendations[0]
        assert "audit trail" in recommendations[1]

    def test_generate_recommendations_aml_specialist(self):
        assessor = RiskAssessor()
        factors = [
            RiskFactor(category=RiskCategory.AML, description="Suspicious pattern", score=60.0, weight=1.0)
        ]
        recommendations = assessor._generate_recommendations(factors, RiskLevel.MEDIUM)
        assert len(recommendations) >= 3
        assert any("AML specialist" in r for r in recommendations)

    def test_generate_recommendations_compliance_specialist(self):
        assessor = RiskAssessor()
        factors = [
            RiskFactor(category=RiskCategory.COMPLIANCE, description="Regulatory issue", score=50.0, weight=1.0)
        ]
        recommendations = assessor._generate_recommendations(factors, RiskLevel.MEDIUM)
        assert any("Compliance review" in r for r in recommendations)

    def test_generate_recommendations_fraud_investigation(self):
        assessor = RiskAssessor()
        factors = [
            RiskFactor(category=RiskCategory.FRAUD, description="Suspicious pattern", score=60.0, weight=1.0)
        ]
        recommendations = assessor._generate_recommendations(factors, RiskLevel.MEDIUM)
        assert any("Fraud investigation" in r for r in recommendations)

    def test_generate_recommendations_no_duplicates(self):
        assessor = RiskAssessor()
        factors = [
            RiskFactor(category=RiskCategory.AML, description="High risk", score=80.0, weight=1.0),
            RiskFactor(category=RiskCategory.AML, description="Very high", score=90.0, weight=1.0),
        ]
        recommendations = assessor._generate_recommendations(factors, RiskLevel.CRITICAL)
        # Should not have duplicates
        assert len(recommendations) == len(set(recommendations))

    def test_assess_intent(self, assessor, mock_record_service, sample_intent_data):
        intent_id = uuid4()
        intent = MagicMock()
        intent.intent_id = intent_id
        intent.intent_type.name = "CREATE_INVOICE"
        intent.data = sample_intent_data

        mock_record_service.get.return_value = intent

        assessment = assessor.assess_intent(intent_id, "test_user")
        assert assessment is not None
        assert assessment.intent_id == intent_id
        assert assessment.assessed_by == "test_user"
        assert assessment.overall_risk in [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        assert assessment.status == RiskAssessmentStatus.ASSESSED
        assert len(assessment.factors) > 0
        assert len(assessment.recommendations) > 0
        # Should be stored
        stored = assessor.get_assessment(intent_id)
        assert stored is not None
        assert stored.assessment_id == assessment.assessment_id

    def test_assess_intent_not_found(self, assessor, mock_record_service):
        mock_record_service.get.return_value = None
        with pytest.raises(ValueError, match="not found"):
            assessor.assess_intent(uuid4(), "test_user")

    def test_get_assessment(self, assessor, mock_record_service, sample_intent_data):
        intent_id = uuid4()
        intent = MagicMock()
        intent.intent_id = intent_id
        intent.intent_type.name = "CREATE_INVOICE"
        intent.data = sample_intent_data
        mock_record_service.get.return_value = intent

        assessment = assessor.assess_intent(intent_id, "test_user")
        retrieved = assessor.get_assessment(intent_id)
        assert retrieved is not None
        assert retrieved.assessment_id == assessment.assessment_id
        # Non-existent
        assert assessor.get_assessment(uuid4()) is None

    def test_update_assessment_status(self, assessor, mock_record_service, sample_intent_data):
        intent_id = uuid4()
        intent = MagicMock()
        intent.intent_id = intent_id
        intent.intent_type.name = "CREATE_INVOICE"
        intent.data = sample_intent_data
        mock_record_service.get.return_value = intent

        assessor.assess_intent(intent_id, "test_user")
        updated = assessor.update_assessment_status(
            intent_id, RiskAssessmentStatus.APPROVED, "approver", "Approved"
        )
        assert updated is not None
        assert updated.status == RiskAssessmentStatus.APPROVED
        assert updated.notes == "Approved"
        assert updated.version == 2

        # Non-existent
        result = assessor.update_assessment_status(uuid4(), RiskAssessmentStatus.APPROVED, "user")
        assert result is None

    def test_save_assessment(self, assessor, sample_risk_assessment):
        assert assessor.get_assessment(sample_risk_assessment.intent_id) is None
        assessor.save_assessment(sample_risk_assessment)
        retrieved = assessor.get_assessment(sample_risk_assessment.intent_id)
        assert retrieved is not None
        assert retrieved.assessment_id == sample_risk_assessment.assessment_id

    def test_get_all_assessments(self, assessor, mock_record_service, sample_intent_data):
        # Create two assessments
        intent_id1 = uuid4()
        intent1 = MagicMock()
        intent1.intent_id = intent_id1
        intent1.intent_type.name = "CREATE_INVOICE"
        intent1.data = sample_intent_data
        mock_record_service.get.return_value = intent1

        assessor.assess_intent(intent_id1, "user1")

        intent_id2 = uuid4()
        intent2 = MagicMock()
        intent2.intent_id = intent_id2
        intent2.intent_type.name = "CREATE_JOURNAL"
        intent2.data = sample_intent_data
        mock_record_service.get.return_value = intent2

        assessor.assess_intent(intent_id2, "user2")

        all_assessments = assessor.get_all_assessments()
        assert len(all_assessments) == 2
        intents = {a.intent_id for a in all_assessments}
        assert intent_id1 in intents
        assert intent_id2 in intents

    def test_delete_assessment(self, assessor, mock_record_service, sample_intent_data):
        intent_id = uuid4()
        intent = MagicMock()
        intent.intent_id = intent_id
        intent.intent_type.name = "CREATE_INVOICE"
        intent.data = sample_intent_data
        mock_record_service.get.return_value = intent

        assessor.assess_intent(intent_id, "test_user")
        assert assessor.get_assessment(intent_id) is not None
        result = assessor.delete_assessment(intent_id)
        assert result is True
        assert assessor.get_assessment(intent_id) is None

        # Delete non-existent
        result2 = assessor.delete_assessment(uuid4())
        assert result2 is False

    def test_count_assessments(self, assessor, mock_record_service, sample_intent_data):
        assert assessor.count_assessments() == 0
        # Create one assessment
        intent_id = uuid4()
        intent = MagicMock()
        intent.intent_id = intent_id
        intent.intent_type.name = "CREATE_INVOICE"
        intent.data = sample_intent_data
        mock_record_service.get.return_value = intent

        assessor.assess_intent(intent_id, "user")
        assert assessor.count_assessments() == 1

    def test_get_statistics(self, assessor, mock_record_service, sample_intent_data):
        assert assessor.get_statistics() == {"total_assessments": 0}

        # Create assessments with different risk levels
        for i in range(3):
            intent_id = uuid4()
            intent = MagicMock()
            intent.intent_id = intent_id
            intent.intent_type.name = "CREATE_INVOICE"
            intent.data = sample_intent_data.copy()
            if i == 0:
                intent.data["amount"] = Decimal("2000000000")  # Critical
            elif i == 1:
                intent.data["amount"] = Decimal("600000000")   # High
            else:
                intent.data["amount"] = Decimal("10000000")    # Low
            mock_record_service.get.return_value = intent
            assessor.assess_intent(intent_id, f"user{i}")

        stats = assessor.get_statistics()
        assert stats["total_assessments"] == 3
        assert "by_risk_level" in stats
        assert "by_status" in stats
        assert stats["average_risk_score"] > 0
        assert stats["requires_approval_count"] > 0
        assert stats["requires_dual_control_count"] > 0

    def test_reset(self, assessor, mock_record_service, sample_intent_data):
        intent_id = uuid4()
        intent = MagicMock()
        intent.intent_id = intent_id
        intent.intent_type.name = "CREATE_INVOICE"
        intent.data = sample_intent_data
        mock_record_service.get.return_value = intent

        assessor.assess_intent(intent_id, "user")
        assert assessor.count_assessments() == 1
        assessor.reset()
        assert assessor.count_assessments() == 0


# ============================================================================
# Singleton Accessor Tests
# ============================================================================

def test_get_risk_assessor_singleton():
    assessor1 = get_risk_assessor()
    assessor2 = get_risk_assessor()
    assert assessor1 is assessor2
    assert isinstance(assessor1, RiskAssessor)