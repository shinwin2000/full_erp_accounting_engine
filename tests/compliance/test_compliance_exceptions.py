# tests/compliance/test_compliance_exceptions.py
# Comprehensive tests for compliance/compliance_exceptions.py
# Covers all exception classes, their constructors, to_dict, to_json, __str__,
# and ComplianceExceptionAggregator functionality.

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from compliance.compliance_exceptions import (
    AMLViolationError,
    ComplianceError,
    ComplianceExceptionAggregator,
    ConflictOfInterestError,
    ConsentMissingError,
    ControlTestFailureError,
    CoretaxAPIError,
    DataBreachNotificationError,
    DataSubjectRequestError,
    EDDRequiredError,
    ErrorCategory,
    ErrorSeverity,
    EthicsError,
    FakturValidationError,
    GDPRViolationError,
    JurisdictionError,
    LegalError,
    ProfessionalJudgmentError,
    ReportGenerationError,
    ReportingError,
    SOXViolationError,
    SPTSubmissionError,
    SanctionListHitError,
    SegregationOfDutyError,
    SuspiciousTransactionReported,
    TaxComplianceError,
)


# ============================================================================
# Enum tests
# ============================================================================

class TestErrorSeverity:
    def test_members(self):
        assert ErrorSeverity.INFO.value == "info"
        assert ErrorSeverity.WARNING.value == "warning"
        assert ErrorSeverity.ERROR.value == "error"
        assert ErrorSeverity.CRITICAL.value == "critical"
        assert ErrorSeverity.FATAL.value == "fatal"


class TestErrorCategory:
    def test_members(self):
        assert ErrorCategory.AML.value == "anti_money_laundering"
        assert ErrorCategory.GDPR.value == "data_privacy"
        assert ErrorCategory.SOX.value == "internal_control"
        assert ErrorCategory.TAX.value == "taxation"
        assert ErrorCategory.REPORTING.value == "reporting"
        assert ErrorCategory.ETHICS.value == "ethics"
        assert ErrorCategory.LEGAL.value == "legal"
        assert ErrorCategory.GENERAL.value == "general"


# ============================================================================
# Base ComplianceError tests
# ============================================================================

class TestComplianceError:
    def test_construction_minimal(self):
        exc = ComplianceError(message="Test error")
        assert exc.message == "Test error"
        assert exc.code == "COMPLIANCEERROR"
        assert exc.severity == ErrorSeverity.ERROR
        assert exc.category == ErrorCategory.GENERAL
        assert exc.context == {}
        assert exc.cause is None
        assert exc.timestamp is not None
        assert exc._traceback is None

    def test_construction_full(self):
        cause = ValueError("root cause")
        exc = ComplianceError(
            message="Test error",
            code="TEST_CODE",
            severity=ErrorSeverity.CRITICAL,
            category=ErrorCategory.AML,
            context={"key": "value"},
            cause=cause,
        )
        assert exc.message == "Test error"
        assert exc.code == "TEST_CODE"
        assert exc.severity == ErrorSeverity.CRITICAL
        assert exc.category == ErrorCategory.AML
        assert exc.context == {"key": "value"}
        assert exc.cause is cause
        assert exc._traceback is not None

    def test_to_dict(self):
        exc = ComplianceError(
            message="Test error",
            code="TEST_CODE",
            severity=ErrorSeverity.ERROR,
            category=ErrorCategory.GENERAL,
            context={"key": "value"},
        )
        d = exc.to_dict()
        assert d["error_class"] == "ComplianceError"
        assert d["code"] == "TEST_CODE"
        assert d["message"] == "Test error"
        assert d["severity"] == "error"
        assert d["category"] == "general"
        assert d["context"] == {"key": "value"}
        assert d["cause"] is None
        assert "timestamp" in d

    def test_to_dict_with_cause(self):
        cause = ValueError("root")
        exc = ComplianceError(message="Test", cause=cause)
        d = exc.to_dict()
        assert d["cause"] == "root"

    def test_to_json(self):
        exc = ComplianceError(message="Test error", code="TEST")
        json_str = exc.to_json()
        data = json.loads(json_str)
        assert data["message"] == "Test error"
        assert data["code"] == "TEST"

    def test_str_representation(self):
        exc = ComplianceError(message="Test error", code="TEST_CODE")
        assert str(exc) == "[ERROR] TEST_CODE: Test error"


