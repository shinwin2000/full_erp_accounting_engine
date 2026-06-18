#!/usr/bin/env python3
"""
Module: test_module_isolation.py
Layer: Governance & Architecture Enforcement

Responsibility:
    Memeriksa isolasi modul spesifik dengan aturan yang sangat ketat, termasuk
    pelarangan impor teknologi tertentu (sqlalchemy, fastapi, kafka) di layer domain,
    dan isolasi kernel, ports, projections, shared_value_objects.
"""

from __future__ import annotations

import ast
import sys
import traceback
from pathlib import Path

import pytest

from architecture.boundary_checker import BoundaryChecker

# Pengecualian yang diizinkan secara arsitektur
ALLOWED_KERNEL_IMPORTS: set[tuple[str, str]] = {
    # Kernel boleh mengimpor infrastructure container untuk dependency injection
    ("kernel/dependency_injector", "infrastructure/dependency_container/ioc_container"),
}


# -------------------------------------------------------------------------
# Helper
# -------------------------------------------------------------------------
def _format_violations(violations: list[tuple[Path, str, int]]) -> str:
    return "\n".join(f"  - {f} (line {line}): {mod}" for f, mod, line in violations)


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def boundary_checker(project_root: Path) -> BoundaryChecker:
    return BoundaryChecker(
        str(project_root), exclude_dirs=["__pycache__", "tests", "venv", ".venv"]
    )


