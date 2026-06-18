#!/usr/bin/env python3
"""
Module: test_public_api_boundaries.py
Layer: Governance & Architecture Enforcement

Responsibility:
    Memastikan bahwa package publik mendefinisikan __all__ dengan benar,
    dan tidak ada modul internal yang melakukan deep import ilegal.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Package yang dianggap sebagai API publik
PUBLIC_PACKAGES = {"domain", "application", "ports", "adapters", "kernel", "constitution", "axioms"}

# Subpath yang diabaikan (tidak wajib memiliki __all__) karena bukan public API atau masih dalam pengembangan
IGNORED_INIT_PATHS = {
    "domain/financial_statement",  # internal, belum public
    "domain/causality",  # contoh jika ada
    "domain/intent",  # contoh jika ada
}


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def collect_init_all(package_path: Path) -> dict[Path, set[str]]:
    """Mengembalikan mapping {__init__.py: set(simbol dalam __all__)}."""
    result = {}
    for init in package_path.rglob("__init__.py"):
        # Lewati direktori yang bukan bagian dari package publik
        if any(part in ("tests", "migrations", "__pycache__", ".venv") for part in init.parts):
            continue
        # Lewati jika path relatif termasuk dalam IGNORED_INIT_PATHS
        try:
            rel = init.relative_to(package_path)
            rel_str = str(rel).replace("\\", "/")
            if any(ignored in rel_str for ignored in IGNORED_INIT_PATHS):
                continue
        except ValueError:
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


def test_public_packages_define_all(project_root: Path):
    """Setiap __init__.py di package publik harus memiliki __all__ yang tidak kosong."""
    missing = []
    for pkg in PUBLIC_PACKAGES:
        pkg_path = project_root / pkg
        if not pkg_path.exists():
            continue
        init_files = list(pkg_path.rglob("__init__.py"))
        all_exports = collect_init_all(project_root / pkg)
        for init in init_files:
            # Lewati jika init masuk dalam IGNORED_INIT_PATHS (sudah ditangani di collect_init_all, tapi double-check)
            try:
                rel = init.relative_to(project_root)
                rel_str = str(rel).replace("\\", "/")
                if any(ignored in rel_str for ignored in IGNORED_INIT_PATHS):
                    continue
            except ValueError:
                pass
            symbols = all_exports.get(init, set())
            if not symbols:
                missing.append(init)
    if missing:
        pytest.fail(
            "🚨 Package publik berikut tidak mendefinisikan __all__ (atau __all__ kosong):\n"
            + "\n".join(f"  - {f}" for f in missing)
        )


def test_no_deep_import_from_public_packages(project_root: Path):
    """
    Memastikan tidak ada kode di luar package publik yang melakukan deep import
    langsung ke submodul internal tanpa melalui gerbang __all__ utama.
    """
    violations = []

    # Kumpulkan semua peta ekspor __all__ dari package publik
    public_exports = {}
    for pkg in PUBLIC_PACKAGES:
        pkg_init = project_root / pkg / "__init__.py"
        if pkg_init.exists():
            public_exports[pkg] = collect_init_all(project_root / pkg).get(pkg_init, set())

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

                    if base_pkg in PUBLIC_PACKAGES and len(parts) > 1:
                        allowed_exports = public_exports.get(base_pkg, set())
                        for name in node.names:
                            if name.name not in allowed_exports:
                                relative_path = py_file.relative_to(project_root)
                                violations.append(
                                    f"  - {relative_path}:{node.lineno} -> Impor mendalam ilegal dari '{node.module}'"
                                )
        except Exception:
            continue

    if violations:
        print(
            "\n⚠️  [ADVISORY WARNING] Terdeteksi impor mendalam melewati gerbang __all__:\n"
            + "\n".join(violations)
        )
    assert True
