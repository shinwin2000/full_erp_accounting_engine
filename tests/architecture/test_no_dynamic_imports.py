#!/usr/bin/env python3
"""
Module: test_no_dynamic_imports.py
Layer: Governance & Architecture Enforcement

Responsibility:
    Melarang penggunaan dynamic import (`__import__()`, `importlib.import_module()`)
    di kode produksi lapisan kritis (application, ports) karena menyulitkan analisis statis.
    Lapisan lain (adapters, infrastructure, domain, dll.) dikecualikan karena sering digunakan
    untuk plugin, lazy loading, atau menghindari circular import.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Pengecualian: file di application/ports yang boleh menggunakan dynamic import
ALLOWED_DYNAMIC_IMPORT_FILES = {
    "application/events/__init__.py",  # menggunakan __import__ untuk registrasi event dinamis
}


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def find_critical_files(root: Path) -> list[Path]:
    """
    Hanya file .py di bawah application/ dan ports/ (lapisan kritis).
    Mengabaikan tests, migrations, dll.
    """
    excluded = {"__pycache__", "tests", "migrations", "venv", ".venv", "build", "dist"}
    files = []
    for py in root.rglob("*.py"):
        rel = py.relative_to(root)
        parts = rel.parts
        if any(part in excluded for part in parts):
            continue
        # Hanya ambil jika berada di application/ atau ports/
        if not (parts[0] == "application" or parts[0] == "ports"):
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


def test_no_dynamic_imports_in_critical_layers(project_root: Path):
    all_files = find_critical_files(project_root)
    violations = []
    for f in all_files:
        rel_path = str(f.relative_to(project_root)).replace("\\", "/")
        if rel_path in ALLOWED_DYNAMIC_IMPORT_FILES:
            continue
        for line, typ in detect_dynamic_imports(f):
            violations.append((f, line, typ))
    if violations:
        lines = ["🚨 DYNAMIC IMPORT DITEMUKAN di lapisan application/ports:"]
        for f, line, typ in violations:
            lines.append(f"  - {f}:{line} → {typ}")
        lines.append(
            "\nGunakan import statis biasa. Jika memang diperlukan, tambahkan file ke ALLOWED_DYNAMIC_IMPORT_FILES."
        )
        pytest.fail("\n".join(lines))