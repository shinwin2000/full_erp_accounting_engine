# test_intent_exceptions.py
# ==========================
# Comprehensive tests for intent_exceptions.py.
# Covers enums, base exception, all specific exceptions, and factory.

import pytest

from domain.intent.intent_exceptions import (
    IntentAlreadyApprovedError,
    IntentAlreadyCancelledError,
    IntentAlreadyExecutedError,
    IntentAlreadySubmittedError,
    IntentApprovalInsufficientError,
    IntentApprovalLevelInvalidError,
    IntentCannotVoidError,
    IntentDataIncompleteError,
    IntentError,
    IntentErrorCode,
    IntentExceptionFactory,
    IntentInvalidStatusError,
    IntentNotFoundError,
    IntentRiskTooHighError,
    IntentSeverity,
    IntentValidationFailedError,
    IntentWorkflowInvalidTransitionError,
)


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------
class TestIntentErrorCode:
    def test_members_exist(self):
        assert hasattr(IntentErrorCode, "INTENT_NOT_FOUND")
        assert hasattr(IntentErrorCode, "INTENT_INVALID_STATUS")
        assert hasattr(IntentErrorCode, "INTENT_ALREADY_SUBMITTED")
        assert hasattr(IntentErrorCode, "INTENT_ALREADY_APPROVED")
        assert hasattr(IntentErrorCode, "INTENT_ALREADY_EXECUTED")
        assert hasattr(IntentErrorCode, "INTENT_ALREADY_CANCELLED")
        assert hasattr(IntentErrorCode, "INTENT_VALIDATION_FAILED")
        assert hasattr(IntentErrorCode, "INTENT_DATA_INCOMPLETE")
        assert hasattr(IntentErrorCode, "INTENT_DATA_INVALID")
        assert hasattr(IntentErrorCode, "INTENT_APPROVAL_NOT_FOUND")
        assert hasattr(IntentErrorCode, "INTENT_APPROVAL_INSUFFICIENT")
        assert hasattr(IntentErrorCode, "INTENT_APPROVAL_LEVEL_INVALID")
        assert hasattr(IntentErrorCode, "INTENT_APPROVAL_ALREADY_GIVEN")
        assert hasattr(IntentErrorCode, "INTENT_RISK_ASSESSMENT_FAILED")
        assert hasattr(IntentErrorCode, "INTENT_RISK_TOO_HIGH")
        assert hasattr(IntentErrorCode, "INTENT_CANNOT_VOID")
        assert hasattr(IntentErrorCode, "INTENT_ALREADY_VOIDED")
        assert hasattr(IntentErrorCode, "INTENT_WORKFLOW_NOT_FOUND")
        assert hasattr(IntentErrorCode, "INTENT_WORKFLOW_INVALID_TRANSITION")
        assert hasattr(IntentErrorCode, "INTENT_UNKNOWN_ERROR")

    def test_member_is_instance(self):
        assert isinstance(IntentErrorCode.INTENT_NOT_FOUND, IntentErrorCode)


class TestIntentSeverity:
    def test_members_exist(self):
        assert hasattr(IntentSeverity, "CRITICAL")
        assert hasattr(IntentSeverity, "HIGH")
        assert hasattr(IntentSeverity, "MEDIUM")
        assert hasattr(IntentSeverity, "LOW")

    def test_member_is_instance(self):
        assert isinstance(IntentSeverity.CRITICAL, IntentSeverity)

    def test_values(self):
        assert IntentSeverity.CRITICAL.value == 80
        assert IntentSeverity.HIGH.value == 60
        assert IntentSeverity.MEDIUM.value == 40
        assert IntentSeverity.LOW.value == 20


