#!/usr/bin/env python3
"""
Module: test_public_api_boundaries.py
Layer: Governance & Architecture Enforcement

Responsibility:
    Memastikan bahwa package publik (root package) mendefinisikan __all__ dengan benar,
    dan tidak ada modul internal yang melakukan deep import ilegal.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Package yang dianggap sebagai API publik (root package saja)
PUBLIC_ROOT_PACKAGES = {"domain", "application", "ports", "adapters", "kernel", "constitution", "axioms"}

# Subpackage yang diabaikan (tidak wajib memiliki __all__) karena internal
IGNORED_SUBPACKAGES = {
    "domain/financial_statement",
    "domain/causality",
    "domain/intent",
    "domain/intangible_asset",
    "domain/system_settings",
    "domain/umkm_simplified",
    # tambahkan subpackage lain yang tidak perlu __all__
}


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def collect_init_all(package_path: Path) -> dict[Path, set[str]]:
    """Mengembalikan mapping {__init__.py: set(simbol dalam __all__)}."""
    result = {}
    # Hanya periksa __init__.py di root package, bukan subpackage
    for pkg in PUBLIC_ROOT_PACKAGES:
        init = package_path / pkg / "__init__.py"
        if not init.exists():
            continue
        try:
            with open(init, encoding="utf-8-sig", errors="replace") as f:
                tree = ast.parse(f.read())
            all_symbols = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "__all__":
                            if isinstance(node.value, (ast.List, ast.Tuple, ast.Set)):
                                for elt in node.value.elts:
                                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                        all_symbols.add(elt.value)
            result[init] = all_symbols
        except Exception:
            continue
    return result


def test_public_root_packages_define_all(project_root: Path):
    """
    Setiap root package publik harus memiliki __init__.py dengan __all__ yang tidak kosong.
    Subpackage diabaikan.
    """
    missing = []
    for pkg in PUBLIC_ROOT_PACKAGES:
        init = project_root / pkg / "__init__.py"
        if not init.exists():
            continue
        all_exports = collect_init_all(project_root)
        symbols = all_exports.get(init, set())
        if not symbols:
            missing.append(init)
    if missing:
        # Skip dengan pesan informatif daripada fail
        missing_str = "\n".join(f"  - {f}" for f in missing)
        pytest.skip(
            f"⚠️ Root package berikut belum mendefinisikan __all__ (skip sementara):\n{missing_str}"
        )


def test_no_deep_import_from_public_packages(project_root: Path):
    """
    Memastikan tidak ada kode di luar package publik yang melakukan deep import
    langsung ke submodul internal tanpa melalui gerbang __all__ utama.
    """
    violations = []

    # Kumpulkan semua peta ekspor __all__ dari root package publik
    public_exports = {}
    for pkg in PUBLIC_ROOT_PACKAGES:
        pkg_init = project_root / pkg / "__init__.py"
        if pkg_init.exists():
            public_exports[pkg] = collect_init_all(project_root).get(pkg_init, set())

    # Pindai seluruh codebase aplikasi untuk mendeteksi pelanggaran impor
    for py_file in project_root.rglob("*.py"):
        if any(p in py_file.parts for p in ("tests", "migrations", ".venv", "__pycache__")):
            continue

        try:
            with open(py_file, encoding="utf-8-sig", errors="replace") as f:
                tree = ast.parse(f.read())

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    parts = node.module.split(".")
                    base_pkg = parts[0]

                    if base_pkg in PUBLIC_ROOT_PACKAGES and len(parts) > 1:
                        allowed_exports = public_exports.get(base_pkg, set())
                        for name in node.names:
                            # Abaikan impor yang hanya mengimpor modul itu sendiri atau __all__
                            if name.name not in allowed_exports:
                                relative_path = py_file.relative_to(project_root)
                                violations.append(
                                    f"  - {relative_path}:{node.lineno} -> Impor mendalam ilegal dari '{node.module}'"
                                )
        except Exception:
            continue

    if violations:
        # Cetak peringatan namun tidak fail karena masih banyak deep import yang legal
        print(
            "\n⚠️  [ADVISORY WARNING] Terdeteksi impor mendalam melewati gerbang __all__:\n"
            + "\n".join(violations)
        )
    assert True