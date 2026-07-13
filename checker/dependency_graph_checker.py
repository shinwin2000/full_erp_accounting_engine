#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dependency_graph_checker.py – Dependency Graph Checker for ERP Accounting System
===================================================================================
Standar: ISO/IEC 25010 · SOX/ISA 315 · PCAOB AS 2405
Memeriksa struktur dependency graph:
- Layer violations (Domain → Infrastructure, etc.)
- Orphan modules (no imports, no imported)
- Hub modules (too many outgoing dependencies)
- Skor kepatuhan berdasarkan aturan arsitektur.
RCA engine terintegrasi untuk root cause analysis.
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import json
import logging
import sys
import threading
import time
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Iterator, Any

# =============================================================================
# PASTIKAN ROOT PROJECT ADA DI sys.path
# =============================================================================
_THIS_FILE = Path(__file__).resolve()
if _THIS_FILE.parent.name == "checker":
    ROOT = _THIS_FILE.parent.parent
else:
    ROOT = _THIS_FILE.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# =============================================================================
# RCA INTEGRATION
# =============================================================================
_RCA_AVAILABLE = False
_rca_engine = None

try:
    from rca import get_engine, analyze_exception
    _rca_engine = get_engine()
    _RCA_AVAILABLE = True
    logger = logging.getLogger("dep_graph")
    logger.info("RCA engine loaded from root rca.py")
except ImportError:
    try:
        from checker.core.rca import get_engine, analyze_exception
        _rca_engine = get_engine()
        _RCA_AVAILABLE = True
        logger = logging.getLogger("dep_graph")
        logger.info("RCA engine loaded from checker.core.rca")
    except ImportError:
        _RCA_AVAILABLE = False
        logger = logging.getLogger("dep_graph")
        logger.warning("RCA engine not available.")

# =============================================================================
# LOGGING
# =============================================================================
logger = logging.getLogger("dep_graph")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)

# =============================================================================
# COLOR
# =============================================================================
def _supports_ansi() -> bool:
    if not sys.stdout.isatty():
        return False
    import platform
    if platform.system() == "Windows":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
                return True
        except Exception:
            return False
    return True

_USE_COLOR = _supports_ansi()
COLOR = {
    "RED": "\033[91m" if _USE_COLOR else "",
    "GREEN": "\033[92m" if _USE_COLOR else "",
    "YELLOW": "\033[93m" if _USE_COLOR else "",
    "CYAN": "\033[96m" if _USE_COLOR else "",
    "BOLD": "\033[1m" if _USE_COLOR else "",
    "DIM": "\033[2m" if _USE_COLOR else "",
    "RESET": "\033[0m" if _USE_COLOR else "",
}

def c(key: str) -> str:
    return COLOR.get(key, "")

# =============================================================================
# CONFIGURATION
# =============================================================================
EXCLUDED_DIRS = {
    "checker", "tests", "migrations", "__pycache__", ".git",
    "docs", "scripts", "deployment", "monitoring", "reports",
}

LAYER_RULES = {
    "infrastructure": {"allowed_to_import": {"infrastructure", "adapters", "ports", "bootstrap"}},
    "adapters": {"allowed_to_import": {"adapters", "ports", "infrastructure"}},
    "ports": {"allowed_to_import": {"ports"}},
    "domain": {"allowed_to_import": {"domain"}},
    "application": {"allowed_to_import": {"application", "domain", "ports", "infrastructure"}},
    "bootstrap": {"allowed_to_import": {"bootstrap", "application", "domain", "ports", "adapters", "infrastructure"}},
    "kernel": {"allowed_to_import": {"kernel"}},
    "axioms": {"allowed_to_import": {"axioms"}},
    "constitution": {"allowed_to_import": {"constitution"}},
    "policy_engine": {"allowed_to_import": {"policy_engine", "domain", "ports"}},
    "compliance": {"allowed_to_import": {"compliance", "domain", "ports"}},
    "audit": {"allowed_to_import": {"audit", "domain", "ports", "infrastructure"}},
}

# =============================================================================
# DATA CLASSES
# =============================================================================
@dataclass
class DependencyNode:
    module: str
    file: str
    layer: str
    imports: Set[str] = field(default_factory=set)
    imported_by: Set[str] = field(default_factory=set)

@dataclass
class Report:
    nodes: List[DependencyNode]
    edges: int
    layer_violations: List[Tuple[str, str, str]]  # from_module, to_module, rule
    orphans: List[str]
    hubs: List[Tuple[str, int]]  # module, outgoing_count
    score: float
    files_scanned: int
    scan_time: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

