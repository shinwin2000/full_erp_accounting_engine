#!/usr/bin/env python3
"""
Module: boundary_checker.py
Layer: Governance & Architecture Enforcement

Responsibility:
    Memeriksa pelanggaran batas antar lapisan dengan menganalisis
    seluruh import statements dalam kode Python.
    Mendukung laporan JSON, HTML, dan integrasi CI.

Metode yang ditambahkan:
- Untuk ImportViolation: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk BoundaryChecker: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


# ============================================================================
# ImportViolation (dengan entity dasar)
# ============================================================================
class ImportViolation:
    """Merekam pelanggaran aturan impor."""

    def __init__(
        self,
        source_file: str,
        source_module: str,
        target_module: str,
        line_no: int,
        reason: str,
        source_layer: str = "",
        target_layer: str = "",
    ):
        self.source_file = source_file
        self.source_module = source_module
        self.target_module = target_module
        self.line_no = line_no
        self.reason = reason
        self.source_layer = source_layer
        self.target_layer = target_layer
        self.violation_id = hashlib.md5(
            f"{source_file}:{line_no}:{target_module}".encode()
        ).hexdigest()[:8]

        # Fields untuk audit dan versioning
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not self.source_file:
            raise ValueError("source_file is required")
        if not self.source_module:
            raise ValueError("source_module is required")
        if not self.target_module:
            raise ValueError("target_module is required")
        if self.line_no < 1:
            raise ValueError("line_no must be positive")
        if not self.reason:
            raise ValueError("reason is required")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "violation_id": self.violation_id,
                "source_file": self.source_file,
                "source_module": self.source_module,
                "target_module": self.target_module,
                "line_no": self.line_no,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "violation_id": self.violation_id,
                "details": details,
            }
        )

    @property
    def file_path(self) -> str:
        """Alias properti untuk kompatibilitas."""
        return self.source_file

    def __str__(self) -> str:
        return (
            f"{self.source_file}:{self.line_no}: {self.reason} "
            f"({self.source_module} -> {self.target_module})"
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict:
        return {
            "violation_id": self.violation_id,
            "source_file": self.source_file,
            "source_module": self.source_module,
            "source_layer": self.source_layer,
            "target_module": self.target_module,
            "target_layer": self.target_layer,
            "line_no": self.line_no,
            "reason": self.reason,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ImportViolation:
        instance = cls(
            source_file=data["source_file"],
            source_module=data["source_module"],
            target_module=data["target_module"],
            line_no=data["line_no"],
            reason=data["reason"],
            source_layer=data.get("source_layer", ""),
            target_layer=data.get("target_layer", ""),
        )
        instance.violation_id = data.get("violation_id", instance.violation_id)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> ImportViolation:
        new = ImportViolation(
            source_file=self.source_file,
            source_module=self.source_module,
            target_module=self.target_module,
            line_no=self.line_no,
            reason=self.reason,
            source_layer=self.source_layer,
            target_layer=self.target_layer,
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self.violation_id})
        return new

    def snapshot(self) -> dict:
        return {
            "version": self._version,
            "violation_id": self.violation_id,
            "source_file": self.source_file,
            "line_no": self.line_no,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ImportViolation:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# BoundaryChecker (dengan entity dasar)
# ============================================================================
class BoundaryChecker:
    """
    Pemeriksa batas arsitektur.
    Menemukan semua file Python, mem-parsing import, dan memvalidasi
    terhadap aturan dependensi lapisan.
    """

    def __init__(
        self,
        root_path: str,
        exclude_dirs: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ):
        self.root_path = Path(root_path).resolve()
        self.exclude_dirs = set(
            exclude_dirs
            or [
                "__pycache__",
                ".git",
                ".pytest_cache",
                ".mypy_cache",
                "venv",
                "env",
                ".venv",
                "migrations",
                "tests/fixtures",
                "build",
                "dist",
                "*.egg-info",
            ]
        )
        self.exclude_patterns = exclude_patterns or []
        self.violations: list[ImportViolation] = []
        self._stdlib_modules = self._get_stdlib_modules()

        self._internal_layers = {
            "domain",
            "application",
            "ports",
            "adapters",
            "infrastructure",
            "kernel",
            "foundation",
            "reports",
            "architecture",
        }

        # Fields untuk versioning dan audit
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._checker_id = str(uuid4())
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "checker_id": self._checker_id,
                "root_path": str(self.root_path),
                "violations_count": len(self.violations),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "checker_id": self._checker_id,
                "details": details,
            }
        )

    def _get_stdlib_modules(self) -> set[str]:
        stdlib = set(sys.builtin_module_names)
        stdlib.update(
            [
                "__future__",
                "abc",
                "argparse",
                "asyncio",
                "base64",
                "builtins",
                "collections",
                "contextlib",
                "copy",
                "crypt",
                "csv",
                "dataclasses",
                "datetime",
                "decimal",
                "enum",
                "functools",
                "hashlib",
                "hmac",
                "io",
                "itertools",
                "json",
                "logging",
                "math",
                "os",
                "pathlib",
                "pickle",
                "random",
                "re",
                "shutil",
                "signal",
                "sqlite3",
                "string",
                "sys",
                "tempfile",
                "threading",
                "time",
                "typing",
                "unittest",
                "uuid",
                "warnings",
                "weakref",
                "xml",
            ]
        )
        return stdlib

    def _should_exclude(self, path: Path) -> bool:
        for part in path.parts:
            if part in self.exclude_dirs:
                return True
        return any(pattern in str(path) for pattern in self.exclude_patterns)

    def _get_module_name(self, file_path: Path) -> str:
        rel_path = file_path.relative_to(self.root_path)
        module_str = str(rel_path.with_suffix("")).replace("\\", ".").replace("/", ".")
        return module_str

    def _is_stdlib_module(self, module_name: str) -> bool:
        base = module_name.split(".")[0]
        return base in self._stdlib_modules

    def _is_external_library(self, module_name: str) -> bool:
        base = module_name.split(".")[0].lower()
        return not self._is_stdlib_module(module_name) and base not in self._internal_layers

    def _parse_imports(self, file_path: Path) -> list[tuple[str, int]]:
        imports = []
        try:
            with open(file_path, encoding="utf-8-sig", errors="replace") as f:
                content = f.read()
            tree = ast.parse(content, filename=str(file_path))
        except Exception as e:
            error_msg = f"Gagal memproses analisis AST pada file: {file_path}\nPenyebab: {type(e).__name__} - {e}"
            if isinstance(e, SyntaxError):
                raise SyntaxError(error_msg) from e
            raise RuntimeError(error_msg) from e

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append((alias.name, node.lineno))
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append((node.module, node.lineno))
        return imports

    def _is_relative_import(self, module_name: str) -> bool:
        return module_name.startswith(".")

    def _resolve_relative_import(self, source_module: str, target_module: str) -> str:
        if target_module.startswith("."):
            parts = source_module.split(".")
            dots = len(target_module) - len(target_module.lstrip("."))
            base_parts = parts[:-dots] if dots > 0 else parts
            relative_part = target_module.lstrip(".")
            if relative_part:
                return ".".join([*base_parts, relative_part])
            else:
                return ".".join(base_parts)
        return target_module

    def check(self) -> list[ImportViolation]:
        from .layer_definitions import get_layer_for_module, is_allowed_import

        self.violations = []
        all_files = list(self.root_path.rglob("*.py"))

        for file_path in all_files:
            if self._should_exclude(file_path):
                continue
            if file_path.name == "__init__.py" and self._should_exclude(file_path.parent):
                continue

            source_module = self._get_module_name(file_path)
            source_layer_obj = get_layer_for_module(source_module)
            source_layer = source_layer_obj.name if source_layer_obj else "Unknown"

            if source_layer_obj is None:
                continue

            imports = self._parse_imports(file_path)
            for target_module_raw, line_no in imports:
                if self._is_relative_import(target_module_raw):
                    target_module = self._resolve_relative_import(source_module, target_module_raw)
                else:
                    target_module = target_module_raw

                if self._is_stdlib_module(target_module):
                    continue
                if self._is_external_library(target_module):
                    continue
                if target_module == source_module:
                    continue

                if not is_allowed_import(source_module, target_module):
                    target_layer_obj = get_layer_for_module(target_module)
                    target_layer = target_layer_obj.name if target_layer_obj else "Unknown"
                    reason = (
                        f"Layer '{source_layer}' cannot import from '{target_layer}'. "
                        f"Violates dependency rule (outer layers can depend on inner, not reverse)."
                    )
                    violation = ImportViolation(
                        source_file=str(file_path),
                        source_module=source_module,
                        target_module=target_module,
                        line_no=line_no,
                        reason=reason,
                        source_layer=source_layer,
                        target_layer=target_layer,
                    )
                    self.violations.append(violation)

        self._record_audit("CHECK", "system", {"violations": len(self.violations)})
        return self.violations

    def report(self) -> str:
        if not self.violations:
            return "✅ No architecture boundary violations found."

        lines = [f"❌ Found {len(self.violations)} architecture violation(s):"]
        by_file = defaultdict(list)
        for v in self.violations:
            by_file[v.source_file].append(v)
        for source_file, viols in sorted(by_file.items()):
            lines.append(f"\n📄 {source_file}")
            for v in viols:
                lines.append(f"    Line {v.line_no}: {v.target_module} - {v.reason}")
        return "\n".join(lines)

    def report_json(self) -> dict:
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "root_path": str(self.root_path),
            "total_violations": len(self.violations),
            "violations": [v.to_dict() for v in self.violations],
            "version": self._version,
        }

    def report_html(self, output_file: Path | None = None) -> str:
        html = f"""<!DOCTYPE html>
