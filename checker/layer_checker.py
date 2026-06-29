#!/usr/bin/env python3
"""
layer_checker.py - Dependency Layer Validator for Hexagonal/DDD Architecture
=============================================================================
Memeriksa kepatuhan struktur layer menggunakan dependency matrix (allow-list)
bukan hanya berdasarkan level numerik.
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
from typing import Dict, Set, List, Optional, Tuple

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
# Project root
# -----------------------------------------------------------------------------
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

# -----------------------------------------------------------------------------
# Mapping folder → layer
# -----------------------------------------------------------------------------
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
    # pendukung
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

# -----------------------------------------------------------------------------
# Dependency Matrix (Allow-list)
# -----------------------------------------------------------------------------
ALLOWED_PAIRS: Set[Tuple[str, str]] = {
    # Domain layer
    ("domain", "domain"),
    ("domain", "axioms"),
    ("domain", "constitution"),
    # Axioms
    ("axioms", "axioms"),
    ("axioms", "constitution"),
    # Constitution
    ("constitution", "constitution"),
    ("constitution", "domain"),
    ("constitution", "axioms"),
    # Kernel
    ("kernel", "kernel"),
    ("kernel", "domain"),
    ("kernel", "axioms"),
    ("kernel", "constitution"),
    ("kernel", "ports"),
    ("kernel", "config"),
    # Ports
    ("ports", "ports"),
    ("ports", "domain"),
    # Application
    ("application", "application"),
    ("application", "domain"),
    ("application", "kernel"),
    ("application", "ports"),
    ("application", "axioms"),
    ("application", "constitution"),
    ("application", "config"),
    # --- ADDED ---
    ("application", "policy_engine"),  # Tax business rules
    ("application", "audit"),          # Audit domain logic
    # Adapters
    ("adapters", "adapters"),
    ("adapters", "application"),
    ("adapters", "domain"),
    ("adapters", "kernel"),
    ("adapters", "ports"),
    ("adapters", "infrastructure"),
    ("adapters", "config"),
    # Projections
    ("projections", "projections"),
    ("projections", "domain"),
    ("projections", "application"),
    ("projections", "infrastructure"),
    ("projections", "config"),
    # Reports
    ("reports", "reports"),
    ("reports", "projections"),
    ("reports", "application"),
    ("reports", "infrastructure"),
    ("reports", "config"),
    # Event Gateway
    ("event_gateway", "event_gateway"),
    ("event_gateway", "domain"),
    ("event_gateway", "application"),
    ("event_gateway", "infrastructure"),
    # Infrastructure
    ("infrastructure", "infrastructure"),
    ("infrastructure", "domain"),
    ("infrastructure", "ports"),
    ("infrastructure", "kernel"),
    ("infrastructure", "config"),
    # Bootstrap
    ("bootstrap", "bootstrap"),
    ("bootstrap", "config"),
    ("bootstrap", "infrastructure"),
    ("bootstrap", "application"),
    ("bootstrap", "adapters"),
    # App
    ("app", "app"),
    ("app", "bootstrap"),
    ("app", "adapters"),
    ("app", "infrastructure"),
    # Policy Engine
    ("policy_engine", "policy_engine"),
    ("policy_engine", "domain"),
    ("policy_engine", "kernel"),
    ("policy_engine", "config"),
    ("policy_engine", "compliance"),
    # Compliance
    ("compliance", "compliance"),
    ("compliance", "policy_engine"),
    ("compliance", "domain"),
    ("compliance", "application"),
    # Audit
    ("audit", "audit"),
    ("audit", "domain"),
    ("audit", "application"),
    ("audit", "kernel"),
    # --- GENERIC SAME-LAYER ALLOW ---
    # Untuk semua layer lainnya, kita izinkan import internal (layer → layer sendiri)
    # Ini mencakup config → config, checker → checker, tests → tests, dll.
    ("config", "config"),
    ("checker", "checker"),
    ("scripts", "scripts"),
    ("tools", "tools"),
    ("migrations", "migrations"),
    ("deployment", "deployment"),
    ("docs", "docs"),
    ("monitoring", "monitoring"),
    ("config_files", "config_files"),
    ("logs", "logs"),
    ("tests", "tests"),
    ("test", "test"),
    ("utils", "utils"),
    ("common", "common"),
    ("shared", "shared"),
    ("lib", "lib"),
    ("vendor", "vendor"),
    ("external", "external"),
    # Juga untuk layer utama yang mungkin belum tercakup:
    ("projections", "projections"),
    ("reports", "reports"),
    ("event_gateway", "event_gateway"),
    ("policy_engine", "policy_engine"),
    ("compliance", "compliance"),
    ("audit", "audit"),
    ("kernel", "kernel"),
}

# Layer yang tidak dicek sama sekali (tidak ada aturan)
SKIP_LAYERS = {
    "unknown", "checker", "scripts", "tools", "migrations", "deployment",
    "docs", "monitoring", "config_files", "logs", "tests", "test",
    "utils", "common", "shared", "lib", "vendor", "external"
}

# -----------------------------------------------------------------------------
# Standard library modules
# -----------------------------------------------------------------------------
try:
    import sys as _sys
    STD_LIB_MODULES = set(_sys.stdlib_module_names) if hasattr(_sys, 'stdlib_module_names') else set()
except Exception:
    STD_LIB_MODULES = set()
STD_LIB_MODULES.update({"typing", "dataclasses", "enum", "uuid", "decimal", "datetime",
                        "abc", "collections", "itertools", "functools", "re", "json", "pathlib"})

# Friend packages (diizinkan meskipun tidak ada di matrix)
FRIEND_PACKAGES: Dict[str, Set[str]] = {
    "domain": {"typing", "abc", "dataclasses", "enum", "uuid", "decimal", "datetime", "dateutil"},
    "application": {"typing", "dataclasses", "enum", "uuid", "decimal", "datetime"},
    "kernel": {"typing", "dataclasses", "enum", "uuid", "decimal", "datetime"},
}

# -----------------------------------------------------------------------------
# Data structures
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
    rule: str
    message: str

@dataclass
class LayerStats:
    total_imports: int = 0
    violations: List[Violation] = field(default_factory=list)
    layer_counts: Dict[str, int] = field(default_factory=dict)
    dependency_graph: Dict[str, Set[str]] = field(default_factory=dict)
    cycles: List[List[str]] = field(default_factory=list)

# -----------------------------------------------------------------------------
# Utility functions
# -----------------------------------------------------------------------------
def get_layer_from_module(module: str) -> str:
    if not module:
        return "unknown"
    top = module.split(".")[0]
    for folder, layer in LAYER_MAP.items():
        if module == folder or module.startswith(folder + "."):
            return layer
    return "unknown"

def get_relative_path(path: pathlib.Path) -> str:
    try:
        rel = path.relative_to(PROJECT_ROOT)
        return str(rel).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")

def resolve_relative_import(source_module: str, level: int, target: Optional[str]) -> str:
    parts = source_module.split(".")
    if level > len(parts):
        return target or ""
    base_parts = parts[:-level] if level > 0 else parts
    if target:
        return ".".join(base_parts + [target])
    else:
        return ".".join(base_parts)

def is_stdlib_module(module: str) -> bool:
    base = module.split(".")[0]
    return base in STD_LIB_MODULES

def is_friend_package(layer: str, module: str) -> bool:
    friends = FRIEND_PACKAGES.get(layer, set())
    for friend in friends:
        if module == friend or module.startswith(friend + "."):
            return True
    return False

# -----------------------------------------------------------------------------
# AST parsing
# -----------------------------------------------------------------------------
def extract_imports_from_file(file_path: pathlib.Path) -> List[ImportRecord]:
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return []

    rel_path = get_relative_path(file_path)
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
# Circular dependency detection
# -----------------------------------------------------------------------------
def find_cycles(graph: Dict[str, Set[str]]) -> List[List[str]]:
    cycles = []
    visited = set()
    rec_stack = set()
    path = []

    def dfs(node: str) -> None:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        for neighbor in graph.get(node, set()):
            if neighbor not in visited:
                dfs(neighbor)
            elif neighbor in rec_stack:
                idx = path.index(neighbor)
                cycle = path[idx:] + [neighbor]
                if len(cycle) > 2:
                    cycles.append(cycle)
        path.pop()
        rec_stack.remove(node)

    for node in list(graph.keys()):
        if node not in visited:
            dfs(node)
    return cycles

# -----------------------------------------------------------------------------
# Scanner
# -----------------------------------------------------------------------------
def scan_project() -> LayerStats:
    stats = LayerStats()
    py_files = []

    for path in PROJECT_ROOT.rglob("*.py"):
        if any(part in {".venv", "venv", "__pycache__", ".git", "node_modules", "dist", "build"} for part in path.parts):
            continue
        if path.name in {"main_checker.py", "main_checker_2.py", "main_checker_3.py", "layer_checker.py",
                         "setup.py", "manage.py", "conftest.py"}:
            continue
        py_files.append(path)

    all_imports = []
    for py_file in py_files:
        imps = extract_imports_from_file(py_file)
        all_imports.extend(imps)

    stats.total_imports = len(all_imports)

    layer_counter = defaultdict(int)
    for imp in all_imports:
        layer_counter[imp.source_layer] += 1
    stats.layer_counts = dict(layer_counter)

    # Build dependency graph for cycles (only non-skipped layers)
    graph = defaultdict(set)
    for imp in all_imports:
        src = imp.source_layer
        tgt = imp.target_layer
        if src in SKIP_LAYERS or tgt in SKIP_LAYERS:
            continue
        if src == tgt:
            continue
        graph[src].add(tgt)
    stats.dependency_graph = dict(graph)
    stats.cycles = find_cycles(graph)

    # Check violations based on matrix
    violations = []
    for imp in all_imports:
        src = imp.source_layer
        tgt = imp.target_layer
        if src in SKIP_LAYERS or tgt in SKIP_LAYERS:
            continue
        if is_stdlib_module(imp.target_module):
            continue
        if is_friend_package(src, imp.target_module):
            continue
        # Check if (src, tgt) is allowed
        if (src, tgt) not in ALLOWED_PAIRS:
            violations.append(Violation(
                source_file=imp.source_file,
                source_layer=src,
                target_module=imp.target_module,
                target_layer=tgt,
                line=imp.line,
                rule="matrix",
                message=f"Import from '{src}' to '{tgt}' is not allowed by dependency matrix"
            ))

    stats.violations = violations
    return stats

# -----------------------------------------------------------------------------
# Report
# -----------------------------------------------------------------------------
def print_report(stats: LayerStats, verbose: bool = False, hide_unknown: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*80}{c['RESET']}")
    print(f"{c['CYAN']}LAYER DEPENDENCY VIOLATION REPORT (Matrix-based){c['RESET']}")
    print(f"{c['CYAN']}{'='*80}{c['RESET']}")

    print(f"\n  Total import statements : {stats.total_imports}")
    print(f"  Total violations        : {len(stats.violations)}")
    print(f"  Circular dependencies   : {len(stats.cycles)}")

    if stats.layer_counts:
        print("\n  Layer import counts:")
        for layer, count in sorted(stats.layer_counts.items()):
            if hide_unknown and layer == "unknown":
                continue
            print(f"    {layer:<18}: {count}")

    if stats.cycles:
        print(f"\n{c['RED']}⚠️ Circular dependencies detected:{c['RESET']}")
        for i, cycle in enumerate(stats.cycles, 1):
            print(f"  {i}. {' → '.join(cycle)}")

    if stats.violations:
        # Group by file
        by_file = defaultdict(list)
        for v in stats.violations:
            by_file[v.source_file].append(v)

        print(f"\n{c['RED']}❌ Violations (by file):{c['RESET']}")
        print(f"  Total files with violations: {len(by_file)}\n")

        sorted_files = sorted(by_file.items(), key=lambda x: len(x[1]), reverse=True)
        for idx, (file_path, violations) in enumerate(sorted_files, 1):
            print(f"{c['YELLOW']}[{idx}] {file_path}{c['RESET']}  ({len(violations)} violations)")
            for v in violations:
                line_str = f"{c['CYAN']}line {v.line:>4}{c['RESET']}"
                rule_str = f"{c['GREEN']}{v.rule:<14}{c['RESET']}"
                src_tgt = f"{v.source_layer} → {v.target_layer}"
                print(f"    {line_str}  {rule_str}  {src_tgt:<25}  {v.message}")
            print()

        print(f"\n{c['CYAN']}Summary by rule type:{c['RESET']}")
        rule_counts = defaultdict(int)
        for v in stats.violations:
            rule_counts[v.rule] += 1
        for rule, count in sorted(rule_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {rule:<18}: {count}")
    else:
        print(f"\n{c['GREEN']}✅ No layer violations found!{c['RESET']}")

    print(f"\n{c['CYAN']}{'─'*80}{c['RESET']}")

def save_json(stats: LayerStats, filepath: str, hide_unknown: bool = False):
    violations = [v.__dict__ for v in stats.violations]
    layer_counts = {k: v for k, v in stats.layer_counts.items() if not (hide_unknown and k == "unknown")}
    data = {
        "total_imports": stats.total_imports,
        "violations_count": len(stats.violations),
        "layer_counts": layer_counts,
        "cycles": stats.cycles,
        "violations": violations,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{c['CYAN']}JSON report saved to {filepath}{c['RESET']}")

# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Layer Dependency Checker (Matrix-based)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan laporan JSON")
    parser.add_argument("--quiet", "-q", action="store_true", help="Ringkasan saja")
    parser.add_argument("--hide-unknown", action="store_true", help="Sembunyikan layer unknown")
    args = parser.parse_args()

    start = time.monotonic()
    stats = scan_project()

    if not args.quiet:
        print_report(stats, verbose=args.verbose, hide_unknown=args.hide_unknown)
    if args.json:
        save_json(stats, args.json, hide_unknown=args.hide_unknown)

    elapsed = time.monotonic() - start
    if not args.quiet:
        print(f"\n  ⏱️ Waktu: {elapsed:.2f}s")

    exit_code = 0 if (len(stats.violations) == 0 and len(stats.cycles) == 0) else 1
    sys.exit(exit_code)

if __name__ == "__main__":
    main()