# =============================================================================
# CHECKER
# =============================================================================
class DependencyGraphChecker:
    def __init__(self, root: Path, exclude: List[str] = None, max_workers: int = 4, hub_threshold: int = 20):
        self.root = root
        self.exclude = set(exclude or [])
        self.max_workers = max_workers
        self.hub_threshold = hub_threshold
        self._lock = threading.Lock()
        self._nodes: Dict[str, DependencyNode] = {}
        self._layer_cache: Dict[str, str] = {}
        self._files_scanned = 0

    def scan(self, progress_callback: Optional[Callable] = None) -> Report:
        start = time.perf_counter()
        py_files = list(self._walk())
        self._files_scanned = len(py_files)
        total = len(py_files)
        logger.info(f"Scanning {total} Python files for dependency graph...")

        # Pass 1: collect imports and build nodes
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = [ex.submit(self._analyze_file, f) for f in py_files]
            for idx, future in enumerate(concurrent.futures.as_completed(futures)):
                if progress_callback:
                    progress_callback(idx + 1, total)
                future.result()

        # Build reverse edges
        for node in self._nodes.values():
            for imp in node.imports:
                if imp in self._nodes:
                    self._nodes[imp].imported_by.add(node.module)

        # Detect violations
        layer_violations = []
        for node in self._nodes.values():
            from_layer = node.layer
            for imp in node.imports:
                if imp not in self._nodes:
                    continue
                to_node = self._nodes[imp]
                to_layer = to_node.layer
                if from_layer in LAYER_RULES:
                    allowed = LAYER_RULES[from_layer].get("allowed_to_import", set())
                    if to_layer not in allowed:
                        layer_violations.append((node.module, imp, f"{from_layer} → {to_layer} not allowed"))

        # Orphans
        orphans = []
        for node in self._nodes.values():
            if not node.imports and not node.imported_by:
                orphans.append(node.module)

        # Hubs
        hubs = []
        for node in self._nodes.values():
            if len(node.imports) > self.hub_threshold:
                hubs.append((node.module, len(node.imports)))

        # Score
        score = 100.0
        score -= len(layer_violations) * 5
        score -= len(orphans) * 2
        score -= len(hubs) * 0.5
        score = max(0.0, min(100.0, score))

        # RCA
        if _RCA_AVAILABLE and (layer_violations or orphans or hubs):
            ctx = {
                "layer_violations": len(layer_violations),
                "orphans": len(orphans),
                "hubs": len(hubs),
                "score": score,
                "files_scanned": self._files_scanned,
            }
            try:
                _rca_engine.analyze(RuntimeError("Dependency graph issues"), ctx)
            except Exception:
                pass

        return Report(
            nodes=list(self._nodes.values()),
            edges=sum(len(n.imports) for n in self._nodes.values()),
            layer_violations=layer_violations,
            orphans=orphans,
            hubs=hubs,
            score=round(score, 2),
            files_scanned=self._files_scanned,
            scan_time=time.perf_counter() - start,
        )

    def _walk(self) -> Iterator[Path]:
        for p in self.root.rglob("*.py"):
            if any(part in self.exclude for part in p.parts):
                continue
            if p.name.startswith("__"):
                continue
            if "checker" in str(p):
                continue
            yield p

    def _get_layer(self, module: str) -> str:
        if module in self._layer_cache:
            return self._layer_cache[module]
        parts = module.split(".")
        for part in parts:
            if part in LAYER_RULES:
                self._layer_cache[module] = part
                return part
        # fallback: root dir name
        first = parts[0] if parts else "unknown"
        self._layer_cache[module] = first
        return first

    def _analyze_file(self, py_file: Path) -> None:
        # Baca file dengan encoding yang tepat
        content = None
        for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
            try:
                content = py_file.read_text(encoding=enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if content is None:
            logger.warning(f"Could not read {py_file} (encoding issue)")
            return

        # Parse AST
        try:
            tree = ast.parse(content, filename=str(py_file))
        except SyntaxError as e:
            logger.warning(f"Could not parse {py_file}: {e}")
            return
        except Exception as e:
            logger.warning(f"Unexpected error parsing {py_file}: {e}")
            return

        rel_path = str(py_file.relative_to(self.root))
        module = rel_path.replace("\\", ".").replace("/", ".").replace(".py", "")
        layer = self._get_layer(module)

        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])

        with self._lock:
            self._nodes[module] = DependencyNode(
                module=module,
                file=rel_path,
                layer=layer,
                imports=imports,
            )

