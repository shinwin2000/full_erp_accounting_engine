# tests/infrastructure/persistence_orm/test_aml_risk_score_table.py
"""
Comprehensive unit tests for infrastructure/persistence_orm/aml_risk_score_table.py.
Covers all properties, methods, state transitions, and edge cases.
Uses direct instantiation without a DB session for testing model logic.
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from infrastructure.persistence_orm.aml_risk_score_table import AMLRiskScoreTable

# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_aml_risk():
    """Create an AMLRiskScoreTable instance with default values."""
    return AMLRiskScoreTable(
        id=uuid4(),
        customer_id=uuid4(),
        customer_type="individual",
        risk_score=Decimal("45.50"),
        risk_category="medium",
        scoring_model="rule_based",
        scoring_version="v2.0",
        risk_factors={"factor1": 20, "factor2": 25.5},
        pep_status=False,
        pep_details=None,
        sanction_list_hit=False,
        sanction_list_details=None,
        manual_adjustment=Decimal("0"),
        adjustment_reason=None,
        adjusted_by=None,
        adjusted_at=None,
        calculated_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        valid_until=datetime(2027, 1, 1, 12, 0, 0, tzinfo=UTC),
        created_by=uuid4(),
        updated_by=uuid4(),
        legal_entity_id=uuid4(),
        version=1,
    )


@pytest.fixture
def sample_high_risk(sample_aml_risk):
    risk = sample_aml_risk
    risk.risk_category = "high"
    risk.risk_score = Decimal("75")
    return risk


@pytest.fixture
def sample_very_high_risk(sample_aml_risk):
    risk = sample_aml_risk
    risk.risk_category = "very_high"
    risk.risk_score = Decimal("92")
    return risk


@pytest.fixture
def sample_low_risk(sample_aml_risk):
    risk = sample_aml_risk
    risk.risk_category = "low"
    risk.risk_score = Decimal("15")
    return risk


# ============================================================================
# TABLE METADATA TESTS
# ============================================================================

class TestAMLRiskScoreTableMetadata:
    def test_tablename_defined(self):
        assert hasattr(AMLRiskScoreTable, "__tablename__")
        assert AMLRiskScoreTable.__tablename__ == "aml_risk_score"

    def test_table_args_defined(self):
        assert hasattr(AMLRiskScoreTable, "__table_args__")
        args = AMLRiskScoreTable.__table_args__
        assert isinstance(args, tuple)
        # Check for constraints and indexes
        constraints = [arg for arg in args if hasattr(arg, "name")]
        assert len(constraints) > 0


# ============================================================================
# INSTANTIATION TESTS
# ============================================================================

class TestAMLRiskScoreTableInstantiation:
    def test_instantiation(self, sample_aml_risk):
        assert isinstance(sample_aml_risk, AMLRiskScoreTable)
        assert sample_aml_risk.customer_type == "individual"
        assert sample_aml_risk.risk_score == Decimal("45.50")
        assert sample_aml_risk.risk_category == "medium"
        assert sample_aml_risk.version == 1

    def test_instantiation_with_defaults(self):
        risk = AMLRiskScoreTable(
            customer_id=uuid4(),
            risk_score=Decimal("10"),
            risk_category="low",
            customer_type="company",
        )
        assert risk.scoring_model == "rule_based"
        assert risk.manual_adjustment == Decimal("0")
        assert risk.pep_status is False
        assert risk.sanction_list_hit is False
        assert risk.calculated_at is not None


# ============================================================================
# PROPERTY TESTS
# ============================================================================

class TestAMLRiskScoreTableProperties:
    def test_is_high_risk_true_for_high(self, sample_high_risk):
        assert sample_high_risk.is_high_risk is True

    def test_is_high_risk_true_for_very_high(self, sample_very_high_risk):
        assert sample_very_high_risk.is_high_risk is True

    def test_is_high_risk_false_for_low(self, sample_low_risk):
        assert sample_low_risk.is_high_risk is False

    def test_is_high_risk_false_for_medium(self, sample_aml_risk):
        assert sample_aml_risk.is_high_risk is False

    def test_is_low_risk_true_for_low(self, sample_low_risk):
        assert sample_low_risk.is_low_risk is True

    def test_is_low_risk_false_for_medium(self, sample_aml_risk):
        assert sample_aml_risk.is_low_risk is False

    def test_is_low_risk_false_for_high(self, sample_high_risk):
        assert sample_high_risk.is_low_risk is False

    def test_effective_risk_score_no_adjustment(self, sample_aml_risk):
        assert sample_aml_risk.effective_risk_score == Decimal("45.50")

    def test_effective_risk_score_with_positive_adjustment(self, sample_aml_risk):
        sample_aml_risk.manual_adjustment = Decimal("10")
        assert sample_aml_risk.effective_risk_score == Decimal("55.50")

    def test_effective_risk_score_with_negative_adjustment(self, sample_aml_risk):
        sample_aml_risk.manual_adjustment = Decimal("-5")
        assert sample_aml_risk.effective_risk_score == Decimal("40.50")

    def test_effective_risk_score_with_zero_adjustment(self, sample_aml_risk):
        sample_aml_risk.manual_adjustment = Decimal("0")
        assert sample_aml_risk.effective_risk_score == Decimal("45.50")

    def test_is_expired_when_valid_until_in_future(self, sample_aml_risk):
        with patch("infrastructure.persistence_orm.aml_risk_score_table.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
            assert sample_aml_risk.is_expired is False

    def test_is_expired_when_valid_until_in_past(self, sample_aml_risk):
        with patch("infrastructure.persistence_orm.aml_risk_score_table.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2027, 6, 1, 12, 0, 0, tzinfo=UTC)
            assert sample_aml_risk.is_expired is True

    def test_is_expired_when_valid_until_is_none(self, sample_aml_risk):
        sample_aml_risk.valid_until = None
        with patch("infrastructure.persistence_orm.aml_risk_score_table.datetime") as mock_dt:
            mock_dt.utcnow.return_value = datetime(2099, 1, 1, 12, 0, 0, tzinfo=UTC)
            assert sample_aml_risk.is_expired is False


# ============================================================================
# METHOD TESTS
# ============================================================================

class TestAMLRiskScoreTableMethods:
    def test_update_risk_score_success(self, sample_aml_risk):
        old_version = sample_aml_risk.version
        with patch("infrastructure.persistence_orm.aml_risk_score_table.datetime") as mock_dt:
            fixed_now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
            mock_dt.utcnow.return_value = fixed_now
            sample_aml_risk.update_risk_score(
                new_score=Decimal("80"),
                new_category="high",
                risk_factors={"new_factor": 80},
                scoring_model="ml_model_v1"
            )
        assert sample_aml_risk.risk_score == Decimal("80")
        assert sample_aml_risk.risk_category == "high"
        assert sample_aml_risk.risk_factors == {"new_factor": 80}
        assert sample_aml_risk.scoring_model == "ml_model_v1"
        assert sample_aml_risk.calculated_at == fixed_now
        assert sample_aml_risk.version == old_version + 1

    def test_update_risk_score_without_optional_fields(self, sample_aml_risk):
        old_version = sample_aml_risk.version
        sample_aml_risk.update_risk_score(
            new_score=Decimal("30"),
            new_category="low",
        )
        assert sample_aml_risk.risk_score == Decimal("30")
        assert sample_aml_risk.risk_category == "low"
        # risk_factors and scoring_model remain unchanged
        assert sample_aml_risk.risk_factors == {"factor1": 20, "factor2": 25.5}
        assert sample_aml_risk.scoring_model == "rule_based"
        assert sample_aml_risk.version == old_version + 1

    def test_update_risk_score_invalid_score_low(self, sample_aml_risk):
        with pytest.raises(ValueError, match="Risk score must be between 0 and 100"):
            sample_aml_risk.update_risk_score(
                new_score=Decimal("-1"),
                new_category="low"
            )

    def test_update_risk_score_invalid_score_high(self, sample_aml_risk):
        with pytest.raises(ValueError, match="Risk score must be between 0 and 100"):
            sample_aml_risk.update_risk_score(
                new_score=Decimal("101"),
                new_category="high"
            )

    def test_apply_manual_adjustment_success(self, sample_aml_risk):
        old_version = sample_aml_risk.version
        adjusted_by = uuid4()
        with patch("infrastructure.persistence_orm.aml_risk_score_table.datetime") as mock_dt:
            fixed_now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
            mock_dt.utcnow.return_value = fixed_now
            sample_aml_risk.apply_manual_adjustment(
                adjustment=Decimal("15"),
                reason="Additional risk factor",
                adjusted_by=adjusted_by
            )
        assert sample_aml_risk.manual_adjustment == Decimal("15")
        assert sample_aml_risk.adjustment_reason == "Additional risk factor"
        assert sample_aml_risk.adjusted_by == adjusted_by
        assert sample_aml_risk.adjusted_at == fixed_now
        assert sample_aml_risk.version == old_version + 1

    def test_apply_manual_adjustment_negative(self, sample_aml_risk):
        old_version = sample_aml_risk.version
        adjusted_by = uuid4()
        sample_aml_risk.apply_manual_adjustment(
            adjustment=Decimal("-10"),
            reason="Overestimated",
            adjusted_by=adjusted_by
        )
        assert sample_aml_risk.manual_adjustment == Decimal("-10")
        assert sample_aml_risk.version == old_version + 1

    def test_apply_manual_adjustment_zero(self, sample_aml_risk):
        old_version = sample_aml_risk.version
        adjusted_by = uuid4()
        sample_aml_risk.apply_manual_adjustment(
            adjustment=Decimal("0"),
            reason="No change",
            adjusted_by=adjusted_by
        )
        assert sample_aml_risk.manual_adjustment == Decimal("0")
        assert sample_aml_risk.version == old_version + 1

    def test_apply_manual_adjustment_invalid_high(self, sample_aml_risk):
        with pytest.raises(ValueError, match="Adjustment must be between -100 and +100"):
            sample_aml_risk.apply_manual_adjustment(
                adjustment=Decimal("101"),
                reason="Too high",
                adjusted_by=uuid4()
            )

    def test_apply_manual_adjustment_invalid_low(self, sample_aml_risk):
        with pytest.raises(ValueError, match="Adjustment must be between -100 and +100"):
            sample_aml_risk.apply_manual_adjustment(
                adjustment=Decimal("-101"),
                reason="Too low",
                adjusted_by=uuid4()
            )

    def test_set_pep_status_true(self, sample_aml_risk):
        old_version = sample_aml_risk.version
        details = "Politically exposed person in government"
        sample_aml_risk.set_pep_status(is_pep=True, details=details)
        assert sample_aml_risk.pep_status is True
        assert sample_aml_risk.pep_details == details
        assert sample_aml_risk.version == old_version + 1

    def test_set_pep_status_false(self, sample_aml_risk):
        old_version = sample_aml_risk.version
        sample_aml_risk.set_pep_status(is_pep=False)
        assert sample_aml_risk.pep_status is False
        assert sample_aml_risk.pep_details is None
        assert sample_aml_risk.version == old_version + 1

    def test_set_pep_status_without_details(self, sample_aml_risk):
        old_version = sample_aml_risk.version
        sample_aml_risk.set_pep_status(is_pep=True)
        assert sample_aml_risk.pep_status is True
        assert sample_aml_risk.pep_details is None
        assert sample_aml_risk.version == old_version + 1

    def test_set_sanction_hit_true(self, sample_aml_risk):
        old_version = sample_aml_risk.version
        details = "OFAC sanction list"
        sample_aml_risk.set_sanction_hit(has_hit=True, details=details)
        assert sample_aml_risk.sanction_list_hit is True
        assert sample_aml_risk.sanction_list_details == details
        assert sample_aml_risk.version == old_version + 1

    def test_set_sanction_hit_false(self, sample_aml_risk):
        old_version = sample_aml_risk.version
        sample_aml_risk.set_sanction_hit(has_hit=False)
        assert sample_aml_risk.sanction_list_hit is False
        assert sample_aml_risk.sanction_list_details is None
        assert sample_aml_risk.version == old_version + 1

    def test_set_sanction_hit_without_details(self, sample_aml_risk):
        old_version = sample_aml_risk.version
        sample_aml_risk.set_sanction_hit(has_hit=True)
        assert sample_aml_risk.sanction_list_hit is True
        assert sample_aml_risk.sanction_list_details is None
        assert sample_aml_risk.version == old_version + 1

    def test_to_dict(self, sample_aml_risk):
        d = sample_aml_risk.to_dict()
        assert d["id"] == str(sample_aml_risk.id)
        assert d["customer_id"] == str(sample_aml_risk.customer_id)
        assert d["customer_type"] == "individual"
        assert d["risk_score"] == float(sample_aml_risk.risk_score)
        assert d["risk_category"] == "medium"
        assert d["scoring_model"] == "rule_based"
        assert d["risk_factors"] == {"factor1": 20, "factor2": 25.5}
        assert d["pep_status"] is False
        assert d["sanction_list_hit"] is False
        assert d["manual_adjustment"] == float(sample_aml_risk.manual_adjustment)
        assert d["effective_risk_score"] == float(sample_aml_risk.effective_risk_score)
        assert d["calculated_at"] == "2026-01-01T12:00:00+00:00"
        assert d["valid_until"] == "2027-01-01T12:00:00+00:00"
        assert d["legal_entity_id"] == str(sample_aml_risk.legal_entity_id)
        assert d["version"] == 1

    def test_to_dict_with_none_valid_until(self, sample_aml_risk):
        sample_aml_risk.valid_until = None
        d = sample_aml_risk.to_dict()
        assert d["valid_until"] is None


# ============================================================================
# EDGE CASES & NEGATIVE PATHS
# ============================================================================

class TestAMLRiskScoreTableEdgeCases:
    def test_update_risk_score_with_boundary_values(self, sample_aml_risk):
        # Test 0 and 100
        sample_aml_risk.update_risk_score(new_score=Decimal("0"), new_category="low")
        assert sample_aml_risk.risk_score == Decimal("0")

        sample_aml_risk.update_risk_score(new_score=Decimal("100"), new_category="high")
        assert sample_aml_risk.risk_score == Decimal("100")

    def test_apply_manual_adjustment_with_boundary_values(self, sample_aml_risk):
        # Test -100 and +100
        sample_aml_risk.apply_manual_adjustment(Decimal("100"), "max", uuid4())
        assert sample_aml_risk.manual_adjustment == Decimal("100")

        sample_aml_risk.apply_manual_adjustment(Decimal("-100"), "min", uuid4())
        assert sample_aml_risk.manual_adjustment == Decimal("-100")

    def test_effective_risk_score_after_update_and_adjustment(self, sample_aml_risk):
        sample_aml_risk.update_risk_score(new_score=Decimal("50"), new_category="medium")
        sample_aml_risk.apply_manual_adjustment(Decimal("10"), "adjust", uuid4())
        assert sample_aml_risk.effective_risk_score == Decimal("60")

    def test_version_increment_on_each_operation(self, sample_aml_risk):
        old_version = sample_aml_risk.version
        sample_aml_risk.update_risk_score(Decimal("20"), "low")
        assert sample_aml_risk.version == old_version + 1

        sample_aml_risk.apply_manual_adjustment(Decimal("5"), "reason", uuid4())
        assert sample_aml_risk.version == old_version + 2

        sample_aml_risk.set_pep_status(True)
        assert sample_aml_risk.version == old_version + 3

        sample_aml_risk.set_sanction_hit(True)
        assert sample_aml_risk.version == old_version + 4

    def test_is_expired_with_valid_until_equal_current(self, sample_aml_risk):
        with patch("infrastructure.persistence_orm.aml_risk_score_table.datetime") as mock_dt:
            # Set current time exactly equal to valid_until
            mock_dt.utcnow.return_value = datetime(2027, 1, 1, 12, 0, 0, tzinfo=UTC)
            assert sample_aml_risk.is_expired is False  # not >, so not expired