# ----------------------------------------------------------------------
# Base Exception
# ----------------------------------------------------------------------
class TestIntentError:
    def test_construction_minimal(self):
        err = IntentError(
            message="Test error",
            error_code=IntentErrorCode.INTENT_NOT_FOUND,
        )
        assert err.error_code == IntentErrorCode.INTENT_NOT_FOUND
        assert err.severity == IntentSeverity.MEDIUM  # default
        assert err.component is None
        assert err.details == {}
        assert err.cause is None
        assert err.original_message == "Test error"
        # Check full message formatting
        assert str(err) == "[MEDIUM][INTENT_NOT_FOUND] Test error"

    def test_construction_full(self):
        cause = ValueError("Underlying")
        err = IntentError(
            message="Full error",
            error_code=IntentErrorCode.INTENT_ALREADY_SUBMITTED,
            severity=IntentSeverity.HIGH,
            component="approval",
            details={"key": "value"},
            cause=cause,
        )
        assert err.error_code == IntentErrorCode.INTENT_ALREADY_SUBMITTED
        assert err.severity == IntentSeverity.HIGH
        assert err.component == "approval"
        assert err.details == {"key": "value"}
        assert err.cause is cause
        assert err.original_message == "Full error"
        assert str(err) == "[HIGH][INTENT_ALREADY_SUBMITTED] Full error"  # component prepended? Actually code prepends component if present: "[component] [severity][code] message"
        # Let's check: super().__init__(full_message) where full_message = f"[{component}] {full_message}" if component else full_message
        # so if component given, it's "[component] [severity][code] message"
        assert str(err) == "[approval] [HIGH][INTENT_ALREADY_SUBMITTED] Full error"

    def test_to_dict(self):
        err = IntentError(
            message="Test",
            error_code=IntentErrorCode.INTENT_VALIDATION_FAILED,
            severity=IntentSeverity.CRITICAL,
            component="validator",
            details={"field": "amount"},
            cause=ValueError("bad"),
        )
        d = err.to_dict()
        assert d["type"] == "IntentError"
        assert d["error_code"] == "INTENT_VALIDATION_FAILED"
        assert d["severity"] == "CRITICAL"
        assert d["message"] == "Test"
        assert d["component"] == "validator"
        assert d["details"] == {"field": "amount"}
        assert d["cause"] == "bad"

    def test_is_critical(self):
        err = IntentError(
            message="",
            error_code=IntentErrorCode.INTENT_NOT_FOUND,
            severity=IntentSeverity.CRITICAL,
        )
        assert err.is_critical() is True
        err.severity = IntentSeverity.HIGH
        assert err.is_critical() is False


# ----------------------------------------------------------------------
# Specific Exceptions
# ----------------------------------------------------------------------
class TestIntentNotFoundError:
    def test_construction(self):
        err = IntentNotFoundError(intent_id="abc-123")
        assert err.intent_id == "abc-123"
        assert err.error_code == IntentErrorCode.INTENT_NOT_FOUND
        assert err.severity == IntentSeverity.HIGH
        assert err.component == "capture"
        assert err.details == {"intent_id": "abc-123"}
        assert "Intent abc-123 not found" in err.original_message
        assert str(err).endswith("Intent abc-123 not found")


class TestIntentInvalidStatusError:
    def test_construction(self):
        err = IntentInvalidStatusError(
            intent_id="abc", current_status="DRAFT", required_status="SUBMITTED"
        )
        assert err.intent_id == "abc"
        assert err.current_status == "DRAFT"
        assert err.required_status == "SUBMITTED"
        assert err.error_code == IntentErrorCode.INTENT_INVALID_STATUS
        assert err.severity == IntentSeverity.HIGH
        assert "invalid status DRAFT" in err.original_message
        assert "Required: SUBMITTED" in err.original_message


class TestIntentAlreadySubmittedError:
    def test_construction(self):
        err = IntentAlreadySubmittedError(intent_id="abc")
        assert err.intent_id == "abc"
        assert err.error_code == IntentErrorCode.INTENT_ALREADY_SUBMITTED
        assert err.severity == IntentSeverity.MEDIUM
        assert "already been submitted" in err.original_message


