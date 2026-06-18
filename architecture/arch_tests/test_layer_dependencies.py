#!/usr/bin/env python3
"""
Module: test_layer_dependencies.py
Layer: Governance & Architecture Enforcement

Responsibility:
    Memeriksa dan menegakkan kepatuhan terhadap aturan dependensi lapisan (Clean/Hexagonal Architecture).

Metode yang ditambahkan:
- Untuk TestLayerDependencies: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk TestImportRules: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from architecture.boundary_checker import BoundaryChecker
from architecture.layer_definitions import get_layer_for_module, is_allowed_import

# Daftar pengecualian yang diperbolehkan secara hukum arsitektur (Whitelist)
ALLOWED_VIOLATIONS: set[tuple[str, str]] = {
    # Contoh nyata inversi jika ada perkecualian super khusus yang dilegalkan oleh arsitek:
    # ("domain/journal/aggregate_root", "ports/primary/journal_repository_port")
}


def normalize_module_name(module_name: str) -> str:
    return module_name.replace(".", "/").replace("\\", "/")


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


# ============================================================================
# TestLayerDependencies (dengan entity dasar)
# ============================================================================
class TestLayerDependencies:
    """Test suite untuk menegakkan integritas aturan batasan lapisan aplikasi."""

    _version: int = 1
    _audit_trail: list[dict[str, Any]] = []
    _snapshots: list[dict[str, Any]] = []
    _test_id: str = str(uuid4())

    def __init__(self):
        self._take_snapshot()

    def _take_snapshot(self):
        import datetime

        self._snapshots.append(
            {
                "version": self._version,
                "test_id": self._test_id,
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        import datetime

        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                "version": self._version,
                "test_id": self._test_id,
                "details": details,
            }
        )

    # ==================== FIXTURE ====================
    @pytest.fixture
    def boundary_checker(self, project_root: Path) -> BoundaryChecker:
        return BoundaryChecker(
            str(project_root),
            exclude_dirs=[
                "__pycache__",
                ".git",
                "venv",
                ".venv",
                "env",
                "migrations",
                "tests",
                "build",
                "dist",
                ".pytest_cache",
            ],
        )

    # ==================== TEST METHODS (asli, dipertahankan) ====================
    def test_no_violations(self, boundary_checker: BoundaryChecker):
        violations = boundary_checker.check()
        filtered_violations = []
        for v in violations:
            src_norm = normalize_module_name(v.source_module)
            tgt_norm = normalize_module_name(v.target_module)
            if (src_norm, tgt_norm) not in ALLOWED_VIOLATIONS:
                filtered_violations.append(v)
        if filtered_violations:
            report_lines = [
                f"🚨 ARSITEKTUR GAGAL: Terdeteksi {len(filtered_violations)} Pelanggaran Batas Lapisan!",
                "Detail Pelanggaran Struktural:",
                "-" * 80,
            ]
            for idx, v in enumerate(filtered_violations, 1):
                report_lines.append(
                    f"  [{idx}] File: {v.file_path} (Baris: {getattr(v, 'line_no', 'Unknown')})\n"
                    f"      Modul '{v.source_module}' mencoba mengimpor '{v.target_module}'\n"
                    f"      Status Aturan: Lapisan '{get_layer_for_module(src_norm)}' -> Dilarang mengimpor '{get_layer_for_module(tgt_norm)}'"
                )
            pytest.fail("\n".join(report_lines), pytrace=True)

    def test_foundation_imports_only_stdlib(self, boundary_checker: BoundaryChecker):
        violations = boundary_checker.check()
        foundation_violations = [
            v for v in violations if v.source_module.startswith(("constitution", "axioms"))
        ]
        if foundation_violations:
            lines = [
                "🚨 PELANGGARAN JANGKAR: Lapisan fondasi hukum tertinggi tidak boleh mengimpor modul bisnis lokal!"
            ]
            for v in foundation_violations:
                lines.append(f"  - File: {v.file_path} | {v.source_module} -> {v.target_module}")
            pytest.fail("\n".join(lines))

    def test_domain_not_import_adapters(self, boundary_checker: BoundaryChecker):
        violations = boundary_checker.check()
        domain_to_adapters = [
            v
            for v in violations
            if v.source_module.startswith("domain") and v.target_module.startswith("adapters")
        ]
        if domain_to_adapters:
            pytest.fail(
                f"🚨 KEBOCORAN DOMAIN: Layer Domain mengimpor Adapters konkrit langsung:\n  -> {domain_to_adapters}"
            )

    def test_domain_not_import_infrastructure(self, boundary_checker: BoundaryChecker):
        violations = boundary_checker.check()
        domain_to_infra = [
            v
            for v in violations
            if v.source_module.startswith("domain") and v.target_module.startswith("infrastructure")
        ]
        if domain_to_infra:
            pytest.fail(
                f"🚨 KEBOCORAN INFRAS: Layer Domain mengimpor Infrastructure langsung:\n  -> {domain_to_infra}"
            )

    def test_application_not_import_adapters_directly(self, boundary_checker: BoundaryChecker):
        violations = boundary_checker.check()
        app_to_adapters = [
            v
            for v in violations
            if v.source_module.startswith("application") and v.target_module.startswith("adapters")
        ]
        if app_to_adapters:
            pytest.fail(
                f"🚨 BYPASS ABSTRAKSI: Application Layer menembus batas mengimpor Adapters langsung:\n  -> {app_to_adapters}"
            )

    def test_application_not_import_infrastructure_directly(
        self, boundary_checker: BoundaryChecker
    ):
        violations = boundary_checker.check()
        app_to_infra = [
            v
            for v in violations
            if v.source_module.startswith("application")
            and v.target_module.startswith("infrastructure")
        ]
        if app_to_infra:
            pytest.fail(
                f"🚨 PELANGGARAN ALUR: Application Layer mengimpor Infrastructure langsung:\n  -> {app_to_infra}"
            )

    def test_ports_not_import_adapters(self, boundary_checker: BoundaryChecker):
        violations = boundary_checker.check()
        ports_to_adapters = [
            v
            for v in violations
            if v.source_module.startswith("ports") and v.target_module.startswith("adapters")
        ]
        if ports_to_adapters:
            pytest.fail(
                f"🚨 KETERIKATAN TERBALIK: Ports Layer mengimpor detail implementasi Adapters:\n  -> {ports_to_adapters}"
            )

    def test_kernel_not_import_domain(self, boundary_checker: BoundaryChecker):
        violations = boundary_checker.check()
        kernel_to_domain = [
            v
            for v in violations
            if v.source_module.startswith("kernel") and v.target_module.startswith("domain")
        ]
        if kernel_to_domain:
            pytest.fail(
                f"🚨 PELANGGARAN KERNEL: Sovereign Kernel terkontaminasi dependensi Domain Bisnis:\n  -> {kernel_to_domain}"
            )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self._version < 1:
            errors.append("Version must be >= 1")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self._test_id,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestLayerDependencies:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._test_id = data.get("test_id", str(uuid4()))
        return instance

    def clone(self) -> TestLayerDependencies:
        new = TestLayerDependencies()
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._test_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        import datetime

        return {
            "version": self._version,
            "test_id": self._test_id,
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> TestLayerDependencies:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# TestImportRules (dengan entity dasar)
# ============================================================================
class TestImportRules:
    """Test suite untuk memastikan akurasi mesin pemetaan aturan (layer_definitions)."""

    _version: int = 1
    _audit_trail: list[dict[str, Any]] = []
    _snapshots: list[dict[str, Any]] = []
    _test_id: str = str(uuid4())

    def __init__(self):
        self._take_snapshot()

    def _take_snapshot(self):
        import datetime

        self._snapshots.append(
            {
                "version": self._version,
                "test_id": self._test_id,
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        import datetime

        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                "version": self._version,
                "test_id": self._test_id,
                "details": details,
            }
        )

    # ==================== TEST METHODS (asli, dipertahankan) ====================
    def test_layer_mapping(self, project_root: Path):
        important_modules = [
            "constitution/supreme_law",
            "domain/journal/aggregate_root",
            "application/service_layer/service_journal",
            "ports/primary/journal_repository_port",
            "adapters/secondary_impl/sqlalchemy_journal_repository_impl",
            "infrastructure/database/transaction_manager",
        ]
        for mod in important_modules:
            layer = get_layer_for_module(mod)
            assert layer is not None, (
                f"🚨 KONFIGURASI EROR: Modul '{mod}' tidak memiliki pemetaan layer di layer_definitions.py!"
            )

    def test_allowed_imports_positive(self):
        allowed_pairs = [
            (
                "adapters/primary_api/fastapi_journal_router",
                "application/service_layer/service_journal",
            ),
            ("application/service_layer/service_journal", "domain/journal/aggregate_root"),
            ("domain/journal/aggregate_root", "constitution/enforcement_engine"),
        ]
        for from_mod, to_mod in allowed_pairs:
            is_valid = is_allowed_import(from_mod, to_mod)
            assert is_valid, (
                f"🚨 VALIDASI SALAH: Alur impor {from_mod} -> {to_mod} seharusnya SEHAT & DIIZINKAN."
            )

    def test_allowed_imports_negative(self):
        forbidden_pairs = [
            (
                "domain/journal/aggregate_root",
                "adapters/secondary_impl/sqlalchemy_journal_repository_impl",
            ),
            (
                "application/service_layer/service_journal",
                "infrastructure/database/transaction_manager",
            ),
            ("kernel/sealed_gate", "domain/journal/aggregate_root"),
        ]
        for from_mod, to_mod in forbidden_pairs:
            is_valid = is_allowed_import(from_mod, to_mod)
            assert not is_valid, (
                f"🚨 KEBOCORAN LOLOS: Alur impor {from_mod} -> {to_mod} seharusnya DILARANG!"
            )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self._version < 1:
            errors.append("Version must be >= 1")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self._test_id,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestImportRules:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._test_id = data.get("test_id", str(uuid4()))
        return instance

    def clone(self) -> TestImportRules:
        new = TestImportRules()
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._test_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        import datetime

        return {
            "version": self._version,
            "test_id": self._test_id,
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> TestImportRules:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self