# ============================================================================
# AML Exception tests (parameterized for consistency)
# ============================================================================

class TestAMLViolationError:
    def test_construction(self):
        exc = AMLViolationError(message="AML violation", code="AML001", context={"tx": "123"})
        assert exc.message == "AML violation"
        assert exc.code == "AML001"
        assert exc.severity == ErrorSeverity.CRITICAL
        assert exc.category == ErrorCategory.AML
        assert exc.context == {"tx": "123"}

    def test_default_code(self):
        exc = AMLViolationError(message="AML violation")
        assert exc.code == "AML_VIOLATION"


class TestSanctionListHitError:
    def test_construction(self):
        exc = SanctionListHitError(
            name="John Doe",
            sanction_list="OFAC",
            transaction_id="tx-123",
            context={"amount": "1000"},
        )
        assert exc.message == "Sanction list hit: 'John Doe' found in OFAC"
        assert exc.code == "SANCTION_HIT"
        assert exc.severity == ErrorSeverity.CRITICAL
        assert exc.category == ErrorCategory.AML
        assert exc.context["name"] == "John Doe"
        assert exc.context["sanction_list"] == "OFAC"
        assert exc.context["transaction_id"] == "tx-123"
        assert exc.context["amount"] == "1000"

    def test_construction_minimal(self):
        exc = SanctionListHitError(name="Jane Doe", sanction_list="UN")
        assert exc.context["name"] == "Jane Doe"
        assert exc.context["sanction_list"] == "UN"
        assert exc.context.get("transaction_id") is None


class TestSTRRequiredError:
    def test_construction(self):
        exc = STRRequiredError(
            transaction_id="tx-456",
            risk_score=85,
            reasons=["High velocity", "Offshore account"],
            context={"customer": "cust-1"},
        )
        assert exc.message == "Suspicious transaction tx-456 requires STR (score: 85)"
        assert exc.code == "STR_REQUIRED"
        assert exc.severity == ErrorSeverity.CRITICAL
        assert exc.category == ErrorCategory.AML
        assert exc.context["transaction_id"] == "tx-456"
        assert exc.context["risk_score"] == 85
        assert exc.context["reasons"] == ["High velocity", "Offshore account"]
        assert exc.context["customer"] == "cust-1"


class TestEDDRequiredError:
    def test_construction(self):
        exc = EDDRequiredError(
            customer_id="cust-789",
            risk_level="high",
            context={"country": "XX"},
        )
        assert exc.message == "EDD required for customer cust-789 (risk level: high)"
        assert exc.code == "EDD_REQUIRED"
        assert exc.severity == ErrorSeverity.CRITICAL
        assert exc.category == ErrorCategory.AML
        assert exc.context["customer_id"] == "cust-789"
        assert exc.context["risk_level"] == "high"
        assert exc.context["country"] == "XX"


class TestSuspiciousTransactionReported:
    def test_construction(self):
        exc = SuspiciousTransactionReported(
            message="Suspicious transaction reported",
            report_id="STR-2026-001",
            destination="PPATK",
            context={"transaction_id": "tx-123"},
        )
        assert exc.message == "Suspicious transaction reported"
        assert exc.code == "SUSPICIOUS_REPORTED"
        assert exc.severity == ErrorSeverity.WARNING
        assert exc.category == ErrorCategory.AML
        assert exc.report_id == "STR-2026-001"
        assert exc.destination == "PPATK"
        assert exc.context["transaction_id"] == "tx-123"

    def test_default_destination(self):
        exc = SuspiciousTransactionReported(message="Test", report_id="STR-001")
        assert exc.destination == "PPATK"


