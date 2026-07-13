#!/usr/bin/env python3
"""
performance_anti_pattern_checker.py - Detect N+1 queries, query in loop, inefficient operations
==================================================================================================
Standar: ISO/IEC 25010 · Performa & Efisiensi
Fitur: Deteksi N+1, query dalam loop, dengan grouping per file dan deteksi eager loading
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
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

# ---- Setup logging ----
logger = logging.getLogger("perf_anti_pattern")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)

# ---- Ensure root directory is in sys.path ----
_THIS_DIR = pathlib.Path(__file__).resolve().parent
_ROOT_DIR = _THIS_DIR.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

# ---- RCA integration ----
try:
    from checker.core.rca import (
        Category,
        ErrorCode,
        RCAEngine,
        RCAResult,
        RCARule,
        Severity,
        analyze_exception,
        get_engine,
    )
    RCA_AVAIL = True
    logger.info("RCA engine imported successfully")
except ImportError:
    RCA_AVAIL = False
    class RCARule: pass
    class RCAResult: pass
    class Severity: pass
    class Category: pass
    class ErrorCode: pass
    def get_engine(): return None
    def analyze_exception(e, ctx): return None
    logger.warning("RCA engine not available.")

# ---- Custom RCA Rule ----
class PerformanceAntiPatternRule(RCARule):
    def __init__(self):
        if RCA_AVAIL:
            super().__init__(priority=150, category=Category.PERFORMANCE, name="PerformanceAntiPatternRule")
        else:
            self.priority = 150
            self.enabled = True
            self.name = "PerformanceAntiPatternRule"
            self.category = "PERFORMANCE"
            self.version = "1.0"
            self.author = "system"
            self._stats = {}

    def match(self, exc, frames, context) -> bool:
        if not RCA_AVAIL:
            return False
        if "performance" in str(exc).lower() or "N+1" in str(exc):
            return True
        if context and "kind" in context:
            return True
        return False

    def analyze(self, exc, frames, context):
        if not RCA_AVAIL:
            return None
        if context and "kind" in context:
            kind = context.get("kind")
            file = context.get("file", "unknown")
            line = context.get("line", 0)
            detail = context.get("detail", "")
            sev = Severity.HIGH if kind in ("N_PLUS_1", "QUERY_IN_LOOP") else Severity.MEDIUM
            return RCAResult(
                severity=sev,
                category=Category.PERFORMANCE,
                error_code=ErrorCode.ERP_VALIDATION,
                root_cause=f"Performance anti-pattern: {kind}",
                evidence=[f"File: {file}:{line}", f"Detail: {detail}"],
                impact=[
                    "Potential performance degradation under load.",
                    "May cause slow response times for API endpoints.",
                    "Could lead to database connection exhaustion."
                ],
                suggested_fix=(
                    "For N+1: Use eager loading (joinedload/selectinload) or batch queries. "
                    "For query in loop: Move query outside loop and use IN clause."
                ),
                raw_error=str(exc),
                confidence=0.85
            )
        return None

# ---- Color ----
COLOR = {
    "RED": "\033[91m", "GREEN": "\033[92m", "YELLOW": "\033[93m",
    "CYAN": "\033[96m", "MAGENTA": "\033[95m", "BOLD": "\033[1m", "RESET": "\033[0m"
}
def c(key: str) -> str: return COLOR.get(key, "")

# ---- AST Cache ----
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
class PerfIssue:
    file: str
    line: int
    kind: str  # QUERY_IN_LOOP, N_PLUS_1
    detail: str
    confidence: float
    rca: dict | None = None

@dataclass
class Report:
    issues: list[PerfIssue]
    total_files: int
    score: float
    scan_time: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

# ---- Helper AST functions ----
def get_full_attr_name(node: ast.AST) -> str:
    """Extract a string like 'self.repo' from an AST node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = get_full_attr_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""

def get_loop_target(node: ast.AST) -> str | None:
    """Return the loop variable name for a For loop, else None."""
    if isinstance(node, ast.For):
        if isinstance(node.target, ast.Name):
            return node.target.id
    return None

def depends_on_loop_var(call_node: ast.Call, loop_var: str | None) -> bool:
    """Check if any argument of the call uses the loop variable."""
    if not loop_var:
        return False
    for arg in call_node.args:
        for sub in ast.walk(arg):
            if isinstance(sub, ast.Name) and sub.id == loop_var:
                return True
    for kw in call_node.keywords:
        for sub in ast.walk(kw.value):
            if isinstance(sub, ast.Name) and sub.id == loop_var:
                return True
    return False

