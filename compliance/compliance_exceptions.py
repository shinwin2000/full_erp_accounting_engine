#!/usr/bin/env python3
"""
Module: compliance_exceptions.py
Layer: Compliance

Responsibility:
    Mendefinisikan hierarki exception untuk seluruh modul compliance.
    Memungkinkan penanganan error terstruktur dengan kode error, pesan terperinci,
    dan data kontekstual. Mendukung serialisasi untuk logging dan API response.

Dependencies:
    - typing, enum, json
    - traceback (opsional untuk debugging)

Audit:
    Exception yang terjadi harus dicatat di audit trail dengan severity.
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime
from enum import Enum
from typing import Any


# ============================================================================
# Error Severity & Category
# ============================================================================
class ErrorSeverity(Enum):
    """Tingkat keparahan error compliance."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    FATAL = "fatal"


class ErrorCategory(Enum):
    """Kategori error compliance."""

    AML = "anti_money_laundering"
    GDPR = "data_privacy"
    SOX = "internal_control"
    TAX = "taxation"
    REPORTING = "reporting"
    ETHICS = "ethics"
    LEGAL = "legal"
    GENERAL = "general"


# ============================================================================
# Base Compliance Exception
# ============================================================================
class ComplianceError(Exception):
    """
    Base exception untuk semua error compliance.
    Menyimpan data kontekstual, timestamp, severity, dan category.
    """

    def __init__(
        self,
        message: str,
        code: str | None = None,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        category: ErrorCategory = ErrorCategory.GENERAL,
        context: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__.upper()
        self.severity = severity
        self.category = category
        self.context = context or {}
        self.cause = cause
        self.timestamp = datetime.utcnow()
        self._traceback = None
        if cause:
            self._traceback = traceback.format_exception(type(cause), cause, cause.__traceback__)

    def to_dict(self) -> dict[str, Any]:
        """Konversi exception ke dictionary untuk logging/API response."""
        return {
            "error_class": self.__class__.__name__,
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "category": self.category.value,
            "timestamp": self.timestamp.isoformat() + "Z",
            "context": self.context,
            "cause": str(self.cause) if self.cause else None,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)

    def __str__(self) -> str:
        return f"[{self.severity.value.upper()}] {self.code}: {self.message}"


# ============================================================================
# AML Exceptions
# ============================================================================
class AMLViolationError(ComplianceError):
    """Violasi terhadap regulasi AML."""

    def __init__(
        self,
        message: str,
        code: str = "AML_VIOLATION",
        context: dict | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            severity=ErrorSeverity.CRITICAL,
            category=ErrorCategory.AML,
            context=context,
            cause=cause,
        )


class SanctionListHitError(AMLViolationError):
    """Transaksi ditolak karena nama terdaftar di daftar sanksi."""

    def __init__(
        self,
        name: str,
        sanction_list: str,
        transaction_id: str | None = None,
        context: dict | None = None,
    ):
        message = f"Sanction list hit: '{name}' found in {sanction_list}"
        ctx = context or {}
        ctx.update({"name": name, "sanction_list": sanction_list, "transaction_id": transaction_id})
        super().__init__(message=message, code="SANCTION_HIT", context=ctx)


class STRRequiredError(AMLViolationError):
    """Transaksi mencurigakan memerlukan Suspicious Transaction Report."""

    def __init__(
        self,
        transaction_id: str,
        risk_score: int,
        reasons: list[str],
        context: dict | None = None,
    ):
        message = f"Suspicious transaction {transaction_id} requires STR (score: {risk_score})"
        ctx = context or {}
        ctx.update({"transaction_id": transaction_id, "risk_score": risk_score, "reasons": reasons})
        super().__init__(message=message, code="STR_REQUIRED", context=ctx)


class EDDRequiredError(AMLViolationError):
    """Enhanced Due Diligence diperlukan untuk customer."""

    def __init__(self, customer_id: str, risk_level: str, context: dict | None = None):
        message = f"EDD required for customer {customer_id} (risk level: {risk_level})"
        ctx = context or {}
        ctx.update({"customer_id": customer_id, "risk_level": risk_level})
        super().__init__(message=message, code="EDD_REQUIRED", context=ctx)


# ADDED: SuspiciousTransactionReported exception
class SuspiciousTransactionReported(ComplianceError):
    """
    Exception ketika transaksi mencurigakan dilaporkan ke PPATK.
    Digunakan dalam test_aml_risk_scoring.py.
    """

    def __init__(
        self,
        message: str,
        report_id: str,
        destination: str = "PPATK",
        context: dict | None = None,
    ):
        super().__init__(
            message=message,
            code="SUSPICIOUS_REPORTED",
            severity=ErrorSeverity.WARNING,
            category=ErrorCategory.AML,
            context=context,
        )
        self.report_id = report_id
        self.destination = destination


# ============================================================================
# GDPR Exceptions
# ============================================================================
class GDPRViolationError(ComplianceError):
    """Violasi terhadap GDPR (data privacy)."""

    def __init__(
        self,
        message: str,
        code: str = "GDPR_VIOLATION",
        context: dict | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            severity=ErrorSeverity.HIGH,
            category=ErrorCategory.GDPR,
            context=context,
            cause=cause,
        )


class ConsentMissingError(GDPRViolationError):
    """Consent diperlukan untuk pemrosesan data."""

    def __init__(self, user_id: str, purpose: str, context: dict | None = None):
        message = f"Consent missing for user {user_id} to process data for purpose: {purpose}"
        ctx = context or {"user_id": user_id, "purpose": purpose}
        super().__init__(message=message, code="CONSENT_MISSING", context=ctx)


class DataSubjectRequestError(GDPRViolationError):
    """Error saat memproses permintaan hak subjek data."""

    def __init__(self, request_id: str, reason: str, context: dict | None = None):
        message = f"Data subject request {request_id} failed: {reason}"
        ctx = context or {"request_id": request_id, "reason": reason}
        super().__init__(message=message, code="DSR_ERROR", context=ctx)


class DataBreachNotificationError(GDPRViolationError):
    """Gagal mengirim notifikasi pelanggaran data."""

    def __init__(self, breach_id: str, reason: str, context: dict | None = None):
        message = f"Data breach notification failed for breach {breach_id}: {reason}"
        ctx = context or {"breach_id": breach_id, "reason": reason}
        super().__init__(message=message, code="BREACH_NOTIFY_FAIL", context=ctx)


# ============================================================================
# SOX Exceptions
# ============================================================================
class SOXViolationError(ComplianceError):
    """Violasi terhadap SOX (pengendalian internal)."""

    def __init__(
        self,
        message: str,
        code: str = "SOX_VIOLATION",
        context: dict | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            severity=ErrorSeverity.CRITICAL,
            category=ErrorCategory.SOX,
            context=context,
            cause=cause,
        )


class ControlTestFailureError(SOXViolationError):
    """Kegagalan uji kontrol internal."""

    def __init__(self, control_id: str, test_details: str, context: dict | None = None):
        message = f"Control test failed for {control_id}: {test_details}"
        ctx = context or {"control_id": control_id, "test_details": test_details}
        super().__init__(message=message, code="CONTROL_FAIL", context=ctx)


class SegregationOfDutyError(SOXViolationError):
    """Violasi separation of duties."""

    def __init__(self, user_id: str, role_a: str, role_b: str, context: dict | None = None):
        message = f"User {user_id} has conflicting roles: {role_a} and {role_b}"
        ctx = context or {"user_id": user_id, "role_a": role_a, "role_b": role_b}
        super().__init__(message=message, code="SOD_VIOLATION", context=ctx)


# ============================================================================
# Tax Exceptions
# ============================================================================
class TaxComplianceError(ComplianceError):
    """Violasi terhadap peraturan perpajakan."""

    def __init__(
        self,
        message: str,
        code: str = "TAX_ERROR",
        context: dict | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            severity=ErrorSeverity.HIGH,
            category=ErrorCategory.TAX,
            context=context,
            cause=cause,
        )


class CoretaxAPIError(TaxComplianceError):
    """Error saat berkomunikasi dengan Coretax DJP API."""

    def __init__(
        self, endpoint: str, status_code: int, response_text: str, context: dict | None = None
    ):
        message = f"Coretax API error at {endpoint}: HTTP {status_code} - {response_text[:200]}"
        ctx = context or {
            "endpoint": endpoint,
            "status_code": status_code,
            "response": response_text[:500],
        }
        super().__init__(message=message, code="CORETAX_API_ERROR", context=ctx)


class FakturValidationError(TaxComplianceError):
    """Error validasi faktur pajak."""

    def __init__(self, faktur_number: str, errors: list[str], context: dict | None = None):
        message = f"Faktur {faktur_number} validation failed: {', '.join(errors)}"
        ctx = context or {"faktur_number": faktur_number, "errors": errors}
        super().__init__(message=message, code="FAKTUR_INVALID", context=ctx)


class SPTSubmissionError(TaxComplianceError):
    """Error saat submit SPT ke DJP."""

    def __init__(self, spt_type: str, period: str, reason: str, context: dict | None = None):
        message = f"SPT {spt_type} for period {period} submission failed: {reason}"
        ctx = context or {"spt_type": spt_type, "period": period, "reason": reason}
        super().__init__(message=message, code="SPT_SUBMIT_FAIL", context=ctx)


# ============================================================================
# Reporting Exceptions
# ============================================================================
class ReportingError(ComplianceError):
    """Error saat pembuatan/pengiriman laporan kepatuhan."""

    def __init__(
        self,
        message: str,
        code: str = "REPORTING_ERROR",
        context: dict | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            severity=ErrorSeverity.ERROR,
            category=ErrorCategory.REPORTING,
            context=context,
            cause=cause,
        )


class ReportGenerationError(ReportingError):
    """Gagal generate laporan."""

    def __init__(self, report_type: str, reason: str, context: dict | None = None):
        message = f"Failed to generate {report_type} report: {reason}"
        ctx = context or {"report_type": report_type, "reason": reason}
        super().__init__(message=message, code="GENERATION_FAIL", context=ctx)


# ============================================================================
# Ethics Exceptions (untuk modul compliance/ethics)
# ============================================================================
class EthicsError(ComplianceError):
    """Base exception untuk error etika."""

    def __init__(
        self,
        message: str,
        code: str = "ETHICS_ERROR",
        context: dict | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            severity=ErrorSeverity.WARNING,
            category=ErrorCategory.ETHICS,
            context=context,
            cause=cause,
        )


class ProfessionalJudgmentError(EthicsError):
    """Kesalahan dalam judgment profesional."""

    def __init__(self, judgment_id: str, reason: str, context: dict | None = None):
        message = f"Professional judgment {judgment_id} error: {reason}"
        ctx = context or {"judgment_id": judgment_id, "reason": reason}
        super().__init__(message=message, code="JUDGMENT_ERROR", context=ctx)


class ConflictOfInterestError(EthicsError):
    """Konflik kepentingan tidak dideklarasikan."""

    def __init__(self, user_id: str, transaction_id: str, context: dict | None = None):
        message = f"Conflict of interest for user {user_id} in transaction {transaction_id}"
        ctx = context or {"user_id": user_id, "transaction_id": transaction_id}
        super().__init__(message=message, code="CONFLICT_INTEREST", context=ctx)


# ============================================================================
# Legal Exceptions
# ============================================================================
class LegalError(ComplianceError):
    """Base exception untuk error legal."""

    def __init__(
        self,
        message: str,
        code: str = "LEGAL_ERROR",
        context: dict | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            severity=ErrorSeverity.ERROR,
            category=ErrorCategory.LEGAL,
            context=context,
            cause=cause,
        )


class JurisdictionError(LegalError):
    """Error terkait yurisdiksi."""

    def __init__(self, jurisdiction_code: str, operation: str, context: dict | None = None):
        message = f"Jurisdiction {jurisdiction_code} not supported for operation: {operation}"
        ctx = context or {"jurisdiction_code": jurisdiction_code, "operation": operation}
        super().__init__(message=message, code="JURISDICTION_ERROR", context=ctx)


# ============================================================================
# Utility to aggregate multiple exceptions
# ============================================================================
class ComplianceExceptionAggregator:
    """
    Utility untuk mengumpulkan beberapa exception compliance dan melaporkannya secara agregat.
    """

    def __init__(self):
        self._exceptions: list[ComplianceError] = []

    def add(self, exc: ComplianceError) -> None:
        self._exceptions.append(exc)

    def add_from_context(self, error_dict: dict[str, Any]) -> None:
        """Membuat exception dari dictionary (misalnya dari API response)."""
        # Implementasi sederhana: buat ComplianceError generic
        exc = ComplianceError(
            message=error_dict.get("message", "Unknown compliance error"),
            code=error_dict.get("code"),
            severity=ErrorSeverity(error_dict.get("severity", "error")),
            category=ErrorCategory(error_dict.get("category", "general")),
            context=error_dict.get("context"),
        )
        self._exceptions.append(exc)

    def has_errors(self) -> bool:
        return len(self._exceptions) > 0

    def get_all(self) -> list[ComplianceError]:
        return self._exceptions

    def get_by_severity(self, severity: ErrorSeverity) -> list[ComplianceError]:
        return [e for e in self._exceptions if e.severity == severity]

    def to_dict(self) -> dict:
        return {
            "count": len(self._exceptions),
            "exceptions": [e.to_dict() for e in self._exceptions],
            "summary": {
                "critical": len(self.get_by_severity(ErrorSeverity.CRITICAL)),
                "error": len(self.get_by_severity(ErrorSeverity.ERROR)),
                "warning": len(self.get_by_severity(ErrorSeverity.WARNING)),
            },
        }

    def raise_if_any(self, max_severity: ErrorSeverity = ErrorSeverity.ERROR) -> None:
        """Raise aggregated exception jika ada error dengan severity >= threshold."""
        critical_errors = [
            e
            for e in self._exceptions
            if e.severity in (ErrorSeverity.CRITICAL, ErrorSeverity.FATAL)
        ]
        if critical_errors:
            raise ComplianceError(
                message=f"Aggregated {len(critical_errors)} critical compliance errors",
                context={"errors": [e.to_dict() for e in critical_errors]},
                severity=ErrorSeverity.CRITICAL,
            )
        errors = [
            e
            for e in self._exceptions
            if e.severity == ErrorSeverity.ERROR and e.severity.value >= max_severity.value
        ]
        if errors:
            raise ComplianceError(
                message=f"Aggregated {len(errors)} compliance errors",
                context={"errors": [e.to_dict() for e in errors]},
                severity=ErrorSeverity.ERROR,
            )


# ============================================================================
# Export
# ============================================================================
__all__ = [
    # Base
    "ComplianceError",
    "ErrorSeverity",
    "ErrorCategory",
    # AML
    "AMLViolationError",
    "SanctionListHitError",
    "STRRequiredError",
    "EDDRequiredError",
    "SuspiciousTransactionReported",  # added
    # GDPR
    "GDPRViolationError",
    "ConsentMissingError",
    "DataSubjectRequestError",
    "DataBreachNotificationError",
    # SOX
    "SOXViolationError",
    "ControlTestFailureError",
    "SegregationOfDutyError",
    # Tax
    "TaxComplianceError",
    "CoretaxAPIError",
    "FakturValidationError",
    "SPTSubmissionError",
    # Reporting
    "ReportingError",
    "ReportGenerationError",
    # Ethics
    "EthicsError",
    "ProfessionalJudgmentError",
    "ConflictOfInterestError",
    # Legal
    "LegalError",
    "JurisdictionError",
    # Utility
    "ComplianceExceptionAggregator",
]
