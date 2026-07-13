#!/usr/bin/env python3
"""
double_entry_integrity_checker.py - Ensure debit=credit in all journal entries
================================================================================
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
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

# ---- Setup logging ----
logger = logging.getLogger("double_entry")
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

# ---- RCA ----
try:
    from checker.core.rca import (
        Category,
        ErrorCode,
        RCAResult,
        RCARule,
        Severity,
        analyze_exception,
        get_engine,
    )
    RCA_AVAIL = True
except ImportError:
    RCA_AVAIL = False
    class RCARule: pass
    class RCAResult: pass
    class Severity: pass
    class Category: pass
    class ErrorCode: pass
    def get_engine(): return None
    def analyze_exception(e, ctx): return None

# ---- Color ----
COLOR = {"RED": "\033[91m", "GREEN": "\033[92m", "YELLOW": "\033[93m",
         "CYAN": "\033[96m", "MAGENTA": "\033[95m", "BOLD": "\033[1m", "RESET": "\033[0m"}
def c(k): return COLOR.get(k, "")

# ---- Cache ----
_AST_CACHE = {}
_CACHE_LOCK = threading.Lock()

def get_ast(p: pathlib.Path):
    key = str(p.resolve())
    with _CACHE_LOCK:
        if key in _AST_CACHE:
            return _AST_CACHE[key]
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        with _CACHE_LOCK:
            _AST_CACHE[key] = tree
        return tree
    except Exception:
        with _CACHE_LOCK:
            _AST_CACHE[key] = None
        return None

# ---- Data ----
@dataclass
class DebitCreditIssue:
    file: str
    line: int
    kind: str
    detail: str
    confidence: float
    rca: dict | None = None

@dataclass
class Report:
    issues: list[DebitCreditIssue]
    total_journal_funcs: int
    total_files: int
    score: float
    scan_time: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

# ---- Custom RCA Rule ----
class DoubleEntryRule(RCARule):
    def __init__(self):
        super().__init__(priority=180, category=Category.DDD, name="DoubleEntryRule")
    def match(self, exc, frames, context) -> bool:
        return "balance" in str(exc).lower() or (context and "func" in context)
    def analyze(self, exc, frames, context) -> RCAResult | None:
        if context and "func" in context:
            return RCAResult(
                severity=Severity.HIGH,
                category=Category.DDD,
                error_code=ErrorCode.ERP_VALIDATION,
                root_cause=f"Missing debit=credit validation in journal function '{context['func']}'",
                evidence=[f"File: {context.get('file', 'unknown')}"],
                impact=["Potential unbalanced journal entries."],
                suggested_fix=(
                    "Add: if sum(debits) != sum(credits): raise BalanceError(...)"
                ),
                raw_error=str(exc),
                confidence=0.9
            )
        return None

# ---- Main Checker ----
class DoubleEntryIntegrityChecker:
    # Kata kunci untuk fungsi yang membuat/memodifikasi jurnal
    ACTION_KEYWORDS = {"post", "create", "add", "update", "reverse", "submit", "approve"}
    JOURNAL_KEYWORDS = {"journal", "entry", "ledger"}

    # Kata kunci untuk fungsi query/read/factory (diabaikan)
    IGNORE_ACTION_KEYWORDS = {"get", "find", "exists", "export", "validate", "list", "search", "fetch", "summary", "dashboard", "service"}

    # Path yang relevan (hanya scan folder ini)
    RELEVANT_PATHS = {
        "domain/journal",
        "application/use_cases/journal",
        "application/service_layer/service_journal",
        "application/service_layer/service_ledger",
        "application/service_layer/service_ap",
        "application/service_layer/service_ar",
        "application/service_layer/service_consolidation",
        "adapters/primary_api/v1/fastapi_journal_router",
        "adapters/primary_api/v1/fastapi_ledger_router",
        "adapters/secondary_impl/sqlalchemy_ledger_repository",
        "adapters/secondary_impl/sqlalchemy_journal_repository",
        "bootstrap/ledger"
    }

    # Nama class yang diabaikan (repository)
    IGNORE_CLASSES = {"SQLAlchemyJournalRepository", "SQLAlchemyLedgerRepository"}

    def __init__(self, root: pathlib.Path, exclude: list[str] = None, max_workers: int = 4):
        self.root = root
        self.exclude = set(exclude or [])
        self.max_workers = max_workers
        self._lock = threading.Lock()
        self._issues: list[DebitCreditIssue] = []
        self._total_journal = 0
        self._files = 0

        if RCA_AVAIL:
            engine = get_engine()
            if engine:
                engine.register_rule(DoubleEntryRule())
                logger.info("DoubleEntryRule registered with RCA engine.")

    def scan(self, progress_callback: Callable | None = None) -> Report:
        t0 = time.perf_counter()
        files = list(self._walk())
        self._files = len(files)
        total = len(files)
        logger.info(f"Scanning {total} relevant files for double-entry integrity...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {ex.submit(self._analyze_file, f): f for f in files}
            for idx, future in enumerate(concurrent.futures.as_completed(futures)):
                if progress_callback:
                    progress_callback(idx + 1, total)
                try:
                    issues, journal_count = future.result()
                    with self._lock:
                        self._issues.extend(issues)
                        self._total_journal += journal_count
                except Exception as e:
                    logger.debug(f"Error: {e}")

        if RCA_AVAIL and self._issues:
            ctx = {"total_journal_funcs": self._total_journal, "issue_count": len(self._issues)}
            try:
                r = analyze_exception(RuntimeError("Double-entry issues"), ctx)
                if r and self._issues:
                    self._issues[0].rca = r.to_dict() if hasattr(r, 'to_dict') else {"raw": str(r)}
            except Exception:
                pass

        if not self._issues:
            score = 100.0
        else:
            score = max(0, 100 - len(self._issues) * 5 - self._total_journal * 0.01)
        score = round(score, 2)

        return Report(self._issues, self._total_journal, self._files, score, time.perf_counter() - t0)

    def _walk(self) -> Iterator[pathlib.Path]:
        for p in self.root.rglob("*.py"):
            if any(part in self.exclude for part in p.parts):
                continue
            if "checker" in str(p):
                continue
            rel = str(p.relative_to(self.root)).replace("\\", "/")
            # Hanya scan file di path yang relevan
            for relevant in self.RELEVANT_PATHS:
                if relevant in rel:
                    yield p
                    break

    def _analyze_file(self, py: pathlib.Path) -> tuple[list[DebitCreditIssue], int]:
        tree = get_ast(py)
        if tree is None:
            return [], 0
        issues = []
        journal_count = 0
        rel = str(py.relative_to(self.root))

        # Cek apakah file ini adalah repository class
        is_repository = any(cls in rel for cls in ["repository_impl", "repository_impl.py"])

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if is_repository:
                    # Repository functions are query/CRUD, skip all
                    continue
                if self._is_journal_creator_func(node):
                    journal_count += 1
                    issues.extend(self._analyze_func(node, rel))

        return issues, journal_count

    def _is_journal_creator_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        name = node.name.lower()
        # Skip private/internal methods (except those that create journal)
        if name.startswith('_') and 'journal' not in name and 'entry' not in name:
            return False

        # Skip functions with ignore keywords
        for ignore in self.IGNORE_ACTION_KEYWORDS:
            if ignore in name:
                return False

        # Must contain action keyword AND journal keyword
        has_action = any(action in name for action in self.ACTION_KEYWORDS)
        has_journal = any(journal in name for journal in self.JOURNAL_KEYWORDS)

        # Special case: functions with only journal keyword but no action (e.g., `reverse_journal`)
        # We'll consider them if they have debit/credit variables
        if has_action and has_journal:
            return True

        # If no action, check body for debit/credit and sum/validation
        if has_journal:
            has_debits = False
            has_credits = False
            has_validation = False
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Name) and child.func.id in {"validate_balance", "check_balance"}:
                        has_validation = True
                if isinstance(child, ast.Name):
                    if child.id == "debits" or child.id.endswith("_debits"):
                        has_debits = True
                    elif child.id == "credits" or child.id.endswith("_credits"):
                        has_credits = True
            # If has validation, treat as journal creator (even without action keyword)
            if has_validation:
                return True
            # If has both debits and credits, treat as journal creator
            if has_debits and has_credits:
                return True

        return False

    def _analyze_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef, rel: str) -> list[DebitCreditIssue]:
        issues = []
        has_validation = False

        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    if child.func.id in {"validate_balance", "check_balance", "ensure_balanced", "verify_balance"}:
                        has_validation = True
                elif isinstance(child.func, ast.Attribute):
                    if child.func.attr in {"validate_balance", "check_balance", "ensure_balanced", "verify_balance"}:
                        has_validation = True

        if not has_validation:
            rca = None
            if RCA_AVAIL:
                try:
                    r = analyze_exception(RuntimeError("No balance validation"), {"func": node.name, "file": rel})
                    rca = r.to_dict() if r else None
                except:
                    pass
            issues.append(DebitCreditIssue(
                file=rel,
                line=node.lineno,
                kind="MISSING_VALIDATION",
                detail=f"Function '{node.name}' creates/modifies journal but lacks balance validation",
                confidence=0.9,
                rca=rca
            ))

        return issues

# ---- Reporters ----
def print_report(r: Report, verbose: bool = False):
    print(f"\n{c('CYAN')}{'='*70}{c('RESET')}")
    print(f"{c('BOLD')}DOUBLE ENTRY INTEGRITY CHECKER REPORT{c('RESET')}")
    print(f"{'='*70}")
    print(f"  Timestamp   : {r.timestamp}")
    print(f"  Files       : {r.total_files}")
    print(f"  Journal funcs : {r.total_journal_funcs}")
    print(f"  Issues      : {len(r.issues)}")
    print(f"  Score       : {c('GREEN') if r.score >= 90 else c('YELLOW') if r.score >= 70 else c('RED')}{r.score}/100{c('RESET')}")
    print(f"  Scan time   : {r.scan_time:.2f}s")
    print(f"  RCA Engine  : {'✅ Active' if RCA_AVAIL else '⚠️ Not available'}")

    if r.issues:
        print(f"\n{c('RED')}Issues:{c('RESET')}")
        for issue in r.issues[:20]:
            print(f"  {c('YELLOW')}[{issue.kind}]{c('RESET')} {issue.file}:{issue.line} (conf:{issue.confidence:.2f})")
            print(f"      {issue.detail}")
            if verbose and issue.rca:
                if isinstance(issue.rca, dict):
                    rc = issue.rca.get('root_cause', '')
                    if rc:
                        print(f"      RCA: {rc}")
                    fix = issue.rca.get('suggested_fix', '')
                    if fix:
                        print(f"      Saran: {fix}")
        if len(r.issues) > 20:
            print(f"  ... and {len(r.issues)-20} more issues.")
    else:
        print(f"\n  {c('GREEN')}✅ No double-entry integrity issues detected.{c('RESET')}")

def save_json(r: Report, path: pathlib.Path):
    data = {
        "timestamp": r.timestamp,
        "score": r.score,
        "total_journal_funcs": r.total_journal_funcs,
        "total_files": r.total_files,
        "issues": [{"file": i.file, "line": i.line, "kind": i.kind, "detail": i.detail} for i in r.issues]
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  JSON saved to {path}")

def save_html(r: Report, path: pathlib.Path):
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Double Entry Integrity Report</title>
<style>body{{font-family:sans-serif;padding:2rem}} .issue{{background:#fef2f2;padding:1rem;margin:0.5rem 0;border-left:4px solid #dc2626}}</style>
</head><body>
<h1>Double Entry Integrity Report</h1>
<p>Score: {r.score}/100</p>
<p>Journal functions: {r.total_journal_funcs}</p>
<h2>Issues ({len(r.issues)})</h2>
"""
    for i in r.issues[:50]:
        html += f'<div class="issue"><strong>[{i.kind}]</strong> {i.file}:{i.line}<br>{i.detail}</div>'
    html += "</body></html>"
    with open(path, "w") as f:
        f.write(html)
    print(f"  HTML saved to {path}")

# ---- Main ----
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--json", metavar="FILE")
    p.add_argument("--html", metavar="FILE")
    p.add_argument("--exclude", default=".venv,venv,__pycache__,tests,checker,docs,deployment,migrations")
    p.add_argument("--max-workers", type=int, default=4)
    p.add_argument("--root", "-r", default=None)
    args = p.parse_args()

    root = pathlib.Path(args.root).resolve() if args.root else _ROOT_DIR
    checker = DoubleEntryIntegrityChecker(root, args.exclude.split(","), args.max_workers)

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
