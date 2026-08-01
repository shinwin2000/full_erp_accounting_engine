# tests/audit/sampling_materiality/test_audit_exception_aggregator.py
# Comprehensive tests for audit_exception_aggregator.py

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from audit.sampling_materiality.audit_exception_aggregator import (
    AuditExceptionAggregator,
    ExceptionPattern,
    ExceptionSeverity,
    ExceptionType,
    _get_logger,
    get_exception_aggregator,
)


class TestExceptionSeverity:
    def test_members_exist(self):
        assert hasattr(ExceptionSeverity, "TRIVIAL")
        assert hasattr(ExceptionSeverity, "MINOR")
        assert hasattr(ExceptionSeverity, "MODERATE")
        assert hasattr(ExceptionSeverity, "MAJOR")
        assert hasattr(ExceptionSeverity, "CRITICAL")

    def test_member_values(self):
        assert ExceptionSeverity.TRIVIAL.value == "trivial"
        assert ExceptionSeverity.CRITICAL.value == "critical"

    def test_member_is_instance(self):
        assert isinstance(ExceptionSeverity.TRIVIAL, ExceptionSeverity)


class TestExceptionType:
    def test_members_exist(self):
        expected = [
            "ACCURACY",
            "COMPLETENESS",
            "VALIDITY",
            "CUTOFF",
            "CLASSIFICATION",
            "AUTHORIZATION",
            "DOCUMENTATION",
            "SYSTEM",
        ]
        for name in expected:
            assert hasattr(ExceptionType, name)

    def test_member_values(self):
        assert ExceptionType.ACCURACY.value == "accuracy"
        assert ExceptionType.SYSTEM.value == "system"

    def test_member_is_instance(self):
        assert isinstance(ExceptionType.ACCURACY, ExceptionType)


class TestExceptionPattern:
    def test_members_exist(self):
        expected = ["ISOLATED", "CLUSTERED", "SYSTEMATIC", "FRAUD_INDICATOR"]
        for name in expected:
            assert hasattr(ExceptionPattern, name)

    def test_member_values(self):
        assert ExceptionPattern.ISOLATED.value == "isolated"
        assert ExceptionPattern.FRAUD_INDICATOR.value == "fraud_indicator"

    def test_member_is_instance(self):
        assert isinstance(ExceptionPattern.ISOLATED, ExceptionPattern)


