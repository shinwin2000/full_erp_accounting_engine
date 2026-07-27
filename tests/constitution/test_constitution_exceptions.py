#!/usr/bin/env python3
"""
tests/unit/test_constitution_exceptions.py
Test untuk constitution/constitution_exceptions.py
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from constitution.constitution_exceptions import (
    AmendmentException,
    AuthorizationException,
    ConstitutionalViolationException,
    ConstitutionException,
    ConstitutionExceptionCategory,
    ConstitutionExceptionFactory,
    ConstitutionExceptionHandler,
    ConstitutionExceptionSeverity,
    EnforcementException,
    ForbiddenStateException,
    IntegrityException,
    InvariantViolationException,
    SovereigntyViolationException,
    ValidationException,
    VersionLockException,
)


class TestConstitutionExceptionSeverity:
    def test_members_exist(self):
        assert hasattr(ConstitutionExceptionSeverity, 'CATASTROPHIC')
        assert hasattr(ConstitutionExceptionSeverity, 'CRITICAL')
        assert hasattr(ConstitutionExceptionSeverity, 'HIGH')
        assert hasattr(ConstitutionExceptionSeverity, 'MEDIUM')
        assert hasattr(ConstitutionExceptionSeverity, 'LOW')
        assert hasattr(ConstitutionExceptionSeverity, 'INFO')

    def test_member_is_instance(self):
        assert isinstance(ConstitutionExceptionSeverity.CATASTROPHIC, ConstitutionExceptionSeverity)


class TestConstitutionExceptionCategory:
    def test_members_exist(self):
        assert hasattr(ConstitutionExceptionCategory, 'CONSTITUTION_VIOLATION')
        assert hasattr(ConstitutionExceptionCategory, 'SOVEREIGNTY_VIOLATION')
        assert hasattr(ConstitutionExceptionCategory, 'AMENDMENT_ERROR')
        assert hasattr(ConstitutionExceptionCategory, 'VERSION_LOCK_ERROR')
        assert hasattr(ConstitutionExceptionCategory, 'INVARIANT_VIOLATION')
        assert hasattr(ConstitutionExceptionCategory, 'FORBIDDEN_STATE')
        assert hasattr(ConstitutionExceptionCategory, 'ENFORCEMENT_ERROR')
        assert hasattr(ConstitutionExceptionCategory, 'VALIDATION_ERROR')
        assert hasattr(ConstitutionExceptionCategory, 'INTEGRITY_ERROR')
        assert hasattr(ConstitutionExceptionCategory, 'AUTHORIZATION_ERROR')

    def test_member_is_instance(self):
        assert isinstance(ConstitutionExceptionCategory.CONSTITUTION_VIOLATION, ConstitutionExceptionCategory)


class TestConstitutionException:
    def test_construction(self):
        exc_id = uuid4()
        cmd_id = uuid4()
        tx_id = uuid4()
        le_id = uuid4()
        instance = ConstitutionException(
            message="Test message",
            severity=ConstitutionExceptionSeverity.HIGH,
            category=ConstitutionExceptionCategory.CONSTITUTION_VIOLATION,
            exception_id=exc_id,
            module="test_module",
            user_id="user123",
            command_id=cmd_id,
            transaction_id=tx_id,
            legal_entity_id=le_id,
            context={"key": "value"},
        )
        assert isinstance(instance, ConstitutionException)
        assert isinstance(instance, Exception)
        assert instance.message == "Test message"
        assert instance.severity == ConstitutionExceptionSeverity.HIGH
        assert instance.category == ConstitutionExceptionCategory.CONSTITUTION_VIOLATION
        assert instance.exception_id == exc_id
        assert instance.module == "test_module"
        assert instance.user_id == "user123"
        assert instance.command_id == cmd_id
        assert instance.transaction_id == tx_id
        assert instance.legal_entity_id == le_id
        assert instance.context == {"key": "value"}

    def test_original_message(self):
        instance = ConstitutionException(
            message="Original message",
            severity=ConstitutionExceptionSeverity.HIGH,
            category=ConstitutionExceptionCategory.CONSTITUTION_VIOLATION,
        )
        result = instance.original_message()
        assert result == "Original message"

    def test_to_dict(self):
        exc_id = uuid4()
        cmd_id = uuid4()
        tx_id = uuid4()
        le_id = uuid4()
        instance = ConstitutionException(
            message="Test",
            severity=ConstitutionExceptionSeverity.CRITICAL,
            category=ConstitutionExceptionCategory.ENFORCEMENT_ERROR,
            exception_id=exc_id,
            module="mymodule",
            user_id="u1",
            command_id=cmd_id,
            transaction_id=tx_id,
            legal_entity_id=le_id,
            context={"a": 1},
        )
        d = instance.to_dict()
        assert isinstance(d, dict)
        assert d["message"] == "Test"
        assert d["severity"] == "CRITICAL"
        assert d["category"] == "ENFORCEMENT_ERROR"
        assert d["exception_id"] == str(exc_id)
        assert d["module"] == "mymodule"
        assert d["user_id"] == "u1"
        assert d["command_id"] == str(cmd_id)
        assert d["transaction_id"] == str(tx_id)
        assert d["legal_entity_id"] == str(le_id)
        assert d["context"] == {"a": 1}

    def test_to_json(self):
        instance = ConstitutionException(
            message="Test",
            severity=ConstitutionExceptionSeverity.HIGH,
            category=ConstitutionExceptionCategory.VALIDATION_ERROR,
        )
        json_str = instance.to_json()
        assert isinstance(json_str, str)
        data = json.loads(json_str)
        assert data["message"] == "Test"
        assert data["severity"] == "HIGH"
        assert data["category"] == "VALIDATION_ERROR"

    def test_is_catastrophic(self):
        # Catastrophic severity should return True
        instance = ConstitutionException(
            message="Catastrophic",
            severity=ConstitutionExceptionSeverity.CATASTROPHIC,
            category=ConstitutionExceptionCategory.CONSTITUTION_VIOLATION,
        )
        assert instance.is_catastrophic() is True

        # Non-catastrophic should return False
        instance = ConstitutionException(
            message="Not catastrophic",
            severity=ConstitutionExceptionSeverity.HIGH,
            category=ConstitutionExceptionCategory.CONSTITUTION_VIOLATION,
        )
        assert instance.is_catastrophic() is False

    def test_get_audit_entry(self):
        exc_id = uuid4()
        instance = ConstitutionException(
            message="Audit me",
            severity=ConstitutionExceptionSeverity.HIGH,
            category=ConstitutionExceptionCategory.CONSTITUTION_VIOLATION,
            exception_id=exc_id,
            module="audit_module",
            user_id="auditor",
        )
        entry = instance.get_audit_entry()
        assert isinstance(entry, dict)
        assert entry["audit_type"] == "CONSTITUTION_EXCEPTION"
        assert entry["exception_id"] == str(exc_id)
        assert entry["severity"] == "HIGH"
        assert entry["category"] == "CONSTITUTION_VIOLATION"
        assert entry["message"] == "Audit me"
        assert entry["module"] == "audit_module"
        assert entry["user_id"] == "auditor"
        assert "timestamp" in entry


class TestConstitutionalViolationException:
    def test_construction(self):
        rule_id = uuid4()
        instance = ConstitutionalViolationException(
            message="Violation",
            principle="Double entry",
            rule_id=rule_id,
        )
        assert isinstance(instance, ConstitutionalViolationException)
        assert isinstance(instance, ConstitutionException)
        assert instance.message == "Violation"
        assert instance.principle == "Double entry"
        assert instance.rule_id == rule_id
        assert instance.severity == ConstitutionExceptionSeverity.CRITICAL
        assert instance.category == ConstitutionExceptionCategory.CONSTITUTION_VIOLATION

    def test_to_dict(self):
        rule_id = uuid4()
        instance = ConstitutionalViolationException(
            message="Violation",
            principle="Double entry",
            rule_id=rule_id,
        )
        d = instance.to_dict()
        assert isinstance(d, dict)
        assert d["principle"] == "Double entry"
        assert d["rule_id"] == str(rule_id)
        assert d["message"] == "Violation"


class TestSovereigntyViolationException:
    def test_construction(self):
        instance = SovereigntyViolationException(
            message="Sovereignty violation",
            domain="Accounting",
            operation="Post",
            source="Journal",
        )
        assert isinstance(instance, SovereigntyViolationException)
        assert isinstance(instance, ConstitutionException)
        assert instance.message == "Sovereignty violation"
        assert instance.domain == "Accounting"
        assert instance.operation == "Post"
        assert instance.source == "Journal"
        assert instance.severity == ConstitutionExceptionSeverity.CATASTROPHIC
        assert instance.category == ConstitutionExceptionCategory.SOVEREIGNTY_VIOLATION

    def test_to_dict(self):
        instance = SovereigntyViolationException(
            message="Sovereignty violation",
            domain="Accounting",
            operation="Post",
            source="Journal",
        )
        d = instance.to_dict()
        assert d["domain"] == "Accounting"
        assert d["operation"] == "Post"
        assert d["source"] == "Journal"


class TestAmendmentException:
    def test_construction(self):
        proposal_id = uuid4()
        instance = AmendmentException(
            message="Amendment error",
            proposal_id=proposal_id,
            amendment_type="ADD_RULE",
        )
        assert isinstance(instance, AmendmentException)
        assert isinstance(instance, ConstitutionException)
        assert instance.proposal_id == proposal_id
        assert instance.amendment_type == "ADD_RULE"

    def test_to_dict(self):
        proposal_id = uuid4()
        instance = AmendmentException(
            message="Amendment error",
            proposal_id=proposal_id,
            amendment_type="ADD_RULE",
        )
        d = instance.to_dict()
        assert d["proposal_id"] == str(proposal_id)
        assert d["amendment_type"] == "ADD_RULE"


class TestVersionLockException:
    def test_construction(self):
        instance = VersionLockException(
            message="Version lock",
            current_state="DRAFT",
            required_state="APPROVED",
        )
        assert isinstance(instance, VersionLockException)
        assert isinstance(instance, ConstitutionException)
        assert instance.current_state == "DRAFT"
        assert instance.required_state == "APPROVED"

    def test_to_dict(self):
        instance = VersionLockException(
            message="Version lock",
            current_state="DRAFT",
            required_state="APPROVED",
        )
        d = instance.to_dict()
        assert d["current_state"] == "DRAFT"
        assert d["required_state"] == "APPROVED"


class TestInvariantViolationException:
    def test_construction(self):
        actual = {"a": 1}
        expected = {"a": 2}
        instance = InvariantViolationException(
            message="Invariant violation",
            invariant_type="balance",
            invariant_name="Double entry",
            actual_value=actual,
            expected_value=expected,
        )
        assert isinstance(instance, InvariantViolationException)
        assert isinstance(instance, ConstitutionException)
        assert instance.invariant_type == "balance"
        assert instance.invariant_name == "Double entry"
        assert instance.actual_value == actual
        assert instance.expected_value == expected

    def test_to_dict(self):
        actual = {"a": 1}
        expected = {"a": 2}
        instance = InvariantViolationException(
            message="Invariant violation",
            invariant_type="balance",
            invariant_name="Double entry",
            actual_value=actual,
            expected_value=expected,
        )
        d = instance.to_dict()
        assert d["invariant_type"] == "balance"
        assert d["invariant_name"] == "Double entry"
        assert d["actual_value"] == str(actual)
        assert d["expected_value"] == str(expected)


class TestForbiddenStateException:
    def test_construction(self):
        current = {"state": "DRAFT"}
        attempted = {"action": "POST"}
        instance = ForbiddenStateException(
            message="Forbidden state",
            state_category="journal",
            state_name="CLOSED",
            current_state=current,
            attempted_action=attempted,
        )
        assert isinstance(instance, ForbiddenStateException)
        assert isinstance(instance, ConstitutionException)
        assert instance.state_category == "journal"
        assert instance.state_name == "CLOSED"
        assert instance.current_state == current
        assert instance.attempted_action == attempted

    def test_to_dict(self):
        current = {"state": "DRAFT"}
        attempted = {"action": "POST"}
        instance = ForbiddenStateException(
            message="Forbidden state",
            state_category="journal",
            state_name="CLOSED",
            current_state=current,
            attempted_action=attempted,
        )
        d = instance.to_dict()
        assert d["state_category"] == "journal"
        assert d["state_name"] == "CLOSED"
        assert d["current_state"] == current
        assert d["attempted_action"] == attempted

    def test_truncate_dict(self):
        # Create an instance to access the private method
        instance = ForbiddenStateException(
            message="Forbidden",
            state_category="test",
            state_name="test",
        )
        # Test truncation of long string values
        long_value = "x" * 600
        d = {"key": long_value}
        truncated = instance._truncate_dict(d)
        assert len(truncated["key"]) == 503  # 500 + "..."
        assert truncated["key"].endswith("...")

        # Test nested dict
        nested = {"nested": {"deep": long_value}}
        truncated_nested = instance._truncate_dict(nested)
        assert len(truncated_nested["nested"]["deep"]) == 503

        # Test non-string values are left unchanged
        d2 = {"int": 123, "bool": True}
        truncated2 = instance._truncate_dict(d2)
        assert truncated2["int"] == 123
        assert truncated2["bool"] is True

        # Test max_length parameter
        truncated3 = instance._truncate_dict({"key": long_value}, max_length=10)
        assert len(truncated3["key"]) == 13  # 10 + "..."


class TestEnforcementException:
    def test_construction(self):
        op_id = uuid4()
        instance = EnforcementException(
            message="Enforcement error",
            stage="pre_execution",
            operation_id=op_id,
        )
        assert isinstance(instance, EnforcementException)
        assert isinstance(instance, ConstitutionException)
        assert instance.stage == "pre_execution"
        assert instance.operation_id == op_id

    def test_to_dict(self):
        op_id = uuid4()
        instance = EnforcementException(
            message="Enforcement error",
            stage="pre_execution",
            operation_id=op_id,
        )
        d = instance.to_dict()
        assert d["stage"] == "pre_execution"
        assert d["operation_id"] == str(op_id)


class TestIntegrityException:
    def test_construction(self):
        instance = IntegrityException(
            message="Integrity error",
            expected_hash="abc",
            actual_hash="def",
            affected_entity="Journal",
        )
        assert isinstance(instance, IntegrityException)
        assert isinstance(instance, ConstitutionException)
        assert instance.expected_hash == "abc"
        assert instance.actual_hash == "def"
        assert instance.affected_entity == "Journal"

    def test_to_dict(self):
        instance = IntegrityException(
            message="Integrity error",
            expected_hash="abc",
            actual_hash="def",
            affected_entity="Journal",
        )
        d = instance.to_dict()
        assert d["expected_hash"] == "abc"
        assert d["actual_hash"] == "def"
        assert d["affected_entity"] == "Journal"


class TestAuthorizationException:
    def test_construction(self):
        instance = AuthorizationException(
            message="Authorization error",
            required_roles=["admin", "auditor"],
            user_roles=["user"],
            required_approvers=["CEO"],
        )
        assert isinstance(instance, AuthorizationException)
        assert isinstance(instance, ConstitutionException)
        assert instance.required_roles == ["admin", "auditor"]
        assert instance.user_roles == ["user"]
        assert instance.required_approvers == ["CEO"]

    def test_to_dict(self):
        instance = AuthorizationException(
            message="Authorization error",
            required_roles=["admin", "auditor"],
            user_roles=["user"],
            required_approvers=["CEO"],
        )
        d = instance.to_dict()
        assert d["required_roles"] == ["admin", "auditor"]
        assert d["user_roles"] == ["user"]
        assert d["required_approvers"] == ["CEO"]


class TestValidationException:
    def test_construction(self):
        invalid = {"field": "value"}
        instance = ValidationException(
            message="Validation error",
            field="amount",
            invalid_value=invalid,
            validation_rule="must_be_positive",
        )
        assert isinstance(instance, ValidationException)
        assert isinstance(instance, ConstitutionException)
        assert instance.field == "amount"
        assert instance.invalid_value == invalid
        assert instance.validation_rule == "must_be_positive"

    def test_to_dict(self):
        invalid = {"field": "value"}
        instance = ValidationException(
            message="Validation error",
            field="amount",
            invalid_value=invalid,
            validation_rule="must_be_positive",
        )
        d = instance.to_dict()
        assert d["field"] == "amount"
        assert d["invalid_value"] == invalid
        assert d["validation_rule"] == "must_be_positive"


class TestConstitutionExceptionFactory:
    def test_create_violation(self):
        rule_id = uuid4()
        exc = ConstitutionExceptionFactory.create_violation(
            message="Violation",
            principle="Double entry",
            rule_id=rule_id,
            severity=ConstitutionExceptionSeverity.HIGH,
        )
        assert isinstance(exc, ConstitutionalViolationException)
        assert exc.message == "Violation"
        assert exc.principle == "Double entry"
        assert exc.rule_id == rule_id
        assert exc.severity == ConstitutionExceptionSeverity.HIGH

    def test_create_sovereignty_violation(self):
        exc = ConstitutionExceptionFactory.create_sovereignty_violation(
            message="Sovereignty",
            domain="Accounting",
            operation="Post",
            source="Journal",
        )
        assert isinstance(exc, SovereigntyViolationException)
        assert exc.domain == "Accounting"
        assert exc.operation == "Post"
        assert exc.source == "Journal"

    def test_create_amendment_error(self):
        proposal_id = uuid4()
        exc = ConstitutionExceptionFactory.create_amendment_error(
            message="Amendment error",
            proposal_id=proposal_id,
            amendment_type="ADD_RULE",
        )
        assert isinstance(exc, AmendmentException)
        assert exc.proposal_id == proposal_id
        assert exc.amendment_type == "ADD_RULE"

    def test_create_version_lock_error(self):
        exc = ConstitutionExceptionFactory.create_version_lock_error(
            message="Version lock",
            current_state="DRAFT",
            required_state="APPROVED",
        )
        assert isinstance(exc, VersionLockException)
        assert exc.current_state == "DRAFT"
        assert exc.required_state == "APPROVED"

    def test_create_invariant_violation(self):
        actual = {"a": 1}
        expected = {"a": 2}
        exc = ConstitutionExceptionFactory.create_invariant_violation(
            message="Invariant violation",
            invariant_type="balance",
            invariant_name="Double entry",
            actual_value=actual,
            expected_value=expected,
            severity=ConstitutionExceptionSeverity.HIGH,
        )
        assert isinstance(exc, InvariantViolationException)
        assert exc.message == "Invariant violation"
        assert exc.invariant_type == "balance"
        assert exc.invariant_name == "Double entry"
        assert exc.actual_value == actual
        assert exc.expected_value == expected
        assert exc.severity == ConstitutionExceptionSeverity.HIGH

    def test_create_forbidden_state(self):
        current = {"state": "DRAFT"}
        attempted = {"action": "POST"}
        exc = ConstitutionExceptionFactory.create_forbidden_state(
            message="Forbidden state",
            state_category="journal",
            state_name="CLOSED",
            current_state=current,
            attempted_action=attempted,
        )
        assert isinstance(exc, ForbiddenStateException)
        assert exc.state_category == "journal"
        assert exc.state_name == "CLOSED"
        assert exc.current_state == current
        assert exc.attempted_action == attempted

    def test_create_enforcement_error(self):
        op_id = uuid4()
        exc = ConstitutionExceptionFactory.create_enforcement_error(
            message="Enforcement error",
            stage="pre_execution",
            operation_id=op_id,
        )
        assert isinstance(exc, EnforcementException)
        assert exc.stage == "pre_execution"
        assert exc.operation_id == op_id

    def test_create_integrity_error(self):
        exc = ConstitutionExceptionFactory.create_integrity_error(
            message="Integrity error",
            expected_hash="abc",
            actual_hash="def",
            affected_entity="Journal",
        )
        assert isinstance(exc, IntegrityException)
        assert exc.expected_hash == "abc"
        assert exc.actual_hash == "def"
        assert exc.affected_entity == "Journal"

    def test_create_authorization_error(self):
        exc = ConstitutionExceptionFactory.create_authorization_error(
            message="Authorization error",
            required_roles=["admin", "auditor"],
            user_roles=["user"],
            required_approvers=["CEO"],
        )
        assert isinstance(exc, AuthorizationException)
        assert exc.required_roles == ["admin", "auditor"]
        assert exc.user_roles == ["user"]
        assert exc.required_approvers == ["CEO"]

    def test_create_validation_error(self):
        invalid = {"field": "value"}
        exc = ConstitutionExceptionFactory.create_validation_error(
            message="Validation error",
            field="amount",
            invalid_value=invalid,
            validation_rule="must_be_positive",
        )
        assert isinstance(exc, ValidationException)
        assert exc.field == "amount"
        assert exc.invalid_value == invalid
        assert exc.validation_rule == "must_be_positive"

    def test_from_violation_record_supreme(self):
        # Mock SupremeViolationRecord
        mock_record = MagicMock()
        mock_record.message = "Supreme violation"
        mock_record.principle = MagicMock()
        mock_record.principle.name = "Sovereignty"
        mock_record.rule_id = UUID(int=0)  # This should be converted to None
        mock_record.offending_module = "module"
        mock_record.offending_user = "user"
        mock_record.offending_command_id = uuid4()
        mock_record.violation_id = uuid4()
        mock_record.severity = MagicMock()
        mock_record.severity.value = 70  # Critical

        # Patch the import inside the factory method
        with patch("constitution.constitution_exceptions.SupremeViolationRecord", mock_record.__class__):
            # Also need to patch the isinstance check
            with patch("constitution.constitution_exceptions.isinstance", return_value=True):
                exc = ConstitutionExceptionFactory.from_violation_record(mock_record)
                assert isinstance(exc, ConstitutionalViolationException)
                assert exc.message == "Supreme violation"
                assert exc.principle == "Sovereignty"
                assert exc.rule_id is None  # because UUID(int=0) is converted to None
                assert exc.severity == ConstitutionExceptionSeverity.CRITICAL
                # Ensure the mapping works for severity 70 -> CRITICAL
        # More refined test using actual class from module
        # We'll patch the actual import inside the function

    def test_from_violation_record_invariant(self):
        # Mock InvariantViolationRecord
        mock_record = MagicMock()
        mock_record.message = "Invariant violation"
        mock_record.invariant_type = MagicMock()
        mock_record.invariant_type.name = "Balance"
        mock_record.actual_value = {"actual": 1}
        mock_record.expected_value = {"expected": 2}
        mock_record.offending_module = "inv_module"
        mock_record.offending_user = "inv_user"
        mock_record.transaction_id = uuid4()
        mock_record.legal_entity_id = uuid4()
        mock_record.severity = MagicMock()
        mock_record.severity.value = 80  # Critical

        with patch("constitution.constitution_exceptions.InvariantViolation", mock_record.__class__):
            with patch("constitution.constitution_exceptions.isinstance", return_value=True):
                exc = ConstitutionExceptionFactory.from_violation_record(mock_record)
                assert isinstance(exc, InvariantViolationException)
                assert exc.message == "Invariant violation"
                assert exc.invariant_type == "Balance"
                assert exc.actual_value == {"actual": 1}
                assert exc.expected_value == {"expected": 2}
                assert exc.severity == ConstitutionExceptionSeverity.CRITICAL

    def test_from_violation_record_unknown(self):
        # Unknown record type
        mock_record = MagicMock()
        mock_record.__str__ = lambda self: "Unknown record"
        exc = ConstitutionExceptionFactory.from_violation_record(mock_record)
        assert isinstance(exc, ConstitutionException)
        assert exc.message == "Unknown record"
        assert exc.severity == ConstitutionExceptionSeverity.MEDIUM


class TestConstitutionExceptionHandler:
    def test_handle_returns_dict(self):
        exc = ConstitutionException(
            message="Test",
            severity=ConstitutionExceptionSeverity.CRITICAL,
            category=ConstitutionExceptionCategory.CONSTITUTION_VIOLATION,
        )
        result = ConstitutionExceptionHandler.handle(exception=exc)
        assert isinstance(result, dict)
        assert result["handled"] is True
        assert result["severity"] == "CRITICAL"
        assert result["category"] == "CONSTITUTION_VIOLATION"
        assert "audit_entry" in result
        assert result["action"] == "OPERATION_REJECTED_INVESTIGATE"

    def test_handle_catastrophic(self):
        exc = ConstitutionException(
            message="Catastrophic",
            severity=ConstitutionExceptionSeverity.CATASTROPHIC,
            category=ConstitutionExceptionCategory.INTEGRITY_ERROR,
        )
        result = ConstitutionExceptionHandler.handle(exception=exc)
        assert result["action"] == "SYSTEM_FREEZE_REQUIRED"

    def test_handle_high(self):
        exc = ConstitutionException(
            message="High",
            severity=ConstitutionExceptionSeverity.HIGH,
            category=ConstitutionExceptionCategory.AUTHORIZATION_ERROR,
        )
        result = ConstitutionExceptionHandler.handle(exception=exc)
        assert result["action"] == "OPERATION_REJECTED_REVIEW"

    def test_handle_medium(self):
        exc = ConstitutionException(
            message="Medium",
            severity=ConstitutionExceptionSeverity.MEDIUM,
            category=ConstitutionExceptionCategory.VALIDATION_ERROR,
        )
        result = ConstitutionExceptionHandler.handle(exception=exc)
        assert result["action"] == "OPERATION_REJECTED_RETRY"

    def test_handle_low(self):
        exc = ConstitutionException(
            message="Low",
            severity=ConstitutionExceptionSeverity.LOW,
            category=ConstitutionExceptionCategory.VALIDATION_ERROR,
        )
        result = ConstitutionExceptionHandler.handle(exception=exc)
        assert result["action"] == "WARNING_ONLY"

    def test_handle_info(self):
        exc = ConstitutionException(
            message="Info",
            severity=ConstitutionExceptionSeverity.INFO,
            category=ConstitutionExceptionCategory.VALIDATION_ERROR,
        )
        result = ConstitutionExceptionHandler.handle(exception=exc)
        assert result["action"] == "LOG_ONLY"

    def test_should_retry(self):
        # Medium and below should retry
        exc = ConstitutionException(
            message="Test",
            severity=ConstitutionExceptionSeverity.MEDIUM,
            category=ConstitutionExceptionCategory.VALIDATION_ERROR,
        )
        assert ConstitutionExceptionHandler.should_retry(exc) is True
        exc.severity = ConstitutionExceptionSeverity.LOW
        assert ConstitutionExceptionHandler.should_retry(exc) is True
        exc.severity = ConstitutionExceptionSeverity.INFO
        assert ConstitutionExceptionHandler.should_retry(exc) is True
        # High and above should not retry
        exc.severity = ConstitutionExceptionSeverity.HIGH
        assert ConstitutionExceptionHandler.should_retry(exc) is False
        exc.severity = ConstitutionExceptionSeverity.CRITICAL
        assert ConstitutionExceptionHandler.should_retry(exc) is False
        exc.severity = ConstitutionExceptionSeverity.CATASTROPHIC
        assert ConstitutionExceptionHandler.should_retry(exc) is False

    def test_requires_audit(self):
        # High and above require audit
        exc = ConstitutionException(
            message="Test",
            severity=ConstitutionExceptionSeverity.HIGH,
            category=ConstitutionExceptionCategory.CONSTITUTION_VIOLATION,
        )
        assert ConstitutionExceptionHandler.requires_audit(exc) is True
        exc.severity = ConstitutionExceptionSeverity.CRITICAL
        assert ConstitutionExceptionHandler.requires_audit(exc) is True
        exc.severity = ConstitutionExceptionSeverity.CATASTROPHIC
        assert ConstitutionExceptionHandler.requires_audit(exc) is True
        # Medium and below do not require audit
        exc.severity = ConstitutionExceptionSeverity.MEDIUM
        assert ConstitutionExceptionHandler.requires_audit(exc) is False
        exc.severity = ConstitutionExceptionSeverity.LOW
        assert ConstitutionExceptionHandler.requires_audit(exc) is False
        exc.severity = ConstitutionExceptionSeverity.INFO
        assert ConstitutionExceptionHandler.requires_audit(exc) is False