class TestIntentAlreadyApprovedError:
    def test_construction(self):
        err = IntentAlreadyApprovedError(intent_id="abc")
        assert err.intent_id == "abc"
        assert err.error_code == IntentErrorCode.INTENT_ALREADY_APPROVED
        assert err.severity == IntentSeverity.MEDIUM
        assert "already been approved" in err.original_message


class TestIntentAlreadyExecutedError:
    def test_construction_without_outcome(self):
        err = IntentAlreadyExecutedError(intent_id="abc")
        assert err.intent_id == "abc"
        assert err.error_code == IntentErrorCode.INTENT_ALREADY_EXECUTED
        assert err.severity == IntentSeverity.HIGH
        assert "already been executed" in err.original_message
        assert err.details.get("outcome_id") is None

    def test_construction_with_outcome(self):
        err = IntentAlreadyExecutedError(intent_id="abc", outcome_id="out-123")
        assert err.intent_id == "abc"
        assert err.details["outcome_id"] == "out-123"
        assert "Outcome: out-123" in err.original_message


class TestIntentAlreadyCancelledError:
    def test_construction(self):
        err = IntentAlreadyCancelledError(intent_id="abc")
        assert err.intent_id == "abc"
        assert err.error_code == IntentErrorCode.INTENT_ALREADY_CANCELLED
        assert err.severity == IntentSeverity.MEDIUM
        assert "already been cancelled" in err.original_message


class TestIntentValidationFailedError:
    def test_construction(self):
        errors = [{"field": "amount", "error": "must be positive"}]
        err = IntentValidationFailedError(message="Invalid data", errors=errors)
        assert err.errors == errors
        assert err.error_code == IntentErrorCode.INTENT_VALIDATION_FAILED
        assert err.severity == IntentSeverity.HIGH
        assert "Invalid data" in err.original_message
        assert err.details["validation_errors"] == errors


class TestIntentDataIncompleteError:
    def test_construction(self):
        missing = ["amount", "description"]
        err = IntentDataIncompleteError(missing_fields=missing)
        assert err.missing_fields == missing
        assert err.error_code == IntentErrorCode.INTENT_DATA_INCOMPLETE
        assert err.severity == IntentSeverity.HIGH
        assert "Missing fields: amount, description" in err.original_message


class TestIntentApprovalInsufficientError:
    def test_construction(self):
        err = IntentApprovalInsufficientError(
            intent_id="abc", required_approvals=3, current_approvals=1
        )
        assert err.intent_id == "abc"
        assert err.required_approvals == 3
        assert err.current_approvals == 1
        assert err.error_code == IntentErrorCode.INTENT_APPROVAL_INSUFFICIENT
        assert err.severity == IntentSeverity.HIGH
        assert "1/3" in err.original_message


class TestIntentApprovalLevelInvalidError:
    def test_construction(self):
        err = IntentApprovalLevelInvalidError(
            intent_id="abc", required_level="LEVEL_3", provided_level="LEVEL_1"
        )
        assert err.intent_id == "abc"
        assert err.error_code == IntentErrorCode.INTENT_APPROVAL_LEVEL_INVALID
        assert err.severity == IntentSeverity.HIGH
        assert "Required: LEVEL_3, Provided: LEVEL_1" in err.original_message


class TestIntentRiskTooHighError:
    def test_construction(self):
        err = IntentRiskTooHighError(
            intent_id="abc", risk_level="HIGH", risk_score=85.5
        )
        assert err.intent_id == "abc"
        assert err.error_code == IntentErrorCode.INTENT_RISK_TOO_HIGH
        assert err.severity == IntentSeverity.CRITICAL
        assert "risk level HIGH (score: 85.5)" in err.original_message
        assert err.details["risk_level"] == "HIGH"
        assert err.details["risk_score"] == 85.5


class TestIntentCannotVoidError:
    def test_construction(self):
        err = IntentCannotVoidError(intent_id="abc", reason="Already executed")
        assert err.intent_id == "abc"
        assert err.error_code == IntentErrorCode.INTENT_CANNOT_VOID
        assert err.severity == IntentSeverity.HIGH
        assert "Cannot void intent abc: Already executed" in err.original_message
        assert err.details["reason"] == "Already executed"


