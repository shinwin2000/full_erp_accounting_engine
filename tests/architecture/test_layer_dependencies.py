#!/usr/bin/env python3
"""
Module: test_layer_dependencies.py
Layer: Governance & Architecture Enforcement

Responsibility:
    Memeriksa dan menegakkan kepatuhan terhadap aturan dependensi lapisan (Clean/Hexagonal Architecture).
    Memastikan inversi dependensi dipatuhi: lapisan dalam tidak boleh mengimpor lapisan luar.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Asumsikan modul architecture sudah tersedia di proyek
try:
    from architecture.boundary_checker import BoundaryChecker, ImportViolation
    from architecture.layer_definitions import get_layer_for_module, is_allowed_import
except ImportError as e:
    pytest.skip(f"Modul architecture tidak ditemukan: {e}", allow_module_level=True)

# Pengecualian yang dilegalkan (whitelist) - pelanggaran yang diizinkan secara arsitektur
ALLOWED_VIOLATIONS: set[tuple[str, str]] = {
    # Kernel boleh mengimpor infrastructure container (dependency injection adalah bagian kernel)
    ("kernel/dependency_injector", "infrastructure/dependency_container/ioc_container"),
    # Adapters boleh mengimpor reports (infrastructure) karena reports adalah bagian dari infrastruktur
    ("adapters/primary_api/v1/fastapi_report_router", "reports/distributor_email_whatsapp"),
    ("adapters/primary_api/v1/fastapi_report_router", "reports/scheduler_cron"),
}


def normalize_module_name(module_name: str) -> str:
    """Normalisasi dari dot notation ke slash notation."""
    return module_name.replace(".", "/").replace("\\", "/")


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def boundary_checker(project_root: Path) -> BoundaryChecker:
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
            ".mypy_cache",
            "logs",
            "config_files",
            "docs",
            "deployment",
        ],
    )


class TestLayerDependencies:
    """Test suite untuk menegakkan integritas batasan lapisan."""

    def test_no_violations(self, boundary_checker: BoundaryChecker):
        violations = boundary_checker.check()
        filtered = []
        for v in violations:
            src_norm = normalize_module_name(v.source_module)
            tgt_norm = normalize_module_name(v.target_module)
            if (src_norm, tgt_norm) not in ALLOWED_VIOLATIONS:
                filtered.append(v)

        if filtered:
            lines = [f"🚨 ARSITEKTUR GAGAL: {len(filtered)} Pelanggaran Batas Lapisan!", "-" * 80]
            for i, v in enumerate(filtered, 1):
                lines.append(
                    f"[{i}] File: {v.file_path} (line {getattr(v, 'line_no', '?')})\n"
                    f"    {v.source_module} → {v.target_module}\n"
                    f"    Layer: {get_layer_for_module(src_norm)} → {get_layer_for_module(tgt_norm)}"
                )
            pytest.fail("\n".join(lines))

    def test_foundation_imports_only_stdlib(self, boundary_checker: BoundaryChecker):
        violations = boundary_checker.check()
        bad = [v for v in violations if v.source_module.startswith(("constitution", "axioms"))]
        if bad:
            lines = ["🚨 PELANGGARAN JANGKAR: Constitution/Axioms mengimpor modul bisnis lokal!"]
            lines.extend(f"  - {v.file_path} | {v.source_module} -> {v.target_module}" for v in bad)
            pytest.fail("\n".join(lines))

    def test_domain_no_adapters(self, boundary_checker: BoundaryChecker):
        violations = boundary_checker.check()
        bad = [
            v
            for v in violations
            if v.source_module.startswith("domain") and v.target_module.startswith("adapters")
        ]
        if bad:
            pytest.fail(f"🚨 KEBOCORAN DOMAIN: Domain mengimpor Adapters:\n{self._fmt(bad)}")

    def test_domain_no_infrastructure(self, boundary_checker: BoundaryChecker):
        violations = boundary_checker.check()
        bad = [
            v
            for v in violations
            if v.source_module.startswith("domain") and v.target_module.startswith("infrastructure")
        ]
        if bad:
            pytest.fail(f"🚨 KEBOCORAN INFRAS: Domain mengimpor Infrastructure:\n{self._fmt(bad)}")

    def test_application_no_adapters_directly(self, boundary_checker: BoundaryChecker):
        violations = boundary_checker.check()
        bad = [
            v
            for v in violations
            if v.source_module.startswith("application") and v.target_module.startswith("adapters")
        ]
        if bad:
            pytest.fail(f"🚨 BYPASS ABSTRAKSI: Application mengimpor Adapters:\n{self._fmt(bad)}")

    def test_application_no_infrastructure(self, boundary_checker: BoundaryChecker):
        violations = boundary_checker.check()
        bad = [
            v
            for v in violations
            if v.source_module.startswith("application")
            and v.target_module.startswith("infrastructure")
        ]
        if bad:
            pytest.fail(
                f"🚨 PELANGGARAN ALUR: Application mengimpor Infrastructure:\n{self._fmt(bad)}"
            )

    def test_ports_no_adapters(self, boundary_checker: BoundaryChecker):
        violations = boundary_checker.check()
        bad = [
            v
            for v in violations
            if v.source_module.startswith("ports") and v.target_module.startswith("adapters")
        ]
        if bad:
            pytest.fail(f"🚨 KETERIKATAN TERBALIK: Ports mengimpor Adapters:\n{self._fmt(bad)}")

    def test_kernel_no_domain(self, boundary_checker: BoundaryChecker):
        violations = boundary_checker.check()
        bad = [
            v
            for v in violations
            if v.source_module.startswith("kernel") and v.target_module.startswith("domain")
        ]
        if bad:
            pytest.fail(f"🚨 PELANGGARAN KERNEL: Kernel bergantung pada Domain:\n{self._fmt(bad)}")

    def _fmt(self, violations):
        return "\n".join(f"  - {v.file_path} ({getattr(v, 'line_no', '?')})" for v in violations)


class TestImportRules:
    """Test akurasi aturan di layer_definitions."""

    def test_layer_mapping(self, project_root: Path):
        important = [
            "constitution/supreme_law",
            "domain/journal/aggregate_root",
            "application/service_layer/service_journal",
            "ports/primary/journal_repository_port",
            "adapters/secondary_impl/sqlalchemy_journal_repository_impl",
            "infrastructure/database/transaction_manager",
        ]
        for mod in important:
            layer = get_layer_for_module(mod)
            assert layer is not None, f"Modul '{mod}' tidak memiliki pemetaan layer!"

    def test_allowed_imports_positive(self):
        allowed = [
            (
                "adapters/primary_api/fastapi_journal_router",
                "application/service_layer/service_journal",
            ),
            ("application/service_layer/service_journal", "domain/journal/aggregate_root"),
            ("domain/journal/aggregate_root", "constitution/enforcement_engine"),
        ]
        for src, tgt in allowed:
            assert is_allowed_import(src, tgt), f"Seharusnya diizinkan: {src} -> {tgt}"

    def test_allowed_imports_negative(self):
        forbidden = [
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
        for src, tgt in forbidden:
            assert not is_allowed_import(src, tgt), f"Seharusnya DILARANG: {src} -> {tgt}"
