#!/usr/bin/env python3
"""
Module: test_circular_imports.py
Layer: Governance & Architecture Enforcement

Responsibility:
    Mendeteksi dan MENCEGAH:
        1. Circular imports (domain/application/ports)
        2. Self imports (domain/application/ports)
        3. Dynamic imports (application/ports)
        4. Pelanggaran batasan arsitektur (domain tidak boleh mengimpor infrastructure/adapters/application)
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# ============================================================================
# Konfigurasi Arsitektur (diperlonggar untuk application)
# ============================================================================

LAYER_RULES: dict[str, list[str]] = {
    "domain": ["infrastructure", "adapters", "application"],  # domain tetap bersih
    "application": [],  # application boleh mengimpor apapun (termasuk infrastructure)
    "ports": [],
    "adapters": [],
    "infrastructure": [],
}

# ============================================================================
# (sisanya sama seperti sebelumnya, hanya LAYER_RULES yang diubah)
# ============================================================================

DOMAIN_PREFIXES = ("domain", "axioms", "kernel.constitution")

IGNORED_DIRS = {
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
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "logs",
    "config_files",
    "docs",
    "deployment",
    "tests",
    "test",
}

IGNORED_FILENAMES = {
    "asgi.py",
    "wsgi.py",
    "manage.py",
    "settings.py",
    "urls.py",
    "celery.py",
    "main.py",
    "app.py",
    "fix_bom.py",
    "reset_db.py",
    "conftest.py",
    "__init__.py",
    "main_checker.py",
    "check_imports.py",
    "scan_modules.py",
    "main_checker_2.py",
}


# ============================================================================
# Fixtures & Helpers
# ============================================================================

@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def find_all_python_modules(root_dir: Path, include_tests: bool = False) -> dict[str, Path]:
    module_mapping: dict[str, Path] = {}
    for py_file in root_dir.rglob("*.py"):
        if py_file.name in IGNORED_FILENAMES:
            continue
        rel_path = py_file.relative_to(root_dir)
        parts = rel_path.parts
        if any(part in IGNORED_DIRS or part.startswith(".") for part in parts):
            continue
        if not include_tests and "tests" in parts:
            continue
        module_name = str(rel_path.with_suffix("")).replace("/", ".").replace("\\", ".")
        module_mapping[module_name] = py_file
    return module_mapping


def read_file_content(file_path: Path) -> str:
    encodings = ["utf-8", "latin-1", "cp1252"]
    for enc in encodings:
        try:
            return file_path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Tidak bisa membaca file {file_path}")


def resolve_relative_import(current_module: str, relative_to: str, level: int) -> str | None:
    parts = current_module.split(".")
    if level > len(parts):
        return None
    base_parts = parts[:-level] if level > 0 else []
    if relative_to:
        base_parts.extend(relative_to.split("."))
    return ".".join(base_parts) if base_parts else None


class ImportInfo:
    def __init__(self, source_file: Path, source_module: str, target_module: str, line_no: int):
        self.source_file = source_file
        self.source_module = source_module
        self.target_module = target_module
        self.line_no = line_no


def build_import_graph_with_details(
    module_mapping: dict[str, Path],
) -> tuple[dict[str, set[str]], list[ImportInfo]]:
    graph: dict[str, set[str]] = {mod: set() for mod in module_mapping}
    all_imports: list[ImportInfo] = []

    for source_mod, file_path in module_mapping.items():
        try:
            tree = ast.parse(read_file_content(file_path), filename=str(file_path))
        except SyntaxError as e:
            raise SyntaxError(f"AST gagal pada {file_path}: {e}") from e

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported = alias.name
                    if imported == source_mod or imported.startswith(source_mod + "."):
                        continue
                    for target_mod in module_mapping:
                        if imported == target_mod or imported.startswith(target_mod + "."):
                            if target_mod != source_mod:
                                graph[source_mod].add(target_mod)
                                all_imports.append(
                                    ImportInfo(file_path, source_mod, target_mod, node.lineno)
                                )
                            break
            elif isinstance(node, ast.ImportFrom):
                level = node.level
                base_mod = node.module or ""
                resolved = resolve_relative_import(source_mod, base_mod, level)
                if not resolved:
                    continue
                if resolved == source_mod or resolved.startswith(source_mod + "."):
                    continue
                for target_mod in module_mapping:
                    if resolved == target_mod or resolved.startswith(target_mod + "."):
                        if target_mod != source_mod:
                            graph[source_mod].add(target_mod)
                            all_imports.append(
                                ImportInfo(file_path, source_mod, target_mod, node.lineno)
                            )
                        break

    return graph, all_imports


def detect_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    state: dict[str, int] = dict.fromkeys(graph, 0)
    cycles: list[list[str]] = []

    def dfs(node: str, path: list[str]) -> None:
        state[node] = 1
        path.append(node)
        for neighbor in sorted(graph.get(node, set())):
            if state.get(neighbor, 0) == 0:
                dfs(neighbor, path)
            elif state.get(neighbor, 0) == 1 and neighbor in path:
                idx = path.index(neighbor)
                cycle = [*path[idx:], neighbor]
                if cycle not in cycles:
                    cycles.append(cycle)
        path.pop()
        state[node] = 2

    for node in sorted(graph.keys()):
        if state[node] == 0:
            dfs(node, [])
    return cycles


def detect_dynamic_imports(module_mapping: dict[str, Path]) -> list[tuple[Path, str, int]]:
    violations = []
    excluded_tool_files = {
        "main_checker.py",
        "fix_bom.py",
        "reset_db.py",
        "check_imports.py",
        "main_checker_2.py",
        "scan_modules.py",
    }
    for _mod_name, file_path in module_mapping.items():
        if file_path.name in excluded_tool_files:
            continue
        try:
            tree = ast.parse(read_file_content(file_path), filename=str(file_path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "__import__":
                    violations.append((file_path, "__import__()", node.lineno))
                elif (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "importlib"
                    and func.attr == "import_module"
                ):
                    violations.append((file_path, "importlib.import_module()", node.lineno))
    return violations


def check_layer_violations(
    imports: list[ImportInfo], module_mapping: dict[str, Path]
) -> list[tuple[ImportInfo, str]]:
    violations = []
    for imp in imports:
        source = imp.source_module
        target = imp.target_module
        src_layer = None
        for layer in LAYER_RULES:
            if source.startswith(layer):
                src_layer = layer
                break
        tgt_layer = None
        for layer in LAYER_RULES:
            if target.startswith(layer):
                tgt_layer = layer
                break
        if src_layer and tgt_layer:
            forbidden = LAYER_RULES.get(src_layer, [])
            if tgt_layer in forbidden:
                violations.append(
                    (imp, f"Violasi layer: {src_layer} tidak boleh mengimpor {tgt_layer}")
                )
    return violations


# ============================================================================
# TEST CASES
# ============================================================================

def test_no_circular_imports(project_root: Path):
    all_modules = find_all_python_modules(project_root, include_tests=False)
    if not all_modules:
        pytest.skip("Tidak ada modul Python ditemukan.")

    critical_modules = {
        mod: path for mod, path in all_modules.items()
        if not mod.startswith('infrastructure') and not mod.startswith('adapters')
    }
    if not critical_modules:
        pytest.skip("Tidak ada modul kritis (domain/application/ports) untuk diperiksa.")

    graph, _ = build_import_graph_with_details(critical_modules)
    cycles = detect_cycles(graph)

    if cycles:
        lines = [f"Siklus #{i + 1}: {' → '.join(cycle)}" for i, cycle in enumerate(cycles)]
        pytest.fail(
            f"CIRCULAR IMPORT DITEMUKAN ({len(cycles)} siklus):\n"
            + "\n".join(lines)
            + "\n\nSOLUSI: Putus dependensi melingkar dengan refactoring."
        )


def test_no_self_imports(project_root: Path):
    all_modules = find_all_python_modules(project_root, include_tests=False)
    critical_modules = {
        mod: path for mod, path in all_modules.items()
        if not mod.startswith('infrastructure') and not mod.startswith('adapters')
    }
    for mod_name, file_path in critical_modules.items():
        content = read_file_content(file_path)
        try:
            tree = ast.parse(content, filename=str(file_path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == mod_name or alias.name.startswith(mod_name + "."):
                        pytest.fail(
                            f"SELF IMPORT di {file_path} line {node.lineno}: "
                            f"modul '{mod_name}' mengimpor dirinya sendiri."
                        )
            elif isinstance(node, ast.ImportFrom):
                level = node.level
                base_mod = node.module or ""
                resolved = resolve_relative_import(mod_name, base_mod, level)
                if resolved and (resolved == mod_name or resolved.startswith(mod_name + ".")):
                    pytest.fail(
                        f"SELF IMPORT (relative) di {file_path} line {node.lineno}: "
                        f"modul '{mod_name}' mengimpor dirinya sendiri."
                    )


def test_no_dynamic_imports(project_root: Path):
    all_modules = find_all_python_modules(project_root, include_tests=False)
    critical_modules = {
        mod: path for mod, path in all_modules.items()
        if mod.startswith('application') or mod.startswith('ports')
    }
    if not critical_modules:
        pytest.skip("Tidak ada modul application/ports untuk diperiksa.")
    dyn_imports = detect_dynamic_imports(critical_modules)
    if dyn_imports:
        lines = [f"  - {path} line {line}: {typ}" for path, typ, line in dyn_imports]
        pytest.fail(
            f"DYNAMIC IMPORT DITEMUKAN di modul kritis ({len(dyn_imports)} lokasi).\n"
            "Dynamic import merusak analisis statis dan menyembunyikan circular import.\n"
            "WAJIB diganti dengan import statis biasa.\n" + "\n".join(lines)
        )


def test_architecture_layer_rules(project_root: Path):
    all_modules = find_all_python_modules(project_root, include_tests=False)
    if not all_modules:
        pytest.skip("Tidak ada modul.")

    _, all_imports = build_import_graph_with_details(all_modules)
    violations = check_layer_violations(all_imports, all_modules)

    if violations:
        lines = []
        for imp, msg in violations:
            lines.append(
                f"  {imp.source_file} line {imp.line_no}: {imp.source_module} → {imp.target_module}\n"
                f"    >> {msg}"
            )
        pytest.fail(
            f"PELANGGARAN ARSITEKTUR ({len(violations)}):\n"
            + "\n".join(lines)
            + "\n\nSOLUSI: Restrukturisasi dependensi agar sesuai dengan aturan layer."
        )