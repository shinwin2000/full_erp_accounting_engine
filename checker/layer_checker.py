#!/usr/bin/env python3
"""
layer_checker.py - Dependency Layer Validator for Hexagonal/DDD Architecture
=============================================================================
Memeriksa kepatuhan struktur layer berdasarkan aturan ketergantungan yang telah
ditetapkan untuk proyek ERP Accounting Engine.

Aturan dasar (dapat disesuaikan):
  - domain        : hanya boleh mengimpor domain, axioms, constitution
  - axioms        : hanya boleh mengimpor axioms, constitution
  - constitution  : hanya boleh mengimpor constitution, domain, axioms
  - kernel        : boleh mengimpor kernel, domain, axioms, constitution, ports, config
  - ports         : hanya boleh mengimpor ports, domain
  - application   : boleh mengimpor application, domain, kernel, ports, axioms, constitution, config, bootstrap
  - adapters      : boleh mengimpor adapters, application, domain, kernel, ports, infrastructure, config
  - infrastructure: boleh mengimpor infrastructure, domain, ports, kernel, config, application
  - bootstrap     : boleh mengimpor bootstrap, config, infrastructure, application, adapters
  - config        : boleh mengimpor config, bootstrap
  - app           : boleh mengimpor app, bootstrap, adapters, infrastructure
  - policy_engine : boleh mengimpor policy_engine, domain, kernel, config, compliance
  - compliance    : boleh mengimpor compliance, policy_engine, domain, application
  - audit         : boleh mengimpor audit, domain, application, kernel
  - projections   : boleh mengimpor projections, domain, application, infrastructure
  - reports       : boleh mengimpor reports, projections, application, infrastructure
  - event_gateway : boleh mengimpor event_gateway, domain, application, infrastructure

  - Layer 'tests' dan file checker (main_checker*.py) diabaikan.

Cara pakai:
  python layer_checker.py [--verbose] [--json FILE] [--strict] [--quiet]
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
# Konfigurasi Layer
# -----------------------------------------------------------------------------
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent

# Pemetaan folder top-level ke layer
LAYER_MAP = {
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

# Layer yang diabaikan (tidak dicek)
SKIP_LAYERS = {"tests", "unknown"}
SKIP_FILES = {"main_checker.py", "main_checker_2.py", "main_checker_3.py", "layer_checker.py"}

# -----------------------------------------------------------------------------
# Data Structures
# -----------------------------------------------------------------------------
@dataclass
class ImportRecord:
    source_file: str          # path relatif
    source_layer: str
    target_module: str        # nama modul yang diimpor (absolute)
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
    """Tentukan layer dari nama modul (absolute)."""
    if not module:
        return "unknown"
    top = module.split(".")[0]
    # Cari berdasarkan folder (termasuk modul yang sama dengan folder)
    for folder, layer in LAYER_MAP.items():
        if module == folder or module.startswith(folder + "."):
            return layer
    return "unknown"

def get_layer_from_path(path: pathlib.Path) -> str:
    """Dapatkan layer dari path file (relatif ke root)."""
    try:
        rel = path.relative_to(PROJECT_ROOT)
    except ValueError:
        return "unknown"
    parts = rel.parts
    if not parts:
        return "unknown"
    top = parts[0]
    return LAYER_MAP.get(top, "unknown")

def resolve_relative_import(source_module: str, level: int, target: str | None) -> str:
    """
    Ubah relative import menjadi absolute module name.
    source_module: modul sumber absolut (misal 'domain.journal.aggregate_root')
    level: jumlah dot (1,2,...)
    target: modul setelah dot (None jika dari . import x)
    """
    parts = source_module.split(".")
    if level > len(parts):
        # tidak mungkin, return as-is
        return target or ""
    # Potong bagian akhir sebanyak level
    base_parts = parts[:-level] if level > 0 else parts
    if target:
        return ".".join(base_parts + [target])
    else:
        return ".".join(base_parts)

# -----------------------------------------------------------------------------
# Parser AST (akurat)
# -----------------------------------------------------------------------------
def extract_imports_from_file(file_path: pathlib.Path) -> list[ImportRecord]:
    """Ekstrak semua import (Import, ImportFrom) dari file Python."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    # Tentukan source module & source layer
    try:
        rel = file_path.relative_to(PROJECT_ROOT)
        source_module = str(rel.with_suffix("")).replace("/", ".")
    except ValueError:
        source_module = str(file_path)
    source_layer = get_layer_from_module(source_module)

    records = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = alias.name
                records.append(ImportRecord(
                    source_file=str(rel) if 'rel' in locals() else str(file_path),
                    source_layer=source_layer,
                    target_module=target,
                    target_layer=get_layer_from_module(target),
                    line=node.lineno,
                    is_relative=False,
                ))
        elif isinstance(node, ast.ImportFrom):
            # node.module bisa None jika relative import tanpa nama modul (from . import x)
            # node.level menunjukkan jumlah dot (1,2,...)
            if node.level == 0:
                # absolute import
                target = node.module
                if target:
                    records.append(ImportRecord(
                        source_file=str(rel) if 'rel' in locals() else str(file_path),
                        source_layer=source_layer,
                        target_module=target,
                        target_layer=get_layer_from_module(target),
                        line=node.lineno,
                        is_relative=False,
                    ))
            else:
                # relative import
                # target_module kosong? Kita resolve
                if node.module:
                    # from .module import x
                    target = resolve_relative_import(source_module, node.level, node.module)
                else:
                    # from . import x
                    target = resolve_relative_import(source_module, node.level, None)
                if target:
                    records.append(ImportRecord(
                        source_file=str(rel) if 'rel' in locals() else str(file_path),
                        source_layer=source_layer,
                        target_module=target,
                        target_layer=get_layer_from_module(target),
                        line=node.lineno,
                        is_relative=True,
                    ))
                else:
                    # Jika gagal resolve, abaikan (tidak mungkin terjadi)
                    pass
    return records

