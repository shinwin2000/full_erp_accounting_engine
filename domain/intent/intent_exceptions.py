#!/usr/bin/env python3
"""
Module: intent_exceptions.py
Layer: 5 - Domain / Intent
Responsibility: Exception terkait intent.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Any


class IntentErrorCode(Enum):
    INTENT_NOT_FOUND = auto()
    INTENT_INVALID_STATUS = auto()
    INTENT_ALREADY_SUBMITTED = auto()
    INTENT_ALREADY_APPROVED = auto()
    INTENT_ALREADY_EXECUTED = auto()
    INTENT_ALREADY_CANCELLED = auto()
    INTENT_VALIDATION_FAILED = auto()
    INTENT_DATA_INCOMPLETE = auto()
    INTENT_DATA_INVALID = auto()
    INTENT_APPROVAL_NOT_FOUND = auto()
    INTENT_APPROVAL_INSUFFICIENT = auto()
    INTENT_APPROVAL_LEVEL_INVALID = auto()
    INTENT_APPROVAL_ALREADY_GIVEN = auto()
    INTENT_RISK_ASSESSMENT_FAILED = auto()
    INTENT_RISK_TOO_HIGH = auto()
    INTENT_CANNOT_VOID = auto()
    INTENT_ALREADY_VOIDED = auto()
    INTENT_WORKFLOW_NOT_FOUND = auto()
    INTENT_WORKFLOW_INVALID_TRANSITION = auto()
    INTENT_UNKNOWN_ERROR = auto()


class IntentSeverity(Enum):
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20


class IntentError(Exception):
    def __init__(
        self,
        message: str,
        error_code: IntentErrorCode,
        severity: IntentSeverity = IntentSeverity.MEDIUM,
        component: str | None = None,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        self.error_code = error_code
        self.severity = severity
        self.component = component
        self.details = details or {}
        self.cause = cause
        full_message = f"[{severity.name}][{error_code.name}] {message}"
        if component:
            full_message = f"[{component}] {full_message}"
        super().__init__(full_message)
        self._original_message = message

    @property
    def original_message(self) -> str:
        return self._original_message

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.__class__.__name__,
            "error_code": self.error_code.name,
            "severity": self.severity.name,
            "message": self._original_message,
            "component": self.component,
            "details": self.details,
            "cause": str(self.cause) if self.cause else None,
        }

    def is_critical(self) -> bool:
        return self.severity == IntentSeverity.CRITICAL


class IntentNotFoundError(IntentError):
    def __init__(self, intent_id: str, **kwargs):
        super().__init__(
            message=f"Intent {intent_id} not found",
            error_code=IntentErrorCode.INTENT_NOT_FOUND,
            severity=IntentSeverity.HIGH,
            component="capture",
            details={"intent_id": intent_id},
            **kwargs,
        )
        self.intent_id = intent_id


class IntentInvalidStatusError(IntentError):
    def __init__(self, intent_id: str, current_status: str, required_status: str, **kwargs):
        super().__init__(
            message=f"Intent {intent_id} has invalid status {current_status}. Required: {required_status}",
            error_code=IntentErrorCode.INTENT_INVALID_STATUS,
            severity=IntentSeverity.HIGH,
            component="capture",
            details={
                "intent_id": intent_id,
                "current_status": current_status,
                "required_status": required_status,
            },
            **kwargs,
        )
        self.intent_id = intent_id
        self.current_status = current_status
        self.required_status = required_status


class IntentAlreadySubmittedError(IntentError):
    def __init__(self, intent_id: str, **kwargs):
        super().__init__(
            message=f"Intent {intent_id} has already been submitted for approval",
            error_code=IntentErrorCode.INTENT_ALREADY_SUBMITTED,
            severity=IntentSeverity.MEDIUM,
            component="approval",
            details={"intent_id": intent_id},
            **kwargs,
        )
        self.intent_id = intent_id


class IntentAlreadyApprovedError(IntentError):
    def __init__(self, intent_id: str, **kwargs):
        super().__init__(
            message=f"Intent {intent_id} has already been approved",
            error_code=IntentErrorCode.INTENT_ALREADY_APPROVED,
            severity=IntentSeverity.MEDIUM,
            component="approval",
            details={"intent_id": intent_id},
            **kwargs,
        )
        self.intent_id = intent_id


class IntentAlreadyExecutedError(IntentError):
    def __init__(self, intent_id: str, outcome_id: str | None = None, **kwargs):
        super().__init__(
            message=f"Intent {intent_id} has already been executed. Outcome: {outcome_id}",
            error_code=IntentErrorCode.INTENT_ALREADY_EXECUTED,
            severity=IntentSeverity.HIGH,
            component="execution",
            details={"intent_id": intent_id, "outcome_id": outcome_id},
            **kwargs,
        )
        self.intent_id = intent_id


class IntentAlreadyCancelledError(IntentError):
    def __init__(self, intent_id: str, **kwargs):
        super().__init__(
            message=f"Intent {intent_id} has already been cancelled",
            error_code=IntentErrorCode.INTENT_ALREADY_CANCELLED,
            severity=IntentSeverity.MEDIUM,
            component="void",
            details={"intent_id": intent_id},
            **kwargs,
        )
        self.intent_id = intent_id


class IntentValidationFailedError(IntentError):
    def __init__(self, message: str, errors: list[dict[str, Any]], **kwargs):
        super().__init__(
            message=f"Intent validation failed: {message}",
            error_code=IntentErrorCode.INTENT_VALIDATION_FAILED,
            severity=IntentSeverity.HIGH,
            component="validation",
            details={"validation_errors": errors},
            **kwargs,
        )
        self.errors = errors


class IntentDataIncompleteError(IntentError):
    def __init__(self, missing_fields: list[str], **kwargs):
        super().__init__(
            message=f"Intent data incomplete. Missing fields: {', '.join(missing_fields)}",
            error_code=IntentErrorCode.INTENT_DATA_INCOMPLETE,
            severity=IntentSeverity.HIGH,
            component="capture",
            details={"missing_fields": missing_fields},
            **kwargs,
        )
        self.missing_fields = missing_fields


class IntentApprovalInsufficientError(IntentError):
    def __init__(self, intent_id: str, required_approvals: int, current_approvals: int, **kwargs):
        super().__init__(
            message=f"Insufficient approvals for intent {intent_id}: {current_approvals}/{required_approvals}",
            error_code=IntentErrorCode.INTENT_APPROVAL_INSUFFICIENT,
            severity=IntentSeverity.HIGH,
            component="approval",
            details={
                "intent_id": intent_id,
                "required_approvals": required_approvals,
                "current_approvals": current_approvals,
            },
            **kwargs,
        )
        self.intent_id = intent_id
        self.required_approvals = required_approvals
        self.current_approvals = current_approvals


class IntentApprovalLevelInvalidError(IntentError):
    def __init__(self, intent_id: str, required_level: str, provided_level: str, **kwargs):
        super().__init__(
            message=f"Invalid approval level for intent {intent_id}. Required: {required_level}, Provided: {provided_level}",
            error_code=IntentErrorCode.INTENT_APPROVAL_LEVEL_INVALID,
            severity=IntentSeverity.HIGH,
            component="approval",
            details={
                "intent_id": intent_id,
                "required_level": required_level,
                "provided_level": provided_level,
            },
            **kwargs,
        )
        self.intent_id = intent_id


class IntentRiskTooHighError(IntentError):
    def __init__(self, intent_id: str, risk_level: str, risk_score: float, **kwargs):
        super().__init__(
            message=f"Intent {intent_id} has risk level {risk_level} (score: {risk_score}) which exceeds acceptable threshold",
            error_code=IntentErrorCode.INTENT_RISK_TOO_HIGH,
            severity=IntentSeverity.CRITICAL,
            component="risk",
            details={"intent_id": intent_id, "risk_level": risk_level, "risk_score": risk_score},
            **kwargs,
        )
        self.intent_id = intent_id


class IntentCannotVoidError(IntentError):
    def __init__(self, intent_id: str, reason: str, **kwargs):
        super().__init__(
            message=f"Cannot void intent {intent_id}: {reason}",
            error_code=IntentErrorCode.INTENT_CANNOT_VOID,
            severity=IntentSeverity.HIGH,
            component="void",
            details={"intent_id": intent_id, "reason": reason},
            **kwargs,
        )
        self.intent_id = intent_id


class IntentWorkflowInvalidTransitionError(IntentError):
    def __init__(self, intent_id: str, from_status: str, to_status: str, **kwargs):
        super().__init__(
            message=f"Invalid workflow transition for intent {intent_id}: {from_status} -> {to_status}",
            error_code=IntentErrorCode.INTENT_WORKFLOW_INVALID_TRANSITION,
            severity=IntentSeverity.HIGH,
            component="workflow",
            details={"intent_id": intent_id, "from_status": from_status, "to_status": to_status},
            **kwargs,
        )
        self.intent_id = intent_id
        self.from_status = from_status
        self.to_status = to_status


class IntentExceptionFactory:
    @staticmethod
    def not_found(intent_id: str, **kwargs) -> IntentNotFoundError:
        return IntentNotFoundError(intent_id=intent_id, **kwargs)

    @staticmethod
    def invalid_status(
        intent_id: str, current: str, required: str, **kwargs
    ) -> IntentInvalidStatusError:
        return IntentInvalidStatusError(
            intent_id=intent_id, current_status=current, required_status=required, **kwargs
        )

    @staticmethod
    def already_submitted(intent_id: str, **kwargs) -> IntentAlreadySubmittedError:
        return IntentAlreadySubmittedError(intent_id=intent_id, **kwargs)

    @staticmethod
    def already_approved(intent_id: str, **kwargs) -> IntentAlreadyApprovedError:
        return IntentAlreadyApprovedError(intent_id=intent_id, **kwargs)

    @staticmethod
    def already_executed(
        intent_id: str, outcome_id: str | None = None, **kwargs
    ) -> IntentAlreadyExecutedError:
        return IntentAlreadyExecutedError(intent_id=intent_id, outcome_id=outcome_id, **kwargs)

    @staticmethod
    def cannot_void(intent_id: str, reason: str, **kwargs) -> IntentCannotVoidError:
        return IntentCannotVoidError(intent_id=intent_id, reason=reason, **kwargs)

    @staticmethod
    def validation_failed(
        message: str, errors: list[dict[str, Any]], **kwargs
    ) -> IntentValidationFailedError:
        return IntentValidationFailedError(message=message, errors=errors, **kwargs)

    @staticmethod
    def data_incomplete(missing_fields: list[str], **kwargs) -> IntentDataIncompleteError:
        return IntentDataIncompleteError(missing_fields=missing_fields, **kwargs)

    @staticmethod
    def approval_insufficient(
        intent_id: str, required: int, current: int, **kwargs
    ) -> IntentApprovalInsufficientError:
        return IntentApprovalInsufficientError(
            intent_id=intent_id, required_approvals=required, current_approvals=current, **kwargs
        )

    @staticmethod
    def risk_too_high(
        intent_id: str, risk_level: str, risk_score: float, **kwargs
    ) -> IntentRiskTooHighError:
        return IntentRiskTooHighError(
            intent_id=intent_id, risk_level=risk_level, risk_score=risk_score, **kwargs
        )

    @staticmethod
    def invalid_transition(
        intent_id: str, from_status: str, to_status: str, **kwargs
    ) -> IntentWorkflowInvalidTransitionError:
        return IntentWorkflowInvalidTransitionError(
            intent_id=intent_id, from_status=from_status, to_status=to_status, **kwargs
        )


__all__ = [
    "IntentAlreadyApprovedError",
    "IntentAlreadyCancelledError",
    "IntentAlreadyExecutedError",
    "IntentAlreadySubmittedError",
    "IntentApprovalInsufficientError",
    "IntentApprovalLevelInvalidError",
    "IntentCannotVoidError",
    "IntentDataIncompleteError",
    "IntentError",
    "IntentErrorCode",
    "IntentExceptionFactory",
    "IntentInvalidStatusError",
    "IntentNotFoundError",
    "IntentRiskTooHighError",
    "IntentSeverity",
    "IntentValidationFailedError",
    "IntentWorkflowInvalidTransitionError",
]
