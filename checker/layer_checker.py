#!/usr/bin/env python3
"""
layer_checker.py - Dependency Layer Validator for Hexagonal/DDD Architecture
=============================================================================
Memeriksa kepatuhan struktur layer berdasarkan aturan ketergantungan yang telah
ditetapkan untuk proyek ERP Accounting Engine.

Cara pakai:
  python layer_checker.py [--verbose] [--json FILE] [--strict] [--quiet] [--hide-unknown]
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field

# -----------------------------------------------------------------------------
# Color
# -----------------------------------------------------------------------------
COLOR = {"RED": "", "GREEN": "", "YELLOW": "", "CYAN": "", "RESET": ""}
try:
    import colorama
    colorama.init(autoreset=True)
    COLOR["RED"] = colorama.Fore.RED
    COLOR["GREEN"] = colorama.Fore.GREEN
    COLOR["YELLOW"] = colorama.Fore.YELLOW
    COLOR["CYAN"] = colorama.Fore.CYAN
    COLOR["RESET"] = colorama.Style.RESET_ALL
except ImportError:
    pass

# -----------------------------------------------------------------------------
# Konfigurasi
# -----------------------------------------------------------------------------
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Pemetaan folder top-level ke layer (diperluas)
LAYER_MAP = {
    # Layer utama
    "domain": "domain",
    "axioms": "axioms",
    "constitution": "constitution",
    "kernel": "kernel",
    "ports": "ports",
    "application": "application",
    "adapters": "adapters",
    "infrastructure": "infrastructure",
    "bootstrap": "bootstrap",
    "config": "config",
    "app": "app",
    "policy_engine": "policy_engine",
    "compliance": "compliance",
    "audit": "audit",
    "projections": "projections",
    "reports": "reports",
    "event_gateway": "event_gateway",
    # Folder pendukung (diabaikan dari pengecekan dependency, tapi tidak muncul sebagai unknown)
    "checker": "checker",
    "scripts": "scripts",
    "tools": "tools",
    "migrations": "migrations",
    "deployment": "deployment",
    "docs": "docs",
    "monitoring": "monitoring",
    "config_files": "config_files",
    "logs": "logs",
    "tests": "tests",
    "test": "test",
    "utils": "utils",
    "common": "common",
    "shared": "shared",
    "lib": "lib",
    "vendor": "vendor",
    "external": "external",
}

# Aturan ketergantungan: source_layer -> set(target_layer yang diizinkan)
ALLOWED_DEPENDENCIES: dict[str, set[str]] = {
    "domain": {"domain", "axioms", "constitution"},
    "axioms": {"axioms", "constitution"},
    "constitution": {"constitution", "domain", "axioms"},
    "kernel": {"kernel", "domain", "axioms", "constitution", "ports", "config"},
    "ports": {"ports", "domain"},
    "application": {"application", "domain", "kernel", "ports", "axioms", "constitution", "config", "bootstrap"},
    "adapters": {"adapters", "application", "domain", "kernel", "ports", "infrastructure", "config"},
    "infrastructure": {"infrastructure", "domain", "ports", "kernel", "config", "application"},
    "bootstrap": {"bootstrap", "config", "infrastructure", "application", "adapters"},
    "config": {"config", "bootstrap"},
    "app": {"app", "bootstrap", "adapters", "infrastructure"},
    "policy_engine": {"policy_engine", "domain", "kernel", "config", "compliance"},
    "compliance": {"compliance", "policy_engine", "domain", "application"},
    "audit": {"audit", "domain", "application", "kernel"},
    "projections": {"projections", "domain", "application", "infrastructure"},
    "reports": {"reports", "projections", "application", "infrastructure"},
    "event_gateway": {"event_gateway", "domain", "application", "infrastructure"},
}

# Layer yang tidak dicek (tidak ada aturan dependency)
SKIP_LAYERS = {"unknown", "checker", "scripts", "tools", "migrations", "deployment",
               "docs", "monitoring", "config_files", "logs", "tests", "test",
               "utils", "common", "shared", "lib", "vendor", "external"}

# File dan folder yang diabaikan
SKIP_FILES = {"main_checker.py", "main_checker_2.py", "main_checker_3.py", "layer_checker.py",
              "setup.py", "manage.py", "conftest.py", "pytest.ini", "tox.ini", "requirements.txt"}
SKIP_DIRS = {".venv", "venv", "__pycache__", ".git", "node_modules", "dist", "build"}

# -----------------------------------------------------------------------------
# Data Structures
# -----------------------------------------------------------------------------
@dataclass
class ImportRecord:
    source_file: str
    source_layer: str
    target_module: str
    target_layer: str
    line: int
    is_relative: bool = False

@dataclass
class Violation:
    source_file: str
    source_layer: str
    target_module: str
    target_layer: str
    line: int
    message: str

@dataclass
class LayerStats:
    total_imports: int = 0
    violations: list[Violation] = field(default_factory=list)
    layer_counts: dict[str, int] = field(default_factory=dict)

# -----------------------------------------------------------------------------
# Utilitas
# -----------------------------------------------------------------------------
def get_layer_from_module(module: str) -> str:
    """Tentukan layer dari nama modul absolute."""
    if not module:
        return "unknown"
    top = module.split(".")[0]
    for folder, layer in LAYER_MAP.items():
        if module == folder or module.startswith(folder + "."):
            return layer
    return "unknown"

def get_relative_path(path: pathlib.Path) -> str:
    """Path relatif terhadap PROJECT_ROOT dengan forward slash."""
    try:
        rel = path.relative_to(PROJECT_ROOT)
        return str(rel).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")

def resolve_relative_import(source_module: str, level: int, target: str | None) -> str:
    """Resolve relative import ke absolute module name."""
    parts = source_module.split(".")
    if level > len(parts):
        return target or ""
    base_parts = parts[:-level] if level > 0 else parts
    if target:
        return ".".join(base_parts + [target])
    else:
        return ".".join(base_parts)

# -----------------------------------------------------------------------------
# Parser AST
# -----------------------------------------------------------------------------
def extract_imports_from_file(file_path: pathlib.Path) -> list[ImportRecord]:
    """Ekstrak semua import dari file Python."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return []

    rel_path = get_relative_path(file_path)
    # Ubah path relatif menjadi module name
    source_module = rel_path.replace("/", ".").rsplit(".", 1)[0]
    source_layer = get_layer_from_module(source_module)

    records = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = alias.name
                records.append(ImportRecord(
                    source_file=rel_path,
                    source_layer=source_layer,
                    target_module=target,
                    target_layer=get_layer_from_module(target),
                    line=node.lineno,
                    is_relative=False,
                ))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                target = node.module
                if target:
                    records.append(ImportRecord(
                        source_file=rel_path,
                        source_layer=source_layer,
                        target_module=target,
                        target_layer=get_layer_from_module(target),
                        line=node.lineno,
                        is_relative=False,
                    ))
            else:
                if node.module:
                    target = resolve_relative_import(source_module, node.level, node.module)
                else:
                    target = resolve_relative_import(source_module, node.level, None)
                if target:
                    records.append(ImportRecord(
                        source_file=rel_path,
                        source_layer=source_layer,
                        target_module=target,
                        target_layer=get_layer_from_module(target),
                        line=node.lineno,
                        is_relative=True,
                    ))
    return records

