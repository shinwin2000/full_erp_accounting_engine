# tests/kernel/guards/test_guard_exceptions.py
"""
Comprehensive unit tests for kernel/guards/guard_exceptions.py.

Covers:
- Enums: GuardErrorCode, GuardSeverity
  - members, display_name, to_dict, from_string
- GuardViolationError:
  - construction with various parameters
  - original_message property
  - to_dict method (including missing fields)
  - is_critical method
- All specific exception classes:
  - BalanceCheckerError
  - PeriodLockError
  - CurrencyValidatorError
  - LegalEntityBoundaryError
  - AuthorityMatrixError
  - EvidenceAttacherError
  - RegulatoryComplianceError
  - TemporalConsistencyError
  - EmergencyFreezeError
  - CoretaxFormatError
  - SODEnforcerError
  - BudgetAvailabilityError
  - CreditLimitEnforcerError
  - (verify guard_name, error_code, details, attributes)
- GuardExceptionFactory:
  - all static methods return correct exception types with proper attributes
  - test each factory method
- Edge cases: missing cause, details, None values
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kernel.guards.guard_exceptions import (
    AuthorityMatrixError,
    BalanceCheckerError,
    BudgetAvailabilityError,
    CoretaxFormatError,
    CreditLimitEnforcerError,
    CurrencyValidatorError,
    EmergencyFreezeError,
    EvidenceAttacherError,
    GuardErrorCode,
    GuardExceptionFactory,
    GuardSeverity,
    GuardViolationError,
    LegalEntityBoundaryError,
    PeriodLockError,
    RegulatoryComplianceError,
    SODEnforcerError,
    TemporalConsistencyError,
)


# ============================================================================
# Tests for GuardErrorCode Enum
# ============================================================================

class TestGuardErrorCode:
    def test_members_exist(self):
        assert hasattr(GuardErrorCode, "BALANCE_NEGATIVE")
        assert hasattr(GuardErrorCode, "BALANCE_INSUFFICIENT")
        assert hasattr(GuardErrorCode, "BALANCE_CURRENCY_MISMATCH")
        assert hasattr(GuardErrorCode, "PERIOD_CLOSED")
        assert hasattr(GuardErrorCode, "PERIOD_LOCKED")
        assert hasattr(GuardErrorCode, "PERIOD_FUTURE")
        assert hasattr(GuardErrorCode, "PERIOD_NOT_FOUND")
        assert hasattr(GuardErrorCode, "CURRENCY_NOT_SUPPORTED")
        assert hasattr(GuardErrorCode, "CURRENCY_EXCHANGE_RATE_MISSING")
        assert hasattr(GuardErrorCode, "CURRENCY_EXCHANGE_RATE_INVALID")
        assert hasattr(GuardErrorCode, "ENTITY_ACCESS_DENIED")
        assert hasattr(GuardErrorCode, "ENTITY_NOT_FOUND")
        assert hasattr(GuardErrorCode, "ENTITY_CROSS_ACCESS_DENIED")
        assert hasattr(GuardErrorCode, "AUTHORIZATION_MISSING")
        assert hasattr(GuardErrorCode, "ROLE_NOT_FOUND")
        assert hasattr(GuardErrorCode, "PERMISSION_DENIED")
        assert hasattr(GuardErrorCode, "EVIDENCE_MISSING")
        assert hasattr(GuardErrorCode, "EVIDENCE_TYPE_INVALID")
        assert hasattr(GuardErrorCode, "EVIDENCE_INTEGRITY_FAILED")
        assert hasattr(GuardErrorCode, "REGULATORY_VIOLATION")
        assert hasattr(GuardErrorCode, "AML_THRESHOLD_EXCEEDED")
        assert hasattr(GuardErrorCode, "TAX_COMPLIANCE_FAILED")
        assert hasattr(GuardErrorCode, "TEMPORAL_INCONSISTENCY")
        assert hasattr(GuardErrorCode, "CLOCK_SKEW_DETECTED")
        assert hasattr(GuardErrorCode, "BACKDATING_EXCEEDED")
        assert hasattr(GuardErrorCode, "SYSTEM_FROZEN")
        assert hasattr(GuardErrorCode, "FREEZE_AUTHORIZATION_MISSING")
        assert hasattr(GuardErrorCode, "CORETAX_FORMAT_INVALID")
        assert hasattr(GuardErrorCode, "CORETAX_NPWP_INVALID")
        assert hasattr(GuardErrorCode, "CORETAX_NTPN_INVALID")
        assert hasattr(GuardErrorCode, "CORETAX_FAKTUR_INVALID")
        assert hasattr(GuardErrorCode, "SOD_MAKER_CHECKER_VIOLATION")
        assert hasattr(GuardErrorCode, "SOD_ROLE_CONFLICT")
        assert hasattr(GuardErrorCode, "SOD_DUAL_CONTROL_REQUIRED")
        assert hasattr(GuardErrorCode, "SOD_APPROVAL_LIMIT_EXCEEDED")
        assert hasattr(GuardErrorCode, "BUDGET_INSUFFICIENT")
        assert hasattr(GuardErrorCode, "BUDGET_NOT_FOUND")
        assert hasattr(GuardErrorCode, "BUDGET_APPROVAL_REQUIRED")
        assert hasattr(GuardErrorCode, "CREDIT_LIMIT_EXCEEDED")
        assert hasattr(GuardErrorCode, "CREDIT_LIMIT_WARNING")
        assert hasattr(GuardErrorCode, "GUARD_NOT_APPLICABLE")
        assert hasattr(GuardErrorCode, "GUARD_VALIDATION_FAILED")

    def test_display_name(self):
        assert GuardErrorCode.BALANCE_NEGATIVE.display_name() == "Negative Balance"
        assert GuardErrorCode.PERIOD_CLOSED.display_name() == "Period Closed"
        assert GuardErrorCode.CORETAX_NPWP_INVALID.display_name() == "Invalid NPWP"
        assert GuardErrorCode.GUARD_VALIDATION_FAILED.display_name() == "Guard Validation Failed"

    def test_to_dict(self):
        d = GuardErrorCode.BALANCE_INSUFFICIENT.to_dict()
        assert d["value"] == "BALANCE_INSUFFICIENT"
        assert d["display"] == "Insufficient Balance"

    def test_from_string_valid(self):
        code = GuardErrorCode.from_string("BALANCE_NEGATIVE")
        assert code == GuardErrorCode.BALANCE_NEGATIVE

        code2 = GuardErrorCode.from_string("PERIOD_CLOSED")
        assert code2 == GuardErrorCode.PERIOD_CLOSED

    def test_from_string_invalid(self):
        with pytest.raises(ValueError, match="Unknown GuardErrorCode"):
            GuardErrorCode.from_string("INVALID_CODE")


# ============================================================================
# Tests for GuardSeverity Enum
# ============================================================================

class TestGuardSeverity:
    def test_members(self):
        assert GuardSeverity.CRITICAL.value == 80
        assert GuardSeverity.HIGH.value == 60
        assert GuardSeverity.MEDIUM.value == 40
        assert GuardSeverity.LOW.value == 20

    def test_display_name(self):
        assert GuardSeverity.CRITICAL.display_name() == "Critical"
        assert GuardSeverity.HIGH.display_name() == "High"
        assert GuardSeverity.MEDIUM.display_name() == "Medium"
        assert GuardSeverity.LOW.display_name() == "Low"

    def test_to_dict(self):
        d = GuardSeverity.CRITICAL.to_dict()
        assert d["value"] == "CRITICAL"
        assert d["level"] == 80
        assert d["display"] == "Critical"

    def test_from_string_valid(self):
        sev = GuardSeverity.from_string("CRITICAL")
        assert sev == GuardSeverity.CRITICAL
        sev2 = GuardSeverity.from_string("LOW")
        assert sev2 == GuardSeverity.LOW

    def test_from_string_invalid(self):
        with pytest.raises(ValueError, match="Unknown GuardSeverity"):
            GuardSeverity.from_string("INVALID")


# ============================================================================
# Tests for GuardViolationError
# ============================================================================

class TestGuardViolationError:
    def test_construction_minimal(self):
        exc = GuardViolationError(
            message="Something went wrong",
            guard_name="test_guard",
        )
        assert exc.guard_name == "test_guard"
        assert exc.error_code == GuardErrorCode.GUARD_VALIDATION_FAILED
        assert exc.severity == GuardSeverity.HIGH
        assert exc.details == {}
        assert exc.cause is None
        assert exc.original_message == "Something went wrong"
        assert str(exc).startswith("[test_guard][HIGH] Something went wrong")

    def test_construction_full(self):
        cause = ValueError("underlying")
        exc = GuardViolationError(
            message="Critical guard failure",
            guard_name="auth_guard",
            error_code=GuardErrorCode.PERMISSION_DENIED,
            severity=GuardSeverity.CRITICAL,
            details={"user": "admin"},
            cause=cause,
        )
        assert exc.guard_name == "auth_guard"
        assert exc.error_code == GuardErrorCode.PERMISSION_DENIED
        assert exc.severity == GuardSeverity.CRITICAL
        assert exc.details == {"user": "admin"}
        assert exc.cause == cause
        assert exc.original_message == "Critical guard failure"

    def test_original_message_property(self):
        exc = GuardViolationError("My message", "guard")
        assert exc.original_message == "My message"

    def test_to_dict(self):
        exc = GuardViolationError(
            message="Error",
            guard_name="test",
            error_code=GuardErrorCode.EVIDENCE_MISSING,
            severity=GuardSeverity.MEDIUM,
            details={"key": "value"},
            cause=ValueError("cause"),
        )
        d = exc.to_dict()
        assert d["type"] == "GuardViolationError"
        assert d["guard_name"] == "test"
        assert d["error_code"] == "EVIDENCE_MISSING"
        assert d["error_code_display"] == "Evidence Missing"
        assert d["severity"] == "MEDIUM"
        assert d["severity_level"] == 40
        assert d["message"] == "Error"
        assert d["details"] == {"key": "value"}
        assert d["cause"] == "cause"

    def test_to_dict_no_cause(self):
        exc = GuardViolationError("No cause", "guard")
        d = exc.to_dict()
        assert d["cause"] is None

    def test_is_critical(self):
        exc_critical = GuardViolationError("critical", "g", severity=GuardSeverity.CRITICAL)
        assert exc_critical.is_critical() is True

        exc_high = GuardViolationError("high", "g", severity=GuardSeverity.HIGH)
        assert exc_high.is_critical() is False


# ============================================================================
# Tests for Specific Exception Classes
# ============================================================================

class TestSpecificExceptions:
    def test_balance_checker_error(self):
        exc = BalanceCheckerError("Insufficient funds", "ACC001", 100.0)
        assert isinstance(exc, GuardViolationError)
        assert exc.guard_name == "balance_checker"
        assert exc.error_code == GuardErrorCode.BALANCE_INSUFFICIENT
        assert exc.account_code == "ACC001"
        assert exc.current_balance == 100.0
        assert exc.details["account_code"] == "ACC001"
        assert exc.details["current_balance"] == "100.0"

    def test_period_lock_error(self):
        exc = PeriodLockError("Period closed", "2025-01", "CLOSED")
        assert exc.guard_name == "period_lock"
        assert exc.error_code == GuardErrorCode.PERIOD_CLOSED
        assert exc.period_name == "2025-01"
        assert exc.period_status == "CLOSED"

    def test_currency_validator_error(self):
        exc = CurrencyValidatorError("Unsupported currency", "XYZ")
        assert exc.guard_name == "currency_validator"
        assert exc.error_code == GuardErrorCode.CURRENCY_NOT_SUPPORTED
        assert exc.currency == "XYZ"

    def test_legal_entity_boundary_error(self):
        exc = LegalEntityBoundaryError("Access denied", "entity-123")
        assert exc.guard_name == "legal_entity_boundary"
        assert exc.error_code == GuardErrorCode.ENTITY_ACCESS_DENIED
        assert exc.target_entity_id == "entity-123"

    def test_authority_matrix_error(self):
        exc = AuthorityMatrixError("Permission denied", "resource", "write")
        assert exc.guard_name == "authority_matrix"
        assert exc.error_code == GuardErrorCode.PERMISSION_DENIED
        assert exc.resource == "resource"
        assert exc.action == "write"

    def test_evidence_attacher_error(self):
        exc = EvidenceAttacherError("Evidence missing", "JOURNAL")
        assert exc.guard_name == "evidence_attacher"
        assert exc.error_code == GuardErrorCode.EVIDENCE_MISSING
        assert exc.transaction_type == "JOURNAL"

    def test_regulatory_compliance_error(self):
        exc = RegulatoryComplianceError("Violation", "AML", "AML-001")
        assert exc.guard_name == "regulatory_compliance"
        assert exc.error_code == GuardErrorCode.REGULATORY_VIOLATION
        assert exc.domain == "AML"
        assert exc.rule_id == "AML-001"

    def test_temporal_consistency_error(self):
        exc = TemporalConsistencyError("Backdating", "2025-01-15", "2025-01-10")
        assert exc.guard_name == "temporal_consistency"
        assert exc.error_code == GuardErrorCode.TEMPORAL_INCONSISTENCY
        assert exc.transaction_date == "2025-01-15"
        assert exc.last_date == "2025-01-10"

    def test_emergency_freeze_error(self):
        exc = EmergencyFreezeError("System frozen", freeze_id="freeze-001")
        assert exc.guard_name == "emergency_freeze"
        assert exc.error_code == GuardErrorCode.SYSTEM_FROZEN
        assert exc.freeze_id == "freeze-001"

        exc2 = EmergencyFreezeError("No ID")
        assert exc2.freeze_id is None

    def test_coretax_format_error(self):
        exc = CoretaxFormatError("Invalid NPWP", "npwp", "123")
        assert exc.guard_name == "coretax_format_validator"
        assert exc.error_code == GuardErrorCode.CORETAX_FORMAT_INVALID
        assert exc.field == "npwp"
        assert exc.value == "123"

    def test_sod_enforcer_error(self):
        exc = SODEnforcerError("Maker-checker violation", "SOD-001")
        assert exc.guard_name == "sod_enforcer"
        assert exc.error_code == GuardErrorCode.SOD_MAKER_CHECKER_VIOLATION
        assert exc.rule_id == "SOD-001"

    def test_budget_availability_error(self):
        exc = BudgetAvailabilityError("Budget exceeded", "CC001", "ACCOUNT-001")
        assert exc.guard_name == "budget_availability"
        assert exc.error_code == GuardErrorCode.BUDGET_INSUFFICIENT
        assert exc.cost_center == "CC001"
        assert exc.account == "ACCOUNT-001"

    def test_credit_limit_enforcer_error(self):
        credit_limit = MagicMock()
        outstanding = MagicMock()
        exc = CreditLimitEnforcerError("Credit limit exceeded", "CUST-001", credit_limit, outstanding)
        assert exc.guard_name == "credit_limit_enforcer"
        assert exc.error_code == GuardErrorCode.CREDIT_LIMIT_EXCEEDED
        assert exc.customer_id == "CUST-001"
        assert exc.credit_limit == credit_limit
        assert exc.outstanding == outstanding
        assert exc.details["credit_limit"] == str(credit_limit)
        assert exc.details["outstanding"] == str(outstanding)


# ============================================================================
# Tests for GuardExceptionFactory
# ============================================================================

class TestGuardExceptionFactory:
    def test_balance_error(self):
        exc = GuardExceptionFactory.balance_error("Insufficient", "ACC123", 50.0, severity=GuardSeverity.HIGH)
        assert isinstance(exc, BalanceCheckerError)
        assert exc.message == "Insufficient"
        assert exc.account_code == "ACC123"
        assert exc.current_balance == 50.0
        assert exc.severity == GuardSeverity.HIGH

    def test_period_error(self):
        exc = GuardExceptionFactory.period_error("Closed", "2025-01", "CLOSED")
        assert isinstance(exc, PeriodLockError)
        assert exc.period_name == "2025-01"
        assert exc.period_status == "CLOSED"

    def test_currency_error(self):
        exc = GuardExceptionFactory.currency_error("Not supported", "XYZ")
        assert isinstance(exc, CurrencyValidatorError)
        assert exc.currency == "XYZ"

    def test_entity_error(self):
        exc = GuardExceptionFactory.entity_error("Access denied", "entity-123")
        assert isinstance(exc, LegalEntityBoundaryError)
        assert exc.target_entity_id == "entity-123"

    def test_permission_error(self):
        exc = GuardExceptionFactory.permission_error("Denied", "resource", "write")
        assert isinstance(exc, AuthorityMatrixError)
        assert exc.resource == "resource"
        assert exc.action == "write"

    def test_evidence_error(self):
        exc = GuardExceptionFactory.evidence_error("Missing", "INVOICE")
        assert isinstance(exc, EvidenceAttacherError)
        assert exc.transaction_type == "INVOICE"

    def test_regulatory_error(self):
        exc = GuardExceptionFactory.regulatory_error("Violation", "TAX", "TAX-001")
        assert isinstance(exc, RegulatoryComplianceError)
        assert exc.domain == "TAX"
        assert exc.rule_id == "TAX-001"

    def test_temporal_error(self):
        exc = GuardExceptionFactory.temporal_error("Backdating", "2025-01-15", "2025-01-10")
        assert isinstance(exc, TemporalConsistencyError)
        assert exc.transaction_date == "2025-01-15"
        assert exc.last_date == "2025-01-10"

        exc2 = GuardExceptionFactory.temporal_error("No last", "2025-01-15")
        assert exc2.last_date is None

    def test_freeze_error(self):
        exc = GuardExceptionFactory.freeze_error("Frozen", "freeze-001")
        assert isinstance(exc, EmergencyFreezeError)
        assert exc.freeze_id == "freeze-001"

        exc2 = GuardExceptionFactory.freeze_error("No freeze id")
        assert exc2.freeze_id is None

    def test_coretax_error(self):
        exc = GuardExceptionFactory.coretax_error("Invalid", "npwp", "123")
        assert isinstance(exc, CoretaxFormatError)
        assert exc.field == "npwp"
        assert exc.value == "123"

    def test_sod_error(self):
        exc = GuardExceptionFactory.sod_error("SOD violation", "SOD-002")
        assert isinstance(exc, SODEnforcerError)
        assert exc.rule_id == "SOD-002"

    def test_budget_error(self):
        exc = GuardExceptionFactory.budget_error("Budget insufficient", "CC001", "ACCOUNT-001")
        assert isinstance(exc, BudgetAvailabilityError)
        assert exc.cost_center == "CC001"
        assert exc.account == "ACCOUNT-001"

    def test_credit_error(self):
        credit_limit = MagicMock()
        outstanding = MagicMock()
        exc = GuardExceptionFactory.credit_error("Credit exceeded", "CUST-001", credit_limit, outstanding)
        assert isinstance(exc, CreditLimitEnforcerError)
        assert exc.customer_id == "CUST-001"
        assert exc.credit_limit == credit_limit
        assert exc.outstanding == outstanding