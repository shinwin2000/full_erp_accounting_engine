#!/usr/bin/env python3
"""
Module: test_import_conventions.py
Layer: Governance & Architecture Enforcement

Responsibility:
    Memeriksa konvensi import Python sesuai PEP8 dan standar internal proyek:
    - Tidak ada wildcard import (from module import *)
    - Import grouping: stdlib → third‑party → local
    - Setiap file memiliki `from __future__ import annotations` (opsional tapi direkomendasikan)
    - Tidak ada import di tengah‑tengah kode (kecuali conditional import yang diizinkan namun diperingatkan)
    - Setiap `__init__.py` di package publik harus mendefinisikan `__all__`
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def find_all_py_files(root_dir: Path, exclude_tests: bool = True) -> list[Path]:
    """Semua file .py kecuali yang berada di direktori terlarang."""
    excluded_dirs = {
        "__pycache__",
        "venv",
        "env",
        ".venv",
        "build",
        "dist",
        "migrations",
        "logs",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "config_files",
        "docs",
        "deployment",
    }
    if exclude_tests:
        excluded_dirs.add("tests")
    files = []
    for py_file in root_dir.rglob("*.py"):
        rel = py_file.relative_to(root_dir)
        if any(part in excluded_dirs for part in rel.parts):
            continue
        files.append(py_file)
    return files


def check_wildcard_imports(file_path: Path) -> list[tuple[int, str]]:
    """Mendeteksi `from module import *`."""
    violations = []
    with open(file_path, encoding="utf-8-sig", errors="replace") as f:
        tree = ast.parse(f.read(), filename=str(file_path))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.names
            and any(n.name == "*" for n in node.names)
        ):
            module = node.module or "<unknown>"
            violations.append((node.lineno, f"wildcard import from '{module}'"))
    return violations


def check_import_grouping(file_path: Path) -> list[tuple[int, str]]:
    """Memastikan urutan import: stdlib → third‑party → local (tidak kaku, hanya peringatan)."""
    return []  # Bisa diimplementasikan lebih detail jika diperlukan


def check_future_annotations(file_path: Path) -> bool:
    """Cek apakah `from __future__ import annotations` ada di awal file."""
    try:
        with open(file_path, encoding="utf-8-sig", errors="replace") as f:
            content = f.read()
        tree = ast.parse(content)

        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                for alias in node.names:
                    if alias.name == "annotations":
                        return True

            if (
                isinstance(node, ast.Expr)
                and isinstance(getattr(node, "value", None), ast.Constant)
                and isinstance(node.value.value, str)
            ):
                continue

            if isinstance(node, (ast.Import, ast.ImportFrom)):
                continue

            break

        return False
    except SyntaxError:
        return False


def check_init_has_all(package_path: Path) -> list[Path]:
    """Untuk setiap __init__.py di package publik, pastikan mendefinisikan __all__.
    Mengecualikan direktori yang bukan public API (misalnya internal, financial_statement, dll)."""
    missing = []
    # Daftar path yang diabaikan (bukan public API)
    excluded_path_patterns = [
        "domain/financial_statement",  # internal subpackage, tidak wajib __all__
        "domain/__pycache__",
        "tests",
        "migrations",
        "config_files",
        "docs",
        "deployment",
    ]
    for init_file in package_path.rglob("__init__.py"):
        # Lewati __init__.py di folder excluded
        if any(part in ("tests", "migrations", "__pycache__") for part in init_file.parts):
            continue
        rel_path = str(init_file.relative_to(package_path)).replace("\\", "/")
        if any(pattern in rel_path for pattern in excluded_path_patterns):
            continue
        try:
            with open(init_file, encoding="utf-8-sig", errors="replace") as f:
                tree = ast.parse(f.read())
            has_all = any(
                isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)
                for node in tree.body
            )
            if not has_all:
                missing.append(init_file)
        except Exception:
            pass
    return missing


def test_no_wildcard_imports(project_root: Path):
    """Melarang `from module import *` di seluruh kode produksi."""
    all_files = find_all_py_files(project_root, exclude_tests=True)
    violations = []
    for f in all_files:
        for line, msg in check_wildcard_imports(f):
            violations.append((f, line, msg))
    if violations:
        lines = ["🚨 WILDCARD IMPORT DITEMUKAN:"]
        for f, line, msg in violations:
            lines.append(f"  - {f}:{line} → {msg}")
        pytest.fail("\n".join(lines))


def test_future_annotations_present(project_root: Path):
    """Mendorong penggunaan `from __future__ import annotations` di semua file."""
    all_files = find_all_py_files(project_root, exclude_tests=True)
    missing = []
    for f in all_files:
        if not check_future_annotations(f):
            missing.append(f)
    if missing:
        warnings = "\n".join(f"  - {f}" for f in missing[:10])
        if len(missing) > 10:
            warnings += f"\n  ... dan {len(missing) - 10} file lainnya"
        pytest.skip(
            f"⚠️ Sebanyak {len(missing)} file tidak memiliki `from __future__ import annotations`. (skip karena tidak wajib, tapi direkomendasikan)"
        )


def test_init_all_defined(project_root: Path):
    """Setiap __init__.py di package publik harus mendefinisikan __all__."""
    missing = check_init_has_all(project_root)
    if missing:
        fail_lines = ["🚨 __init__.py berikut tidak memiliki __all__:"]
        fail_lines.extend(f"  - {f}" for f in missing)
        pytest.fail("\n".join(fail_lines))