# -----------------------------------------------------------------------------
# Checker
# -----------------------------------------------------------------------------
def scan_project() -> LayerStats:
    stats = LayerStats()
    py_files = []

    for path in PROJECT_ROOT.rglob("*.py"):
        # Skip direktori yang tidak diinginkan
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        # Skip file yang tidak diinginkan
        if path.name in SKIP_FILES:
            continue
        # Skip jika file berada di folder yang tidak dikenali dan dianggap tidak perlu
        py_files.append(path)

    all_imports = []
    for py_file in py_files:
        imps = extract_imports_from_file(py_file)
        all_imports.extend(imps)

    stats.total_imports = len(all_imports)

    # Hitung layer counts
    layer_counter = defaultdict(int)
    for imp in all_imports:
        layer_counter[imp.source_layer] += 1
    stats.layer_counts = dict(layer_counter)

    # Periksa pelanggaran
    violations = []
    for imp in all_imports:
        src = imp.source_layer
        tgt = imp.target_layer
        if src in SKIP_LAYERS or tgt in SKIP_LAYERS:
            continue
        if src == tgt:
            continue
        allowed = ALLOWED_DEPENDENCIES.get(src, set())
        if tgt not in allowed:
            violations.append(Violation(
                source_file=imp.source_file,
                source_layer=src,
                target_module=imp.target_module,
                target_layer=tgt,
                line=imp.line,
                message=f"Layer '{src}' tidak boleh mengimpor '{tgt}'"
            ))

    stats.violations = violations
    return stats

# -----------------------------------------------------------------------------
# Laporan
# -----------------------------------------------------------------------------
def print_report(stats: LayerStats, verbose: bool = False, hide_unknown: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*72}{c['RESET']}")
    print(f"{c['CYAN']}LAYER DEPENDENCY VIOLATION REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*72}{c['RESET']}")

    print(f"\n  Total import statements : {stats.total_imports}")
    print(f"  Total violations       : {len(stats.violations)}")

    if stats.layer_counts:
        print("\n  Layer import counts:")
        for layer, count in sorted(stats.layer_counts.items()):
            if hide_unknown and layer == "unknown":
                continue
            print(f"    {layer:<18}: {count}")

    if stats.violations:
        print(f"\n{c['RED']}❌ Violations:{c['RESET']}")
        for v in stats.violations:
            print(f"  {c['RED']}✖{c['RESET']} {v.source_file}:{v.line}")
            print(f"     {v.source_layer} → {v.target_layer}  (import {v.target_module})")
            if verbose:
                print(f"     {v.message}")
    else:
        print(f"\n{c['GREEN']}✅ No layer violations found!{c['RESET']}")

    print(f"\n{c['CYAN']}{'─'*72}{c['RESET']}")

def save_json(stats: LayerStats, filepath: str, hide_unknown: bool = False):
    violations = [v.__dict__ for v in stats.violations]
    layer_counts = {k: v for k, v in stats.layer_counts.items() if not (hide_unknown and k == "unknown")}
    data = {
        "total_imports": stats.total_imports,
        "violations_count": len(stats.violations),
        "layer_counts": layer_counts,
        "violations": violations,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{c['CYAN']}JSON report saved to {filepath}{c['RESET']}")

# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Layer Dependency Checker")
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan detail setiap pelanggaran")
    parser.add_argument("--json", metavar="FILE", help="Simpan laporan JSON")
    parser.add_argument("--quiet", "-q", action="store_true", help="Hanya tampilkan ringkasan")
    parser.add_argument("--hide-unknown", action="store_true", help="Sembunyikan layer 'unknown' dari laporan")
    args = parser.parse_args()

    start = time.monotonic()
    stats = scan_project()
    if not args.quiet:
        print_report(stats, verbose=args.verbose, hide_unknown=args.hide_unknown)
    if args.json:
        save_json(stats, args.json, hide_unknown=args.hide_unknown)

    elapsed = time.monotonic() - start
    if not args.quiet:
        print(f"\n  Waktu: {elapsed:.2f}s")

    sys.exit(0 if len(stats.violations) == 0 else 1)

if __name__ == "__main__":
    main()