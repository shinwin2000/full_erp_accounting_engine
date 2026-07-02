#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kernel/error_analysis.py
========================
Lapisan abstraksi untuk Root Cause Analysis (RCA).
Memisahkan aplikasi dari implementasi RCA (checker.core.rca)
agar arsitektur tetap bersih (app → kernel → checker).

Big-4 Audit Grade: Tidak ada pelanggaran layer.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("erp_engine.rca")

# ─── Tipe data hasil RCA ──────────────────────────────────────────────────────
class RCAResult:
    """Hasil analisis RCA yang aman dan serializable."""
    __slots__ = (
        "severity", "category", "error_code",
        "root_cause", "evidence", "impact",
        "suggested_fix", "confidence",
        "_raw"
    )

    def __init__(
        self,
        severity: str = "UNKNOWN",
        category: str = "Unknown",
        error_code: str = "UNKNOWN",
        root_cause: str = "",
        evidence: Optional[List[str]] = None,
        impact: Optional[List[str]] = None,
        suggested_fix: str = "",
        confidence: float = 0.0,
        _raw: Optional[Any] = None,
    ):
        self.severity = severity
        self.category = category
        self.error_code = error_code
        self.root_cause = root_cause
        self.evidence = evidence or []
        self.impact = impact or []
        self.suggested_fix = suggested_fix
        self.confidence = confidence
        self._raw = _raw

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity,
            "category": self.category,
            "error_code": self.error_code,
            "root_cause": self.root_cause,
            "evidence": self.evidence[:10],
            "impact": self.impact[:5],
            "suggested_fix": self.suggested_fix,
            "confidence": round(self.confidence, 4),
        }

    def summary(self) -> str:
        return f"[{self.severity}] {self.root_cause[:80]}"

    def is_fatal_or_critical(self) -> bool:
        return self.severity in ("FATAL", "CRITICAL")

    def __repr__(self) -> str:
        return f"<RCAResult severity={self.severity} confidence={self.confidence}>"


# ─── Wrapper ──────────────────────────────────────────────────────────────────
_RCA_ENGINE = None
_RCA_AVAILABLE = False


def _import_rca() -> bool:
    """Import RCA engine secara lazy dan cache hasilnya."""
    global _RCA_ENGINE, _RCA_AVAILABLE
    if _RCA_AVAILABLE:
        return True

    try:
        # Coba dari checker.core.rca (lokasi default)
        from checker.core.rca import analyze_exception, Severity, get_engine
        _RCA_ENGINE = get_engine()
        _RCA_AVAILABLE = True
        logger.debug("RCA engine loaded from checker.core.rca")
        return True
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"RCA engine load failed: {e}")

    # Fallback: try local rca module
    try:
        import rca
        _RCA_ENGINE = rca.get_engine()
        _RCA_AVAILABLE = True
        logger.debug("RCA engine loaded from local rca module")
        return True
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Local RCA engine load failed: {e}")

    _RCA_AVAILABLE = False
    return False


def analyze_error(
    exception: Exception,
    context: Optional[Dict[str, Any]] = None,
) -> RCAResult:
    """
    Analisis root cause dari exception menggunakan RCA engine (jika tersedia).
    Fallback ke dict sederhana jika engine tidak tersedia.

    Args:
        exception: Exception yang terjadi
        context: Dict tambahan (URL, user, module, dll.)

    Returns:
        RCAResult yang aman untuk serialisasi
    """
    if not _import_rca():
        # Fallback sederhana
        return RCAResult(
            severity="ERROR",
            category="Runtime",
            error_code="RCA_FALLBACK",
            root_cause=f"{type(exception).__name__}: {str(exception)}",
            evidence=[f"RCA engine tidak tersedia. Traceback tidak dianalisis."],
            impact=["Perbaiki instalasi checker.core.rca atau rca.py"],
            suggested_fix="Instal RCA engine atau perbaiki import",
            confidence=0.3,
            _raw=exception,
        )

    try:
        from checker.core.rca import analyze_exception as _rca_analyze, Severity

        ctx = context or {}
        result = _rca_analyze(exception, ctx)

        # Konversi ke RCAResult kita
        return RCAResult(
            severity=result.severity.value if hasattr(result.severity, "value") else str(result.severity),
            category=result.category.value if hasattr(result.category, "value") else str(result.category),
            error_code=result.error_code.value if hasattr(result.error_code, "value") else str(result.error_code),
            root_cause=result.root_cause,
            evidence=list(result.evidence)[:10],
            impact=list(result.impact)[:5],
            suggested_fix=result.suggested_fix,
            confidence=result.confidence,
            _raw=result,
        )
    except Exception as e:
        logger.warning(f"RCA analyze failed: {e}, using fallback")
        return RCAResult(
            severity="ERROR",
            category="RCA",
            error_code="RCA_ERROR",
            root_cause=f"RCA engine error: {e}",
            evidence=[f"Original exception: {type(exception).__name__}: {str(exception)}"],
            impact=["RCA analysis failed, but original error is logged"],
            suggested_fix="Periksa RCA engine atau log traceback",
            confidence=0.5,
            _raw=exception,
        )


# ─── Helper untuk logging ────────────────────────────────────────────────────
def log_rca_result(logger_obj: logging.Logger, rca: RCAResult, prefix: str = "RCA") -> None:
    """Log hasil RCA dengan level sesuai severity."""
    level = logging.ERROR
    if rca.severity in ("FATAL", "CRITICAL"):
        level = logging.CRITICAL
    elif rca.severity in ("HIGH", "MEDIUM"):
        level = logging.ERROR
    elif rca.severity == "LOW":
        level = logging.WARNING
    else:
        level = logging.INFO

    msg = (
        f"{prefix} [{rca.severity}] {rca.root_cause[:200]}"
        f" (conf={rca.confidence:.2f})"
    )
    logger_obj.log(level, msg)
    if rca.evidence:
        logger_obj.debug(f"{prefix} Evidence: {rca.evidence[:3]}")
    if rca.suggested_fix:
        logger_obj.info(f"{prefix} Fix: {rca.suggested_fix[:200]}")


# ─── Ekspor ──────────────────────────────────────────────────────────────────
__all__ = [
    "RCAResult",
    "analyze_error",
    "log_rca_result",
]