class TestModuleIsolation:
    # ------------------------------------------------------------
    # Kernel isolation
    # ------------------------------------------------------------
    def test_kernel_only_imports_allowed_modules(self, boundary_checker: BoundaryChecker):
        violations = boundary_checker.check()
        kernel_violations = []
        stdlib = set(sys.stdlib_module_names)
        builtin = set(sys.builtin_module_names)

        for v in violations:
            if not v.source_module.startswith("kernel"):
                continue
            target = v.target_module
            src_norm = v.source_module.replace(".", "/")
            tgt_norm = target.replace(".", "/")

            # Check whitelist
            if (src_norm, tgt_norm) in ALLOWED_KERNEL_IMPORTS:
                continue

            # Modul yang diizinkan
            if target.startswith(
                (
                    "constitution",
                    "axioms",
                    "kernel.guards",
                    "kernel.immutable_laws",
                    "ports.primary",
                    "kernel",
                )
            ):
                continue
            if target.split(".")[0] in stdlib or target.split(".")[0] in builtin:
                continue
            kernel_violations.append(v)

        assert len(kernel_violations) == 0, "Sovereign Kernel melanggar isolasi:\n" + "\n".join(
            f"  - {v.file_path} (line {getattr(v, 'line_no', '?')}): {v.source_module} -> {v.target_module}"
            for v in kernel_violations
        )

    # ------------------------------------------------------------
    # Domain isolation: dilarang mengimpor infrastructure/teknologi
    # ------------------------------------------------------------
    def test_domain_no_infrastructure_imports(self, boundary_checker: BoundaryChecker):
        violations = boundary_checker.check()
        bad = [
            v
            for v in violations
            if v.source_module.startswith("domain") and v.target_module.startswith("infrastructure")
        ]
        assert len(bad) == 0, (
            f"Domain mengimpor Infrastructure:\n{_format_violations([(Path(v.file_path), v.target_module, getattr(v, 'line_no', 0)) for v in bad])}"
        )

    def test_domain_no_sqlalchemy_fastapi_kafka(self, project_root: Path):
        forbidden = {"sqlalchemy", "fastapi", "kafka", "redis", "requests", "boto3", "aiohttp"}
        domain_dir = project_root / "domain"
        if not domain_dir.exists():
            pytest.skip("Folder domain tidak ditemukan")
        violations = []
        parse_errors = []
        for file_path in domain_dir.rglob("*.py"):
            if file_path.name == "__init__.py":
                continue
            try:
                with open(file_path, encoding="utf-8-sig", errors="replace") as f:
                    content = f.read()
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            mod = alias.name.split(".")[0]
                            if mod in forbidden:
                                violations.append((file_path, mod, node.lineno))
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        mod = node.module.split(".")[0]
                        if mod in forbidden:
                            violations.append((file_path, mod, node.lineno))
            except Exception as e:
                parse_errors.append((file_path, str(e), traceback.format_exc()))
        if parse_errors:
            pytest.fail(
                "Gagal parsing Domain:\n" + "\n".join(f"  {f}: {err}" for f, err, _ in parse_errors)
            )
        assert len(violations) == 0, (
            f"Domain mengimpor pustaka terlarang:\n{_format_violations(violations)}"
        )

    # ------------------------------------------------------------
    # Application tidak boleh mengimpor adapters
    # ------------------------------------------------------------
    def test_application_no_adapters_imports(self, boundary_checker: BoundaryChecker):
        violations = boundary_checker.check()
        bad = [
            v
            for v in violations
            if v.source_module.startswith("application") and v.target_module.startswith("adapters")
        ]
        assert len(bad) == 0, (
            f"Application mengimpor Adapters:\n{_format_violations([(Path(v.file_path), v.target_module, getattr(v, 'line_no', 0)) for v in bad])}"
        )

    # ------------------------------------------------------------
    # Ports tidak boleh mengimpor implementasi konkret
    # ------------------------------------------------------------
    def test_ports_no_implementation_imports(self, boundary_checker: BoundaryChecker):
        violations = boundary_checker.check()
        bad = []
        for v in violations:
            if v.source_module.startswith("ports") and any(
                v.target_module.startswith(p)
                for p in ["adapters", "infrastructure", "sqlalchemy", "kafka", "redis", "boto3"]
            ):
                bad.append(v)
        assert len(bad) == 0, (
            f"Ports mengimpor implementasi konkret:\n{_format_violations([(Path(v.file_path), v.target_module, getattr(v, 'line_no', 0)) for v in bad])}"
        )

    # ------------------------------------------------------------
    # Event gateway tidak boleh mengimpor domain
    # ------------------------------------------------------------
    def test_event_gateway_no_domain_imports(self, boundary_checker: BoundaryChecker):
        violations = boundary_checker.check()
        bad = [
            v
            for v in violations
            if v.source_module.startswith(("event_gateway", "transformers"))
            and v.target_module.startswith("domain")
        ]
        assert len(bad) == 0, (
            f"Gateway/Transformer mengimpor Domain:\n{_format_violations([(Path(v.file_path), v.target_module, getattr(v, 'line_no', 0)) for v in bad])}"
        )

    # ------------------------------------------------------------
    # Projections (read models) hanya boleh mengimpor domain_events/value_objects
    # ------------------------------------------------------------
    def test_projections_no_aggregate_imports(self, project_root: Path):
        projections_dir = project_root / "projections"
        if not projections_dir.exists():
            pytest.skip("Folder projections tidak ditemukan")
        violations = []
        for file_path in projections_dir.rglob("*.py"):
            if file_path.name == "__init__.py":
                continue
            try:
                with open(file_path, encoding="utf-8-sig", errors="replace") as f:
                    content = f.read()
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name.startswith("domain.") and not alias.name.startswith(
                                ("domain.shared_value_objects", "domain.journal.domain_events")
                            ):
                                violations.append((file_path, alias.name, node.lineno))
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and node.module.startswith("domain."):
                            if not node.module.startswith(
                                ("domain.shared_value_objects", "domain.journal.domain_events")
                            ):
                                violations.append((file_path, node.module, node.lineno))
            except Exception as e:
                pytest.fail(f"Gagal parsing {file_path}: {e}")
        assert len(violations) == 0, (
            f"Projections mengimpor Aggregate Domain:\n{_format_violations(violations)}"
        )

    # ------------------------------------------------------------
    # Shared Value Objects harus benar‑benar mandiri
    # ------------------------------------------------------------
    def test_shared_value_objects_no_internal_imports(self, project_root: Path):
        svo_dir = project_root / "domain" / "shared_value_objects"
        if not svo_dir.exists():
            pytest.skip("Folder shared_value_objects tidak ditemukan")
        violations = []
        internal_packages = (
            "domain",
            "application",
            "infrastructure",
            "adapters",
            "ports",
            "kernel",
            "architecture",
            "projections",
        )
        for file_path in svo_dir.rglob("*.py"):
            if file_path.name == "__init__.py":
                continue
            try:
                with open(file_path, encoding="utf-8-sig", errors="replace") as f:
                    content = f.read()
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name.startswith(
                                internal_packages
                            ) and not alias.name.startswith("domain.shared_value_objects"):
                                violations.append((file_path, alias.name, node.lineno))
                    elif isinstance(node, ast.ImportFrom) and (
                        node.module
                        and node.module.startswith(internal_packages)
                        and not node.module.startswith("domain.shared_value_objects")
                    ):
                        violations.append((file_path, node.module, node.lineno))
            except Exception as e:
                pytest.fail(f"Gagal parsing {file_path}: {e}")
        assert len(violations) == 0, (
            f"Shared Value Objects mengimpor internal:\n{_format_violations(violations)}"
        )