# -----------------------------------------------------------------------------
# Checker
# -----------------------------------------------------------------------------
def scan_project() -> LayerStats:
    stats = LayerStats()

    # Kumpulkan semua file .py
    exclude_dirs = {
        ".venv", "venv", "__pycache__", ".git", "node_modules",
        "dist", "build", "migrations", "deployment", "docs",
        "monitoring", "config_files", "logs", "tests"  # tests diabaikan
    }
    py_files = []
    for path in PROJECT_ROOT.rglob("*.py"):
        # skip directory yang di-exclude
        if any(part in exclude_dirs for part in path.parts):
            continue
        # skip file checker
        if path.name in SKIP_FILES:
            continue
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
        # Skip jika source layer diabaikan
        if src in SKIP_LAYERS or tgt in SKIP_LAYERS:
            continue
        # Self-import diperbolehkan
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
def print_report(stats: LayerStats, verbose: bool = False, strict: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*72}{c['RESET']}")
    print(f"{c['CYAN']}LAYER DEPENDENCY VIOLATION REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*72}{c['RESET']}")

    print(f"\n  Total import statements : {stats.total_imports}")
    print(f"  Total violations       : {len(stats.violations)}")

    if stats.layer_counts:
        print("\n  Layer import counts:")
        for layer, count in sorted(stats.layer_counts.items()):
            print(f"    {layer:<18}: {count}")

    if stats.violations:
        print(f"\n{c['RED']}❌ Violations:{c['RESET']}")
        for v in stats.violations:
            # Tampilkan hanya jika strict atau severity-nya tinggi? Di sini semua pelanggaran dianggap error.
            print(f"  {c['RED']}✖{c['RESET']} {v.source_file}:{v.line}")
            print(f"     {v.source_layer} → {v.target_layer}  (import {v.target_module})")
            if verbose:
                print(f"     {v.message}")
    else:
        print(f"\n{c['GREEN']}✅ No layer violations found!{c['RESET']}")

    print(f"\n{c['CYAN']}{'─'*72}{c['RESET']}")

def save_json(stats: LayerStats, filepath: str):
    data = {
        "total_imports": stats.total_imports,
        "violations_count": len(stats.violations),
        "layer_counts": stats.layer_counts,
        "violations": [
            {
                "file": v.source_file,
                "line": v.line,
                "source_layer": v.source_layer,
                "target_layer": v.target_layer,
                "target_module": v.target_module,
                "message": v.message,
            }
            for v in stats.violations
        ]
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{c['CYAN']}JSON report saved to {filepath}{c['RESET']}")

# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Layer Dependency Checker")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail setiap pelanggaran")
    parser.add_argument("--strict", action="store_true", help="Perlakukan semua pelanggaran sebagai error (tidak diimplementasikan khusus, semua sudah error)")
    parser.add_argument("--json", metavar="FILE", help="Simpan laporan JSON")
    parser.add_argument("--quiet", action="store_true", help="Hanya tampilkan ringkasan")
    args = parser.parse_args()

    start = time.monotonic()
    stats = scan_project()
    if not args.quiet:
        print_report(stats, verbose=args.verbose)
    if args.json:
        save_json(stats, args.json)

    elapsed = time.monotonic() - start
    if not args.quiet:
        print(f"\n  Waktu: {elapsed:.2f}s")

    # Exit code: 0 jika tidak ada pelanggaran, 1 jika ada
    sys.exit(0 if len(stats.violations) == 0 else 1)

if __name__ == "__main__":
    main()