def has_eager_loading_on_call(call_node: ast.Call) -> bool:
    """
    Check if this call chain includes an .options() call with joinedload/selectinload.
    Example: session.query(Model).options(joinedload(...))
    """
    # Walk up the chain? Actually we have the call node, we can check its func.
    # If func is Attribute with attr 'options', and its value is a Call (the query),
    # then this call is the options call. But we need to see if options is applied.
    # Better: traverse from the call_node backwards? We'll check if any Call in chain
    # has attr 'options' and argument contains eager loading method.
    def _check(node):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "options":
                    for arg in node.args:
                        if isinstance(arg, ast.Call):
                            if isinstance(arg.func, ast.Name) and arg.func.id in EAGER_LOAD_METHODS:
                                return True
                            if isinstance(arg.func, ast.Attribute) and arg.func.attr in EAGER_LOAD_METHODS:
                                return True
                # Recurse into the base object
                return _check(node.func.value)
        return False
    return _check(call_node)

# ---- Main Checker ----
class PerformanceAntiPatternChecker:
    # Nama method yang menunjukkan READ query (SELECT)
    READ_METHODS = {
        "get", "fetch", "select", "all", "first", "one", "scalar",
        "count", "exists", "find"
    }

    # Nama method yang menunjukkan WRITE query - diabaikan
    WRITE_METHODS = {
        "add", "save", "update", "delete", "merge", "refresh",
        "insert", "bulk_insert", "bulk_save", "bulk_update"
    }

    # Ambiguous: execute, query
    AMBIGUOUS_METHODS = {"execute", "query"}

    # Non-query names (false positive prevention)
    NON_QUERY_NAMES = {
        "getattr", "setattr", "hasattr", "isinstance", "issubclass",
        "len", "sum", "max", "min", "sorted", "reversed", "enumerate",
        "zip", "map", "filter", "reduce", "any", "all",
        "format", "join", "split", "replace", "strip", "lower", "upper"
    }

    # Eager loading methods
    EAGER_LOAD_METHODS = {"selectinload", "joinedload", "subqueryload", "immediateload"}

    LOOP_TYPES = (ast.For, ast.While)

    # Path yang diabaikan (low-risk false positive)
    IGNORE_PATHS = {
        "migrations", "docs", "tests", "checker",
        "domain/shared_value_objects", "domain/dto",
        "adapters/coretax_djp",
        "adapters/primary_api/common",
        "adapters/primary_api/cli_command_adapter",
        "adapters/primary_api/grpc_accounting_service",
        "asgi.py",
        "fix_bom.py"
    }

    # Hanya scan folder ini untuk mengurangi false positive
    TARGET_PATHS = {
        "domain/", "application/service_layer/", "application/use_cases/",
        "adapters/secondary_impl/"
    }

    def __init__(self, root: pathlib.Path, exclude: list[str] = None, max_workers: int = 4):
        self.root = root
        self.exclude = set(exclude or [".venv", "venv", "__pycache__", "tests", "checker", "docs", "migrations"])
        self.max_workers = max_workers
        self._lock = threading.Lock()
        self._issues: list[PerfIssue] = []
        self._files = 0

        if RCA_AVAIL:
            engine = get_engine()
            if engine:
                try:
                    engine.register_rule(PerformanceAntiPatternRule())
                    logger.info("PerformanceAntiPatternRule registered with RCA engine.")
                except Exception as e:
                    logger.debug(f"RCA rule registration error: {e}")

    def scan(self, progress_callback: Callable | None = None) -> Report:
        t0 = time.perf_counter()
        files = list(self._walk())
        self._files = len(files)
        total = len(files)
        logger.info(f"Scanning {total} files for performance anti-patterns...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {ex.submit(self._analyze_file, f): f for f in files}
            for idx, future in enumerate(concurrent.futures.as_completed(futures)):
                if progress_callback:
                    progress_callback(idx + 1, total)
                try:
                    issues = future.result()
                    with self._lock:
                        self._issues.extend(issues)
                except Exception as e:
                    logger.debug(f"Error analyzing file: {e}")

        # RCA
        if RCA_AVAIL and self._issues:
            ctx = {
                "issue_count": len(self._issues),
                "sample": [{"file": i.file, "line": i.line, "kind": i.kind} for i in self._issues[:3]]
            }
            try:
                exc = RuntimeError("Performance anti-patterns detected")
                rca_result = analyze_exception(exc, ctx)
                if rca_result and self._issues:
                    rca_dict = rca_result.to_dict() if hasattr(rca_result, 'to_dict') else {"raw": str(rca_result)}
                    self._issues[0].rca = rca_dict
            except Exception as e:
                logger.debug(f"RCA analysis error: {e}")

        # Score: 100 - (issues * 5), min 0
        if not self._issues:
            score = 100.0
        else:
            score = max(0, 100 - len(self._issues) * 5)
        score = round(score, 2)

        return Report(
            issues=self._issues,
            total_files=self._files,
            score=score,
            scan_time=time.perf_counter() - t0
        )

    def _walk(self) -> Iterator[pathlib.Path]:
        for p in self.root.rglob("*.py"):
            if any(part in self.exclude for part in p.parts):
                continue
            if "checker" in str(p):
                continue
            rel = str(p.relative_to(self.root)).replace("\\", "/")
            # Hanya scan target paths
            for target in self.TARGET_PATHS:
                if target in rel:
                    break
            else:
                continue
            # Skip ignored paths
            for ignore in self.IGNORE_PATHS:
                if ignore in rel:
                    break
            else:
                yield p

    def _analyze_file(self, py_file: pathlib.Path) -> list[PerfIssue]:
        tree = get_ast(py_file)
        if tree is None:
            return []
        issues = []
        rel = str(py_file.relative_to(self.root))

        for node in ast.walk(tree):
            if isinstance(node, self.LOOP_TYPES):
                issues.extend(self._check_loop(node, rel, tree))

        return issues

    def _is_read_query_call(self, call_node: ast.Call) -> tuple[bool, str, bool, bool]:
        """
        Return (is_read_query, method_name, has_limit_one, depends_on_loop)
        We don't know loop var here, will be checked separately.
        """
        # Determine method name and object
        method_name = ""
        obj_name = ""
        if isinstance(call_node.func, ast.Attribute):
            method_name = call_node.func.attr
            obj_name = get_full_attr_name(call_node.func.value)
        elif isinstance(call_node.func, ast.Name):
            method_name = call_node.func.id
            obj_name = method_name  # function call like select(...)
        else:
            return (False, "", False, False)

        # Skip non-query names
        if method_name in self.NON_QUERY_NAMES:
            return (False, method_name, False, False)

        # Check for limit(1) or first/one
        has_limit_one = False
        if method_name == "limit":
            for arg in call_node.args:
                if isinstance(arg, ast.Constant) and arg.value == 1:
                    has_limit_one = True
        if method_name in ("first", "one"):
            has_limit_one = True

        # Detect if this is likely a database read
        is_read = False

        # 1. If object name contains repo/session/db/store/query/engine
        db_keywords = ("repo", "session", "db", "store", "query", "engine")
        if any(kw in obj_name.lower() for kw in db_keywords):
            if method_name in self.READ_METHODS:
                is_read = True
            elif method_name in self.AMBIGUOUS_METHODS:
                # Check for raw SQL SELECT
                for arg in call_node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if "SELECT" in arg.value.upper():
                            is_read = True
                            break

        # 2. Function calls like select(...) from sqlalchemy
        if isinstance(call_node.func, ast.Name) and method_name in ("select", "fetch"):
            is_read = True

        # 3. execute with SELECT string
        if method_name in ("execute", "query"):
            for arg in call_node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if "SELECT" in arg.value.upper():
                        is_read = True
                        break

        # Skip write methods
        if method_name in self.WRITE_METHODS:
            is_read = False

        return (is_read, method_name, has_limit_one, False)  # depends handled later

    def _check_loop(self, loop_node: ast.AST, rel: str, tree: ast.AST) -> list[PerfIssue]:
        issues = []
        read_queries = []  # list of (lineno, method_name, has_limit_one, depends_on_loop, call_node)

        loop_var = get_loop_target(loop_node)  # only for For loops

        # Collect all read query calls inside this loop (excluding nested loops)
        for child in ast.walk(loop_node):
            if isinstance(child, self.LOOP_TYPES) and child is not loop_node:
                continue
            if isinstance(child, ast.Call):
                is_read, method, has_limit_one, _ = self._is_read_query_call(child)
                if is_read:
                    # Check dependency on loop variable
                    depends = depends_on_loop_var(child, loop_var)
                    # If no loop_var (while), assume depends=True to be safe
                    if loop_var is None:
                        depends = True
                    read_queries.append((child.lineno, method, has_limit_one, depends, child))

        # Filter out queries with limit(1) or first() as safe
        safe_queries = []
        for item in read_queries:
            if item[2]:  # has_limit_one
                continue
            safe_queries.append(item)

        if not safe_queries:
            return []

        # Check if any query uses eager loading
        eager_used = any(has_eager_loading_on_call(item[4]) for item in safe_queries)

        # Separate dependent and independent queries
        dependent = [q for q in safe_queries if q[3]]
        independent = [q for q in safe_queries if not q[3]]

        # Decision:
        # - If there are >=2 dependent queries -> N+1 (high confidence)
        # - If there is 1 dependent query -> QUERY_IN_LOOP
        # - If there are only independent queries, we may still warn but with lower confidence
        #   especially if there are multiple.

        if len(dependent) >= 2:
            methods = list(set([q[1] for q in dependent]))
            detail = f"Multiple database read queries inside loop (potential N+1): {', '.join(methods)}"
            if eager_used:
                detail += " (eager loading detected, but multiple queries remain)"
            confidence = 0.85 if not eager_used else 0.70
            issues.append(PerfIssue(
                file=rel,
                line=loop_node.lineno,
                kind="N_PLUS_1",
                detail=detail,
                confidence=confidence,
                rca=None
            ))
        elif len(dependent) == 1:
            method = dependent[0][1]
            detail = f"Database read query inside loop: {method}"
            if eager_used:
                detail += " (eager loading detected)"
            confidence = 0.75 if not eager_used else 0.60
            issues.append(PerfIssue(
                file=rel,
                line=loop_node.lineno,
                kind="QUERY_IN_LOOP",
                detail=detail,
                confidence=confidence,
                rca=None
            ))
        else:
            # Only independent queries
            if len(independent) >= 2:
                methods = list(set([q[1] for q in independent]))
                detail = f"Multiple database read queries inside loop (potential N+1, not dependent on loop variable): {', '.join(methods)}"
                confidence = 0.60
                issues.append(PerfIssue(
                    file=rel,
                    line=loop_node.lineno,
                    kind="N_PLUS_1",
                    detail=detail,
                    confidence=confidence,
                    rca=None
                ))
            elif len(independent) == 1:
                method = independent[0][1]
                detail = f"Database read query inside loop (not dependent on loop variable): {method}"
                confidence = 0.55
                issues.append(PerfIssue(
                    file=rel,
                    line=loop_node.lineno,
                    kind="QUERY_IN_LOOP",
                    detail=detail,
                    confidence=confidence,
                    rca=None
                ))

        return issues

# ---- Reporters ----
def print_report(r: Report, verbose: bool = False):
    print(f"\n{c('CYAN')}{'='*80}{c('RESET')}")
    print(f"{c('BOLD')}PERFORMANCE ANTI-PATTERN CHECKER REPORT{c('RESET')}")
    print(f"{'='*80}")
    print(f"  Timestamp       : {r.timestamp}")
    print(f"  Files           : {r.total_files}")
    print(f"  Total Issues    : {len(r.issues)}")
    print(f"  RCA Engine      : {'✅ Active' if RCA_AVAIL else '⚠️ Not available'}")
    print(f"  Score           : {c('GREEN') if r.score >= 90 else c('YELLOW') if r.score >= 70 else c('RED')}{r.score}/100{c('RESET')}")
    print(f"  Scan time       : {r.scan_time:.2f}s")

    if not r.issues:
        print(f"\n  {c('GREEN')}✅ No performance anti-patterns detected.{c('RESET')}")
        return

    # Group issues by file
    grouped = defaultdict(list)
    for issue in r.issues:
        grouped[issue.file].append(issue)

    print(f"\n{c('YELLOW')}Issues by File:{c('RESET')}")
    print("  " + "=" * 76)

    # Sort files with most issues first
    sorted_files = sorted(grouped.items(), key=lambda x: len(x[1]), reverse=True)

    for file_path, issues in sorted_files:
        n1_count = sum(1 for i in issues if i.kind == "N_PLUS_1")
        qil_count = sum(1 for i in issues if i.kind == "QUERY_IN_LOOP")

        print(f"\n  {c('BOLD')}{file_path}{c('RESET')}")
        print(f"    N+1: {c('RED')}{n1_count}{c('RESET')}  |  Query in loop: {c('YELLOW')}{qil_count}{c('RESET')}")

        for issue in issues[:10]:
            color = c("RED") if issue.kind == "N_PLUS_1" else c("YELLOW")
            print(f"      {color}[{issue.kind}]{c('RESET')} line {issue.line:4d}  (conf:{issue.confidence:.2f})")
            print(f"          {issue.detail}")
            if verbose and issue.rca:
                if isinstance(issue.rca, dict):
                    rc = issue.rca.get('root_cause', '')
                    if rc:
                        print(f"          RCA: {rc[:100]}")
                    fix = issue.rca.get('suggested_fix', '')
                    if fix:
                        print(f"          Saran: {fix[:100]}")

        if len(issues) > 10:
            print(f"      ... and {len(issues)-10} more issues in this file")

    total_n1 = sum(1 for i in r.issues if i.kind == "N_PLUS_1")
    total_qil = len(r.issues) - total_n1
    print(f"\n  {c('CYAN')}{'='*76}{c('RESET')}")
    print(f"  {c('BOLD')}Summary:{c('RESET')}")
    print(f"    Total files with issues: {len(grouped)}")
    print(f"    N+1 issues: {c('RED')}{total_n1}{c('RESET')} (High priority)")
    print(f"    Query in loop issues: {c('YELLOW')}{total_qil}{c('RESET')} (Medium priority)")
    print(f"  {c('CYAN')}{'='*76}{c('RESET')}")

def save_json(r: Report, path: pathlib.Path):
    data = {
        "timestamp": r.timestamp,
        "score": r.score,
        "total_files": r.total_files,
        "scan_time": r.scan_time,
        "issues": [
            {"file": i.file, "line": i.line, "kind": i.kind, "detail": i.detail, "confidence": i.confidence}
            for i in r.issues
        ]
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  JSON saved to {path}")

def save_html(r: Report, path: pathlib.Path):
    grouped = defaultdict(list)
    for issue in r.issues:
        grouped[issue.file].append(issue)

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Performance Anti-Pattern Report</title>
<style>
body{{font-family:sans-serif;padding:2rem;background:#f8fafc}}
.issue{{margin:0.5rem 0;padding:0.5rem;border-left:4px solid #dc2626;background:#fef2f2;border-radius:4px}}
.score{{font-size:2rem;font-weight:bold}}
.file-group{{background:#f1f5f9;padding:1rem;margin:1rem 0;border-radius:8px}}
.n1{{color:#dc2626}} .qil{{color:#ca8a04}}
</style>
</head><body>
<h1>⚡ Performance Anti-Pattern Report</h1>
<p>Score: <span class="score" style="color:{'#16a34a' if r.score>=90 else '#ca8a04' if r.score>=70 else '#dc2626'}">{r.score}/100</span></p>
<p>Files: {r.total_files} | Total Issues: {len(r.issues)}</p>
<h2>Issues by File</h2>
"""
    for file_path, issues in grouped.items():
        n1_count = sum(1 for i in issues if i.kind == "N_PLUS_1")
        qil_count = len(issues) - n1_count
        html += f"""
<div class="file-group">
    <h3>{file_path} <span style="font-size:0.9rem;font-weight:normal">N+1: <span class="n1">{n1_count}</span> | Query in loop: <span class="qil">{qil_count}</span></span></h3>
"""
        for issue in issues[:20]:
            html += f"""
    <div class="issue">
        <strong>[{issue.kind}]</strong> line {issue.line} (conf:{issue.confidence:.2f})
        <br><small>{issue.detail}</small>
    </div>
"""
        if len(issues) > 20:
            html += f"    <p>... and {len(issues)-20} more issues</p>"
        html += "</div>"
    html += "</body></html>"
    with open(path, "w") as f:
        f.write(html)
    print(f"  HTML saved to {path}")

# ---- Main ----
def main():
    parser = argparse.ArgumentParser(description="Performance Anti-Pattern Checker")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    parser.add_argument("--json", metavar="FILE", help="Save JSON report")
    parser.add_argument("--html", metavar="FILE", help="Save HTML report")
    parser.add_argument("--exclude", default=".venv,venv,__pycache__,tests,checker,docs,deployment,migrations",
                        help="Comma-separated dirs to exclude")
    parser.add_argument("--max-workers", type=int, default=4, help="Number of parallel workers")
    parser.add_argument("--root", "-r", default=None, help="Root directory to scan (default: parent of script)")
    args = parser.parse_args()

    if args.root:
        root = pathlib.Path(args.root).resolve()
    else:
        root = _ROOT_DIR

    checker = PerformanceAntiPatternChecker(root, args.exclude.split(","), args.max_workers)

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
        save_json(report, pathlib.Path(args.json))
    if args.html:
        save_html(report, pathlib.Path(args.html))

if __name__ == "__main__":
    main()