# ============================================================================
# GDPR Exception tests
# ============================================================================

class TestGDPRViolationError:
    def test_construction(self):
        exc = GDPRViolationError(
            message="GDPR violation",
            code="GDPR001",
            context={"data": "personal"},
            cause=ValueError("cause"),
        )
        assert exc.message == "GDPR violation"
        assert exc.code == "GDPR001"
        assert exc.severity == ErrorSeverity.HIGH
        assert exc.category == ErrorCategory.GDPR
        assert exc.context == {"data": "personal"}
        assert exc.cause is not None

    def test_default_code(self):
        exc = GDPRViolationError(message="GDPR violation")
        assert exc.code == "GDPR_VIOLATION"


class TestConsentMissingError:
    def test_construction(self):
        exc = ConsentMissingError(
            user_id="user-123",
            purpose="marketing",
            context={"channel": "email"},
        )
        assert exc.message == "Consent missing for user user-123 to process data for purpose: marketing"
        assert exc.code == "CONSENT_MISSING"
        assert exc.severity == ErrorSeverity.HIGH
        assert exc.category == ErrorCategory.GDPR
        assert exc.context["user_id"] == "user-123"
        assert exc.context["purpose"] == "marketing"
        assert exc.context["channel"] == "email"


class TestDataSubjectRequestError:
    def test_construction(self):
        exc = DataSubjectRequestError(
            request_id="dsr-456",
            reason="Identity verification failed",
            context={"verification_attempts": 3},
        )
        assert exc.message == "Data subject request dsr-456 failed: Identity verification failed"
        assert exc.code == "DSR_ERROR"
        assert exc.severity == ErrorSeverity.HIGH
        assert exc.category == ErrorCategory.GDPR
        assert exc.context["request_id"] == "dsr-456"
        assert exc.context["reason"] == "Identity verification failed"
        assert exc.context["verification_attempts"] == 3


class TestDataBreachNotificationError:
    def test_construction(self):
        exc = DataBreachNotificationError(
            breach_id="br-789",
            reason="Supervisory authority unreachable",
            context={"attempts": 5},
        )
        assert exc.message == "Data breach notification failed for breach br-789: Supervisory authority unreachable"
        assert exc.code == "BREACH_NOTIFY_FAIL"
        assert exc.severity == ErrorSeverity.HIGH
        assert exc.category == ErrorCategory.GDPR
        assert exc.context["breach_id"] == "br-789"
        assert exc.context["reason"] == "Supervisory authority unreachable"
        assert exc.context["attempts"] == 5


# ============================================================================
# SOX Exception tests
# ============================================================================

class TestSOXViolationError:
    def test_construction(self):
        exc = SOXViolationError(
            message="SOX violation",
            code="SOX001",
            context={"control": "C-001"},
            cause=ValueError("cause"),
        )
        assert exc.message == "SOX violation"
        assert exc.code == "SOX001"
        assert exc.severity == ErrorSeverity.CRITICAL
        assert exc.category == ErrorCategory.SOX
        assert exc.context == {"control": "C-001"}

    def test_default_code(self):
        exc = SOXViolationError(message="SOX violation")
        assert exc.code == "SOX_VIOLATION"


class TestControlTestFailureError:
    def test_construction(self):
        exc = ControlTestFailureError(
            control_id="C-001",
            test_details="Segregation of duties failed",
            context={"test_date": "2026-01-01"},
        )
        assert exc.message == "Control test failed for C-001: Segregation of duties failed"
        assert exc.code == "CONTROL_FAIL"
        assert exc.severity == ErrorSeverity.CRITICAL
        assert exc.category == ErrorCategory.SOX
        assert exc.context["control_id"] == "C-001"
        assert exc.context["test_details"] == "Segregation of duties failed"
        assert exc.context["test_date"] == "2026-01-01"


