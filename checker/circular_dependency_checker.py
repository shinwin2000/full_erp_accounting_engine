#!/usr/bin/env python3
"""
circular_dependency_checker.py - Detect circular imports with full graph cycle detection
==========================================================================================
Standar: Big 4 Audit · ISO/IEC 25010 · SOX/ISA 315
Fitur: Tarjan/DFS cycle detection, severity by cycle length, RCA integration, multi-thread,
       cache, HTML/JSON/SARIF output, progress bar.
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import json
import logging
import pathlib
import sys
import threading
import time
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

# ---- Setup logging (harus sebelum inisialisasi RCA) ----
logger = logging.getLogger("circular_dep")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)

# ---- Ensure root directory is in sys.path for importing 'checker' package ----
_THIS_DIR = pathlib.Path(__file__).resolve().parent      # checker/
_ROOT_DIR = _THIS_DIR.parent                             # full_erp_accounting_engine/
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

# ---- RCA integration ----
_RCA_ENGINE = None
_RCA_AVAIL = False

def _init_rca():
    """Initialize RCA engine from checker.core.rca with fallback."""
    global _RCA_ENGINE, _RCA_AVAIL
    if _RCA_AVAIL:
        return True

    # Try primary import: checker.core.rca
    try:
        from checker.core import rca
        # Expect a function get_engine() or a class RCAEngine
        if hasattr(rca, 'get_engine'):
            engine = rca.get_engine()
        elif hasattr(rca, 'RCAEngine'):
            engine = rca.RCAEngine()
        else:
            # Maybe the module itself is the engine?
            engine = rca
        # Check if engine has 'analyze' method
        if hasattr(engine, 'analyze'):
            _RCA_ENGINE = engine
            _RCA_AVAIL = True
            logger.info("RCA engine loaded from checker.core.rca")
            return True
        else:
            logger.warning("RCA engine loaded but does not have 'analyze' method")
    except ImportError as e:
        logger.debug(f"Primary RCA import failed: {e}")
    except Exception as e:
        logger.warning(f"Error initializing RCA from checker.core.rca: {e}")

    # Fallback: try other common paths
    try:
        for mod_name in ("checker.rca", "rca"):
            try:
                mod = __import__(mod_name, fromlist=["get_engine", "RCAEngine"])
                if hasattr(mod, 'get_engine'):
                    engine = mod.get_engine()
                elif hasattr(mod, 'RCAEngine'):
                    engine = mod.RCAEngine()
                else:
                    engine = mod
                if hasattr(engine, 'analyze'):
                    _RCA_ENGINE = engine
                    _RCA_AVAIL = True
                    logger.info(f"RCA engine loaded from {mod_name}")
                    return True
            except ImportError:
                continue
    except Exception as e:
        logger.warning(f"Fallback RCA import failed: {e}")

    logger.warning("RCA engine not available. Circular dependency analysis will proceed without RCA.")
    return False

# Call initialization
_init_rca()

def get_rca_engine():
    return _RCA_ENGINE

def analyze_with_rca(exc, ctx):
    if _RCA_AVAIL and _RCA_ENGINE:
        try:
            return _RCA_ENGINE.analyze(exc, ctx)
        except Exception as e:
            logger.debug(f"RCA analysis failed: {e}")
    return None

# ---- Color ----
COLOR = {"RED": "\033[91m", "GREEN": "\033[92m", "YELLOW": "\033[93m", "CYAN": "\033[96m", "MAGENTA": "\033[95m", "BOLD": "\033[1m", "RESET": "\033[0m"}
def c(key: str) -> str: return COLOR.get(key, "")

# ---- Caches ----
_AST_CACHE: dict[str, ast.AST | None] = {}
_CACHE_LOCK = threading.Lock()

def get_ast(file_path: pathlib.Path) -> ast.AST | None:
    key = str(file_path.resolve())
    with _CACHE_LOCK:
        if key in _AST_CACHE:
            return _AST_CACHE[key]
    try:
        src = file_path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(file_path))
        with _CACHE_LOCK:
            _AST_CACHE[key] = tree
        return tree
    except Exception:
        with _CACHE_LOCK:
            _AST_CACHE[key] = None
        return None

# ---- Data ----
@dataclass
class Dependency:
    from_mod: str
    to_mod: str
    file: str
    line: int

@dataclass
class Cycle:
    nodes: list[str]
    severity: str  # CRITICAL (>5), HIGH (>3), MEDIUM
    confidence: float
    deps: list[Dependency]
    rca: dict | None = None

@dataclass
class Report:
    cycles: list[Cycle]
    total_nodes: int
    total_edges: int
    score: float
    scan_time: float
    files_scanned: int
    timestamp: str

# ---- Scanner ----
class CircularDependencyScanner:
    def __init__(self, root: pathlib.Path, exclude: list[str] = None, max_workers: int = 4):
        self.root = root
        self.exclude = set(exclude or [".venv", "venv", "__pycache__", "tests", "checker", "docs", "migrations"])
        self.max_workers = max_workers
        self.graph: dict[str, set[str]] = defaultdict(set)
        self.deps: list[Dependency] = []
        self._lock = threading.Lock()
        self._files_scanned = 0

    def scan(self, progress_callback=None) -> Report:
        t0 = time.perf_counter()
        py_files = list(self._walk())
        total = len(py_files)
        self._files_scanned = total
        logger.info(f"Scanning {total} Python files...")

        # Parallel parse
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self._parse_file, p): p for p in py_files}
            for idx, future in enumerate(concurrent.futures.as_completed(futures)):
                if progress_callback:
                    progress_callback(idx + 1, total)
                future.result()

        cycles = self._detect_cycles()
        # Fixed scoring: 100 - (cycles / total_nodes * 100) * 10, min 0
        # 0 cycles -> 100, 10% cycles -> 90, 100% cycles -> 0
        score = 100 - (len(cycles) / max(1, len(self.graph)) * 100) * 10
        score = max(0, min(100, score))
        return Report(
            cycles=cycles,
            total_nodes=len(self.graph),
            total_edges=len(self.deps),
            score=round(score, 2),
            scan_time=time.perf_counter() - t0,
            files_scanned=self._files_scanned,
            timestamp=datetime.now(UTC).isoformat()
        )

    def _walk(self) -> Iterator[pathlib.Path]:
        for p in self.root.rglob("*.py"):
            if any(part in self.exclude for part in p.parts): continue
            if p.name.startswith("__"): continue
            if "checker" in str(p): continue
            yield p

    def _parse_file(self, py_file: pathlib.Path) -> None:
        mod = self._module_name(py_file)
        tree = get_ast(py_file)
        if tree is None:
            return
        local_deps = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = alias.name.split(".")[0]
                    local_deps.append(Dependency(mod, target, str(py_file), node.lineno))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    target = node.module.split(".")[0]
                    local_deps.append(Dependency(mod, target, str(py_file), node.lineno))
        with self._lock:
            for d in local_deps:
                self.graph[d.from_mod].add(d.to_mod)
                self.deps.append(d)

    def _module_name(self, p: pathlib.Path) -> str:
        return ".".join(p.relative_to(self.root).with_suffix("").parts)

    def _detect_cycles(self) -> list[Cycle]:
        graph = {k: set(v) for k, v in self.graph.items() if k in self.graph}
        state = dict.fromkeys(graph, 0)
        stack = []
        cycles = []

        def dfs(n: str):
            if state.get(n, 0) == 1:
                # n is in current stack -> cycle found
                try:
                    idx = stack.index(n)
                except ValueError:
                    # Should not happen, but safeguard
                    return
                cyc = stack[idx:] + [n]
                sev = "CRITICAL" if len(cyc) > 5 else "HIGH" if len(cyc) > 3 else "MEDIUM"
                deps = []
                for i in range(len(cyc)-1):
                    d = next((d for d in self.deps if d.from_mod == cyc[i] and d.to_mod == cyc[i+1]), None)
                    if d: deps.append(d)
                rca = None
                if _RCA_AVAIL:
                    try:
                        exc = RuntimeError(f"Circular dependency: {' → '.join(cyc)}")
                        r = analyze_with_rca(exc, {"cycle": cyc, "severity": sev})
                        if r and hasattr(r, 'to_dict'):
                            rca = r.to_dict()
                        elif isinstance(r, dict):
                            rca = r
                        else:
                            # Try to convert to dict if possible
                            rca = {"raw": str(r)}
                    except Exception as e:
                        logger.debug(f"RCA analysis error: {e}")
                cycles.append(Cycle(cyc, sev, 0.9 if sev == "CRITICAL" else 0.8, deps, rca))
                return
            if state.get(n, 0) == 2:
                return
            state[n] = 1
            stack.append(n)
            for nb in graph.get(n, []):
                if nb in graph:
                    dfs(nb)
            stack.pop()
            state[n] = 2

        for n in list(graph.keys()):
            if state.get(n, 0) == 0:
                dfs(n)
        return cycles

# ---- Reporters ----
def print_report(report: Report, verbose: bool = False):
    print(f"\n{c('CYAN')}{'='*70}{c('RESET')}")
    print(f"{c('BOLD')}CIRCULAR DEPENDENCY CHECKER REPORT{c('RESET')}")
    print(f"{'='*70}")
    print(f"  Timestamp       : {report.timestamp}")
    print(f"  Files scanned   : {report.files_scanned}")
    print(f"  Modules         : {report.total_nodes}")
    print(f"  Import edges    : {report.total_edges}")
    print(f"  Cycles detected : {len(report.cycles)}")
    print(f"  RCA Engine      : {'✅ Active' if _RCA_AVAIL else '⚠️ Not available'}")
    print(f"  Compliance Score: {c('GREEN') if report.score >= 90 else c('YELLOW')}{report.score}/100{c('RESET')}")
    print(f"  Scan time       : {report.scan_time:.2f}s")

    if report.cycles:
        print(f"\n{c('RED')}Cycles:{c('RESET')}")
        for cyc in report.cycles:
            color = c("RED") if cyc.severity == "CRITICAL" else c("YELLOW")
            print(f"  {color}[{cyc.severity}]{c('RESET')} {' → '.join(cyc.nodes)} (conf:{cyc.confidence:.2f})")
            if verbose:
                for d in cyc.deps[:5]:
                    print(f"      {d.from_mod} -> {d.to_mod} at {d.file}:{d.line}")
                if cyc.rca:
                    rc = cyc.rca.get('root_cause', '')[:100]
                    if rc:
                        print(f"      RCA: {rc}")
                    fix = cyc.rca.get('suggested_fix', '')[:100]
                    if fix:
                        print(f"      Fix: {fix}")
    else:
        print(f"\n  {c('GREEN')}✅ No circular dependencies detected.{c('RESET')}")

def save_json(report: Report, path: pathlib.Path):
    data = {
        "version": "2.0",
        "timestamp": report.timestamp,
        "score": report.score,
        "total_nodes": report.total_nodes,
        "total_edges": report.total_edges,
        "files_scanned": report.files_scanned,
        "scan_time": report.scan_time,
        "cycles": [
            {"nodes": c.nodes, "severity": c.severity, "confidence": c.confidence,
             "deps": [{"from": d.from_mod, "to": d.to_mod, "file": d.file, "line": d.line} for d in c.deps[:10]]}
            for c in report.cycles
        ]
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  JSON saved to {path}")

def save_html(report: Report, path: pathlib.Path):
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Circular Dependency Report</title>
<style>body{{font-family:sans-serif;padding:2rem}} .score{{font-size:2rem}}
.cycle{{margin:1rem 0;padding:0.5rem;background:#f8f9fa;border-left:4px solid #dc3545}}
.error{{border-color:#dc3545}} .warning{{border-color:#ffc107}}
</style></head><body>
<h1>Circular Dependency Report</h1>
<p>Score: <span class="score">{report.score}/100</span></p>
<p>Files: {report.files_scanned} | Nodes: {report.total_nodes} | Edges: {report.total_edges}</p>
<h2>Cycles ({len(report.cycles)})</h2>
"""
    for c in report.cycles:
        cls = "error" if c.severity == "CRITICAL" else "warning"
        html += f'<div class="cycle {cls}"><strong>{c.severity}</strong> {" → ".join(c.nodes)}<br><small>Confidence: {c.confidence}</small></div>'
    html += "</body></html>"
    with open(path, "w") as f:
        f.write(html)
    print(f"  HTML saved to {path}")