# =============================================================================
# REPORT
# =============================================================================
def print_report(r: Report, verbose: bool = False) -> None:
    print(f"\n{c('CYAN')}{'='*90}{c('RESET')}")
    print(f"{c('BOLD')}DEPENDENCY GRAPH CHECKER REPORT{c('RESET')}")
    print(f"{'='*90}")
    print(f"  Timestamp       : {r.timestamp}")
    print(f"  Files scanned   : {r.files_scanned}")
    print(f"  Nodes           : {len(r.nodes)}")
    print(f"  Edges           : {r.edges}")
    print(f"  RCA Engine      : {'✅ Active' if _RCA_AVAILABLE else '⚠️ Not available'}")
    print(f"  Scan time       : {r.scan_time:.2f}s")

    print(f"\n{c('BOLD')}COMPLIANCE SCORE{c('RESET')}")
    score_color = c("GREEN") if r.score >= 90 else c("YELLOW") if r.score >= 70 else c("RED")
    print(f"  {score_color}{r.score}/100{c('RESET')}")

    if r.layer_violations or r.orphans or r.hubs:
        print(f"\n  Penalty Breakdown:")
        print(f"    • Layer violations: {len(r.layer_violations)} × 5 = {len(r.layer_violations)*5}")
        print(f"    • Orphans         : {len(r.orphans)} × 2 = {len(r.orphans)*2}")
        print(f"    • Hubs            : {len(r.hubs)} × 0.5 = {len(r.hubs)*0.5}")
        print(f"    • Raw score       : 100 - {len(r.layer_violations)*5 + len(r.orphans)*2 + len(r.hubs)*0.5} = {r.score}")

    # Layer violations
    print(f"\n1. LAYER VIOLATIONS ({len(r.layer_violations)})")
    if r.layer_violations:
        for from_mod, to_mod, rule in r.layer_violations[:20]:
            print(f"    ❌ {from_mod} → {to_mod} : {rule}")
        if len(r.layer_violations) > 20:
            print(f"    ... and {len(r.layer_violations)-20} more")
    else:
        print("    ✅ Tidak ada pelanggaran layer.")

    # Orphans
    print(f"\n2. ORPHANS ({len(r.orphans)})")
    if r.orphans:
        for mod in r.orphans[:20]:
            print(f"    ⚠️ {mod}")
        if len(r.orphans) > 20:
            print(f"    ... and {len(r.orphans)-20} more")
    else:
        print("    ✅ Tidak ada orphan.")

    # Hubs
    print(f"\n3. HUBS ({len(r.hubs)})")
    if r.hubs:
        for mod, count in sorted(r.hubs, key=lambda x: -x[1])[:20]:
            print(f"    🔥 {mod} ({count} outgoing)")
        if len(r.hubs) > 20:
            print(f"    ... and {len(r.hubs)-20} more")
    else:
        print("    ✅ Tidak ada hub.")

    print(f"\n{'='*90}")
    if r.score >= 80:
        print(f"  {c('GREEN')}✅ Status: LULUS (Skor baik){c('RESET')}")
    elif r.score >= 60:
        print(f"  {c('YELLOW')}⚠️  Status: PERLU PERBAIKAN (Skor sedang){c('RESET')}")
    else:
        print(f"  {c('RED')}❌ Status: GAGAL (Skor rendah){c('RESET')}")
    print(f"{'='*90}\n")

def save_json(r: Report, path: Path) -> None:
    data = {
        "timestamp": r.timestamp,
        "score": r.score,
        "files_scanned": r.files_scanned,
        "nodes": len(r.nodes),
        "edges": r.edges,
        "layer_violations": r.layer_violations,
        "orphans": r.orphans,
        "hubs": r.hubs,
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  JSON saved to {path}")

# =============================================================================
# MAIN
# =============================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="Dependency Graph Checker")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE", help="Save JSON report")
    parser.add_argument("--exclude", default=".venv,venv,__pycache__,tests,checker,docs,deployment,migrations")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--hub-threshold", type=int, default=20, help="Outgoing threshold for hub detection")
    parser.add_argument("--root", "-r", default=None)
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else ROOT
    checker = DependencyGraphChecker(
        root=root,
        exclude=args.exclude.split(","),
        max_workers=args.max_workers,
        hub_threshold=args.hub_threshold,
    )

    def progress(current, total):
        if not sys.stdout.isatty():
            return
        pct = current / total * 100
        bar = "█" * int(pct / 2) + "░" * (50 - int(pct / 2))
        print(f"\r  [{bar}] {current}/{total} ({pct:.1f}%)", end="", flush=True)
        if current >= total:
            print()

    report = checker.scan(progress_callback=progress)
    print_report(report, args.verbose)
    if args.json:
        save_json(report, Path(args.json))

if __name__ == "__main__":
    main()