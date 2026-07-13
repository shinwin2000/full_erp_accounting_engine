"""
Tests for kernel.error_analysis module.
Comprehensive unit tests for Root Cause Analysis (RCA) functionality.
"""

import logging
from unittest.mock import MagicMock

import pytest

from kernel.error_analysis import RCAResult, analyze_error, log_rca_result


class TestRCAResult:
    def test_construction_with_defaults(self):
        result = RCAResult()
        assert result.severity == "UNKNOWN"
        assert result.category == "Unknown"
        assert result.error_code == "UNKNOWN"
        assert result.root_cause == ""
        assert result.evidence == []
        assert result.impact == []
        assert result.suggested_fix == ""
        assert result.confidence == 0.0
        assert result._raw is None

    def test_construction_with_values(self):
        evidence = ["error1", "error2"]
        impact = ["impact1"]
        result = RCAResult(
            severity="CRITICAL",
            category="Database",
            error_code="DB_CONN_FAIL",
            root_cause="Connection timeout",
            evidence=evidence,
            impact=impact,
            suggested_fix="Check database connection",
            confidence=0.95,
            _raw={"original": "data"},
        )
        assert result.severity == "CRITICAL"
        assert result.category == "Database"
        assert result.error_code == "DB_CONN_FAIL"
        assert result.root_cause == "Connection timeout"
        assert result.evidence == evidence
        assert result.impact == impact
        assert result.suggested_fix == "Check database connection"
        assert result.confidence == 0.95
        assert result._raw == {"original": "data"}

    def test_construction_with_none_lists(self):
        result = RCAResult(evidence=None, impact=None)
        assert result.evidence == []
        assert result.impact == []

    def test_to_dict(self):
        result = RCAResult(
            severity="HIGH",
            category="Network",
            error_code="NET_TIMEOUT",
            root_cause="Network timeout after 30s",
            evidence=["trace1", "trace2", "trace3"],
            impact=["service_down"],
            suggested_fix="Increase timeout or check network",
            confidence=0.87654321,
        )
        d = result.to_dict()
        assert d["severity"] == "HIGH"
        assert d["category"] == "Network"
        assert d["error_code"] == "NET_TIMEOUT"
        assert d["root_cause"] == "Network timeout after 30s"
        assert d["evidence"] == ["trace1", "trace2", "trace3"]
        assert d["impact"] == ["service_down"]
        assert d["suggested_fix"] == "Increase timeout or check network"
        assert d["confidence"] == 0.8765

    def test_to_dict_truncates_large_lists(self):
        result = RCAResult(
            evidence=[f"e{i}" for i in range(20)],
            impact=[f"i{i}" for i in range(10)],
        )
        d = result.to_dict()
        assert len(d["evidence"]) == 10
        assert len(d["impact"]) == 5

    def test_summary(self):
        result = RCAResult(
            severity="CRITICAL",
            root_cause="Database connection failed due to timeout",
        )
        summary = result.summary()
        assert summary == "[CRITICAL] Database connection failed due to timeout"

    def test_summary_truncates_long_root_cause(self):
        long_cause = "A" * 100
        result = RCAResult(severity="HIGH", root_cause=long_cause)
        summary = result.summary()
        assert len(summary) == 87
        assert summary.startswith("[HIGH] ")
        assert summary.endswith("A" * 80)

    def test_is_fatal_or_critical_true(self):
        fatal = RCAResult(severity="FATAL")
        critical = RCAResult(severity="CRITICAL")
        assert fatal.is_fatal_or_critical() is True
        assert critical.is_fatal_or_critical() is True

    def test_is_fatal_or_critical_false(self):
        for severity in ["HIGH", "MEDIUM", "LOW", "UNKNOWN", "INFO"]:
            result = RCAResult(severity=severity)
            assert result.is_fatal_or_critical() is False, f"Failed for {severity}"

    def test_repr(self):
        result = RCAResult(severity="HIGH", confidence=0.75)
        repr_str = repr(result)
        assert "RCAResult" in repr_str
        assert "severity=HIGH" in repr_str
        assert "confidence=0.75" in repr_str

    def test_slots_efficiency(self):
        assert hasattr(RCAResult, "__slots__")
        result = RCAResult()
        assert not hasattr(result, "__dict__")