<html>
<head><title>Architecture Boundary Report</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 20px; }}
.violation {{ background: #ffeeee; border-left: 4px solid red; margin: 10px 0; padding: 10px; }}
.summary {{ background: #eef; padding: 10px; border-radius: 5px; }}
pre {{ white-space: pre-wrap; }}
</style>
</head>
<body>
<h1>Architecture Boundary Check Report</h1>
<div class="summary">
    <strong>Root:</strong> {self.root_path}<br>
    <strong>Timestamp:</strong> {datetime.now(UTC).isoformat()}<br>
    <strong>Total Violations:</strong> {len(self.violations)}
</div>
<h2>Violations</h2>
"""
        for v in self.violations:
            html += f"""
<div class="violation">
    <strong>{v.source_file}:{v.line_no}</strong><br>
    <code>{v.source_module} → {v.target_module}</code><br>
    {v.reason}
</div>
"""
        html += "</body></html>"
        if output_file:
            output_file.write_text(html, encoding="utf-8")
        return html

    def get_statistics(self) -> dict:
        from .layer_definitions import LAYER_DEFINITIONS

        layer_stats = {ld.layer.name: {"files": 0, "violations": 0} for ld in LAYER_DEFINITIONS}
        layer_stats["Unknown"] = {"files": 0, "violations": 0}

        all_files = list(self.root_path.rglob("*.py"))
        for file_path in all_files:
            if self._should_exclude(file_path):
                continue
            module = self._get_module_name(file_path)
            from .layer_definitions import get_layer_for_module

            layer = get_layer_for_module(module)
            layer_name = layer.name if layer else "Unknown"
            if layer_name not in layer_stats:
                layer_stats[layer_name] = {"files": 0, "violations": 0}
            layer_stats[layer_name]["files"] += 1

        for v in self.violations:
            layer_name = v.source_layer if v.source_layer else "Unknown"
            if layer_name in layer_stats:
                layer_stats[layer_name]["violations"] += 1
            else:
                layer_stats[layer_name] = {"files": 0, "violations": 1}

        return {
            "total_files": len(all_files),
            "total_violations": len(self.violations),
            "by_layer": layer_stats,
            "version": self._version,
        }

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.root_path.exists():
            errors.append(f"Root path {self.root_path} does not exist")
        if self._version < 1:
            errors.append("Version must be >= 1")
        for v in self.violations:
            res = v.validate()
            if not res["is_valid"]:
                errors.extend([f"Violation {v.violation_id}: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "checker_id": self._checker_id,
            "root_path": str(self.root_path),
            "exclude_dirs": list(self.exclude_dirs),
            "exclude_patterns": self.exclude_patterns,
            "total_violations": len(self.violations),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BoundaryChecker:
        instance = cls(
            root_path=data["root_path"],
            exclude_dirs=data.get("exclude_dirs"),
            exclude_patterns=data.get("exclude_patterns"),
        )
        instance._version = data.get("version", 1)
        instance._checker_id = data.get("checker_id", str(uuid4()))
        return instance

    def clone(self) -> BoundaryChecker:
        new = BoundaryChecker(
            root_path=str(self.root_path),
            exclude_dirs=list(self.exclude_dirs),
            exclude_patterns=self.exclude_patterns.copy(),
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._checker_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "checker_id": self._checker_id,
            "root_path": str(self.root_path),
            "violations_count": len(self.violations),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> BoundaryChecker:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        """Reset checker state (untuk testing)."""
        self.violations = []
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._checker_id = str(uuid4())
        self._record_audit("RESET", "system", {})


# ============================================================================
# Convenience Functions
# ============================================================================
def check_all_boundaries(root_path: str = ".", verbose: bool = True) -> bool:
    checker = BoundaryChecker(root_path)
    violations = checker.check()
    if verbose:
        print(checker.report())
    return len(violations) == 0


def get_architecture_report(root_path: str = ".", format: str = "json") -> Any:
    checker = BoundaryChecker(root_path)
    checker.check()
    if format == "json":
        return checker.report_json()
    elif format == "html":
        return checker.report_html()
    else:
        return checker.report()


# ============================================================================
# Main CLI (dipertahankan)
# ============================================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Check architecture boundaries")
    parser.add_argument("--root", default=".", help="Root directory")
    parser.add_argument("--format", choices=["text", "json", "html"], default="text")
    parser.add_argument("--output", help="Output file")
    args = parser.parse_args()

    checker = BoundaryChecker(args.root)
    violations = checker.check()

    if args.format == "json":
        report = checker.report_json()
        output = json.dumps(report, indent=2)
    elif args.format == "html":
        output = checker.report_html()
    else:
        output = checker.report()

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output)

    sys.exit(0 if len(violations) == 0 else 1)

# ============================================================================
# EKSPOR
# ============================================================================
__all__ = [
    "BoundaryChecker",
    "ImportViolation",
    "check_all_boundaries",
    "get_architecture_report",
]