class TestSegregationOfDutyError:
    def test_construction(self):
        exc = SegregationOfDutyError(
            user_id="user-123",
            role_a="approver",
            role_b="requester",
            context={"department": "finance"},
        )
        assert exc.message == "User user-123 has conflicting roles: approver and requester"
        assert exc.code == "SOD_VIOLATION"
        assert exc.severity == ErrorSeverity.CRITICAL
        assert exc.category == ErrorCategory.SOX
        assert exc.context["user_id"] == "user-123"
        assert exc.context["role_a"] == "approver"
        assert exc.context["role_b"] == "requester"
        assert exc.context["department"] == "finance"


# ============================================================================
# Tax Exception tests
# ============================================================================

class TestTaxComplianceError:
    def test_construction(self):
        exc = TaxComplianceError(
            message="Tax error",
            code="TAX001",
            context={"tax_period": "2026-01"},
            cause=ValueError("cause"),
        )
        assert exc.message == "Tax error"
        assert exc.code == "TAX001"
        assert exc.severity == ErrorSeverity.HIGH
        assert exc.category == ErrorCategory.TAX
        assert exc.context == {"tax_period": "2026-01"}

    def test_default_code(self):
        exc = TaxComplianceError(message="Tax error")
        assert exc.code == "TAX_ERROR"


class TestCoretaxAPIError:
    def test_construction(self):
        exc = CoretaxAPIError(
            endpoint="/api/submit",
            status_code=500,
            response_text="Internal Server Error",
            context={"request_id": "req-123"},
        )
        assert exc.message == "Coretax API error at /api/submit: HTTP 500 - Internal Server Error"
        assert exc.code == "CORETAX_API_ERROR"
        assert exc.severity == ErrorSeverity.HIGH
        assert exc.category == ErrorCategory.TAX
        assert exc.context["endpoint"] == "/api/submit"
        assert exc.context["status_code"] == 500
        assert exc.context["response"] == "Internal Server Error"
        assert exc.context["request_id"] == "req-123"

    def test_response_truncated(self):
        long_response = "x" * 1000
        exc = CoretaxAPIError("/api", 400, long_response)
        assert len(exc.context["response"]) == 500


class TestFakturValidationError:
    def test_construction(self):
        exc = FakturValidationError(
            faktur_number="FAKTUR-001",
            errors=["NPWP tidak valid", "Tanggal tidak sesuai"],
            context={"supplier": "SUP-1"},
        )
        assert exc.message == "Faktur FAKTUR-001 validation failed: NPWP tidak valid, Tanggal tidak sesuai"
        assert exc.code == "FAKTUR_INVALID"
        assert exc.severity == ErrorSeverity.HIGH
        assert exc.category == ErrorCategory.TAX
        assert exc.context["faktur_number"] == "FAKTUR-001"
        assert exc.context["errors"] == ["NPWP tidak valid", "Tanggal tidak sesuai"]
        assert exc.context["supplier"] == "SUP-1"


class TestSPTSubmissionError:
    def test_construction(self):
        exc = SPTSubmissionError(
            spt_type="PPN-1111",
            period="2026-01",
            reason="Connection timeout",
            context={"attempts": 3},
        )
        assert exc.message == "SPT PPN-1111 for period 2026-01 submission failed: Connection timeout"
        assert exc.code == "SPT_SUBMIT_FAIL"
        assert exc.severity == ErrorSeverity.HIGH
        assert exc.category == ErrorCategory.TAX
        assert exc.context["spt_type"] == "PPN-1111"
        assert exc.context["period"] == "2026-01"
        assert exc.context["reason"] == "Connection timeout"
        assert exc.context["attempts"] == 3


# ============================================================================
# Reporting Exception tests
# ============================================================================

