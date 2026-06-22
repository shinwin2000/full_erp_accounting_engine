#!/usr/bin/env python3
"""
Module: guard_exceptions.py
Layer: 4 - Kernel / Guards
Responsibility: Exception untuk semua guard di kernel.
               Mendefinisikan hierarchy exception untuk error yang terjadi
               di guard layer, seperti balance checker, period lock,
               currency validator, dll.

Dependencies:
- standard library (enum, typing)

Audit: Setiap exception guard dictat untuk audit.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Any

# === 1. CONSTANTS & ENUMS ===


class GuardErrorCode(Enum):
    """Kode error untuk guard."""

    # Balance checker errors
    BALANCE_NEGATIVE = auto()
    BALANCE_INSUFFICIENT = auto()
    BALANCE_CURRENCY_MISMATCH = auto()

    # Period lock errors
    PERIOD_CLOSED = auto()
    PERIOD_LOCKED = auto()
    PERIOD_FUTURE = auto()
    PERIOD_NOT_FOUND = auto()

    # Currency validator errors
    CURRENCY_NOT_SUPPORTED = auto()
    CURRENCY_EXCHANGE_RATE_MISSING = auto()
    CURRENCY_EXCHANGE_RATE_INVALID = auto()

    # Legal entity boundary errors
    ENTITY_ACCESS_DENIED = auto()
    ENTITY_NOT_FOUND = auto()
    ENTITY_CROSS_ACCESS_DENIED = auto()

    # Authority matrix errors
    AUTHORIZATION_MISSING = auto()
    ROLE_NOT_FOUND = auto()
    PERMISSION_DENIED = auto()

    # Evidence attacher errors
    EVIDENCE_MISSING = auto()
    EVIDENCE_TYPE_INVALID = auto()
    EVIDENCE_INTEGRITY_FAILED = auto()

    # Regulatory compliance errors
    REGULATORY_VIOLATION = auto()
    AML_THRESHOLD_EXCEEDED = auto()
    TAX_COMPLIANCE_FAILED = auto()

    # Temporal consistency errors
    TEMPORAL_INCONSISTENCY = auto()
    CLOCK_SKEW_DETECTED = auto()
    BACKDATING_EXCEEDED = auto()

    # Emergency freeze errors
    SYSTEM_FROZEN = auto()
    FREEZE_AUTHORIZATION_MISSING = auto()

    # Coretax format errors
    CORETAX_FORMAT_INVALID = auto()
    CORETAX_NPWP_INVALID = auto()
    CORETAX_NTPN_INVALID = auto()
    CORETAX_FAKTUR_INVALID = auto()

    # SOD enforcer errors
    SOD_MAKER_CHECKER_VIOLATION = auto()
    SOD_ROLE_CONFLICT = auto()
    SOD_DUAL_CONTROL_REQUIRED = auto()
    SOD_APPROVAL_LIMIT_EXCEEDED = auto()

    # Budget availability errors
    BUDGET_INSUFFICIENT = auto()
    BUDGET_NOT_FOUND = auto()
    BUDGET_APPROVAL_REQUIRED = auto()

    # Credit limit enforcer errors
    CREDIT_LIMIT_EXCEEDED = auto()
    CREDIT_LIMIT_WARNING = auto()

    # General guard errors
    GUARD_NOT_APPLICABLE = auto()
    GUARD_VALIDATION_FAILED = auto()

    def display_name(self) -> str:
        """Return human-readable display name."""
        names = {
            GuardErrorCode.BALANCE_NEGATIVE: "Negative Balance",
            GuardErrorCode.BALANCE_INSUFFICIENT: "Insufficient Balance",
            GuardErrorCode.BALANCE_CURRENCY_MISMATCH: "Currency Mismatch",
            GuardErrorCode.PERIOD_CLOSED: "Period Closed",
            GuardErrorCode.PERIOD_LOCKED: "Period Locked",
            GuardErrorCode.PERIOD_FUTURE: "Future Period",
            GuardErrorCode.PERIOD_NOT_FOUND: "Period Not Found",
            GuardErrorCode.CURRENCY_NOT_SUPPORTED: "Currency Not Supported",
            GuardErrorCode.CURRENCY_EXCHANGE_RATE_MISSING: "Exchange Rate Missing",
            GuardErrorCode.CURRENCY_EXCHANGE_RATE_INVALID: "Invalid Exchange Rate",
            GuardErrorCode.ENTITY_ACCESS_DENIED: "Entity Access Denied",
            GuardErrorCode.ENTITY_NOT_FOUND: "Entity Not Found",
            GuardErrorCode.ENTITY_CROSS_ACCESS_DENIED: "Cross-Entity Access Denied",
            GuardErrorCode.AUTHORIZATION_MISSING: "Authorization Missing",
            GuardErrorCode.ROLE_NOT_FOUND: "Role Not Found",
            GuardErrorCode.PERMISSION_DENIED: "Permission Denied",
            GuardErrorCode.EVIDENCE_MISSING: "Evidence Missing",
            GuardErrorCode.EVIDENCE_TYPE_INVALID: "Invalid Evidence Type",
            GuardErrorCode.EVIDENCE_INTEGRITY_FAILED: "Evidence Integrity Failed",
            GuardErrorCode.REGULATORY_VIOLATION: "Regulatory Violation",
            GuardErrorCode.AML_THRESHOLD_EXCEEDED: "AML Threshold Exceeded",
            GuardErrorCode.TAX_COMPLIANCE_FAILED: "Tax Compliance Failed",
            GuardErrorCode.TEMPORAL_INCONSISTENCY: "Temporal Inconsistency",
            GuardErrorCode.CLOCK_SKEW_DETECTED: "Clock Skew Detected",
            GuardErrorCode.BACKDATING_EXCEEDED: "Backdating Exceeded",
            GuardErrorCode.SYSTEM_FROZEN: "System Frozen",
            GuardErrorCode.FREEZE_AUTHORIZATION_MISSING: "Freeze Authorization Missing",
            GuardErrorCode.CORETAX_FORMAT_INVALID: "Coretax Format Invalid",
            GuardErrorCode.CORETAX_NPWP_INVALID: "Invalid NPWP",
            GuardErrorCode.CORETAX_NTPN_INVALID: "Invalid NTPN",
            GuardErrorCode.CORETAX_FAKTUR_INVALID: "Invalid Faktur",
            GuardErrorCode.SOD_MAKER_CHECKER_VIOLATION: "Maker-Checker Violation",
            GuardErrorCode.SOD_ROLE_CONFLICT: "Role Conflict",
            GuardErrorCode.SOD_DUAL_CONTROL_REQUIRED: "Dual Control Required",
            GuardErrorCode.SOD_APPROVAL_LIMIT_EXCEEDED: "Approval Limit Exceeded",
            GuardErrorCode.BUDGET_INSUFFICIENT: "Insufficient Budget",
            GuardErrorCode.BUDGET_NOT_FOUND: "Budget Not Found",
            GuardErrorCode.BUDGET_APPROVAL_REQUIRED: "Budget Approval Required",
            GuardErrorCode.CREDIT_LIMIT_EXCEEDED: "Credit Limit Exceeded",
            GuardErrorCode.CREDIT_LIMIT_WARNING: "Credit Limit Warning",
            GuardErrorCode.GUARD_NOT_APPLICABLE: "Guard Not Applicable",
            GuardErrorCode.GUARD_VALIDATION_FAILED: "Guard Validation Failed",
        }
        return names.get(self, self.name.replace("_", " ").title())

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.name,
            "display": self.display_name(),
        }

    @classmethod
    def from_string(cls, value: str) -> GuardErrorCode:
        """Parse from string."""
        for code in cls:
            if code.name == value:
                return code
        raise ValueError(f"Unknown GuardErrorCode: {value}")


class GuardSeverity(Enum):
    """Severity untuk guard error."""

    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20

    def display_name(self) -> str:
        """Return human-readable display name."""
        names = {
            GuardSeverity.CRITICAL: "Critical",
            GuardSeverity.HIGH: "High",
            GuardSeverity.MEDIUM: "Medium",
            GuardSeverity.LOW: "Low",
        }
        return names.get(self, self.name.title())

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.name,
            "level": self.value,
            "display": self.display_name(),
        }

    @classmethod
    def from_string(cls, value: str) -> GuardSeverity:
        """Parse from string."""
        for severity in cls:
            if severity.name == value:
                return severity
        raise ValueError(f"Unknown GuardSeverity: {value}")


# === 2. BASE EXCEPTION ===


class GuardViolationError(Exception):
    """
    Base exception untuk semua pelanggaran guard.

    Business context: Exception yang terjadi di guard layer harus
    mewarisi kelas ini untuk konsistensi handling.
    """

    def __init__(
        self,
        message: str,
        guard_name: str,
        error_code: GuardErrorCode = GuardErrorCode.GUARD_VALIDATION_FAILED,
        severity: GuardSeverity = GuardSeverity.HIGH,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        self.guard_name = guard_name
        self.error_code = error_code
        self.severity = severity
        self.details = details or {}
        self.cause = cause

        full_message = f"[{guard_name}][{severity.name}] {message}"
        super().__init__(full_message)
        self._original_message = message

    @property
    def original_message(self) -> str:
        return self._original_message

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.__class__.__name__,
            "guard_name": self.guard_name,
            "error_code": self.error_code.name,
            "error_code_display": self.error_code.display_name() if hasattr(self.error_code, "display_name") else self.error_code.name,
            "severity": self.severity.name,
            "severity_level": self.severity.value,
            "message": self._original_message,
            "details": self.details,
            "cause": str(self.cause) if self.cause else None,
        }

    def is_critical(self) -> bool:
        return self.severity == GuardSeverity.CRITICAL


# === 3. CONCRETE EXCEPTIONS ===


class BalanceCheckerError(GuardViolationError):
    """Error dari balance checker guard."""

    def __init__(self, message: str, account_code: str, current_balance: Any, **kwargs):
        super().__init__(
            message=message,
            guard_name="balance_checker",
            error_code=GuardErrorCode.BALANCE_INSUFFICIENT,
            details={"account_code": account_code, "current_balance": str(current_balance)},
            **kwargs,
        )
        self.account_code = account_code
        self.current_balance = current_balance


class PeriodLockError(GuardViolationError):
    """Error dari period lock guard."""

    def __init__(self, message: str, period_name: str, period_status: str, **kwargs):
        super().__init__(
            message=message,
            guard_name="period_lock",
            error_code=GuardErrorCode.PERIOD_CLOSED,
            details={"period_name": period_name, "period_status": period_status},
            **kwargs,
        )
        self.period_name = period_name
        self.period_status = period_status


class CurrencyValidatorError(GuardViolationError):
    """Error dari currency validator guard."""

    def __init__(self, message: str, currency: str, **kwargs):
        super().__init__(
            message=message,
            guard_name="currency_validator",
            error_code=GuardErrorCode.CURRENCY_NOT_SUPPORTED,
            details={"currency": currency},
            **kwargs,
        )
        self.currency = currency


class LegalEntityBoundaryError(GuardViolationError):
    """Error dari legal entity boundary guard."""

    def __init__(self, message: str, target_entity_id: str, **kwargs):
        super().__init__(
            message=message,
            guard_name="legal_entity_boundary",
            error_code=GuardErrorCode.ENTITY_ACCESS_DENIED,
            details={"target_entity_id": target_entity_id},
            **kwargs,
        )
        self.target_entity_id = target_entity_id


class AuthorityMatrixError(GuardViolationError):
    """Error dari authority matrix guard."""

    def __init__(self, message: str, resource: str, action: str, **kwargs):
        super().__init__(
            message=message,
            guard_name="authority_matrix",
            error_code=GuardErrorCode.PERMISSION_DENIED,
            details={"resource": resource, "action": action},
            **kwargs,
        )
        self.resource = resource
        self.action = action


class EvidenceAttacherError(GuardViolationError):
    """Error dari evidence attacher guard."""

    def __init__(self, message: str, transaction_type: str, **kwargs):
        super().__init__(
            message=message,
            guard_name="evidence_attacher",
            error_code=GuardErrorCode.EVIDENCE_MISSING,
            details={"transaction_type": transaction_type},
            **kwargs,
        )
        self.transaction_type = transaction_type


class RegulatoryComplianceError(GuardViolationError):
    """Error dari regulatory compliance guard."""

    def __init__(self, message: str, domain: str, rule_id: str, **kwargs):
        super().__init__(
            message=message,
            guard_name="regulatory_compliance",
            error_code=GuardErrorCode.REGULATORY_VIOLATION,
            details={"domain": domain, "rule_id": rule_id},
            **kwargs,
        )
        self.domain = domain
        self.rule_id = rule_id


class TemporalConsistencyError(GuardViolationError):
    """Error dari temporal consistency guard."""

    def __init__(self, message: str, transaction_date: str, last_date: str | None = None, **kwargs):
        super().__init__(
            message=message,
            guard_name="temporal_consistency",
            error_code=GuardErrorCode.TEMPORAL_INCONSISTENCY,
            details={"transaction_date": transaction_date, "last_date": last_date},
            **kwargs,
        )
        self.transaction_date = transaction_date


class EmergencyFreezeError(GuardViolationError):
    """Error dari emergency freeze guard."""

    def __init__(self, message: str, freeze_id: str | None = None, **kwargs):
        super().__init__(
            message=message,
            guard_name="emergency_freeze",
            error_code=GuardErrorCode.SYSTEM_FROZEN,
            details={"freeze_id": freeze_id},
            **kwargs,
        )
        self.freeze_id = freeze_id


class CoretaxFormatError(GuardViolationError):
    """Error dari coretax format validator guard."""

    def __init__(self, message: str, field: str, value: str, **kwargs):
        super().__init__(
            message=message,
            guard_name="coretax_format_validator",
            error_code=GuardErrorCode.CORETAX_FORMAT_INVALID,
            details={"field": field, "value": value[:50]},
            **kwargs,
        )
        self.field = field
        self.value = value


class SODEnforcerError(GuardViolationError):
    """Error dari SOD enforcer guard."""

    def __init__(self, message: str, rule_id: str, **kwargs):
        super().__init__(
            message=message,
            guard_name="sod_enforcer",
            error_code=GuardErrorCode.SOD_MAKER_CHECKER_VIOLATION,
            details={"rule_id": rule_id},
            **kwargs,
        )
        self.rule_id = rule_id


class BudgetAvailabilityError(GuardViolationError):
    """Error dari budget availability guard."""

    def __init__(self, message: str, cost_center: str, account: str, **kwargs):
        super().__init__(
            message=message,
            guard_name="budget_availability",
            error_code=GuardErrorCode.BUDGET_INSUFFICIENT,
            details={"cost_center": cost_center, "account": account},
            **kwargs,
        )
        self.cost_center = cost_center
        self.account = account


class CreditLimitEnforcerError(GuardViolationError):
    """Error dari credit limit enforcer guard."""

    def __init__(
        self, message: str, customer_id: str, credit_limit: Any, outstanding: Any, **kwargs
    ):
        super().__init__(
            message=message,
            guard_name="credit_limit_enforcer",
            error_code=GuardErrorCode.CREDIT_LIMIT_EXCEEDED,
            details={
                "customer_id": customer_id,
                "credit_limit": str(credit_limit),
                "outstanding": str(outstanding),
            },
            **kwargs,
        )
        self.customer_id = customer_id


# === 4. EXCEPTION FACTORY ===


class GuardExceptionFactory:
    """
    Factory untuk membuat guard exceptions dengan konsistensi.
    """

    @staticmethod
    def balance_error(
        message: str, account_code: str, current_balance: Any, **kwargs
    ) -> BalanceCheckerError:
        return BalanceCheckerError(
            message=message, account_code=account_code, current_balance=current_balance, **kwargs
        )

    @staticmethod
    def period_error(
        message: str, period_name: str, period_status: str, **kwargs
    ) -> PeriodLockError:
        return PeriodLockError(
            message=message, period_name=period_name, period_status=period_status, **kwargs
        )

    @staticmethod
    def currency_error(message: str, currency: str, **kwargs) -> CurrencyValidatorError:
        return CurrencyValidatorError(message=message, currency=currency, **kwargs)

    @staticmethod
    def entity_error(message: str, target_entity_id: str, **kwargs) -> LegalEntityBoundaryError:
        return LegalEntityBoundaryError(
            message=message, target_entity_id=target_entity_id, **kwargs
        )

    @staticmethod
    def permission_error(
        message: str, resource: str, action: str, **kwargs
    ) -> AuthorityMatrixError:
        return AuthorityMatrixError(message=message, resource=resource, action=action, **kwargs)

    @staticmethod
    def evidence_error(message: str, transaction_type: str, **kwargs) -> EvidenceAttacherError:
        return EvidenceAttacherError(message=message, transaction_type=transaction_type, **kwargs)

    @staticmethod
    def regulatory_error(
        message: str, domain: str, rule_id: str, **kwargs
    ) -> RegulatoryComplianceError:
        return RegulatoryComplianceError(message=message, domain=domain, rule_id=rule_id, **kwargs)

    @staticmethod
    def temporal_error(
        message: str, transaction_date: str, last_date: str | None = None, **kwargs
    ) -> TemporalConsistencyError:
        return TemporalConsistencyError(
            message=message, transaction_date=transaction_date, last_date=last_date, **kwargs
        )

    @staticmethod
    def freeze_error(message: str, freeze_id: str | None = None, **kwargs) -> EmergencyFreezeError:
        return EmergencyFreezeError(message=message, freeze_id=freeze_id, **kwargs)

    @staticmethod
    def coretax_error(message: str, field: str, value: str, **kwargs) -> CoretaxFormatError:
        return CoretaxFormatError(message=message, field=field, value=value, **kwargs)

    @staticmethod
    def sod_error(message: str, rule_id: str, **kwargs) -> SODEnforcerError:
        return SODEnforcerError(message=message, rule_id=rule_id, **kwargs)

    @staticmethod
    def budget_error(
        message: str, cost_center: str, account: str, **kwargs
    ) -> BudgetAvailabilityError:
        return BudgetAvailabilityError(
            message=message, cost_center=cost_center, account=account, **kwargs
        )

    @staticmethod
    def credit_error(
        message: str, customer_id: str, credit_limit: Any, outstanding: Any, **kwargs
    ) -> CreditLimitEnforcerError:
        return CreditLimitEnforcerError(
            message=message,
            customer_id=customer_id,
            credit_limit=credit_limit,
            outstanding=outstanding,
            **kwargs,
        )


# === 5. EXPORTS ===

__all__ = [
    "AuthorityMatrixError",
    "BalanceCheckerError",
    "BudgetAvailabilityError",
    "CoretaxFormatError",
    "CreditLimitEnforcerError",
    "CurrencyValidatorError",
    "EmergencyFreezeError",
    "EvidenceAttacherError",
    "GuardErrorCode",
    "GuardExceptionFactory",
    "GuardSeverity",
    "GuardViolationError",
    "LegalEntityBoundaryError",
    "PeriodLockError",
    "RegulatoryComplianceError",
    "SODEnforcerError",
    "TemporalConsistencyError",
]