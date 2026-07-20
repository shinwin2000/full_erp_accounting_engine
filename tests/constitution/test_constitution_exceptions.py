#!/usr/bin/env python3
"""
tests/unit/test_constitution_exceptions.py
Test untuk constitution/constitution_exceptions.py
"""

from __future__ import annotations

import json
from uuid import uuid4

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
        assert d["actual_value"] == actual
        assert d["expected_value"] == expected


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


class TestConstitutionExceptionHandler:
    def test_handle_returns_dict(self):
        # handle is a static method that takes an exception and returns a dict
        exc = ConstitutionException(
            message="Test",
            severity=ConstitutionExceptionSeverity.CRITICAL,
            category=ConstitutionExceptionCategory.CONSTITUTION_VIOLATION,
        )
        result = ConstitutionExceptionHandler.handle(exception=exc)
        assert isinstance(result, dict)
        # Check some expected keys
        assert "handled" in result
        assert "severity" in result

    def test_should_retry_returns_bool(self):
        exc = ConstitutionException(
            message="Test",
            severity=ConstitutionExceptionSeverity.LOW,
            category=ConstitutionExceptionCategory.VALIDATION_ERROR,
        )
        result = ConstitutionExceptionHandler.should_retry(exception=exc)
        assert isinstance(result, bool)

    def test_requires_audit_returns_bool(self):
        exc = ConstitutionException(
            message="Test",
            severity=ConstitutionExceptionSeverity.CRITICAL,
            category=ConstitutionExceptionCategory.CONSTITUTION_VIOLATION,
        )
        result = ConstitutionExceptionHandler.requires_audit(exception=exc)
        assert isinstance(result, bool)