class TestReportingError:
    def test_construction(self):
        exc = ReportingError(
            message="Reporting error",
            code="REP001",
            context={"report": "annual"},
            cause=ValueError("cause"),
        )
        assert exc.message == "Reporting error"
        assert exc.code == "REP001"
        assert exc.severity == ErrorSeverity.ERROR
        assert exc.category == ErrorCategory.REPORTING
        assert exc.context == {"report": "annual"}

    def test_default_code(self):
        exc = ReportingError(message="Reporting error")
        assert exc.code == "REPORTING_ERROR"


class TestReportGenerationError:
    def test_construction(self):
        exc = ReportGenerationError(
            report_type="balance_sheet",
            reason="Missing data for account 101",
            context={"missing_accounts": ["101", "102"]},
        )
        assert exc.message == "Failed to generate balance_sheet report: Missing data for account 101"
        assert exc.code == "GENERATION_FAIL"
        assert exc.severity == ErrorSeverity.ERROR
        assert exc.category == ErrorCategory.REPORTING
        assert exc.context["report_type"] == "balance_sheet"
        assert exc.context["reason"] == "Missing data for account 101"
        assert exc.context["missing_accounts"] == ["101", "102"]


# ============================================================================
# Ethics Exception tests
# ============================================================================

class TestEthicsError:
    def test_construction(self):
        exc = EthicsError(
            message="Ethics violation",
            code="ETH001",
            context={"policy": "code_of_conduct"},
            cause=ValueError("cause"),
        )
        assert exc.message == "Ethics violation"
        assert exc.code == "ETH001"
        assert exc.severity == ErrorSeverity.WARNING
        assert exc.category == ErrorCategory.ETHICS
        assert exc.context == {"policy": "code_of_conduct"}

    def test_default_code(self):
        exc = EthicsError(message="Ethics violation")
        assert exc.code == "ETHICS_ERROR"


class TestProfessionalJudgmentError:
    def test_construction(self):
        exc = ProfessionalJudgmentError(
            judgment_id="judge-001",
            reason="Insufficient evidence",
            context={"asset": "goodwill"},
        )
        assert exc.message == "Professional judgment judge-001 error: Insufficient evidence"
        assert exc.code == "JUDGMENT_ERROR"
        assert exc.severity == ErrorSeverity.WARNING
        assert exc.category == ErrorCategory.ETHICS
        assert exc.context["judgment_id"] == "judge-001"
        assert exc.context["reason"] == "Insufficient evidence"
        assert exc.context["asset"] == "goodwill"


class TestConflictOfInterestError:
    def test_construction(self):
        exc = ConflictOfInterestError(
            user_id="user-123",
            transaction_id="tx-456",
            context={"amount": "1000000"},
        )
        assert exc.message == "Conflict of interest for user user-123 in transaction tx-456"
        assert exc.code == "CONFLICT_INTEREST"
        assert exc.severity == ErrorSeverity.WARNING
        assert exc.category == ErrorCategory.ETHICS
        assert exc.context["user_id"] == "user-123"
        assert exc.context["transaction_id"] == "tx-456"
        assert exc.context["amount"] == "1000000"


# ============================================================================
# Legal Exception tests
# ============================================================================

class TestLegalError:
    def test_construction(self):
        exc = LegalError(
            message="Legal error",
            code="LEG001",
            context={"jurisdiction": "ID"},
            cause=ValueError("cause"),
        )
        assert exc.message == "Legal error"
        assert exc.code == "LEG001"
        assert exc.severity == ErrorSeverity.ERROR
        assert exc.category == ErrorCategory.LEGAL
        assert exc.context == {"jurisdiction": "ID"}

    def test_default_code(self):
        exc = LegalError(message="Legal error")
        assert exc.code == "LEGAL_ERROR"


