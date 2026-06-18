#!/usr/bin/env python3
"""
Module: policy_exceptions.py
Layer: 7 - Policy Engine
Responsibility: Exception hierarchy untuk policy engine.
               Mendefinisikan semua exception yang dapat terjadi
               saat memuat, menginterpretasi, atau mengeksekusi
               kebijakan akuntansi dan perpajakan.

Dependencies:
- standard library (enum)

Audit: Setiap error kebijakan dictat.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Any

# === 1. CONSTANTS & ENUMS ===


class PolicyErrorSeverity(Enum):
    """Tingkat keparahan error kebijakan."""

    CRITICAL = 100  # Sistem tidak dapat beroperasi
    HIGH = 80  # Transaksi ditolak, perlu intervensi manual
    MEDIUM = 50  # Peringatan, dapat diproses dengan catatan
    LOW = 20  # Informasi, tidak mempengaruhi keputusan


class PolicyErrorCode(Enum):
    """Kode error untuk kebijakan."""

    # Loader errors
    POLICY_FILE_NOT_FOUND = auto()
    POLICY_FILE_INVALID_FORMAT = auto()
    POLICY_SCHEMA_VALIDATION_FAILED = auto()
    POLICY_DUPLICATE_ID = auto()

    # Interpreter errors
    POLICY_NOT_FOUND = auto()
    POLICY_CONDITION_EVALUATION_FAILED = auto()
    POLICY_ACTION_EXECUTION_FAILED = auto()
    POLICY_UNSUPPORTED_OPERATOR = auto()

    # Temporal errors
    POLICY_NOT_EFFECTIVE = auto()
    POLICY_EXPIRED = auto()
    EFFECTIVE_DATE_OUT_OF_RANGE = auto()

    # Jurisdiction errors
    JURISDICTION_NOT_FOUND = auto()
    JURISDICTION_MISMATCH = auto()

    # Conflict errors
    POLICY_CONFLICT_DETECTED = auto()
    CONFLICT_RESOLUTION_FAILED = auto()

    # Override errors
    OVERRIDE_NOT_AUTHORIZED = auto()
    OVERRIDE_EXPIRED = auto()
    OVERRIDE_LIMIT_EXCEEDED = auto()

    # Version errors
    VERSION_NOT_FOUND = auto()
    VERSION_MISMATCH = auto()
    VERSION_ROLLBACK_NOT_ALLOWED = auto()


# === 2. BASE EXCEPTION ===


class PolicyError(Exception):
    """
    Base exception untuk semua error di policy engine.
    """

    def __init__(
        self,
        message: str,
        error_code: PolicyErrorCode,
        severity: PolicyErrorSeverity = PolicyErrorSeverity.MEDIUM,
        policy_id: str | None = None,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        self.error_code = error_code
        self.severity = severity
        self.policy_id = policy_id
        self.details = details or {}
        self.cause = cause

        full_message = f"[{severity.name}][{error_code.name}] {message}"
        if policy_id:
            full_message = f"[Policy:{policy_id}] {full_message}"
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
            "policy_id": self.policy_id,
            "details": self.details,
            "cause": str(self.cause) if self.cause else None,
        }

    def is_critical(self) -> bool:
        return self.severity == PolicyErrorSeverity.CRITICAL


# === 3. CONCRETE EXCEPTIONS ===


class PolicyNotFoundError(PolicyError):
    """Kebijakan tidak ditemukan."""

    def __init__(self, policy_id: str, **kwargs):
        super().__init__(
            message=f"Policy not found: {policy_id}",
            error_code=PolicyErrorCode.POLICY_NOT_FOUND,
            severity=PolicyErrorSeverity.HIGH,
            policy_id=policy_id,
            details={"policy_id": policy_id},
            **kwargs,
        )


class PolicyValidationError(PolicyError):
    """Validasi kebijakan gagal."""

    def __init__(self, policy_id: str, validation_errors: list, **kwargs):
        super().__init__(
            message=f"Policy validation failed: {', '.join(validation_errors)}",
            error_code=PolicyErrorCode.POLICY_SCHEMA_VALIDATION_FAILED,
            severity=PolicyErrorSeverity.HIGH,
            policy_id=policy_id,
            details={"validation_errors": validation_errors},
            **kwargs,
        )
        self.validation_errors = validation_errors


class PolicyConflictError(PolicyError):
    """Konflik antar kebijakan."""

    def __init__(
        self,
        policy_id_1: str,
        policy_id_2: str,
        conflict_description: str,
        **kwargs,
    ):
        super().__init__(
            message=f"Policy conflict between {policy_id_1} and {policy_id_2}: {conflict_description}",
            error_code=PolicyErrorCode.POLICY_CONFLICT_DETECTED,
            severity=PolicyErrorSeverity.CRITICAL,
            details={
                "policy_id_1": policy_id_1,
                "policy_id_2": policy_id_2,
                "conflict_description": conflict_description,
            },
            **kwargs,
        )
        self.policy_id_1 = policy_id_1
        self.policy_id_2 = policy_id_2


class PolicyOverrideNotAuthorizedError(PolicyError):
    """Override kebijakan tidak diotorisasi."""

    def __init__(self, policy_id: str, user_id: str, reason: str, **kwargs):
        super().__init__(
            message=f"Override not authorized for policy {policy_id} by user {user_id}: {reason}",
            error_code=PolicyErrorCode.OVERRIDE_NOT_AUTHORIZED,
            severity=PolicyErrorSeverity.HIGH,
            policy_id=policy_id,
            details={"user_id": user_id, "reason": reason},
            **kwargs,
        )
        self.user_id = user_id


class PolicyVersionError(PolicyError):
    """Error terkait versi kebijakan."""

    def __init__(self, policy_id: str, expected_version: int, actual_version: int, **kwargs):
        super().__init__(
            message=f"Version mismatch for policy {policy_id}: expected {expected_version}, got {actual_version}",
            error_code=PolicyErrorCode.VERSION_MISMATCH,
            severity=PolicyErrorSeverity.MEDIUM,
            policy_id=policy_id,
            details={"expected_version": expected_version, "actual_version": actual_version},
            **kwargs,
        )
        self.expected_version = expected_version
        self.actual_version = actual_version


class TemporalResolutionError(PolicyError):
    """Error resolusi temporal kebijakan."""

    def __init__(self, effective_date: str, reason: str, **kwargs):
        super().__init__(
            message=f"Temporal resolution failed for date {effective_date}: {reason}",
            error_code=PolicyErrorCode.POLICY_NOT_EFFECTIVE,
            severity=PolicyErrorSeverity.HIGH,
            details={"effective_date": effective_date, "reason": reason},
            **kwargs,
        )
        self.effective_date = effective_date


class JurisdictionResolutionError(PolicyError):
    """Error resolusi jurisdiksi kebijakan."""

    def __init__(self, jurisdiction: str, reason: str, **kwargs):
        super().__init__(
            message=f"Jurisdiction resolution failed for {jurisdiction}: {reason}",
            error_code=PolicyErrorCode.JURISDICTION_NOT_FOUND,
            severity=PolicyErrorSeverity.HIGH,
            details={"jurisdiction": jurisdiction, "reason": reason},
            **kwargs,
        )
        self.jurisdiction = jurisdiction


# === 4. EXCEPTION FACTORY ===


class PolicyExceptionFactory:
    """Factory untuk membuat policy exceptions dengan konsistensi."""

    @staticmethod
    def not_found(policy_id: str, **kwargs) -> PolicyNotFoundError:
        return PolicyNotFoundError(policy_id=policy_id, **kwargs)

    @staticmethod
    def validation_failed(policy_id: str, errors: list, **kwargs) -> PolicyValidationError:
        return PolicyValidationError(policy_id=policy_id, validation_errors=errors, **kwargs)

    @staticmethod
    def conflict(
        policy_id_1: str, policy_id_2: str, description: str, **kwargs
    ) -> PolicyConflictError:
        return PolicyConflictError(
            policy_id_1=policy_id_1,
            policy_id_2=policy_id_2,
            conflict_description=description,
            **kwargs,
        )

    @staticmethod
    def override_not_authorized(
        policy_id: str, user_id: str, reason: str, **kwargs
    ) -> PolicyOverrideNotAuthorizedError:
        return PolicyOverrideNotAuthorizedError(
            policy_id=policy_id, user_id=user_id, reason=reason, **kwargs
        )

    @staticmethod
    def version_mismatch(
        policy_id: str, expected: int, actual: int, **kwargs
    ) -> PolicyVersionError:
        return PolicyVersionError(
            policy_id=policy_id, expected_version=expected, actual_version=actual, **kwargs
        )

    @staticmethod
    def temporal_error(effective_date: str, reason: str, **kwargs) -> TemporalResolutionError:
        return TemporalResolutionError(effective_date=effective_date, reason=reason, **kwargs)

    @staticmethod
    def jurisdiction_error(jurisdiction: str, reason: str, **kwargs) -> JurisdictionResolutionError:
        return JurisdictionResolutionError(jurisdiction=jurisdiction, reason=reason, **kwargs)


# === 5. EXPORTS ===

__all__ = [
    "JurisdictionResolutionError",
    "PolicyConflictError",
    "PolicyError",
    "PolicyErrorCode",
    "PolicyErrorSeverity",
    "PolicyExceptionFactory",
    "PolicyNotFoundError",
    "PolicyOverrideNotAuthorizedError",
    "PolicyValidationError",
    "PolicyVersionError",
    "TemporalResolutionError",
]