class TestAnalyzeError:
    @pytest.fixture(autouse=True)
    def reset_rca_engine(self):
        import kernel.error_analysis as module
        module._RCA_ENGINE = None
        module._RCA_AVAILABLE = False
        yield
        module._RCA_ENGINE = None
        module._RCA_AVAILABLE = False

    def test_fallback_when_no_rca_engine(self):
        import kernel.error_analysis as module
        module._RCA_AVAILABLE = False
        exc = ValueError("Test error")
        result = analyze_error(exc, context={"user": "test"})
        assert isinstance(result, RCAResult)
        assert result.severity == "MEDIUM"
        assert result.category == "DDD"
        assert result.error_code == "RCA063"
        assert "ValueError: Test error" in result.root_cause
        assert result.confidence == 0.5

    def test_fallback_includes_exception_details(self):
        import kernel.error_analysis as module
        module._RCA_AVAILABLE = False
        exc = RuntimeError("Something went wrong")
        result = analyze_error(exc)
        assert "RuntimeError: Something went wrong" in result.root_cause


class TestLogRCAResult:
    def test_logs_critical_at_critical_level(self):
        logger = MagicMock(spec=logging.Logger)
        rca = RCAResult(severity="CRITICAL", root_cause="Critical issue", confidence=0.9)
        log_rca_result(logger, rca, prefix="TEST")
        logger.log.assert_called()
        call_args = logger.log.call_args
        assert call_args[0][0] == logging.CRITICAL

    def test_logs_high_at_error_level(self):
        logger = MagicMock(spec=logging.Logger)
        rca = RCAResult(severity="HIGH", root_cause="High issue", confidence=0.8)
        log_rca_result(logger, rca, prefix="TEST")
        call_args = logger.log.call_args
        assert call_args[0][0] == logging.ERROR

    def test_logs_low_at_warning_level(self):
        logger = MagicMock(spec=logging.Logger)
        rca = RCAResult(severity="LOW", root_cause="Low issue", confidence=0.5)
        log_rca_result(logger, rca, prefix="TEST")
        call_args = logger.log.call_args
        assert call_args[0][0] == logging.WARNING

    def test_message_format(self):
        logger = MagicMock(spec=logging.Logger)
        rca = RCAResult(severity="HIGH", root_cause="Database connection timeout", confidence=0.85)
        log_rca_result(logger, rca, prefix="RCA")
        call_args = logger.log.call_args
        message = call_args[0][1]
        assert "RCA [HIGH]" in message
        assert "conf=0.85" in message

    def test_default_prefix(self):
        logger = MagicMock(spec=logging.Logger)
        rca = RCAResult(severity="HIGH", root_cause="Test", confidence=0.8)
        log_rca_result(logger, rca)
        call_args = logger.log.call_args
        message = call_args[0][1]
        assert "RCA" in message


class TestIntegration:
    @pytest.fixture(autouse=True)
    def reset_rca_engine(self):
        import kernel.error_analysis as module
        module._RCA_ENGINE = None
        module._RCA_AVAILABLE = False
        yield
        module._RCA_ENGINE = None
        module._RCA_AVAILABLE = False

    def test_full_workflow_fallback(self):
        import kernel.error_analysis as module
        module._RCA_AVAILABLE = False
        exc = ValueError("Invalid input provided")
        result = analyze_error(exc, context={"user": "admin", "action": "delete"})
        assert isinstance(result, RCAResult)
        assert result.is_fatal_or_critical() is False
        d = result.to_dict()
        assert d["severity"] == "MEDIUM"
        assert "Invalid input" in d["root_cause"]

    def test_multiple_severity_levels(self):
        severities = ["FATAL", "CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]
        for sev in severities:
            result = RCAResult(severity=sev, root_cause=f"Test {sev}", confidence=0.5)
            d = result.to_dict()
            assert d["severity"] == sev
            if sev in ("FATAL", "CRITICAL"):
                assert result.is_fatal_or_critical() is True
            else:
                assert result.is_fatal_or_critical() is False

    def test_confidence_rounding(self):
        result = RCAResult(confidence=0.123456789)
        d = result.to_dict()
        assert d["confidence"] == 0.1235