class TestJurisdictionError:
    def test_construction(self):
        exc = JurisdictionError(
            jurisdiction_code="XX",
            operation="cross_border_transfer",
            context={"amount": "50000"},
        )
        assert exc.message == "Jurisdiction XX not supported for operation: cross_border_transfer"
        assert exc.code == "JURISDICTION_ERROR"
        assert exc.severity == ErrorSeverity.ERROR
        assert exc.category == ErrorCategory.LEGAL
        assert exc.context["jurisdiction_code"] == "XX"
        assert exc.context["operation"] == "cross_border_transfer"
        assert exc.context["amount"] == "50000"


# ============================================================================
# ComplianceExceptionAggregator tests
# ============================================================================

class TestComplianceExceptionAggregator:
    def test_construction(self):
        agg = ComplianceExceptionAggregator()
        assert agg._exceptions == []
        assert agg.has_errors() is False

    def test_add_single(self):
        agg = ComplianceExceptionAggregator()
        exc = ComplianceError(message="Test")
        agg.add(exc)
        assert agg.has_errors() is True
        assert len(agg.get_all()) == 1
        assert agg.get_all()[0] is exc

    def test_add_multiple(self):
        agg = ComplianceExceptionAggregator()
        exc1 = ComplianceError(message="Test 1")
        exc2 = ComplianceError(message="Test 2")
        agg.add(exc1)
        agg.add(exc2)
        assert len(agg.get_all()) == 2

    def test_add_from_context(self):
        agg = ComplianceExceptionAggregator()
        error_dict = {
            "message": "API error",
            "code": "API001",
            "severity": "error",
            "category": "general",
            "context": {"endpoint": "/api"},
        }
        agg.add_from_context(error_dict)
        assert agg.has_errors() is True
        exc = agg.get_all()[0]
        assert isinstance(exc, ComplianceError)
        assert exc.message == "API error"
        assert exc.code == "API001"
        assert exc.severity == ErrorSeverity.ERROR
        assert exc.category == ErrorCategory.GENERAL
        assert exc.context == {"endpoint": "/api"}

    def test_add_from_context_invalid_severity(self):
        agg = ComplianceExceptionAggregator()
        error_dict = {"message": "Test", "severity": "invalid", "category": "general"}
        agg.add_from_context(error_dict)
        exc = agg.get_all()[0]
        # Should default to ERROR if invalid severity
        assert exc.severity == ErrorSeverity.ERROR

    def test_get_by_severity(self):
        agg = ComplianceExceptionAggregator()
        agg.add(ComplianceError(message="Info", severity=ErrorSeverity.INFO))
        agg.add(ComplianceError(message="Warning", severity=ErrorSeverity.WARNING))
        agg.add(ComplianceError(message="Error", severity=ErrorSeverity.ERROR))
        agg.add(ComplianceError(message="Critical", severity=ErrorSeverity.CRITICAL))

        info = agg.get_by_severity(ErrorSeverity.INFO)
        assert len(info) == 1
        assert info[0].message == "Info"

        critical = agg.get_by_severity(ErrorSeverity.CRITICAL)
        assert len(critical) == 1
        assert critical[0].message == "Critical"

    def test_to_dict(self):
        agg = ComplianceExceptionAggregator()
        agg.add(ComplianceError(message="Error 1", code="E001", severity=ErrorSeverity.ERROR))
        agg.add(ComplianceError(message="Critical", code="E002", severity=ErrorSeverity.CRITICAL))
        agg.add(ComplianceError(message="Warning", code="E003", severity=ErrorSeverity.WARNING))

        d = agg.to_dict()
        assert d["count"] == 3
        assert len(d["exceptions"]) == 3
        assert d["summary"]["critical"] == 1
        assert d["summary"]["error"] == 1
        assert d["summary"]["warning"] == 1

    def test_raise_if_any_no_errors(self):
        agg = ComplianceExceptionAggregator()
        # Should not raise
        agg.raise_if_any()

    def test_raise_if_any_with_warning_only(self):
        agg = ComplianceExceptionAggregator()
        agg.add(ComplianceError(message="Warning", severity=ErrorSeverity.WARNING))
        # Should not raise (warning < error threshold)
        agg.raise_if_any()

    def test_raise_if_any_with_error(self):
        agg = ComplianceExceptionAggregator()
        agg.add(ComplianceError(message="Error", severity=ErrorSeverity.ERROR))
        with pytest.raises(ComplianceError) as exc_info:
            agg.raise_if_any()
        assert "Aggregated 1 compliance errors" in str(exc_info.value)

    def test_raise_if_any_with_critical(self):
        agg = ComplianceExceptionAggregator()
        agg.add(ComplianceError(message="Critical", severity=ErrorSeverity.CRITICAL))
        with pytest.raises(ComplianceError) as exc_info:
            agg.raise_if_any()
        assert "Aggregated 1 critical compliance errors" in str(exc_info.value)

    def test_raise_if_any_with_fatal(self):
        agg = ComplianceExceptionAggregator()
        agg.add(ComplianceError(message="Fatal", severity=ErrorSeverity.FATAL))
        with pytest.raises(ComplianceError) as exc_info:
            agg.raise_if_any()
        assert "Aggregated 1 critical compliance errors" in str(exc_info.value)

    def test_raise_if_any_max_severity(self):
        agg = ComplianceExceptionAggregator()
        agg.add(ComplianceError(message="Error", severity=ErrorSeverity.ERROR))
        agg.add(ComplianceError(message="Warning", severity=ErrorSeverity.WARNING))
        # With max_severity=CRITICAL, ERROR should NOT raise
        agg.raise_if_any(max_severity=ErrorSeverity.CRITICAL)

    def test_raise_if_any_mixed_errors(self):
        agg = ComplianceExceptionAggregator()
        agg.add(ComplianceError(message="Warning", severity=ErrorSeverity.WARNING))
        agg.add(ComplianceError(message="Error", severity=ErrorSeverity.ERROR))
        agg.add(ComplianceError(message="Critical", severity=ErrorSeverity.CRITICAL))
        with pytest.raises(ComplianceError) as exc_info:
            agg.raise_if_any()
        # Should raise with critical error count
        assert "Aggregated 1 critical compliance errors" in str(exc_info.value)