def save_sarif(report: Report, path: pathlib.Path):
    sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "CircularDependencyChecker", "version": "2.0"}},
            "results": [
                {"ruleId": "CIRC-001", "level": "error" if c.severity == "CRITICAL" else "warning",
                 "message": {"text": f"Cycle: {' → '.join(c.nodes)}"},
                 "locations": [{"physicalLocation": {"artifactLocation": {"uri": d.file}, "region": {"startLine": d.line}}} for d in c.deps[:3]]
                } for c in report.cycles
            ]
        }]
    }
    with open(path, "w") as f:
        json.dump(sarif, f, indent=2)
    print(f"  SARIF saved to {path}")

# ---- Main ----
def main():
    parser = argparse.ArgumentParser(description="Circular Dependency Checker")
    parser.add_argument("--root", "-r", default=None, help="Root directory to scan (default: parent of script directory)")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE", help="Save JSON report")
    parser.add_argument("--html", metavar="FILE", help="Save HTML report")
    parser.add_argument("--sarif", metavar="FILE", help="Save SARIF report")
    parser.add_argument("--exclude", default=".venv,venv,__pycache__,tests,checker,docs,migrations")
    parser.add_argument("--max-workers", type=int, default=4)
    args = parser.parse_args()

    if args.root:
        root = pathlib.Path(args.root).resolve()
    else:
        root = _ROOT_DIR  # default to project root

    scanner = CircularDependencyScanner(root, args.exclude.split(","), args.max_workers)

    # Progress bar
    def progress(current, total):
        if not sys.stdout.isatty():
            return
        pct = current / total * 100
        bar = "█" * int(pct / 2) + "░" * (50 - int(pct / 2))
        print(f"\r  [{bar}] {current}/{total} ({pct:.1f}%)", end="", flush=True)
        if current >= total:
            print()

    report = scanner.scan(progress_callback=progress)
    print_report(report, args.verbose)
    if args.json:
        save_json(report, pathlib.Path(args.json))
    if args.html:
        save_html(report, pathlib.Path(args.html))
    if args.sarif:
        save_sarif(report, pathlib.Path(args.sarif))

if __name__ == "__main__":
    main()
