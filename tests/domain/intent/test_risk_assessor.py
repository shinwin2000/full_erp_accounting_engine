# tests/domain/intent/test_risk_assessor.py
"""
Comprehensive unit tests for domain/intent/risk_assessor.py.
All datetime usage is mocked to avoid flakiness.
Covers all public and private methods with positive and negative paths.
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

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

FIXED_NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now in risk_assessor to fixed time."""
    with patch("domain.intent.risk_assessor.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


@pytest.fixture
def sample_intent_data():
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
    intent = MagicMock()
    intent.intent_id = uuid4()
    intent.intent_type = MagicMock()
    intent.intent_type.name = "CREATE_INVOICE"
    intent.data = {}
    return intent


@pytest.fixture
def sample_risk_factor():
    return RiskFactor(
        category=RiskCategory.AML,
        description="Large transaction amount (>100M)",
        score=30.0,
        weight=1.5,
        version=1,
    )


@pytest.fixture
def sample_risk_assessment():
    return RiskAssessment(
        assessment_id=uuid4(),
        intent_id=uuid4(),
        assessed_at=FIXED_NOW,
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


@pytest.fixture
def mock_record_service():
    """Mock the intent record service."""
    with patch("domain.intent.risk_assessor.get_immutable_intent_record_service") as mock:
        service = MagicMock()
        mock.return_value = service
        yield service


@pytest.fixture
def assessor(mock_record_service):
    """Create RiskAssessor with mocked record service."""
    assessor = RiskAssessor()
    # Ensure the internal record_service is the mock
    assessor._record_service = mock_record_service
    # Reset assessments
    assessor._assessments = {}
    return assessor


# ============================================================================
# Enum Tests
# ============================================================================

class TestRiskCategory:
    def test_members(self):
        assert RiskCategory.AML.value == "aml"
        assert RiskCategory.FRAUD.value == "fraud"

    def test_from_string(self):
        assert RiskCategory.from_string("aml") == RiskCategory.AML
        assert RiskCategory.from_string("FRAUD") == RiskCategory.FRAUD
        with pytest.raises(ValueError, match="Unknown RiskCategory"):
            RiskCategory.from_string("unknown")


class TestRiskLevel:
    def test_members(self):
        assert RiskLevel.LOW.value == 1
        assert RiskLevel.CRITICAL.value == 4

    def test_from_int(self):
        assert RiskLevel.from_int(1) == RiskLevel.LOW
        assert RiskLevel.from_int(5) == RiskLevel.LOW  # default

    def test_requires_approval(self):
        assert RiskLevel.LOW.requires_approval() is False
        assert RiskLevel.HIGH.requires_approval() is True
        assert RiskLevel.CRITICAL.requires_approval() is True

    def test_requires_dual_control(self):
        assert RiskLevel.CRITICAL.requires_dual_control() is True
        assert RiskLevel.HIGH.requires_dual_control() is False


class TestRiskAssessmentStatus:
    def test_members(self):
        assert RiskAssessmentStatus.PENDING is not None
        assert RiskAssessmentStatus.ASSESSED is not None

    def test_from_string(self):
        assert RiskAssessmentStatus.from_string("ASSESSED") == RiskAssessmentStatus.ASSESSED
        with pytest.raises(ValueError, match="Unknown RiskAssessmentStatus"):
            RiskAssessmentStatus.from_string("unknown")


# ============================================================================
# RiskFactor Tests
# ============================================================================

class TestRiskFactor:
    def test_construction_valid(self, sample_risk_factor):
        assert sample_risk_factor.category == RiskCategory.AML
        assert sample_risk_factor.score == 30.0
        assert sample_risk_factor.weight == 1.5

    def test_construction_invalid_category(self):
        with pytest.raises(ValueError, match="category must be RiskCategory"):
            RiskFactor(
                category="AML",  # type: ignore
                description="test",
                score=50.0,
                weight=1.0,
            )

    def test_construction_empty_description(self):
        with pytest.raises(ValueError, match="description cannot be empty"):
            RiskFactor(category=RiskCategory.AML, description="", score=50.0, weight=1.0)

    def test_construction_score_low(self):
        with pytest.raises(ValueError, match="score must be between 0 and 100"):
            RiskFactor(category=RiskCategory.AML, description="test", score=-1.0, weight=1.0)

    def test_construction_score_high(self):
        with pytest.raises(ValueError, match="score must be between 0 and 100"):
            RiskFactor(category=RiskCategory.AML, description="test", score=101.0, weight=1.0)

    def test_construction_zero_weight(self):
        with pytest.raises(ValueError, match="weight must be positive"):
            RiskFactor(category=RiskCategory.AML, description="test", score=50.0, weight=0.0)

    def test_construction_version_zero(self):
        with pytest.raises(ValueError, match="version must be >= 1"):
            RiskFactor(category=RiskCategory.AML, description="test", score=50.0, weight=1.0, version=0)

    def test_create(self, sample_risk_factor):
        result = sample_risk_factor.create("creator")
        assert result is sample_risk_factor

    def test_update(self, sample_risk_factor):
        updated = sample_risk_factor.update("updater", description="New desc", score=75.0)
        assert updated.description == "New desc"
        assert updated.score == 75.0
        assert updated.version == 2
        # Ensure version field not overwritten
        updated2 = sample_risk_factor.update("updater", version=99)
        assert updated2.version == 2  # incremented, not 99

    def test_delete(self, sample_risk_factor):
        result = sample_risk_factor.delete("deleter", "reason")
        assert result is sample_risk_factor

    def test_restore(self, sample_risk_factor):
        result = sample_risk_factor.restore("restorer")
        assert result is sample_risk_factor

    def test_activate(self, sample_risk_factor):
        result = sample_risk_factor.activate("activator")
        assert result is sample_risk_factor

    def test_deactivate(self, sample_risk_factor):
        result = sample_risk_factor.deactivate("deactivator", "reason")
        assert result is sample_risk_factor

    def test_lock_unlock(self, sample_risk_factor):
        locked = sample_risk_factor.lock("locker", "reason")
        assert locked is sample_risk_factor
        unlocked = sample_risk_factor.unlock("unlocker")
        assert unlocked is sample_risk_factor

    def test_validate_valid(self, sample_risk_factor):
        result = sample_risk_factor.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid(self, sample_risk_factor):
        sample_risk_factor.score = -10
        result = sample_risk_factor.validate()
        assert result["is_valid"] is False
        assert "score must be between 0 and 100" in result["errors"]

    def test_to_dict(self, sample_risk_factor):
        d = sample_risk_factor.to_dict()
        assert d["category"] == "aml"
        assert d["score"] == 30.0

    def test_from_dict(self):
        data = {"category": "fraud", "description": "test", "score": 50.0, "weight": 2.0, "version": 3}
        factor = RiskFactor.from_dict(data)
        assert factor.category == RiskCategory.FRAUD
        assert factor.weight == 2.0

    def test_clone(self, sample_risk_factor):
        cloned = sample_risk_factor.clone()
        assert cloned is not sample_risk_factor
        assert cloned.version == 1

    def test_snapshot(self, sample_risk_factor):
        snap = sample_risk_factor.snapshot()
        assert snap["version"] == sample_risk_factor.version

    def test_audit_trail(self, sample_risk_factor):
        trail = sample_risk_factor.audit_trail()
        assert len(trail) >= 1
        sample_risk_factor.touch("toucher")
        trail2 = sample_risk_factor.audit_trail()
        assert len(trail2) >= 2
        assert trail2[-1]["action"] == "TOUCH"

    def test_weighted_score(self, sample_risk_factor):
        assert sample_risk_factor.weighted_score() == 45.0


# ============================================================================
# RiskAssessment Tests
# ============================================================================

class TestRiskAssessment:
    def test_construction_valid(self, sample_risk_assessment):
        assert sample_risk_assessment.overall_risk == RiskLevel.MEDIUM
        assert sample_risk_assessment.cryptographic_hash != ""

    # Negative path: validation errors
    def test_validation_invalid_assessment_id(self):
        with pytest.raises(ValueError, match="assessment_id must be UUID"):
            RiskAssessment(
                assessment_id="not-uuid",  # type: ignore
                intent_id=uuid4(),
                assessed_at=FIXED_NOW,
                assessed_by="user",
                overall_risk=RiskLevel.LOW,
                risk_score=10.0,
                factors=[],
                recommendations=[],
                status=RiskAssessmentStatus.PENDING,
                requires_approval=False,
                requires_dual_control=False,
            )

    def test_validation_invalid_intent_id(self):
        with pytest.raises(ValueError, match="intent_id must be UUID"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id="not-uuid",  # type: ignore
                assessed_at=FIXED_NOW,
                assessed_by="user",
                overall_risk=RiskLevel.LOW,
                risk_score=10.0,
                factors=[],
                recommendations=[],
                status=RiskAssessmentStatus.PENDING,
                requires_approval=False,
                requires_dual_control=False,
            )

    def test_validation_empty_assessed_by(self):
        with pytest.raises(ValueError, match="assessed_by cannot be empty"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id=uuid4(),
                assessed_at=FIXED_NOW,
                assessed_by="",
                overall_risk=RiskLevel.LOW,
                risk_score=10.0,
                factors=[],
                recommendations=[],
                status=RiskAssessmentStatus.PENDING,
                requires_approval=False,
                requires_dual_control=False,
            )

    def test_validation_invalid_overall_risk(self):
        with pytest.raises(ValueError, match="overall_risk must be RiskLevel"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id=uuid4(),
                assessed_at=FIXED_NOW,
                assessed_by="user",
                overall_risk="LOW",  # type: ignore
                risk_score=10.0,
                factors=[],
                recommendations=[],
                status=RiskAssessmentStatus.PENDING,
                requires_approval=False,
                requires_dual_control=False,
            )

    def test_validation_risk_score_out_of_range_low(self):
        with pytest.raises(ValueError, match="risk_score must be between 0 and 100"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id=uuid4(),
                assessed_at=FIXED_NOW,
                assessed_by="user",
                overall_risk=RiskLevel.LOW,
                risk_score=-1.0,
                factors=[],
                recommendations=[],
                status=RiskAssessmentStatus.PENDING,
                requires_approval=False,
                requires_dual_control=False,
            )

    def test_validation_risk_score_out_of_range_high(self):
        with pytest.raises(ValueError, match="risk_score must be between 0 and 100"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id=uuid4(),
                assessed_at=FIXED_NOW,
                assessed_by="user",
                overall_risk=RiskLevel.LOW,
                risk_score=101.0,
                factors=[],
                recommendations=[],
                status=RiskAssessmentStatus.PENDING,
                requires_approval=False,
                requires_dual_control=False,
            )

    def test_validation_factors_not_list(self):
        with pytest.raises(ValueError, match="factors must be list"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id=uuid4(),
                assessed_at=FIXED_NOW,
                assessed_by="user",
                overall_risk=RiskLevel.LOW,
                risk_score=10.0,
                factors="not-list",  # type: ignore
                recommendations=[],
                status=RiskAssessmentStatus.PENDING,
                requires_approval=False,
                requires_dual_control=False,
            )

    def test_validation_recommendations_not_list(self):
        with pytest.raises(ValueError, match="recommendations must be list"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id=uuid4(),
                assessed_at=FIXED_NOW,
                assessed_by="user",
                overall_risk=RiskLevel.LOW,
                risk_score=10.0,
                factors=[],
                recommendations="not-list",  # type: ignore
                status=RiskAssessmentStatus.PENDING,
                requires_approval=False,
                requires_dual_control=False,
            )

    def test_validation_invalid_status(self):
        with pytest.raises(ValueError, match="status must be RiskAssessmentStatus"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id=uuid4(),
                assessed_at=FIXED_NOW,
                assessed_by="user",
                overall_risk=RiskLevel.LOW,
                risk_score=10.0,
                factors=[],
                recommendations=[],
                status="PENDING",  # type: ignore
                requires_approval=False,
                requires_dual_control=False,
            )

    def test_validation_requires_approval_not_bool(self):
        with pytest.raises(ValueError, match="requires_approval must be bool"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id=uuid4(),
                assessed_at=FIXED_NOW,
                assessed_by="user",
                overall_risk=RiskLevel.LOW,
                risk_score=10.0,
                factors=[],
                recommendations=[],
                status=RiskAssessmentStatus.PENDING,
                requires_approval="True",  # type: ignore
                requires_dual_control=False,
            )

    def test_validation_requires_dual_control_not_bool(self):
        with pytest.raises(ValueError, match="requires_dual_control must be bool"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id=uuid4(),
                assessed_at=FIXED_NOW,
                assessed_by="user",
                overall_risk=RiskLevel.LOW,
                risk_score=10.0,
                factors=[],
                recommendations=[],
                status=RiskAssessmentStatus.PENDING,
                requires_approval=False,
                requires_dual_control="False",  # type: ignore
            )

    def test_validation_version_zero(self):
        with pytest.raises(ValueError, match="version must be >= 1"):
            RiskAssessment(
                assessment_id=uuid4(),
                intent_id=uuid4(),
                assessed_at=FIXED_NOW,
                assessed_by="user",
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
        h1 = sample_risk_assessment.compute_hash()
        h2 = sample_risk_assessment.compute_hash()
        assert h1 == h2

    def test_create(self, sample_risk_assessment):
        result = sample_risk_assessment.create("creator")
        assert result is sample_risk_assessment

    def test_update(self, sample_risk_assessment):
        updated = sample_risk_assessment.update(
            "updater",
            status=RiskAssessmentStatus.APPROVED,
            notes="Approved"
        )
        assert updated.status == RiskAssessmentStatus.APPROVED
        assert updated.notes == "Approved"
        assert updated.version == 2
        # Ensure other fields unchanged
        assert updated.overall_risk == sample_risk_assessment.overall_risk
        assert updated.risk_score == sample_risk_assessment.risk_score

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
        assert activated.version == 2

    def test_activate_from_assessed(self, sample_risk_assessment):
        sample_risk_assessment.status = RiskAssessmentStatus.ASSESSED
        activated = sample_risk_assessment.activate("activator")
        assert activated is sample_risk_assessment

    def test_deactivate_from_assessed(self, sample_risk_assessment):
        sample_risk_assessment.status = RiskAssessmentStatus.ASSESSED
        deactivated = sample_risk_assessment.deactivate("deactivator", "reason")
        assert deactivated.status == RiskAssessmentStatus.NEEDS_REVIEW
        assert deactivated.version == 2

    def test_deactivate_from_pending(self, sample_risk_assessment):
        sample_risk_assessment.status = RiskAssessmentStatus.PENDING
        deactivated = sample_risk_assessment.deactivate("deactivator", "reason")
        assert deactivated is sample_risk_assessment

    def test_lock_unlock(self, sample_risk_assessment):
        locked = sample_risk_assessment.lock("locker", "reason")
        assert locked is sample_risk_assessment
        unlocked = sample_risk_assessment.unlock("unlocker")
        assert unlocked is sample_risk_assessment

    def test_validate_valid(self, sample_risk_assessment):
        result = sample_risk_assessment.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_hash_mismatch(self, sample_risk_assessment):
        object.__setattr__(sample_risk_assessment, "cryptographic_hash", "fake")
        result = sample_risk_assessment.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_to_dict(self, sample_risk_assessment):
        d = sample_risk_assessment.to_dict()
        assert d["overall_risk"] == "MEDIUM"
        assert d["risk_score"] == 45.5
        assert "cryptographic_hash" in d

    def test_from_dict(self):
        assessment_id = uuid4()
        intent_id = uuid4()
        data = {
            "assessment_id": str(assessment_id),
            "intent_id": str(intent_id),
            "assessed_at": FIXED_NOW.isoformat(),
            "assessed_by": "user",
            "overall_risk": "HIGH",
            "risk_score": 80.0,
            "factors": [
                {
                    "category": "aml",
                    "description": "Test",
                    "score": 50.0,
                    "weight": 1.5,
                    "version": 1,
                }
            ],
            "recommendations": ["Rec1"],
            "status": "ASSESSED",
            "requires_approval": True,
            "requires_dual_control": False,
            "notes": "Notes",
            "version": 2,
            "cryptographic_hash": "",
        }
        assessment = RiskAssessment.from_dict(data)
        assert assessment.assessment_id == assessment_id
        assert assessment.overall_risk == RiskLevel.HIGH
        assert len(assessment.factors) == 1

    def test_clone(self, sample_risk_assessment):
        cloned = sample_risk_assessment.clone()
        assert cloned.assessment_id != sample_risk_assessment.assessment_id
        assert cloned.status == RiskAssessmentStatus.PENDING
        assert cloned.version == 1

    def test_snapshot(self, sample_risk_assessment):
        snap = sample_risk_assessment.snapshot()
        assert snap["assessment_id"] == str(sample_risk_assessment.assessment_id)

    def test_audit_trail(self, sample_risk_assessment):
        trail = sample_risk_assessment.audit_trail()
        assert len(trail) >= 1
        sample_risk_assessment.touch("toucher")
        trail2 = sample_risk_assessment.audit_trail()
        assert len(trail2) >= 2

    def test_is_actionable(self, sample_risk_assessment):
        sample_risk_assessment.status = RiskAssessmentStatus.ASSESSED
        assert sample_risk_assessment.is_actionable() is True
        sample_risk_assessment.status = RiskAssessmentStatus.PENDING
        assert sample_risk_assessment.is_actionable() is False


# ============================================================================
# RiskAssessor Tests
# ============================================================================

class TestRiskAssessor:
    def test_singleton(self):
        assessor1 = RiskAssessor()
        assessor2 = RiskAssessor()
        assert assessor1 is assessor2

    # ---- Private assessment methods ----
    def test_assess_aml_risk(self, assessor, sample_intent):
        # Very large amount
        sample_intent.data = {"amount": Decimal("1500000000")}
        factor = assessor._assess_aml_risk(sample_intent)
        assert factor is not None
        assert factor.category == RiskCategory.AML
        assert factor.score == 50.0

        # International
        sample_intent.data = {"amount": Decimal("1000000"), "is_international": True}
        factor = assessor._assess_aml_risk(sample_intent)
        assert factor is not None
        assert factor.score == 20.0

        # Cash
        sample_intent.data = {"amount": Decimal("1000000"), "payment_method": "CASH"}
        factor = assessor._assess_aml_risk(sample_intent)
        assert factor is not None
        assert factor.score == 35.0

        # Shell company
        sample_intent.data = {"amount": Decimal("1000000"), "is_shell_company": True}
        factor = assessor._assess_aml_risk(sample_intent)
        assert factor is not None
        assert factor.score == 40.0

        # Combined capped at 100
        sample_intent.data = {
            "amount": Decimal("1500000000"),
            "is_international": True,
            "payment_method": "CASH",
            "is_shell_company": True,
        }
        factor = assessor._assess_aml_risk(sample_intent)
        assert factor is not None
        assert factor.score == 100.0

        # No risk
        sample_intent.data = {"amount": Decimal("1000000")}
        factor = assessor._assess_aml_risk(sample_intent)
        assert factor is None

    def test_assess_fraud_risk(self, assessor, sample_intent):
        # Round number
        sample_intent.data = {"amount": Decimal("15000000")}
        factor = assessor._assess_fraud_risk(sample_intent)
        assert factor is not None
        assert factor.score == 15.0

        # Rush
        sample_intent.data = {"amount": Decimal("1000000"), "is_rush": True}
        factor = assessor._assess_fraud_risk(sample_intent)
        assert factor is not None
        assert factor.score == 15.0

        # Duplicate
        sample_intent.data = {"amount": Decimal("1000000"), "is_duplicate_suspected": True}
        factor = assessor._assess_fraud_risk(sample_intent)
        assert factor is not None
        assert factor.score == 25.0

        # Beneficiary mismatch
        sample_intent.data = {"amount": Decimal("1000000"), "beneficiary_mismatch": True}
        factor = assessor._assess_fraud_risk(sample_intent)
        assert factor is not None
        assert factor.score == 30.0

        # Combined
        sample_intent.data = {
            "amount": Decimal("15000000"),
            "is_rush": True,
            "is_duplicate_suspected": True,
            "beneficiary_mismatch": True,
        }
        factor = assessor._assess_fraud_risk(sample_intent)
        assert factor is not None
        assert factor.score == 85.0

        # No risk
        sample_intent.data = {"amount": Decimal("1000000")}
        factor = assessor._assess_fraud_risk(sample_intent)
        assert factor is None

    def test_assess_compliance_risk(self, assessor, sample_intent):
        # Regulated transaction
        sample_intent.data = {"transaction_type": "FOREIGN_EXCHANGE", "source_document_ref": "PO-001"}
        factor = assessor._assess_compliance_risk(sample_intent)
        assert factor is not None
        assert factor.score == 25.0

        # Missing source doc
        sample_intent.data = {"transaction_type": "PURCHASE", "source_document_ref": None}
        factor = assessor._assess_compliance_risk(sample_intent)
        assert factor is not None
        assert factor.score == 20.0

        # Intercompany
        sample_intent.data = {"transaction_type": "PURCHASE", "source_document_ref": "PO-001", "is_intercompany": True}
        factor = assessor._assess_compliance_risk(sample_intent)
        assert factor is not None
        assert factor.score == 15.0

        # Related party
        sample_intent.data = {"transaction_type": "PURCHASE", "source_document_ref": "PO-001", "is_related_party": True}
        factor = assessor._assess_compliance_risk(sample_intent)
        assert factor is not None
        assert factor.score == 20.0

        # Regulatory approval
        sample_intent.data = {
            "transaction_type": "PURCHASE",
            "source_document_ref": "PO-001",
            "requires_regulatory_approval": True,
        }
        factor = assessor._assess_compliance_risk(sample_intent)
        assert factor is not None
        assert factor.score == 30.0

        # No risk
        sample_intent.data = {"transaction_type": "PURCHASE", "source_document_ref": "PO-001"}
        factor = assessor._assess_compliance_risk(sample_intent)
        assert factor is None

    def test_assess_credit_risk(self, assessor, sample_intent):
        # Not applicable intent type
        sample_intent.intent_type.name = "OTHER"
        sample_intent.data = {}
        factor = assessor._assess_credit_risk(sample_intent)
        assert factor is None

        # No customer id
        sample_intent.intent_type.name = "CREATE_INVOICE"
        sample_intent.data = {"customer_id": None}
        factor = assessor._assess_credit_risk(sample_intent)
        assert factor is None

        # High utilization
        sample_intent.data = {
            "customer_id": "CUST-001",
            "amount": Decimal("500000000"),
            "customer_credit_limit": Decimal("600000000"),
            "customer_current_balance": Decimal("100000000"),
            "has_overdue_payments": False,
            "customer_payment_rating": "GOOD",
        }
        factor = assessor._assess_credit_risk(sample_intent)
        assert factor is not None
        assert factor.score >= 30.0

        # Overdue payments
        sample_intent.data = {
            "customer_id": "CUST-001",
            "amount": Decimal("1000000"),
            "customer_credit_limit": Decimal("1000000000"),
            "customer_current_balance": Decimal("0"),
            "has_overdue_payments": True,
            "customer_payment_rating": "GOOD",
        }
        factor = assessor._assess_credit_risk(sample_intent)
        assert factor is not None
        assert factor.score == 25.0

        # Poor rating
        sample_intent.data = {
            "customer_id": "CUST-001",
            "amount": Decimal("1000000"),
            "customer_credit_limit": Decimal("1000000000"),
            "customer_current_balance": Decimal("0"),
            "has_overdue_payments": False,
            "customer_payment_rating": "POOR",
        }
        factor = assessor._assess_credit_risk(sample_intent)
        assert factor is not None
        assert factor.score == 30.0

    def test_assess_tax_risk(self, assessor, sample_intent):
        # Tax avoidance
        sample_intent.data = {"tax_avoidance_indicator": True, "tax_id": "123", "tax_jurisdiction": "IDN"}
        factor = assessor._assess_tax_risk(sample_intent)
        assert factor is not None
        assert factor.score == 40.0

        # Missing tax id
        sample_intent.data = {"tax_avoidance_indicator": False, "tax_id": None, "tax_jurisdiction": "IDN"}
        factor = assessor._assess_tax_risk(sample_intent)
        assert factor is not None
        assert factor.score == 20.0

        # Foreign jurisdiction
        sample_intent.data = {"tax_avoidance_indicator": False, "tax_id": "123", "tax_jurisdiction": "USA"}
        factor = assessor._assess_tax_risk(sample_intent)
        assert factor is not None
        assert factor.score == 15.0

        # Intercompany high value
        sample_intent.data = {
            "tax_avoidance_indicator": False,
            "tax_id": "123",
            "tax_jurisdiction": "IDN",
            "is_intercompany": True,
            "amount": Decimal("1500000000"),
        }
        factor = assessor._assess_tax_risk(sample_intent)
        assert factor is not None
        assert factor.score == 35.0

        # No risk
        sample_intent.data = {"tax_avoidance_indicator": False, "tax_id": "123", "tax_jurisdiction": "IDN"}
        factor = assessor._assess_tax_risk(sample_intent)
        assert factor is None

    def test_generate_recommendations(self, assessor):
        factors = [
            RiskFactor(category=RiskCategory.AML, description="High AML", score=80.0, weight=1.0)
        ]
        # Critical
        recs = assessor._generate_recommendations(factors, RiskLevel.CRITICAL)
        assert len(recs) >= 4
        assert any("compliance committee" in r for r in recs)
        # High
        recs2 = assessor._generate_recommendations([], RiskLevel.HIGH)
        assert len(recs2) >= 3
        assert any("managerial approval" in r for r in recs2)
        # Medium
        recs3 = assessor._generate_recommendations([], RiskLevel.MEDIUM)
        assert len(recs3) >= 2
        # AML specialist
        recs4 = assessor._generate_recommendations(factors, RiskLevel.MEDIUM)
        assert any("AML specialist" in r for r in recs4)
        # Duplicate removal
        factors2 = [
            RiskFactor(category=RiskCategory.AML, description="AML1", score=80.0, weight=1.0),
            RiskFactor(category=RiskCategory.AML, description="AML2", score=80.0, weight=1.0),
        ]
        recs5 = assessor._generate_recommendations(factors2, RiskLevel.CRITICAL)
        # Should have no duplicates
        assert len(recs5) == len(set(recs5))

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
        assert assessment.status == RiskAssessmentStatus.ASSESSED
        assert len(assessment.factors) > 0
        # Stored
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
        intent.data = sample_intent_data
        mock_record_service.get.return_value = intent
        assessor.assess_intent(intent_id, "user")
        retrieved = assessor.get_assessment(intent_id)
        assert retrieved is not None
        assert assessor.get_assessment(uuid4()) is None

    def test_update_assessment_status(self, assessor, mock_record_service, sample_intent_data):
        intent_id = uuid4()
        intent = MagicMock()
        intent.intent_id = intent_id
        intent.data = sample_intent_data
        mock_record_service.get.return_value = intent
        assessor.assess_intent(intent_id, "user")
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

    def test_get_all_assessments(self, assessor, mock_record_service, sample_intent_data):
        # Create two assessments
        for i in range(2):
            intent_id = uuid4()
            intent = MagicMock()
            intent.intent_id = intent_id
            intent.data = sample_intent_data
            mock_record_service.get.return_value = intent
            assessor.assess_intent(intent_id, f"user{i}")
        all_assessments = assessor.get_all_assessments()
        assert len(all_assessments) == 2

    def test_delete_assessment(self, assessor, mock_record_service, sample_intent_data):
        intent_id = uuid4()
        intent = MagicMock()
        intent.intent_id = intent_id
        intent.data = sample_intent_data
        mock_record_service.get.return_value = intent
        assessor.assess_intent(intent_id, "user")
        assert assessor.delete_assessment(intent_id) is True
        assert assessor.get_assessment(intent_id) is None
        assert assessor.delete_assessment(uuid4()) is False

    def test_count_assessments(self, assessor, mock_record_service, sample_intent_data):
        assert assessor.count_assessments() == 0
        intent_id = uuid4()
        intent = MagicMock()
        intent.intent_id = intent_id
        intent.data = sample_intent_data
        mock_record_service.get.return_value = intent
        assessor.assess_intent(intent_id, "user")
        assert assessor.count_assessments() == 1

    def test_get_statistics(self, assessor, mock_record_service, sample_intent_data):
        assert assessor.get_statistics() == {"total_assessments": 0}
        for i in range(3):
            intent_id = uuid4()
            intent = MagicMock()
            intent.intent_id = intent_id
            data = sample_intent_data.copy()
            if i == 0:
                data["amount"] = Decimal("2000000000")
            elif i == 1:
                data["amount"] = Decimal("600000000")
            else:
                data["amount"] = Decimal("10000000")
            intent.data = data
            mock_record_service.get.return_value = intent
            assessor.assess_intent(intent_id, f"user{i}")
        stats = assessor.get_statistics()
        assert stats["total_assessments"] == 3
        assert "by_risk_level" in stats
        assert stats["average_risk_score"] > 0

    def test_reset(self, assessor, mock_record_service, sample_intent_data):
        intent_id = uuid4()
        intent = MagicMock()
        intent.intent_id = intent_id
        intent.data = sample_intent_data
        mock_record_service.get.return_value = intent
        assessor.assess_intent(intent_id, "user")
        assert assessor.count_assessments() == 1
        assessor.reset()
        assert assessor.count_assessments() == 0


# ============================================================================
# Singleton Accessor Test
# ============================================================================

def test_get_risk_assessor_singleton():
    assessor1 = get_risk_assessor()
    assessor2 = get_risk_assessor()
    assert assessor1 is assessor2
