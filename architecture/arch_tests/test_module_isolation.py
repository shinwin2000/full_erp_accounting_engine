#!/usr/bin/env python3
"""
Module: test_module_isolation.py
Layer: Governance & Architecture Enforcement

Responsibility:
    Memeriksa isolasi modul tertentu, misalnya modul 'kernel' hanya boleh
    mengimpor modul yang diizinkan, dan modul 'domain' tidak boleh mengimpor
    'infrastructure' secara langsung.

Metode yang ditambahkan:
- Untuk TestModuleIsolation: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import ast
import sys
import traceback
from typing import Any
from uuid import uuid4

import pytest

from architecture.boundary_checker import BoundaryChecker


# ============================================================================
# TestModuleIsolation (dengan entity dasar)
# ============================================================================
class TestModuleIsolation:
    """Test isolasi modul-modul kritis untuk menjaga integritas arsitektur."""

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
    def boundary_checker(self, project_root):
        return BoundaryChecker(str(project_root))

    # ==================== HELPER ====================
    def _format_violations(self, violations: list[Any]) -> str:
        details = []
        for v in violations:
            file_path = getattr(v, "source_file", getattr(v, "file", "Unknown File"))
            line_no = getattr(v, "line_no", getattr(v, "lineno", "?"))
            src = getattr(v, "source_module", "UnknownSource")
            tgt = getattr(v, "target_module", getattr(v, "imported_module", "UnknownTarget"))
            details.append(
                f"  - [FILE]: {file_path} (Baris: {line_no}) | Modul '{src}' -> Melanggar mengimpor '{tgt}'"
            )
        return "\n".join(details)

    # ==================== TEST METHODS (asli, dipertahankan) ====================
    def test_kernel_only_imports_allowed_modules(self, boundary_checker):
        violations = boundary_checker.check()
        kernel_violations = []
        stdlib_names = getattr(sys, "stdlib_module_names", set())
        builtin_names = sys.builtin_module_names
        for v in violations:
            if not v.source_module.startswith("kernel"):
                continue
            target = v.target_module
            base_target = target.split(".")[0]
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
            if base_target in builtin_names or base_target in stdlib_names:
                continue
            kernel_violations.append(v)
        assert len(kernel_violations) == 0, (
            f"Sovereign Kernel melanggar isolasi arsitektur dengan mengimpor modul ilegal:\n"
            f"{self._format_violations(kernel_violations)}"
        )

    def test_domain_no_infrastructure_imports(self, boundary_checker):
        violations = boundary_checker.check()
        domain_to_infra = [
            v
            for v in violations
            if v.source_module.startswith("domain") and v.target_module.startswith("infrastructure")
        ]
        assert len(domain_to_infra) == 0, (
            f"Kebocoran Terdeteksi! Layer Domain (Pure) tidak boleh mengimpor Infrastructure secara langsung:\n"
            f"{self._format_violations(domain_to_infra)}"
        )

    def test_domain_no_sqlalchemy_imports(self, project_root):
        forbidden_imports = {"sqlalchemy", "fastapi", "kafka", "redis", "requests"}
        domain_dir = project_root / "domain"
        domain_files = list(domain_dir.glob("**/*.py")) if domain_dir.exists() else []
        violations = []
        parse_errors = []
        for file_path in domain_files:
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
                            if mod in forbidden_imports:
                                violations.append((file_path, mod, node.lineno))
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        mod = node.module.split(".")[0]
                        if mod in forbidden_imports:
                            violations.append((file_path, mod, node.lineno))
            except Exception as e:
                parse_errors.append((file_path, str(e), traceback.format_exc()))
        if parse_errors:
            error_msg = "\n".join(
                [f"  - File: {f}\n    Error: {err}\n{tb}" for f, err, tb in parse_errors]
            )
            pytest.fail(f"Gagal memparsing beberapa file Domain selama analisis AST:\n{error_msg}")
        assert len(violations) == 0, (
            "Domain kedapatan mengimpor pustaka pihak ketiga/infrastruktur terlarang:\n"
            + "\n".join(
                [
                    f"  - File: {f} (Baris: {line}) -> Mengimpor: {mod}"
                    for f, mod, line in violations
                ]
            )
        )

    def test_application_no_adapters_imports(self, boundary_checker):
        violations = boundary_checker.check()
        app_to_adapters = [
            v
            for v in violations
            if v.source_module.startswith("application") and v.target_module.startswith("adapters")
        ]
        assert len(app_to_adapters) == 0, (
            f"Pelanggaran Arsitektur! Layer Application tidak boleh bergantung pada konkrusi Adapters:\n"
            f"{self._format_violations(app_to_adapters)}"
        )

    def test_ports_no_implementation_imports(self, boundary_checker):
        violations = boundary_checker.check()
        ports_to_impl = [
            v
            for v in violations
            if v.source_module.startswith("ports")
            and any(
                v.target_module.startswith(p)
                for p in ["adapters", "infrastructure", "sqlalchemy", "kafka"]
            )
        ]
        assert len(ports_to_impl) == 0, (
            f"Abstraksi Gagal! Ports (Interface) mengimpor komponen implementasi konkret:\n"
            f"{self._format_violations(ports_to_impl)}"
        )

    def test_event_gateway_no_domain_imports(self, boundary_checker):
        violations = boundary_checker.check()
        gateway_to_domain = [
            v
            for v in violations
            if v.source_module.startswith(("event_gateway", "transformers"))
            and v.target_module.startswith("domain")
        ]
        assert len(gateway_to_domain) == 0, (
            f"Inversi Arah Terdeteksi! Komponen Gateway/Transformer dilarang keras mengandalkan core Domain:\n"
            f"{self._format_violations(gateway_to_domain)}"
        )

    def test_projections_no_aggregate_imports(self, project_root):
        projections_dir = project_root / "projections"
        projections_files = (
            list(projections_dir.glob("**/*.py")) if projections_dir.exists() else []
        )
        violations = []
        parse_errors = []
        for file_path in projections_files:
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
                parse_errors.append((file_path, str(e), traceback.format_exc()))
        if parse_errors:
            error_msg = "\n".join(
                [f"  - File: {f}\n    Error: {err}\n{tb}" for f, err, tb in parse_errors]
            )
            pytest.fail(f"Gagal memparsing file Projections selama analisis AST:\n{error_msg}")
        assert len(violations) == 0, (
            f"CQRS Violation! Projections (Read Model) mencoba mengimpor Domain Aggregates secara ilegal:\n"
            f"{self._format_violations(violations)}"
        )

    def test_shared_value_objects_no_internal_imports(self, project_root):
        svo_dir = project_root / "domain" / "shared_value_objects"
        svo_files = list(svo_dir.glob("**/*.py")) if svo_dir.exists() else []
        violations = []
        parse_errors = []
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
        for file_path in svo_files:
            try:
                with open(file_path, encoding="utf-8-sig", errors="replace") as f:
                    content = f.read()
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name.startswith(internal_packages):
                                if not alias.name.startswith("domain.shared_value_objects"):
                                    violations.append((file_path, alias.name, node.lineno))
                    elif isinstance(node, ast.ImportFrom):
                        if node.module and node.module.startswith(internal_packages):
                            if not node.module.startswith("domain.shared_value_objects"):
                                violations.append((file_path, node.module, node.lineno))
            except Exception as e:
                parse_errors.append((file_path, str(e), traceback.format_exc()))
        if parse_errors:
            error_msg = "\n".join(
                [f"  - File: {f}\n    Error: {err}\n{tb}" for f, err, tb in parse_errors]
            )
            pytest.fail(
                f"Gagal memparsing file Shared Value Objects selama analisis AST:\n{error_msg}"
            )
        assert len(violations) == 0, (
            "Shared Value Objects harus sepenuhnya terisolasi dan mandiri. Ditemukan ketergantungan internal:\n"
            + "\n".join(
                [
                    f"  - File: {f} (Baris: {line}) -> Mengimpor: {mod}"
                    for f, mod, line in violations
                ]
            )
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
    def from_dict(cls, data: dict[str, Any]) -> TestModuleIsolation:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._test_id = data.get("test_id", str(uuid4()))
        return instance

    def clone(self) -> TestModuleIsolation:
        new = TestModuleIsolation()
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

    def touch(self, touched_by: str) -> TestModuleIsolation:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self
