#!/usr/bin/env python3
"""
Module: audit_exception_aggregator.py
Layer: Audit (Sampling Materiality)
Responsibility: Mengumpulkan, mengkategorikan, dan menganalisis exception (penyimpangan)
               yang ditemukan selama proses audit sampling. Mengevaluasi apakah
               exception bersifat isolated, systematic, atau fraud indicator.
               Juga menghitung effect of exception terhadap kesimpulan audit.
Dependencies:
- decimal, logging, datetime
- infrastructure.telemetry.structured_json_logging (lazy import)
- audit.sampling_materiality.materiality_threshold_calculator
Audit: Exception aggregation digunakan untuk root cause analysis dan laporan audit.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

# Internal dependency (diizinkan, same layer)
from audit.sampling_materiality.materiality_threshold_calculator import get_materiality_calculator

# ============================================================================
# CONSTANTS
# ============================================================================

_logger = None


def _get_logger():
    """Lazy logger initialization from structured logging."""
    global _logger
    if _logger is None:
        mod = importlib.import_module("infrastructure.telemetry.structured_json_logging")
        get_logger_func = getattr(mod, "get_logger")
        _logger = get_logger_func(__name__)
    return _logger


class ExceptionSeverity(str, Enum):
    TRIVIAL = "trivial"
    MINOR = "minor"
    MODERATE = "moderate"
    MAJOR = "major"
    CRITICAL = "critical"


class ExceptionType(str, Enum):
    ACCURACY = "accuracy"  # Nilai salah
    COMPLETENESS = "completeness"  # Transaksi tidak tercatat
    VALIDITY = "validity"  # Transaksi tidak valid
    CUTOFF = "cutoff"  # Periode salah
    CLASSIFICATION = "classification"  # Klasifikasi akun salah
    AUTHORIZATION = "authorization"  # Tanpa otorisasi
    DOCUMENTATION = "documentation"  # Dokumen pendukung tidak ada
    SYSTEM = "system"  # Error sistem


class ExceptionPattern(str, Enum):
    ISOLATED = "isolated"
    CLUSTERED = "clustered"  # Terkonsentrasi pada periode/entitas tertentu
    SYSTEMATIC = "systematic"  # Terjadi berulang dengan pola sama
    FRAUD_INDICATOR = "fraud_indicator"


# ============================================================================
# EXCEPTION AGGREGATOR
# ============================================================================


class AuditExceptionAggregator:
    """
    Aggregator untuk exception audit.

    Fitur:
    - Mengumpulkan exception dengan metadata
    - Mengkategorikan berdasarkan severity dan type
    - Mendeteksi pola exception (isolated, clustered, systematic)
    - Menghitung total dan rata-rata error
    - Memberikan rekomendasi tindak lanjut
    """

    def __init__(self):
        self._exceptions: list[dict[str, Any]] = []
        self._materiality_calc = get_materiality_calculator()

    def add_exception(self, exception_data: dict[str, Any]) -> None:
        """
        Menambahkan exception ke aggregator.

        exception_data harus mengandung:
        - amount: Decimal (nilai error)
        - description: str (deskripsi)
        - exception_type: ExceptionType
        - location: str (entitas, transaksi ID, dll)
        - date: date/datetime
        - severity: ExceptionSeverity (optional, akan dihitung jika tidak ada)
        - root_cause: str (optional)
        """
        # Set severity based on amount if not provided
        if "severity" not in exception_data:
            amount = exception_data.get("amount", Decimal(0))
            threshold_trivial = Decimal(100000)  # Rp 100k
            threshold_minor = Decimal(1000000)  # Rp 1M
            threshold_moderate = Decimal(10000000)  # Rp 10M
            threshold_major = Decimal(100000000)  # Rp 100M

            if amount < threshold_trivial:
                severity = ExceptionSeverity.TRIVIAL
            elif amount < threshold_minor:
                severity = ExceptionSeverity.MINOR
            elif amount < threshold_moderate:
                severity = ExceptionSeverity.MODERATE
            elif amount < threshold_major:
                severity = ExceptionSeverity.MAJOR
            else:
                severity = ExceptionSeverity.CRITICAL
            exception_data["severity"] = severity

        # Add timestamp
        exception_data["added_at"] = datetime.now(UTC).isoformat()

        self._exceptions.append(exception_data)
        logger = _get_logger()
        logger.info(
            f"Exception added: {exception_data.get('exception_type')} amount={exception_data.get('amount')}"
        )

    def add_exceptions_batch(self, exceptions: list[dict[str, Any]]) -> None:
        """Menambahkan multiple exceptions sekaligus."""
        for exc in exceptions:
            self.add_exception(exc)

    def get_summary(self) -> dict[str, Any]:
        """Mendapatkan ringkasan semua exceptions."""
        if not self._exceptions:
            return {"total_exceptions": 0, "total_error_amount": 0}

        total_error = sum(e.get("amount", Decimal(0)) for e in self._exceptions)

        # Count by severity
        by_severity = {}
        for sev in ExceptionSeverity:
            count = sum(1 for e in self._exceptions if e.get("severity") == sev)
            if count > 0:
                by_severity[sev.value] = count

        # Count by type
        by_type = {}
        for typ in ExceptionType:
            count = sum(1 for e in self._exceptions if e.get("exception_type") == typ)
            if count > 0:
                by_type[typ.value] = count

        return {
            "total_exceptions": len(self._exceptions),
            "total_error_amount": float(total_error),
            "average_error": float(total_error / len(self._exceptions)),
            "by_severity": by_severity,
            "by_type": by_type,
            "largest_error": float(max(e.get("amount", 0) for e in self._exceptions)),
        }

    def detect_patterns(self) -> list[dict[str, Any]]:
        """
        Mendeteksi pola exception (isolated, clustered, systematic, fraud indicator).

        Returns:
            List of patterns detected with details
        """
        patterns = []

        # Pattern 1: Isolated vs Clustered (by location/entity)
        locations = {}
        for exc in self._exceptions:
            loc = exc.get("location", "unknown")
            locations[loc] = locations.get(loc, 0) + 1

        total = len(self._exceptions)
        if total > 0:
            max_cluster = max(locations.values())
            if max_cluster / total > 0.7:
                patterns.append(
                    {
                        "pattern": ExceptionPattern.CLUSTERED.value,
                        "description": f"{max_cluster} out of {total} exceptions clustered in {max(locations, key=locations.get)}",
                        "severity": "warning",
                    }
                )
            else:
                patterns.append(
                    {
                        "pattern": ExceptionPattern.ISOLATED.value,
                        "description": "Exceptions are spread across multiple locations",
                        "severity": "info",
                    }
                )

        # Pattern 2: Systematic (same type and similar description)
        type_counts = {}
        for exc in self._exceptions:
            typ = exc.get("exception_type", "unknown")
            type_counts[typ] = type_counts.get(typ, 0) + 1

        for typ, count in type_counts.items():
            if count / total > 0.5 and total >= 3:
                patterns.append(
                    {
                        "pattern": ExceptionPattern.SYSTEMATIC.value,
                        "description": f"{count} exceptions of type {typ.value if hasattr(typ, 'value') else typ} ({count / total * 100:.0f}% of total)",
                        "severity": "warning",
                    }
                )

        # Pattern 3: Fraud indicator (high value, unusual pattern)
        high_value_exceptions = [
            e for e in self._exceptions if e.get("amount", 0) > Decimal(100000000)
        ]  # > Rp 100M
        if high_value_exceptions:
            patterns.append(
                {
                    "pattern": ExceptionPattern.FRAUD_INDICATOR.value,
                    "description": f"{len(high_value_exceptions)} exceptions with very high value (potential fraud indicator)",
                    "severity": "critical",
                }
            )

        # Check for multiple exceptions from same user
        users = {}
        for exc in self._exceptions:
            user = exc.get("user_id", "unknown")
            if user != "unknown":
                users[user] = users.get(user, 0) + 1
        for user, count in users.items():
            if count >= 3:
                patterns.append(
                    {
                        "pattern": ExceptionPattern.CLUSTERED.value,
                        "description": f"User {user} associated with {count} exceptions",
                        "severity": "warning",
                    }
                )

        return patterns

    def evaluate_against_materiality(self, materiality_threshold: Decimal) -> dict[str, Any]:
        """
        Mengevaluasi apakah total error melebihi materialitas.
        """
        total_error = sum(e.get("amount", Decimal(0)) for e in self._exceptions)

        is_material = total_error >= materiality_threshold
        percentage_of_materiality = (
            (total_error / materiality_threshold * 100) if materiality_threshold > 0 else 0
        )

        return {
            "total_error": float(total_error),
            "materiality_threshold": float(materiality_threshold),
            "is_material": is_material,
            "percentage_of_materiality": float(percentage_of_materiality),
            "conclusion": "Material" if is_material else "Not material",
        }

    def generate_recommendations(self) -> list[str]:
        """
        Menghasilkan rekomendasi tindak lanjut berdasarkan exceptions.
        """
        recommendations = []
        summary = self.get_summary()
        patterns = self.detect_patterns()

        if summary["total_exceptions"] == 0:
            recommendations.append("No exceptions found. No further action required.")
            return recommendations

        # Recommendation based on total error
        if summary["total_error_amount"] > 0:
            recommendations.append(
                f"Total error amount: {summary['total_error_amount']:,.2f}. Consider adjusting financial statements."
            )

        # Recommendation based on patterns
        for pattern in patterns:
            if pattern["pattern"] == ExceptionPattern.SYSTEMATIC.value:
                recommendations.append(
                    "Systematic error pattern detected. Review and correct the underlying process or system."
                )
            elif pattern["pattern"] == ExceptionPattern.CLUSTERED.value:
                recommendations.append(
                    f"Exceptions clustered: {pattern['description']}. Focus audit procedures on the affected area."
                )
            elif pattern["pattern"] == ExceptionPattern.FRAUD_INDICATOR.value:
                recommendations.append(
                    "URGENT: Potential fraud indicators detected. Escalate to forensic audit team immediately."
                )

        # Recommendation based on exception types
        by_type = summary.get("by_type", {})
        if by_type.get("authorization", 0) > 2:
            recommendations.append(
                "Multiple authorization exceptions. Review approval matrix and segregation of duties."
            )
        if by_type.get("documentation", 0) > 3:
            recommendations.append(
                "Missing documentation for multiple transactions. Strengthen document retention policy."
            )
        if by_type.get("system", 0) > 0:
            recommendations.append(
                "System errors detected. Review system logs and consider IT audit."
            )

        if not recommendations:
            recommendations.append(
                "Review individual exceptions and determine if adjustments are needed."
            )

        return recommendations

    def clear(self) -> None:
        """Menghapus semua exceptions."""
        self._exceptions.clear()
        logger = _get_logger()
        logger.info("All exceptions cleared")

    def get_exceptions(
        self, severity: ExceptionSeverity | None = None, exception_type: ExceptionType | None = None
    ) -> list[dict]:
        """Mendapatkan exceptions dengan filter."""
        filtered = self._exceptions
        if severity:
            filtered = [e for e in filtered if e.get("severity") == severity]
        if exception_type:
            filtered = [e for e in filtered if e.get("exception_type") == exception_type]
        return filtered

    def get_statistics_by_type(self) -> dict[str, dict]:
        """
        Mendapatkan statistik per jenis exception.
        """
        stats = {}
        for typ in ExceptionType:
            exceptions = self.get_exceptions(exception_type=typ)
            if exceptions:
                total = sum(e.get("amount", Decimal(0)) for e in exceptions)
                stats[typ.value] = {
                    "count": len(exceptions),
                    "total_amount": float(total),
                    "average_amount": float(total / len(exceptions)) if exceptions else 0,
                }
        return stats


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_exception_aggregator: AuditExceptionAggregator | None = None


def get_exception_aggregator() -> AuditExceptionAggregator:
    """Get singleton instance of AuditExceptionAggregator."""
    global _exception_aggregator
    if _exception_aggregator is None:
        _exception_aggregator = AuditExceptionAggregator()
    return _exception_aggregator


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "AuditExceptionAggregator",
    "ExceptionPattern",
    "ExceptionSeverity",
    "ExceptionType",
    "get_exception_aggregator",
]