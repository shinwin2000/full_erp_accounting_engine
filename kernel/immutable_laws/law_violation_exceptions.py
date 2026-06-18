#!/usr/bin/env python3
"""
Module: law_violation_exceptions.py
Layer: 4 - Kernel / Immutable Laws
Responsibility: Exception pelanggaran hukum immutable.
               Mendefinisikan hierarchy exception untuk semua pelanggaran
               terhadap immutable laws yang telah didefinisikan dalam sistem.

Dependencies:
- standard library (enum, typing, datetime)

Audit: Setiap exception pelanggaran hukum immutable dictat.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

# === 1. CONSTANTS & ENUMS ===


class LawViolationSeverity(Enum):
    """Severity pelanggaran hukum immutable."""

    CATASTROPHIC = 100  # Data integrity compromised, system freeze
    CRITICAL = 80  # Pelanggaran hukum fundamental, transaksi ditolak
    HIGH = 60  # Pelanggaran serius, perlu investigasi
    MEDIUM = 40  # Pelanggaran prosedural, perlu koreksi
    LOW = 20  # Warning, tidak menghentikan operasi


class LawCode(Enum):
    """Kode hukum yang dilanggar."""

    IMMUTABILITY = "IMMUTABILITY"
    EVIDENCE_MANDATE = "EVIDENCE_MANDATE"
    DUAL_APPROVAL = "DUAL_APPROVAL"
    REVERSAL_CONSTRAINT = "REVERSAL_CONSTRAINT"
    TRACEABILITY = "TRACEABILITY"
    PERIOD_CLOSURE = "PERIOD_CLOSURE"
    GL_SUPREMACY = "GL_SUPREMACY"
    SEGREGATION_OF_DUTIES = "SEGREGATION_OF_DUTIES"
    NO_RETROACTIVE_POLICY = "NO_RETROACTIVE_POLICY"
    AUDIT_TRAIL_COMPLETENESS = "AUDIT_TRAIL_COMPLETENESS"
    ASSET_EXISTENCE = "ASSET_EXISTENCE"
    FAIR_VALUE_MEASUREMENT = "FAIR_VALUE_MEASUREMENT"


# === 2. BASE EXCEPTION ===


class ImmutableLawViolationError(Exception):
    """
    Base exception untuk semua pelanggaran immutable laws.

    Business context: Exception yang terjadi ketika suatu operasi
    melanggar hukum immutable yang telah ditetapkan.
    """

    def __init__(
        self,
        message: str,
        law_name: str,
        severity: LawViolationSeverity = LawViolationSeverity.HIGH,
        law_code: LawCode | None = None,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        self.law_name = law_name
        self.severity = severity
        self.law_code = law_code
        self.details = details or {}
        self.cause = cause
        self.timestamp = datetime.now(UTC)

        full_message = f"[{severity.name}][{law_name}] {message}"
        super().__init__(full_message)
        self._original_message = message

    @property
    def original_message(self) -> str:
        return self._original_message

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.__class__.__name__,
            "law_name": self.law_name,
            "law_code": self.law_code.value if self.law_code else None,
            "severity": self.severity.name,
            "severity_value": self.severity.value,
            "message": self._original_message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
            "cause": str(self.cause) if self.cause else None,
        }

    def is_catastrophic(self) -> bool:
        return self.severity == LawViolationSeverity.CATASTROPHIC

    def is_critical(self) -> bool:
        return self.severity.value >= LawViolationSeverity.CRITICAL.value


# === 3. CONCRETE EXCEPTIONS ===


class ImmutabilityLawViolation(ImmutableLawViolationError):
    def __init__(self, message: str, attempted_operation: str, target_id: str, **kwargs):
        super().__init__(
            message=message,
            law_name="immutability_enforcer",
            law_code=LawCode.IMMUTABILITY,
            severity=LawViolationSeverity.CRITICAL,
            details={
                "attempted_operation": attempted_operation,
                "target_id": target_id,
                **kwargs.get("details", {}),
            },
            **kwargs,
        )
        self.attempted_operation = attempted_operation
        self.target_id = target_id


class EvidenceMandateViolation(ImmutableLawViolationError):
    def __init__(self, message: str, journal_id: str, journal_type: str, **kwargs):
        super().__init__(
            message=message,
            law_name="evidence_mandate_enforcer",
            law_code=LawCode.EVIDENCE_MANDATE,
            severity=kwargs.get("severity", LawViolationSeverity.CRITICAL),
            details={
                "journal_id": journal_id,
                "journal_type": journal_type,
                **kwargs.get("details", {}),
            },
            **kwargs,
        )
        self.journal_id = journal_id
        self.journal_type = journal_type


class DualApprovalViolation(ImmutableLawViolationError):
    def __init__(
        self, message: str, transaction_id: str, amount: str, required_approvals: int, **kwargs
    ):
        super().__init__(
            message=message,
            law_name="dual_approval_enforcer",
            law_code=LawCode.DUAL_APPROVAL,
            severity=LawViolationSeverity.CRITICAL,
            details={
                "transaction_id": transaction_id,
                "amount": amount,
                "required_approvals": required_approvals,
                **kwargs.get("details", {}),
            },
            **kwargs,
        )
        self.transaction_id = transaction_id
        self.amount = amount


class ReversalConstraintViolation(ImmutableLawViolationError):
    def __init__(self, message: str, original_journal_id: str, **kwargs):
        super().__init__(
            message=message,
            law_name="reversal_constraint_enforcer",
            law_code=LawCode.REVERSAL_CONSTRAINT,
            severity=LawViolationSeverity.HIGH,
            details={"original_journal_id": original_journal_id, **kwargs.get("details", {})},
            **kwargs,
        )
        self.original_journal_id = original_journal_id


class TraceabilityViolation(ImmutableLawViolationError):
    def __init__(self, message: str, transaction_id: str, **kwargs):
        super().__init__(
            message=message,
            law_name="traceability_enforcer",
            law_code=LawCode.TRACEABILITY,
            severity=LawViolationSeverity.HIGH,
            details={"transaction_id": transaction_id, **kwargs.get("details", {})},
            **kwargs,
        )
        self.transaction_id = transaction_id


class PeriodClosureViolation(ImmutableLawViolationError):
    def __init__(self, message: str, period_id: str, period_name: str, **kwargs):
        super().__init__(
            message=message,
            law_name="period_closure_enforcer",
            law_code=LawCode.PERIOD_CLOSURE,
            severity=LawViolationSeverity.CRITICAL,
            details={
                "period_id": period_id,
                "period_name": period_name,
                **kwargs.get("details", {}),
            },
            **kwargs,
        )
        self.period_id = period_id
        self.period_name = period_name


class GLSupremacyViolation(ImmutableLawViolationError):
    def __init__(
        self, message: str, account_code: str, gl_balance: str, subledger_balance: str, **kwargs
    ):
        super().__init__(
            message=message,
            law_name="gl_supremacy_enforcer",
            law_code=LawCode.GL_SUPREMACY,
            severity=LawViolationSeverity.CRITICAL,
            details={
                "account_code": account_code,
                "gl_balance": gl_balance,
                "subledger_balance": subledger_balance,
                **kwargs.get("details", {}),
            },
            **kwargs,
        )
        self.account_code = account_code


class SegregationOfDutiesViolation(ImmutableLawViolationError):
    def __init__(self, message: str, user_id: str, conflicting_roles: list[str], **kwargs):
        super().__init__(
            message=message,
            law_name="segregation_of_duties_enforcer",
            law_code=LawCode.SEGREGATION_OF_DUTIES,
            severity=LawViolationSeverity.CRITICAL,
            details={
                "user_id": user_id,
                "conflicting_roles": conflicting_roles,
                **kwargs.get("details", {}),
            },
            **kwargs,
        )
        self.user_id = user_id
        self.conflicting_roles = conflicting_roles


class NoRetroactivePolicyViolation(ImmutableLawViolationError):
    def __init__(self, message: str, policy_id: str, effective_date: str, **kwargs):
        super().__init__(
            message=message,
            law_name="no_retroactive_policy_enforcer",
            law_code=LawCode.NO_RETROACTIVE_POLICY,
            severity=LawViolationSeverity.HIGH,
            details={
                "policy_id": policy_id,
                "effective_date": effective_date,
                **kwargs.get("details", {}),
            },
            **kwargs,
        )
        self.policy_id = policy_id


class AuditTrailCompletenessViolation(ImmutableLawViolationError):
    def __init__(
        self, message: str, transaction_id: str, gap_sequence: int | None = None, **kwargs
    ):
        super().__init__(
            message=message,
            law_name="audit_trail_completeness_enforcer",
            law_code=LawCode.AUDIT_TRAIL_COMPLETENESS,
            severity=kwargs.get("severity", LawViolationSeverity.CATASTROPHIC),
            details={
                "transaction_id": transaction_id,
                "gap_sequence": gap_sequence,
                **kwargs.get("details", {}),
            },
            **kwargs,
        )
        self.transaction_id = transaction_id
        self.gap_sequence = gap_sequence


class AssetExistenceViolation(ImmutableLawViolationError):
    def __init__(self, message: str, asset_id: str, asset_type: str, **kwargs):
        super().__init__(
            message=message,
            law_name="asset_existence_enforcer",
            law_code=LawCode.ASSET_EXISTENCE,
            severity=LawViolationSeverity.HIGH,
            details={
                "asset_id": asset_id,
                "asset_type": asset_type,
                **kwargs.get("details", {}),
            },
            **kwargs,
        )
        self.asset_id = asset_id
        self.asset_type = asset_type


class FairValueMeasurementViolation(ImmutableLawViolationError):
    def __init__(self, message: str, asset_id: str, hierarchy_level: int, **kwargs):
        super().__init__(
            message=message,
            law_name="fair_value_measurement_enforcer",
            law_code=LawCode.FAIR_VALUE_MEASUREMENT,
            severity=LawViolationSeverity.HIGH,
            details={
                "asset_id": asset_id,
                "hierarchy_level": hierarchy_level,
                **kwargs.get("details", {}),
            },
            **kwargs,
        )
        self.asset_id = asset_id


# === 4. EXCEPTION FACTORY ===


class LawViolationExceptionFactory:
    """Factory untuk membuat law violation exceptions dengan konsistensi."""

    @staticmethod
    def immutability_violation(
        message: str, operation: str, target_id: str, **kwargs
    ) -> ImmutabilityLawViolation:
        return ImmutabilityLawViolation(message, operation, target_id, **kwargs)

    @staticmethod
    def evidence_mandate_violation(
        message: str, journal_id: str, journal_type: str, **kwargs
    ) -> EvidenceMandateViolation:
        return EvidenceMandateViolation(message, journal_id, journal_type, **kwargs)

    @staticmethod
    def dual_approval_violation(
        message: str, tx_id: str, amount: str, required: int, **kwargs
    ) -> DualApprovalViolation:
        return DualApprovalViolation(message, tx_id, amount, required, **kwargs)

    @staticmethod
    def period_closure_violation(
        message: str, period_id: str, period_name: str, **kwargs
    ) -> PeriodClosureViolation:
        return PeriodClosureViolation(message, period_id, period_name, **kwargs)

    @staticmethod
    def sod_violation(
        message: str, user_id: str, conflicting_roles: list[str], **kwargs
    ) -> SegregationOfDutiesViolation:
        return SegregationOfDutiesViolation(message, user_id, conflicting_roles, **kwargs)

    @staticmethod
    def gl_supremacy_violation(
        message: str, account_code: str, gl_balance: str, subledger_balance: str, **kwargs
    ) -> GLSupremacyViolation:
        return GLSupremacyViolation(message, account_code, gl_balance, subledger_balance, **kwargs)

    @staticmethod
    def audit_trail_violation(
        message: str, tx_id: str, gap_seq: int | None = None, **kwargs
    ) -> AuditTrailCompletenessViolation:
        return AuditTrailCompletenessViolation(message, tx_id, gap_seq, **kwargs)

    @staticmethod
    def asset_existence_violation(
        message: str, asset_id: str, asset_type: str, **kwargs
    ) -> AssetExistenceViolation:
        return AssetExistenceViolation(message, asset_id, asset_type, **kwargs)

    @staticmethod
    def fair_value_violation(
        message: str, asset_id: str, hierarchy_level: int, **kwargs
    ) -> FairValueMeasurementViolation:
        return FairValueMeasurementViolation(message, asset_id, hierarchy_level, **kwargs)


# === 5. EXPORTS ===

__all__ = [
    "AssetExistenceViolation",
    "AuditTrailCompletenessViolation",
    "DualApprovalViolation",
    "EvidenceMandateViolation",
    "FairValueMeasurementViolation",
    "GLSupremacyViolation",
    "ImmutabilityLawViolation",
    "ImmutableLawViolationError",
    "LawCode",
    "LawViolationExceptionFactory",
    "LawViolationSeverity",
    "NoRetroactivePolicyViolation",
    "PeriodClosureViolation",
    "ReversalConstraintViolation",
    "SegregationOfDutiesViolation",
    "TraceabilityViolation",
]
