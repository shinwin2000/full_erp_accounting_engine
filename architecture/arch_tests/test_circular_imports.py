#!/usr/bin/env python3
"""
Module: test_circular_imports.py
Layer: Governance & Architecture Enforcement

Responsibility:
    Mendeteksi dependensi melingkar (circular imports) antar modul dalam proyek.
    Menggunakan analisis AST (Abstract Syntax Tree) statis.

Metode yang ditambahkan:
- Untuk kelas TestCircularImports: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import ast
import datetime  # <-- STATIC import untuk datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

try:
    from importlinter import Contract, ForbiddenContractError

    HAS_IMPORT_LINTER = True
except ImportError:
    HAS_IMPORT_LINTER = False


# ============================================================================
# Helper Functions (dipertahankan)
# ============================================================================
def find_all_python_modules(root_dir: Path) -> dict[str, Path]:
    IGNORED_FILENAMES = {
        "asgi.py",
        "wsgi.py",
        "manage.py",
        "settings.py",
        "urls.py",
        "celery.py",
        "__init__.py",
        "main.py",
        "app.py",
        "app_main.py",
    }
    module_mapping: dict[str, Path] = {}
    for py_file in root_dir.rglob("*.py"):
        if py_file.name in IGNORED_FILENAMES:
            continue
        rel_path = py_file.relative_to(root_dir)
        if any(
            part.startswith(".")
            or part
            in (
                "__pycache__",
                "venv",
                "env",
                ".venv",
                "build",
                "dist",
                "migrations",
                "static",
                "media",
                "templates",
            )
            for part in rel_path.parts
        ):
            continue
        module_name = str(rel_path.with_suffix("")).replace("/", ".").replace("\\", ".")
        module_mapping[module_name] = py_file
    return module_mapping


def resolve_relative_import(current_module: str, relative_to: str, level: int) -> str:
    parts = current_module.split(".")
    if level > 0:
        slice_back = level
        if slice_back > len(parts):
            raise ValueError(
                f"Level impor relatif ({level}) melebihi kedalaman modul saat ini '{current_module}'"
            )
        base_parts = parts[:-slice_back]
    else:
        base_parts = []
    if relative_to:
        if level > 0:
            base_parts.extend(relative_to.split("."))
        else:
            return relative_to
    return ".".join(base_parts)


def read_file_with_fallback_encoding(file_path: Path) -> str:
    encodings = ["utf-8", "latin-1", "cp1252"]
    for enc in encodings:
        try:
            with open(file_path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with open(file_path, "rb") as f:
        raw = f.read()
        return raw.decode("utf-8", errors="ignore")


def build_import_graph(module_mapping: dict[str, Path], root_dir: Path) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {mod: set() for mod in module_mapping}
    for module_name, file_path in module_mapping.items():
        content = read_file_with_fallback_encoding(file_path)
        try:
            tree = ast.parse(content, filename=str(file_path))
        except SyntaxError as e:
            raise SyntaxError(
                f"Gagal memproses AST pada file: {file_path}\nPenyebab: {e.msg} di baris {e.lineno}"
            ) from e
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_name = alias.name
                    if imported_name == module_name:
                        continue
                    for target_mod in module_mapping:
                        if imported_name == target_mod or imported_name.startswith(
                            target_mod + "."
                        ):
                            if target_mod != module_name:
                                graph[module_name].add(target_mod)
            elif isinstance(node, ast.ImportFrom):
                level = node.level
                base_mod = node.module if node.module else ""
                try:
                    resolved_base = resolve_relative_import(module_name, base_mod, level)
                except ValueError as e:
                    raise ValueError(f"Error resolusi impor di {file_path}: {e}") from e
                if not resolved_base:
                    continue
                if resolved_base == module_name:
                    continue
                for target_mod in module_mapping:
                    if resolved_base == target_mod or resolved_base.startswith(target_mod + "."):
                        if target_mod != module_name:
                            graph[module_name].add(target_mod)
                for alias in node.names:
                    if alias.name:
                        full_imported_path = f"{resolved_base}.{alias.name}"
                        if full_imported_path == module_name:
                            continue
                        for target_mod in module_mapping:
                            if full_imported_path == target_mod or full_imported_path.startswith(
                                target_mod + "."
                            ):
                                if target_mod != module_name:
                                    graph[module_name].add(target_mod)
    return graph


def detect_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    visited_state: dict[str, int] = dict.fromkeys(graph, 0)
    cycles: list[list[str]] = []

    def dfs(node: str, path: list[str]) -> None:
        visited_state[node] = 1
        path.append(node)
        for neighbor in sorted(graph.get(node, set())):
            if visited_state.get(neighbor, 0) == 0:
                dfs(neighbor, path)
            elif visited_state.get(neighbor, 0) == 1:
                if neighbor in path:
                    start_idx = path.index(neighbor)
                    cycle_path = [*path[start_idx:], neighbor]
                    if cycle_path not in cycles:
                        cycles.append(cycle_path)
        path.pop()
        visited_state[node] = 2

    for node in sorted(graph.keys()):
        if visited_state[node] == 0:
            dfs(node, [])
    return cycles


# ============================================================================
# TestCircularImports (dengan entity dasar)
# ============================================================================
class TestCircularImports:
    """Test suite untuk mendeteksi circular imports."""

    _version: int = 1
    _audit_trail: list[dict[str, Any]] = []
    _snapshots: list[dict[str, Any]] = []
    _test_id: str = str(uuid4())

    def __init__(self):
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "test_id": self._test_id,
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),  # <-- perbaiki
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),  # <-- perbaiki
                "version": self._version,
                "test_id": self._test_id,
                "details": details,
            }
        )

    # ==================== TEST METHODS (asli, dipertahankan) ====================
    @pytest.mark.skipif(not HAS_IMPORT_LINTER, reason="import-linter tidak terinstall")
    def test_no_circular_imports_with_importlinter(self):
        assert HAS_IMPORT_LINTER is True

    def test_no_circular_imports_manual(self, project_root: Path):
        all_modules = find_all_python_modules(project_root)
        target_prefixes = (
            "domain",
            "application",
            "ports",
            "adapters",
            "kernel",
            "infrastructure",
            "constitution",
            "audit",
        )
        core_modules = {
            name: path for name, path in all_modules.items() if name.startswith(target_prefixes)
        }
        graph = build_import_graph(core_modules, project_root)
        cycles = detect_cycles(graph)
        if cycles:
            cycle_lines = []
            for idx, cycle in enumerate(cycles, 1):
                cycle_lines.append(f"  [Siklus {idx}]: {' ──> '.join(cycle)}")
            pytest.fail(
                f"DIAGNOSIS ARSITEKTUR GAGAL: Terdeteksi {len(cycles)} Circular Import Riil!\n"
                + "\n".join(cycle_lines)
            )
        assert len(cycles) == 0

    def test_no_self_import(self, project_root: Path):
        all_modules = find_all_python_modules(project_root)
        for mod_name, file_path in all_modules.items():
            if "." not in mod_name:
                continue
            content = read_file_with_fallback_encoding(file_path)
            try:
                tree = ast.parse(content, filename=str(file_path))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == mod_name or alias.name.startswith(mod_name + "."):
                            pytest.fail(
                                f"PELANGGARAN MANDIRI: Modul '{mod_name}' mengimpor dirinya sendiri!\nLokasi File: {file_path}"
                            )
                elif isinstance(node, ast.ImportFrom):
                    level = node.level
                    base_mod = node.module if node.module else ""
                    try:
                        resolved_base = resolve_relative_import(mod_name, base_mod, level)
                    except ValueError:
                        continue
                    if resolved_base and (
                        resolved_base == mod_name or resolved_base.startswith(mod_name + ".")
                    ):
                        pytest.fail(
                            f"PELANGGARAN MANDIRI: Modul '{mod_name}' melakukan 'ImportFrom' dari dirinya sendiri!\nLokasi File: {file_path}"
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
            "snapshots_count": len(self._snapshots),
            "audit_trail_count": len(self._audit_trail),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestCircularImports:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._test_id = data.get("test_id", str(uuid4()))
        return instance

    def clone(self) -> TestCircularImports:
        new = TestCircularImports()
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._test_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "test_id": self._test_id,
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),  # <-- perbaiki
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> TestCircularImports:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self
