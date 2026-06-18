#!/usr/bin/env python3
"""
Package: architecture
Layer: Governance & Architecture Enforcement

Responsibility:
    Menyediakan alat dan konfigurasi untuk memeriksa dan menegakkan
    aturan arsitektur (dependensi lapisan, circular import, module isolation)
    sesuai dengan dokumen ALUR DEPENDENSI & ATURAN IMPOR FINAL.

Modules:
    - layer_definitions: Mendefinisikan lapisan dan aturan dependensi
    - boundary_checker: Memeriksa pelanggaran batas antar lapisan
    - arch_tests: Test suite untuk arsitektur (pytest)

Metode entity dasar:
    Setiap kelas yang diekspor memiliki metode:
    validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__version__ = "2.0.0"
__author__ = "ERP Accounting Engine Team"

# ============================================================================
# Ekspos komponen utama dari submodul
# ============================================================================

from .boundary_checker import (
    BoundaryChecker,
    ImportViolation,
    check_all_boundaries,
    get_architecture_report,
)
from .layer_definitions import (
    DEPENDENCY_RULES,
    LAYER_DEFINITIONS,
    Layer,
    LayerDefinition,
    get_allowed_imports_for_module,
    get_cache_stats,
    get_layer_for_file,
    get_layer_for_module,
    is_allowed_import,
    reset_cache,
    validate_layer_consistency,
)

# ============================================================================
# Utilitas tambahan untuk package
# ============================================================================


def run_full_architecture_check(root_path: str = ".") -> tuple[bool, list[ImportViolation]]:
    """
    Menjalankan pemeriksaan arsitektur lengkap dan mengembalikan hasil.

    Args:
        root_path: Root direktori proyek

    Returns:
        Tuple (is_clean, violations)
    """
    checker = BoundaryChecker(root_path)
    violations = checker.check()
    is_clean = len(violations) == 0
    if not is_clean:
        logger.error(f"Architecture check failed: {len(violations)} violations")
        for v in violations[:10]:
            logger.error(f"  {v}")
    else:
        logger.info("Architecture check passed")
    return is_clean, violations


def get_architecture_summary(root_path: str = ".") -> dict:
    """
    Mendapatkan ringkasan arsitektur untuk laporan.
    """
    from .layer_definitions import get_all_modules_with_layers

    modules = get_all_modules_with_layers(root_path)
    summary = {
        "total_modules": len(modules),
        "layers": {},
        "violations": None,
        "version": __version__,
    }
    for _mod, layer in modules:
        layer_name = layer.name if layer else "Unknown"
        summary["layers"][layer_name] = summary["layers"].get(layer_name, 0) + 1

    is_clean, violations = run_full_architecture_check(root_path)
    summary["violations_count"] = len(violations)
    summary["is_clean"] = is_clean

    return summary


def get_architecture_version() -> str:
    """Mendapatkan versi package architecture."""
    return __version__


# ============================================================================
# Entity dasar untuk package (optional, untuk konsistensi)
# ============================================================================


class ArchitecturePackage:
    """
    Representasi package architecture dengan metode entity dasar.
    Berguna untuk audit dan versioning pada level package.
    """

    def __init__(self, version: str = __version__):
        self._version = version
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._package_id = "architecture"

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        import datetime

        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                "version": self._version,
                "package": self._package_id,
                "details": details,
            }
        )

    def validate(self) -> dict[str, Any]:
        """Validasi package architecture."""
        errors = []
        # Cek bahwa semua modul penting dapat diimpor
        try:
            from .boundary_checker import BoundaryChecker
        except ImportError as e:
            errors.append(f"boundary_checker module missing: {e}")
        try:
            from .layer_definitions import Layer
        except ImportError as e:
            errors.append(f"layer_definitions module missing: {e}")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "package": self._package_id,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArchitecturePackage:
        return cls(version=data.get("version", __version__))

    def clone(self) -> ArchitecturePackage:
        new = ArchitecturePackage(self._version)
        new._version = self._version + "~clone"
        return new

    def snapshot(self) -> dict[str, Any]:
        import datetime

        return {
            "package": self._package_id,
            "version": self._version,
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        }

    def version(self) -> str:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ArchitecturePackage:
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# Logging inisialisasi
# ============================================================================

logger.info(f"Architecture package loaded (version {__version__})")

# ============================================================================
# Ekspor __all__
# ============================================================================

__all__ = [
    # Kelas dan fungsi dari boundary_checker
    "BoundaryChecker",
    "ImportViolation",
    "check_all_boundaries",
    "get_architecture_report",
    # Kelas, enum, dan fungsi dari layer_definitions
    "DEPENDENCY_RULES",
    "LAYER_DEFINITIONS",
    "Layer",
    "LayerDefinition",
    "get_allowed_imports_for_module",
    "get_layer_for_module",
    "get_layer_for_file",
    "is_allowed_import",
    "validate_layer_consistency",
    "reset_cache",
    "get_cache_stats",
    # Utilitas package
    "run_full_architecture_check",
    "get_architecture_summary",
    "get_architecture_version",
    "ArchitecturePackage",
]