# ============================================================================
# Serialization round-trip tests
# ============================================================================

class TestSerialization:
    def test_compliance_error_roundtrip(self):
        exc = ComplianceError(
            message="Test",
            code="TEST001",
            severity=ErrorSeverity.CRITICAL,
            category=ErrorCategory.AML,
            context={"tx": "123"},
        )
        d = exc.to_dict()
        # Reconstruct (not a full roundtrip, but verify data)
        assert d["message"] == "Test"
        assert d["code"] == "TEST001"
        assert d["severity"] == "critical"
        assert d["category"] == "anti_money_laundering"

    def test_json_output_is_valid(self):
        exc = ComplianceError(message="Test", code="TEST")
        json_str = exc.to_json()
        data = json.loads(json_str)
        assert data["message"] == "Test"
        assert data["code"] == "TEST"


# ============================================================================
# Timestamp tests (ensure timestamp is UTC)
# ============================================================================

class TestTimestamp:
    def test_timestamp_is_utc(self):
        exc = ComplianceError(message="Test")
        assert exc.timestamp.tzinfo is None  # datetime.utcnow() returns naive
        # But we can check it's close to current time
        now = datetime.utcnow()
        diff = abs((exc.timestamp - now).total_seconds())
        assert diff < 5  # less than 5 seconds difference


# ============================================================================
# Traceback capture tests
# ============================================================================

class TestTraceback:
    def test_traceback_captured_with_cause(self):
        try:
            raise ValueError("Original error")
        except ValueError as e:
            exc = ComplianceError(message="Wrapped", cause=e)
            assert exc._traceback is not None
            assert len(exc._traceback) > 0
            assert "Original error" in str(exc._traceback)
            assert "ValueError" in str(exc._traceback)

    def test_no_traceback_without_cause(self):
        exc = ComplianceError(message="Test")
        assert exc._traceback is None