class TestIntentWorkflowInvalidTransitionError:
    def test_construction(self):
        err = IntentWorkflowInvalidTransitionError(
            intent_id="abc", from_status="DRAFT", to_status="EXECUTED"
        )
        assert err.intent_id == "abc"
        assert err.from_status == "DRAFT"
        assert err.to_status == "EXECUTED"
        assert err.error_code == IntentErrorCode.INTENT_WORKFLOW_INVALID_TRANSITION
        assert err.severity == IntentSeverity.HIGH
        assert "DRAFT -> EXECUTED" in err.original_message


# ----------------------------------------------------------------------
# IntentExceptionFactory
# ----------------------------------------------------------------------
class TestIntentExceptionFactory:
    def test_not_found(self):
        err = IntentExceptionFactory.not_found(intent_id="abc")
        assert isinstance(err, IntentNotFoundError)
        assert err.intent_id == "abc"

    def test_invalid_status(self):
        err = IntentExceptionFactory.invalid_status(
            intent_id="abc", current="DRAFT", required="SUBMITTED"
        )
        assert isinstance(err, IntentInvalidStatusError)
        assert err.intent_id == "abc"
        assert err.current_status == "DRAFT"
        assert err.required_status == "SUBMITTED"

    def test_already_submitted(self):
        err = IntentExceptionFactory.already_submitted(intent_id="abc")
        assert isinstance(err, IntentAlreadySubmittedError)
        assert err.intent_id == "abc"

    def test_already_approved(self):
        err = IntentExceptionFactory.already_approved(intent_id="abc")
        assert isinstance(err, IntentAlreadyApprovedError)
        assert err.intent_id == "abc"

    def test_already_executed(self):
        err = IntentExceptionFactory.already_executed(intent_id="abc", outcome_id="out-123")
        assert isinstance(err, IntentAlreadyExecutedError)
        assert err.intent_id == "abc"
        assert err.details["outcome_id"] == "out-123"

    def test_cannot_void(self):
        err = IntentExceptionFactory.cannot_void(intent_id="abc", reason="not allowed")
        assert isinstance(err, IntentCannotVoidError)
        assert err.intent_id == "abc"
        assert err.details["reason"] == "not allowed"

    def test_validation_failed(self):
        errors = [{"field": "amount", "error": "too large"}]
        err = IntentExceptionFactory.validation_failed(
            message="Invalid data", errors=errors
        )
        assert isinstance(err, IntentValidationFailedError)
        assert err.errors == errors
        assert err.details["validation_errors"] == errors

    def test_data_incomplete(self):
        missing = ["field1", "field2"]
        err = IntentExceptionFactory.data_incomplete(missing_fields=missing)
        assert isinstance(err, IntentDataIncompleteError)
        assert err.missing_fields == missing

    def test_approval_insufficient(self):
        err = IntentExceptionFactory.approval_insufficient(
            intent_id="abc", required=3, current=1
        )
        assert isinstance(err, IntentApprovalInsufficientError)
        assert err.intent_id == "abc"
        assert err.required_approvals == 3
        assert err.current_approvals == 1

    def test_risk_too_high(self):
        err = IntentExceptionFactory.risk_too_high(
            intent_id="abc", risk_level="HIGH", risk_score=90.0
        )
        assert isinstance(err, IntentRiskTooHighError)
        assert err.intent_id == "abc"
        assert err.details["risk_level"] == "HIGH"
        assert err.details["risk_score"] == 90.0

    def test_invalid_transition(self):
        err = IntentExceptionFactory.invalid_transition(
            intent_id="abc", from_status="DRAFT", to_status="EXECUTED"
        )
        assert isinstance(err, IntentWorkflowInvalidTransitionError)
        assert err.intent_id == "abc"
        assert err.from_status == "DRAFT"
        assert err.to_status == "EXECUTED"