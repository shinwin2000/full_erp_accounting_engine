#!/usr/bin/env python3
"""
Module: test_no_dynamic_imports.py
Layer: Governance & Architecture Enforcement

Responsibility:
    Melarang penggunaan dynamic import (`__import__()`, `importlib.import_module()`)
    di kode produksi karena menyulitkan analisis statis dan dapat menyebabkan circular import runtime.
    Pengecualian hanya diperbolehkan pada modul plugin/loader yang sudah ditandai.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Pengecualian: file yang boleh menggunakan dynamic import (lazy loader, tool, dll.)
ALLOWED_DYNAMIC_IMPORT_FILES = {
    "architecture/plugin_loader.py",
    "kernel/dynamic_loader.py",
    "main_checker.py",  # utility tool, bukan production code
    "main_checker_2.py",
    "domain/intent/__init__.py",  # membutuhkan dynamic import untuk menghindari circular
    "kernel/guards/async_guards/__init__.py",  # lazy loader pattern untuk async guards
    "infrastructure/persistence_orm/__init__.py",  # _safe_import untuk menghindari circular import
}


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def find_production_files(root: Path) -> list[Path]:
    """Semua file .py di luar tests, migrations, dll."""
    excluded = {"__pycache__", "tests", "migrations", "venv", ".venv", "build", "dist"}
    files = []
    for py in root.rglob("*.py"):
        rel = py.relative_to(root)
        if any(part in excluded for part in rel.parts):
            continue
        files.append(py)
    return files


def detect_dynamic_imports(file_path: Path) -> list[tuple[int, str]]:
    violations = []
    try:
        with open(file_path, encoding="utf-8-sig", errors="replace") as f:
            tree = ast.parse(f.read(), filename=str(file_path))
    except SyntaxError:
        return violations
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "__import__":
                violations.append((node.lineno, "__import__()"))
            elif isinstance(func, ast.Attribute) and (
                isinstance(func.value, ast.Name)
                and func.value.id == "importlib"
                and func.attr == "import_module"
            ):
                violations.append((node.lineno, "importlib.import_module()"))
    return violations


def test_no_dynamic_imports_in_production(project_root: Path):
    all_files = find_production_files(project_root)
    violations = []
    for f in all_files:
        rel_path = str(f.relative_to(project_root)).replace("\\", "/")
        if rel_path in ALLOWED_DYNAMIC_IMPORT_FILES:
            continue
        for line, typ in detect_dynamic_imports(f):
            violations.append((f, line, typ))
    if violations:
        lines = ["🚨 DYNAMIC IMPORT DITEMUKAN (dilarang di kode produksi):"]
        for f, line, typ in violations:
            lines.append(f"  - {f}:{line} → {typ}")
        lines.append(
            "\nGunakan import statis biasa. Jika memang diperlukan, tambahkan file ke ALLOWED_DYNAMIC_IMPORT_FILES."
        )
        pytest.fail("\n".join(lines))