class TestAuditExceptionAggregator:
    @pytest.fixture
    def aggregator(self):
        return AuditExceptionAggregator()

    @pytest.fixture
    def sample_exception(self):
        return {
            "amount": Decimal("50000000"),
            "description": "Invoice amount mismatch",
            "exception_type": ExceptionType.ACCURACY,
            "location": "Entity A",
            "date": datetime(2026, 1, 15, tzinfo=UTC),
        }

    @pytest.fixture
    def sample_exceptions(self):
        return [
            {
                "amount": Decimal("30000000"),
                "description": "Missing documentation",
                "exception_type": ExceptionType.DOCUMENTATION,
                "location": "Entity A",
                "date": datetime(2026, 1, 10, tzinfo=UTC),
            },
            {
                "amount": Decimal("150000000"),
                "description": "Unauthorized transaction",
                "exception_type": ExceptionType.AUTHORIZATION,
                "location": "Entity B",
                "date": datetime(2026, 1, 12, tzinfo=UTC),
            },
            {
                "amount": Decimal("25000000"),
                "description": "Cutoff error",
                "exception_type": ExceptionType.CUTOFF,
                "location": "Entity A",
                "date": datetime(2026, 1, 14, tzinfo=UTC),
            },
        ]

    # --- test _get_logger lazy initialization ---
    def test_get_logger_returns_logger(self):
        with patch("importlib.import_module") as mock_import:
            mock_module = MagicMock()
            mock_module.get_logger.return_value = MagicMock()
            mock_import.return_value = mock_module
            logger = _get_logger()
            assert logger is not None
            mock_import.assert_called_once_with("infrastructure.telemetry.structured_json_logging")

    def test_get_logger_caches(self):
        with patch("importlib.import_module") as mock_import:
            mock_module = MagicMock()
            mock_module.get_logger.return_value = MagicMock()
            mock_import.return_value = mock_module
            logger1 = _get_logger()
            logger2 = _get_logger()
            assert logger1 is logger2
            assert mock_import.call_count == 1

    # --- add_exception ---
    def test_add_exception_auto_severity(self, aggregator, sample_exception):
        # amount = 50,000,000 -> moderate (10M - 100M)
        aggregator.add_exception(sample_exception)
        assert len(aggregator._exceptions) == 1
        added = aggregator._exceptions[0]
        assert added["severity"] == ExceptionSeverity.MODERATE
        assert "added_at" in added

    def test_add_exception_severity_trivial(self, aggregator):
        exc = {"amount": Decimal("50000"), "exception_type": ExceptionType.VALIDITY}
        aggregator.add_exception(exc)
        assert aggregator._exceptions[0]["severity"] == ExceptionSeverity.TRIVIAL

    def test_add_exception_severity_minor(self, aggregator):
        exc = {"amount": Decimal("500000"), "exception_type": ExceptionType.VALIDITY}
        aggregator.add_exception(exc)
        assert aggregator._exceptions[0]["severity"] == ExceptionSeverity.MINOR

    def test_add_exception_severity_moderate(self, aggregator):
        exc = {"amount": Decimal("5000000"), "exception_type": ExceptionType.VALIDITY}
        aggregator.add_exception(exc)
        assert aggregator._exceptions[0]["severity"] == ExceptionSeverity.MODERATE

    def test_add_exception_severity_major(self, aggregator):
        exc = {"amount": Decimal("50000000"), "exception_type": ExceptionType.VALIDITY}
        aggregator.add_exception(exc)
        assert aggregator._exceptions[0]["severity"] == ExceptionSeverity.MAJOR

    def test_add_exception_severity_critical(self, aggregator):
        exc = {"amount": Decimal("200000000"), "exception_type": ExceptionType.VALIDITY}
        aggregator.add_exception(exc)
        assert aggregator._exceptions[0]["severity"] == ExceptionSeverity.CRITICAL

    def test_add_exception_preserves_severity(self, aggregator):
        exc = {
            "amount": Decimal("50000000"),
            "severity": ExceptionSeverity.MINOR,  # override
            "exception_type": ExceptionType.VALIDITY,
        }
        aggregator.add_exception(exc)
        assert aggregator._exceptions[0]["severity"] == ExceptionSeverity.MINOR

    # --- add_exceptions_batch ---
    def test_add_exceptions_batch(self, aggregator, sample_exceptions):
        aggregator.add_exceptions_batch(sample_exceptions)
        assert len(aggregator._exceptions) == 3

    # --- get_summary ---
    def test_get_summary_empty(self, aggregator):
        summary = aggregator.get_summary()
        assert summary["total_exceptions"] == 0
        assert summary["total_error_amount"] == 0

    def test_get_summary_with_data(self, aggregator, sample_exceptions):
        aggregator.add_exceptions_batch(sample_exceptions)
        summary = aggregator.get_summary()
        assert summary["total_exceptions"] == 3
        total_error = 30000000 + 150000000 + 25000000  # 205,000,000
        assert summary["total_error_amount"] == float(total_error)
        assert summary["average_error"] == float(total_error / 3)
        assert summary["largest_error"] == float(150000000)
        assert summary["by_severity"] == {
            "moderate": 2,  # 30M and 25M
            "critical": 1,  # 150M
        }
        assert summary["by_type"] == {
            "documentation": 1,
            "authorization": 1,
            "cutoff": 1,
        }

    # --- detect_patterns ---
    def test_detect_patterns_empty(self, aggregator):
        patterns = aggregator.detect_patterns()
        # Should still return isolated pattern (total=0, but logic may produce something)
        # Actually with total=0, it may not add clustered, but isolated is added if total>0
        # Let's check behavior: if total=0, max_cluster = 0, so clustered not added; isolated added?
        # In code: if total > 0: ... else: patterns.append(isolated). So with total=0, no isolated
        # Actually total=0, so nothing added. So patterns empty.
        assert patterns == []

    def test_detect_patterns_isolated(self, aggregator, sample_exceptions):
        # Exceptions spread across locations: Entity A (2), Entity B (1) => not clustered (>0.7)
        aggregator.add_exceptions_batch(sample_exceptions)
        patterns = aggregator.detect_patterns()
        pattern_types = [p["pattern"] for p in patterns]
        assert ExceptionPattern.ISOLATED.value in pattern_types
        # Check that systematic not present (types all different)
        assert ExceptionPattern.SYSTEMATIC.value not in pattern_types

    def test_detect_patterns_clustered(self, aggregator):
        # All exceptions in same location
        excs = [
            {"amount": Decimal("10000"), "exception_type": ExceptionType.ACCURACY, "location": "Entity X"},
            {"amount": Decimal("20000"), "exception_type": ExceptionType.ACCURACY, "location": "Entity X"},
            {"amount": Decimal("30000"), "exception_type": ExceptionType.ACCURACY, "location": "Entity X"},
        ]
        aggregator.add_exceptions_batch(excs)
        patterns = aggregator.detect_patterns()
        pattern_types = [p["pattern"] for p in patterns]
        assert ExceptionPattern.CLUSTERED.value in pattern_types
        assert ExceptionPattern.ISOLATED.value not in pattern_types

    def test_detect_patterns_systematic(self, aggregator):
        # Same exception type for majority
        excs = [
            {"amount": Decimal("10000"), "exception_type": ExceptionType.ACCURACY, "location": "A"},
            {"amount": Decimal("20000"), "exception_type": ExceptionType.ACCURACY, "location": "B"},
            {"amount": Decimal("30000"), "exception_type": ExceptionType.ACCURACY, "location": "C"},
            {"amount": Decimal("40000"), "exception_type": ExceptionType.COMPLETENESS, "location": "D"},
        ]
        aggregator.add_exceptions_batch(excs)
        patterns = aggregator.detect_patterns()
        pattern_types = [p["pattern"] for p in patterns]
        # 3 out of 4 are accuracy (75%) -> systematic
        assert ExceptionPattern.SYSTEMATIC.value in pattern_types

    def test_detect_patterns_fraud_indicator(self, aggregator):
        # High value exceptions
        excs = [
            {"amount": Decimal("150000000"), "exception_type": ExceptionType.ACCURACY, "location": "A"},
            {"amount": Decimal("200000000"), "exception_type": ExceptionType.ACCURACY, "location": "B"},
            {"amount": Decimal("50000"), "exception_type": ExceptionType.ACCURACY, "location": "C"},
        ]
        aggregator.add_exceptions_batch(excs)
        patterns = aggregator.detect_patterns()
        pattern_types = [p["pattern"] for p in patterns]
        assert ExceptionPattern.FRAUD_INDICATOR.value in pattern_types

    def test_detect_patterns_user_clustering(self, aggregator):
        excs = [
            {"amount": Decimal("10000"), "exception_type": ExceptionType.ACCURACY, "location": "A", "user_id": "user1"},
            {"amount": Decimal("20000"), "exception_type": ExceptionType.ACCURACY, "location": "B", "user_id": "user1"},
            {"amount": Decimal("30000"), "exception_type": ExceptionType.ACCURACY, "location": "C", "user_id": "user1"},
            {"amount": Decimal("40000"), "exception_type": ExceptionType.ACCURACY, "location": "D", "user_id": "user2"},
        ]
        aggregator.add_exceptions_batch(excs)
        patterns = aggregator.detect_patterns()
        # Should detect clustered pattern for user1 (3 exceptions)
        assert any(p["pattern"] == ExceptionPattern.CLUSTERED.value and "user1" in p["description"] for p in patterns)

    # --- evaluate_against_materiality ---
    def test_evaluate_against_materiality(self, aggregator, sample_exceptions):
        aggregator.add_exceptions_batch(sample_exceptions)
        total_error = 205000000  # as above
        threshold = Decimal("200000000")
        result = aggregator.evaluate_against_materiality(threshold)
        assert result["total_error"] == float(total_error)
        assert result["materiality_threshold"] == float(threshold)
        assert result["is_material"] is True
        assert result["percentage_of_materiality"] == pytest.approx(102.5)
        assert result["conclusion"] == "Material"

    def test_evaluate_against_materiality_not_material(self, aggregator, sample_exceptions):
        aggregator.add_exceptions_batch(sample_exceptions)
        threshold = Decimal("300000000")
        result = aggregator.evaluate_against_materiality(threshold)
        assert result["is_material"] is False
        assert result["percentage_of_materiality"] == pytest.approx(68.33)
        assert result["conclusion"] == "Not material"

    # --- generate_recommendations ---
    def test_generate_recommendations_empty(self, aggregator):
        recs = aggregator.generate_recommendations()
        assert len(recs) == 1
        assert recs[0] == "No exceptions found. No further action required."

    def test_generate_recommendations_with_data(self, aggregator, sample_exceptions):
        aggregator.add_exceptions_batch(sample_exceptions)
        recs = aggregator.generate_recommendations()
        # Expect at least one recommendation about total error
        assert any("Total error amount" in r for r in recs)
        # Since there is an authorization exception >2, should have authorization recommendation
        assert any("authorization" in r.lower() for r in recs)

    def test_generate_recommendations_fraud_pattern(self, aggregator):
        excs = [
            {"amount": Decimal("150000000"), "exception_type": ExceptionType.ACCURACY, "location": "A"},
            {"amount": Decimal("200000000"), "exception_type": ExceptionType.ACCURACY, "location": "B"},
        ]
        aggregator.add_exceptions_batch(excs)
        recs = aggregator.generate_recommendations()
        assert any("URGENT" in r for r in recs)

    def test_generate_recommendations_systematic(self, aggregator):
        excs = [
            {"amount": Decimal("10000"), "exception_type": ExceptionType.ACCURACY, "location": "A"},
            {"amount": Decimal("20000"), "exception_type": ExceptionType.ACCURACY, "location": "B"},
            {"amount": Decimal("30000"), "exception_type": ExceptionType.ACCURACY, "location": "C"},
        ]
        aggregator.add_exceptions_batch(excs)
        recs = aggregator.generate_recommendations()
        assert any("Systematic error" in r for r in recs)

    # --- clear ---
    def test_clear(self, aggregator, sample_exception):
        aggregator.add_exception(sample_exception)
        assert len(aggregator._exceptions) == 1
        aggregator.clear()
        assert len(aggregator._exceptions) == 0

    # --- get_exceptions ---
    def test_get_exceptions_no_filter(self, aggregator, sample_exceptions):
        aggregator.add_exceptions_batch(sample_exceptions)
        all_exc = aggregator.get_exceptions()
        assert len(all_exc) == 3

    def test_get_exceptions_filter_by_severity(self, aggregator, sample_exceptions):
        aggregator.add_exceptions_batch(sample_exceptions)
        moderate = aggregator.get_exceptions(severity=ExceptionSeverity.MODERATE)
        assert len(moderate) == 2  # 30M and 25M are moderate
        critical = aggregator.get_exceptions(severity=ExceptionSeverity.CRITICAL)
        assert len(critical) == 1  # 150M is critical
        trivial = aggregator.get_exceptions(severity=ExceptionSeverity.TRIVIAL)
        assert len(trivial) == 0

    def test_get_exceptions_filter_by_type(self, aggregator, sample_exceptions):
        aggregator.add_exceptions_batch(sample_exceptions)
        doc = aggregator.get_exceptions(exception_type=ExceptionType.DOCUMENTATION)
        assert len(doc) == 1
        auth = aggregator.get_exceptions(exception_type=ExceptionType.AUTHORIZATION)
        assert len(auth) == 1
        cutoff = aggregator.get_exceptions(exception_type=ExceptionType.CUTOFF)
        assert len(cutoff) == 1

    def test_get_exceptions_filter_by_severity_and_type(self, aggregator, sample_exceptions):
        aggregator.add_exceptions_batch(sample_exceptions)
        result = aggregator.get_exceptions(
            severity=ExceptionSeverity.MODERATE,
            exception_type=ExceptionType.DOCUMENTATION,
        )
        assert len(result) == 1

    # --- get_statistics_by_type ---
    def test_get_statistics_by_type_empty(self, aggregator):
        stats = aggregator.get_statistics_by_type()
        assert stats == {}

    def test_get_statistics_by_type_with_data(self, aggregator, sample_exceptions):
        aggregator.add_exceptions_batch(sample_exceptions)
        stats = aggregator.get_statistics_by_type()
        # Expect entries for DOCUMENTATION, AUTHORIZATION, CUTOFF
        assert set(stats.keys()) == {"documentation", "authorization", "cutoff"}
        assert stats["documentation"]["count"] == 1
        assert stats["documentation"]["total_amount"] == float(30000000)
        assert stats["documentation"]["average_amount"] == float(30000000)
        assert stats["authorization"]["count"] == 1
        assert stats["authorization"]["total_amount"] == float(150000000)
        assert stats["cutoff"]["count"] == 1
        assert stats["cutoff"]["total_amount"] == float(25000000)


# --- singleton test ---
class TestSingleton:
    def test_get_exception_aggregator_singleton(self):
        agg1 = get_exception_aggregator()
        agg2 = get_exception_aggregator()
        assert agg1 is agg2
        assert isinstance(agg1, AuditExceptionAggregator)

    def test_get_exception_aggregator_resets_on_new_instance(self):
        # Since we use a global, we can't easily reset, but we can test that
        # calling get_exception_aggregator returns the same instance.
        agg1 = get_exception_aggregator()
        agg1.add_exception({"amount": Decimal("1000"), "exception_type": ExceptionType.ACCURACY})
        agg2 = get_exception_aggregator()
        assert len(agg2._exceptions) == 1  # same instance
