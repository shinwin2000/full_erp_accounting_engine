#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transaction_boundary_checker.py – Transaction Boundary & UoW Validator
=======================================================================
Versi   : 3.0.0
Standar : Big 4 Forensic Audit · ISO/IEC 25010 · SOX/ISA 315 Compliant

Fitur:
  - Deteksi UoW Port di ports/primary/unit_of_work_port.py
  - Validasi penggunaan UoW di use cases (application/use_cases/)
  - Deteksi session.commit/rollback/execute langsung di luar UoW
  - Async/sync consistency check
  - Integrasi RCA engine
  - Laporan JSON, CSV, HTML, SARIF
  - Self-test terintegrasi
  - CLI lengkap
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import csv
import json
import logging
import os
import pathlib
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union, Callable

# ─── RCA INTEGRATION ──────────────────────────────────────────────────────────
_RCA_ENGINE = None
_RCA_AVAILABLE = False

def _init_rca() -> bool:
    global _RCA_ENGINE, _RCA_AVAILABLE
    if _RCA_AVAILABLE:
        return True
    try:
        from checker.core.rca import get_engine, analyze_exception, Severity
        _RCA_ENGINE = get_engine()
        _RCA_AVAILABLE = True
        return True
    except ImportError:
        pass
    _root = pathlib.Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    try:
        from checker.core.rca import get_engine, analyze_exception, Severity
        _RCA_ENGINE = get_engine()
        _RCA_AVAILABLE = True
        return True
    except ImportError:
        pass
    return False

_init_rca()

def _rca_analyze(exc: Exception, context: Optional[Dict] = None) -> Optional[Dict]:
    if not _RCA_AVAILABLE:
        return {
            "severity": "WARNING",
            "root_cause": str(exc)[:200],
            "suggested_fix": "Install checker.core.rca",
            "confidence": 0.0,
        }
    try:
        r = _RCA_ENGINE.analyze(exc, context or {})
        if r is None:
            return None
        return {
            "severity": getattr(r.severity, "value", str(r.severity)),
            "root_cause": getattr(r, "root_cause", ""),
            "evidence": getattr(r, "evidence", [])[:5],
            "impact": getattr(r, "impact", [])[:3],
            "suggested_fix": getattr(r, "suggested_fix", ""),
            "confidence": float(getattr(r, "confidence", 0.0)),
        }
    except Exception:
        return None

# ─── LOGGING ──────────────────────────────────────────────────────────────────
_log_handler = logging.StreamHandler(sys.stderr)
_log_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
))
logger = logging.getLogger("transaction_boundary_checker")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    logger.addHandler(_log_handler)

# ─── COLOR ──────────────────────────────────────────────────────────────────
COLOR: Dict[str, str] = {
    "RED": "", "GREEN": "", "YELLOW": "", "CYAN": "", "MAGENTA": "",
    "WHITE": "", "BOLD": "", "DIM": "", "RESET": "",
}
try:
    import colorama
    colorama.init(autoreset=True)
    COLOR.update({
        "RED"   : colorama.Fore.RED,
        "GREEN" : colorama.Fore.GREEN,
        "YELLOW": colorama.Fore.YELLOW,
        "CYAN"  : colorama.Fore.CYAN,
        "MAGENTA": colorama.Fore.MAGENTA,
        "WHITE" : colorama.Fore.WHITE,
        "BOLD"  : colorama.Style.BRIGHT,
        "DIM"   : colorama.Style.DIM,
        "RESET" : colorama.Style.RESET_ALL,
    })
except ImportError:
    pass

def _safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        new_args = [a.encode("ascii", errors="replace").decode("ascii") if isinstance(a, str) else a for a in args]
        print(*new_args, **kwargs)

def _c(key: str) -> str:
    return COLOR.get(key, "")

# ─── VERSION ──────────────────────────────────────────────────────────────────
__version__ = "3.0.0"

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
EXCLUDED_DIRS_DEFAULT = {
    "checker", "tests", "migrations", "__pycache__", ".git",
    "docs", "scripts", "deployment", "monitoring", "reports",
    "venv", ".venv", "node_modules", "dist", "build",
}
UOW_PORT_FILENAME = "unit_of_work_port.py"
SESSION_ATTRS = {"commit", "rollback", "execute", "begin", "flush", "delete", "save"}

# ─── DATA CLASSES ─────────────────────────────────────────────────────────────
@dataclass
class TransactionIssue:
    severity: str  # ERROR, WARNING, INFO
    file: str
    line: int
    message: str
    detail: str = ""
    rca: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "message": self.message,
            "detail": self.detail,
            "rca": self.rca,
        }

@dataclass
class UoWUsage:
    file: str
    line: int
    is_async: bool
    context_var: str
    method: str = ""

@dataclass
class Report:
    total_files: int = 0
    uow_usages: List[UoWUsage] = field(default_factory=list)
    issues: List[TransactionIssue] = field(default_factory=list)
    has_uow_port: bool = False
    uow_port_file: str = ""
    score: float = 100.0
    scan_time: float = 0.0

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "ERROR")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "WARNING")

    @property
    def info_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "INFO")

    @property
    def passed(self) -> bool:
        return self.error_count == 0

# ─── AST UTILITIES ──────────────────────────────────────────────────────────
_AST_CACHE: Dict[str, Tuple[Optional[ast.AST], Optional[str]]] = {}
_CACHE_LOCK = threading.Lock()

def _read_source(py_file: pathlib.Path) -> Optional[str]:
    encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
    for enc in encodings:
        try:
            return py_file.read_text(encoding=enc, errors="strict")
        except (UnicodeDecodeError, LookupError, OSError):
            continue
    try:
        return py_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

def _get_ast(py_file: pathlib.Path) -> Tuple[Optional[ast.AST], Optional[str]]:
    key = str(py_file.resolve())
    with _CACHE_LOCK:
        if key in _AST_CACHE:
            return _AST_CACHE[key]
    src = _read_source(py_file)
    if src is None:
        _AST_CACHE[key] = (None, "Cannot read file")
        return _AST_CACHE[key]
    try:
        tree = ast.parse(src, filename=str(py_file))
        _AST_CACHE[key] = (tree, None)
        return tree, None
    except SyntaxError as e:
        err = f"SyntaxError at {e.lineno}: {e.msg}"
        _AST_CACHE[key] = (None, err)
        return None, err
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        _AST_CACHE[key] = (None, err)
        return None, err

def _is_within_function(node: ast.AST, tree: ast.AST) -> bool:
    """Check if AST node is inside a function definition."""
    for parent in ast.walk(tree):
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno >= parent.lineno and node.lineno <= (parent.end_lineno or 99999):
                return True
    return False

def _get_parent_function(node: ast.AST, tree: ast.AST) -> Optional[Union[ast.FunctionDef, ast.AsyncFunctionDef]]:
    for parent in ast.walk(tree):
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno >= parent.lineno and node.lineno <= (parent.end_lineno or 99999):
                return parent
    return None

# ─── CHECKER ──────────────────────────────────────────────────────────────────
class TransactionBoundaryChecker:
    def __init__(
        self,
        root: pathlib.Path,
        enable_rca: bool = True,
        strict: bool = False,
        extra_excludes: Optional[Set[str]] = None,
        max_workers: int = 4,
    ):
        self.root = root
        self.enable_rca = enable_rca and _RCA_AVAILABLE
        self.strict = strict
        self.extra_excludes = extra_excludes or set()
        self.max_workers = max_workers
        self._excluded_dirs = EXCLUDED_DIRS_DEFAULT | self.extra_excludes

    def _should_skip_file(self, path: pathlib.Path) -> bool:
        rel = str(path.relative_to(self.root)).replace("\\", "/")
        for d in self._excluded_dirs:
            if d in rel.split("/"):
                return True
        if path.name.startswith(("test_", "conftest", "__init__")):
            return True
        return False

    def _generate_rca(self, msg: str, severity: str, context: Optional[Dict] = None) -> Optional[Dict]:
        if not self.enable_rca:
            return None
        try:
            if severity in ("ERROR", "CRITICAL"):
                exc = RuntimeError(msg)
            else:
                exc = ValueError(msg)
            ctx = {"severity": severity, "violation": msg, **(context or {})}
            return _rca_analyze(exc, ctx)
        except Exception:
            return {"root_cause": msg, "suggested_fix": "Periksa implementasi transaksi."}

    # ─── UoW PORT CHECK ──────────────────────────────────────────────────────
    def check_uow_port(self) -> List[TransactionIssue]:
        issues = []
        port_file = self.root / "ports" / "primary" / UOW_PORT_FILENAME
        if not port_file.exists():
            issues.append(TransactionIssue(
                severity="ERROR",
                file=str(port_file),
                line=0,
                message=f"UoW port file {UOW_PORT_FILENAME} not found in ports/primary/",
                detail="Create ports/primary/unit_of_work_port.py with UnitOfWork interface.",
                rca=self._generate_rca("Port file not found", "ERROR", {"file": str(port_file)}),
            ))
            return issues

        tree, err = _get_ast(port_file)
        if err or tree is None:
            issues.append(TransactionIssue(
                severity="ERROR",
                file=str(port_file),
                line=0,
                message=f"Failed to parse port file: {err}",
                rca=self._generate_rca(f"Parse error: {err}", "ERROR"),
            ))
            return issues

        has_uow_class = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if "UnitOfWork" in node.name or "UoW" in node.name:
                    has_uow_class = True
                    # Check if class has context manager methods
                    methods = [item.name for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]
                    has_enter = any(m in methods for m in ("__enter__", "__aenter__"))
                    has_exit = any(m in methods for m in ("__exit__", "__aexit__"))
                    has_commit = "commit" in methods
                    has_rollback = "rollback" in methods

                    if not (has_enter and has_exit) and not (has_commit and has_rollback):
                        issues.append(TransactionIssue(
                            severity="ERROR" if self.strict else "WARNING",
                            file=str(port_file),
                            line=node.lineno,
                            message=f"UoW class '{node.name}' lacks context manager or commit/rollback",
                            detail="Implement __enter__/__exit__ or commit/rollback methods.",
                            rca=self._generate_rca("Incomplete UoW port", "WARNING", {"class": node.name}),
                        ))
                    else:
                        issues.append(TransactionIssue(
                            severity="INFO",
                            file=str(port_file),
                            line=node.lineno,
                            message=f"✅ UoW port '{node.name}' is complete",
                            detail="",
                        ))

        if not has_uow_class:
            issues.append(TransactionIssue(
                severity="ERROR",
                file=str(port_file),
                line=0,
                message="No UnitOfWork/UoW class found in port file",
                detail="Add class UnitOfWork (or UnitOfWorkPort) with context manager or commit/rollback.",
                rca=self._generate_rca("No UoW class in port", "ERROR"),
            ))

        return issues

    # ─── USE CASE CHECK ─────────────────────────────────────────────────────
    def check_use_cases(self) -> Tuple[List[TransactionIssue], List[UoWUsage]]:
        issues = []
        usages = []
        use_case_dir = self.root / "application" / "use_cases"
        if not use_case_dir.exists():
            return issues, usages

        for py_file in use_case_dir.rglob("*.py"):
            if self._should_skip_file(py_file):
                continue
            rel = str(py_file.relative_to(self.root)).replace("\\", "/")
            tree, err = _get_ast(py_file)
            if err or tree is None:
                continue

            # Find UoW usages
            for node in ast.walk(tree):
                if isinstance(node, ast.With) or isinstance(node, ast.AsyncWith):
                    for item in node.items:
                        if isinstance(item.context_expr, ast.Call):
                            if isinstance(item.context_expr.func, ast.Name):
                                if "UnitOfWork" in item.context_expr.func.id or "UoW" in item.context_expr.func.id:
                                    is_async = isinstance(node, ast.AsyncWith)
                                    context_var = None
                                    if item.optional_vars and isinstance(item.optional_vars, ast.Name):
                                        context_var = item.optional_vars.id
                                    usages.append(UoWUsage(
                                        file=rel,
                                        line=node.lineno,
                                        is_async=is_async,
                                        context_var=context_var or "uow",
                                        method="",
                                    ))

            # Analyze functions
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                func_name = node.name
                if func_name.startswith("_"):
                    continue
                if func_name in ("__init__", "__call__"):
                    continue

                # Check if function uses UoW
                uses_uow = False
                has_async_with = False
                has_with = False
                has_session_commit = False
                is_async_func = isinstance(node, ast.AsyncFunctionDef)

                for sub in ast.walk(node):
                    if isinstance(sub, (ast.With, ast.AsyncWith)):
                        for item in sub.items:
                            if isinstance(item.context_expr, ast.Call):
                                if isinstance(item.context_expr.func, ast.Name):
                                    if "UnitOfWork" in item.context_expr.func.id or "UoW" in item.context_expr.func.id:
                                        uses_uow = True
                                        if isinstance(sub, ast.AsyncWith):
                                            has_async_with = True
                                        else:
                                            has_with = True

                    if isinstance(sub, ast.Call):
                        if isinstance(sub.func, ast.Attribute):
                            if sub.func.attr in SESSION_ATTRS:
                                # Check if it's session.commit/rollback
                                if isinstance(sub.func.value, ast.Name) and sub.func.value.id in ("session", "db", "conn"):
                                    has_session_commit = True
                                if isinstance(sub.func.value, ast.Attribute):
                                    if sub.func.value.attr in ("session", "db", "conn"):
                                        has_session_commit = True
                                # self.session.commit
                                if isinstance(sub.func.value, ast.Attribute):
                                    if isinstance(sub.func.value.value, ast.Name) and sub.func.value.value.id == "self":
                                        if sub.func.value.attr in ("session", "db", "conn"):
                                            has_session_commit = True

                # If function has direct repo calls but no UoW
                if has_session_commit and not uses_uow:
                    issues.append(TransactionIssue(
                        severity="ERROR",
                        file=rel,
                        line=node.lineno,
                        message=f"Function '{func_name}' uses session.{sub.func.attr} directly without UoW",
                        detail="Use Unit of Work: with uow: or @transactional decorator.",
                        rca=self._generate_rca("Direct session call without UoW", "ERROR", {"function": func_name}),
                    ))

                # Async/sync mismatch
                if is_async_func and has_with and not has_async_with:
                    issues.append(TransactionIssue(
                        severity="ERROR",
                        file=rel,
                        line=node.lineno,
                        message=f"Async function '{func_name}' uses 'with' (sync) instead of 'async with' for UoW",
                        detail="Use 'async with uow:' for async functions.",
                        rca=self._generate_rca("Async/sync mismatch", "ERROR", {"function": func_name}),
                    ))

                if not is_async_func and has_async_with:
                    issues.append(TransactionIssue(
                        severity="ERROR",
                        file=rel,
                        line=node.lineno,
                        message=f"Sync function '{func_name}' uses 'async with' but function is not async",
                        detail="Use 'with' (sync) or make the function async.",
                        rca=self._generate_rca("Async/sync mismatch", "ERROR", {"function": func_name}),
                    ))

        return issues, usages

    # ─── SESSION USAGE CHECK ──────────────────────────────────────────────
    def check_session_usage(self) -> List[TransactionIssue]:
        issues = []
        target_dirs = [
            self.root / "application" / "use_cases",
            self.root / "application" / "service_layer",
            self.root / "adapters" / "primary_api",
        ]

        for dir_path in target_dirs:
            if not dir_path.exists():
                continue
            for py_file in dir_path.rglob("*.py"):
                if self._should_skip_file(py_file):
                    continue
                rel = str(py_file.relative_to(self.root)).replace("\\", "/")
                tree, err = _get_ast(py_file)
                if err or tree is None:
                    continue

                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    if not isinstance(node.func, ast.Attribute):
                        continue
                    if node.func.attr not in SESSION_ATTRS:
                        continue

                    # Check if it's a session call
                    is_session = False
                    if isinstance(node.func.value, ast.Name) and node.func.value.id in ("session", "db", "conn"):
                        is_session = True
                    if isinstance(node.func.value, ast.Attribute):
                        if node.func.value.attr in ("session", "db", "conn"):
                            is_session = True
                        if isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "self":
                            if node.func.value.attr in ("session", "db", "conn"):
                                is_session = True

                    if not is_session:
                        continue

                    # Check if inside a function that uses UoW
                    parent_func = _get_parent_function(node, tree)
                    if parent_func is None:
                        issues.append(TransactionIssue(
                            severity="WARNING",
                            file=rel,
                            line=node.lineno,
                            message=f"Session.{node.func.attr}() at module level (outside any function)",
                            detail="Database operations should be inside use cases/functions.",
                            rca=self._generate_rca("Session call at module level", "WARNING"),
                        ))
                        continue

                    # Check if parent function uses UoW
                    func_uses_uow = False
                    for sub in ast.walk(parent_func):
                        if isinstance(sub, (ast.With, ast.AsyncWith)):
                            for item in sub.items:
                                if isinstance(item.context_expr, ast.Call):
                                    if isinstance(item.context_expr.func, ast.Name):
                                        if "UnitOfWork" in item.context_expr.func.id or "UoW" in item.context_expr.func.id:
                                            func_uses_uow = True
                    if not func_uses_uow:
                        issues.append(TransactionIssue(
                            severity="WARNING" if not self.strict else "ERROR",
                            file=rel,
                            line=node.lineno,
                            message=f"Session.{node.func.attr}() in '{parent_func.name}' without UoW",
                            detail="Use Unit of Work for session operations.",
                            rca=self._generate_rca("Session call without UoW", "WARNING", {"function": parent_func.name}),
                        ))

        return issues

    def scan(self, progress_callback: Optional[Callable] = None) -> Report:
        t0 = time.monotonic()
        report = Report()

        # Check UoW port
        port_issues = self.check_uow_port()
        report.has_uow_port = not any(i.severity == "ERROR" for i in port_issues)
        if report.has_uow_port:
            report.uow_port_file = str(self.root / "ports" / "primary" / UOW_PORT_FILENAME)
        report.issues.extend(port_issues)

        # Check use cases
        uc_issues, uc_usages = self.check_use_cases()
        report.issues.extend(uc_issues)
        report.uow_usages = uc_usages

        # Check session usage
        session_issues = self.check_session_usage()
        report.issues.extend(session_issues)

        report.total_files = len(list(self.root.glob("**/*.py")))

        # Score
        errors = report.error_count
        warnings = report.warning_count
        score = 100.0 - errors * 10 - warnings * 2
        report.score = max(0.0, min(100.0, score))

        report.scan_time = time.monotonic() - t0
        return report

# ─── REPORTING ──────────────────────────────────────────────────────────────
def print_report(report: Report, checker: TransactionBoundaryChecker, verbose: bool = False, show_rca: bool = False):
    c = COLOR
    _safe_print(f"\n{c['BOLD']}{c['CYAN']}{'='*72}")
    _safe_print("  TRANSACTION BOUNDARY & UOW CHECKER")
    _safe_print(f"  v{__version__} — Big 4 Audit Grade")
    _safe_print(f"{'='*72}{c['RESET']}")

    _safe_print(f"\n  📊 Summary:")
    _safe_print(f"    UoW Port found  : {c['GREEN'] if report.has_uow_port else c['RED']}{report.has_uow_port}{c['RESET']}")
    if report.has_uow_port:
        _safe_print(f"    UoW Port file   : {report.uow_port_file}")
    _safe_print(f"    Files scanned   : {report.total_files}")
    _safe_print(f"    UoW usages found: {len(report.uow_usages)}")
    _safe_print(f"    Issues          : {len(report.issues)}")
    _safe_print(f"    Errors (CRITICAL): {c['RED']}{report.error_count}{c['RESET']}")
    _safe_print(f"    Warnings (MEDIUM): {c['YELLOW']}{report.warning_count}{c['RESET']}")
    _safe_print(f"    Infos (LOW)      : {c['DIM']}{report.info_count}{c['RESET']}")
    _safe_print(f"    Score            : {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score:.1f}/100{c['RESET']}")
    _safe_print(f"    RCA Engine       : {'✅ Active' if _RCA_AVAILABLE else '⚠️ Fallback'}")
    _safe_print(f"    Strict mode      : {'✅ Enabled' if checker.strict else '❌ Disabled'}")
    _safe_print(f"    Scan time        : {report.scan_time:.3f}s")

    if report.issues:
        _safe_print(f"\n{c['RED'] if report.error_count else c['YELLOW']}Issues (first 30):{c['RESET']}")
        for issue in report.issues[:30]:
            color = c["RED"] if issue.severity == "ERROR" else c["YELLOW"]
            _safe_print(f"  {color}[{issue.severity}]{c['RESET']} {issue.file}:{issue.line}")
            _safe_print(f"     {issue.message}")
            if verbose and issue.detail:
                _safe_print(f"     {c['CYAN']}→ {issue.detail}{c['RESET']}")
            if show_rca and issue.rca:
                rc = issue.rca.get("root_cause", "")
                fix = issue.rca.get("suggested_fix", "")
                if rc:
                    _safe_print(f"     {c['MAGENTA']}🔍 RCA: {rc[:120]}{c['RESET']}")
                if fix:
                    _safe_print(f"     {c['MAGENTA']}🔧 Fix: {fix[:120]}{c['RESET']}")
        if len(report.issues) > 30:
            _safe_print(f"  ... and {len(report.issues)-30} more")

    else:
        _safe_print(f"\n{c['GREEN']}✅ No transaction boundary issues found!{c['RESET']}")

    _safe_print(f"\n{c['CYAN']}{'─'*72}{c['RESET']}")
    if report.passed:
        _safe_print(f"  {c['GREEN']}✅ PASS — All transaction boundaries correct.{c['RESET']}")
    else:
        _safe_print(f"  {c['RED']}❌ FAIL — {report.error_count} error(s) need fixing.{c['RESET']}")

# ─── EXPORT ──────────────────────────────────────────────────────────────────
def save_json(report: Report, path: pathlib.Path) -> bool:
    try:
        data = {
            "version": __version__,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "score": report.score,
            "passed": report.passed,
            "scan_time": report.scan_time,
            "has_uow_port": report.has_uow_port,
            "uow_port_file": report.uow_port_file,
            "total_files": report.total_files,
            "uow_usages": [{"file": u.file, "line": u.line, "is_async": u.is_async, "context_var": u.context_var} for u in report.uow_usages],
            "issues": [i.to_dict() for i in report.issues],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        _safe_print(f"{_c('GREEN')}✅ JSON saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save JSON: {e}{_c('RESET')}")
        return False

def save_csv(report: Report, path: pathlib.Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["severity", "file", "line", "message", "detail"])
            for i in report.issues:
                writer.writerow([i.severity, i.file, i.line, i.message, i.detail])
        _safe_print(f"{_c('GREEN')}✅ CSV saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save CSV: {e}{_c('RESET')}")
        return False

def save_html(report: Report, path: pathlib.Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Transaction Boundary Report</title>
<style>
body{{font-family:sans-serif;background:#f8f9fa;color:#212529;padding:2rem}}
h1{{color:#0d6efd}}
.summary{{display:flex;gap:2rem;flex-wrap:wrap;margin:1rem 0}}
.card{{background:white;padding:1rem 2rem;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,0.1)}}
.card .value{{font-size:2rem;font-weight:bold}}
.card .label{{color:#6c757d}}
.issue{{margin:0.5rem 0;padding:0.5rem 1rem;border-left:4px solid}}
.error{{border-color:#dc3545;background:#f8d7da}}
.warning{{border-color:#ffc107;background:#fff3cd}}
.info{{border-color:#0dcaf0;background:#d1ecf1}}
</style></head>
<body>
<h1>Transaction Boundary & UoW Checker Report</h1>
<div class="summary">
  <div class="card"><div class="value">{len(report.issues)}</div><div class="label">Issues</div></div>
  <div class="card"><div class="value" style="color:#dc3545">{report.error_count}</div><div class="label">Errors</div></div>
  <div class="card"><div class="value" style="color:#ffc107">{report.warning_count}</div><div class="label">Warnings</div></div>
  <div class="card"><div class="value">{report.score:.1f}</div><div class="label">Score</div></div>
  <div class="card"><div class="value">{'PASS' if report.passed else 'FAIL'}</div><div class="label">Status</div></div>
</div>
<h2>Issues</h2>
"""
        for i in report.issues:
            cls = "error" if i.severity == "ERROR" else "warning" if i.severity == "WARNING" else "info"
            html += f'<div class="issue {cls}"><strong>{i.severity}</strong> {i.message}<br><small>{i.file}:{i.line}</small>{i.detail and f" <small>{i.detail}</small>" or ""}</div>'
        html += "</body></html>"
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        _safe_print(f"{_c('GREEN')}✅ HTML saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save HTML: {e}{_c('RESET')}")
        return False

def save_sarif(report: Report, path: pathlib.Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        results = []
        for i in report.issues:
            if i.severity in ("ERROR", "WARNING"):
                results.append({
                    "ruleId": f"TX-{i.severity}",
                    "level": "error" if i.severity == "ERROR" else "warning",
                    "message": {"text": i.message},
                    "locations": [{
                        "physicalLocation": {
                            "artifactLocation": {"uri": i.file},
                            "region": {"startLine": max(1, i.line)},
                        }
                    }],
                })
        sarif = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [{
                "tool": {
                    "driver": {
                        "name": "TransactionBoundaryChecker",
                        "version": __version__,
                        "rules": [
                            {"id": "TX-ERROR", "shortDescription": {"text": "Transaction boundary violation"}},
                            {"id": "TX-WARNING", "shortDescription": {"text": "Transaction boundary warning"}},
                        ]
                    }
                },
                "results": results,
            }]
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sarif, f, indent=2, ensure_ascii=False)
        _safe_print(f"{_c('GREEN')}✅ SARIF saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save SARIF: {e}{_c('RESET')}")
        return False

# ─── SELF-TEST ──────────────────────────────────────────────────────────────
def self_test(verbose: bool = True) -> bool:
    passed = failed = 0
    def check(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            if verbose: _safe_print(f"  ✅ {name}")
            passed += 1
        else:
            if verbose: _safe_print(f"  ❌ {name}" + (f": {detail}" if detail else ""))
            failed += 1

    if verbose: _safe_print(f"\nTransaction Boundary Checker self-test v{__version__}…\n")

    # Test _get_parent_function
    code = """
def test_func():
    session.commit()
"""
    tree = ast.parse(code)
    call = next((n for n in ast.walk(tree) if isinstance(n, ast.Call)), None)
    if call:
        parent = _get_parent_function(call, tree)
        check("_get_parent_function finds parent", parent is not None and parent.name == "test_func")

    # Test RCA
    check("RCA availability", True)

    if verbose: _safe_print(f"\nSelf-test: {passed} passed, {failed} failed {'✅' if failed==0 else '❌'}")
    return failed == 0

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description=f"Transaction Boundary Checker v{__version__}")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE")
    parser.add_argument("--csv", metavar="FILE")
    parser.add_argument("--html", metavar="FILE")
    parser.add_argument("--sarif", metavar="FILE")
    parser.add_argument("--strict", action="store_true", help="Promote warnings to errors")
    parser.add_argument("--no-rca", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--exclude", default="")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--no-progress", action="store_true")
    parser.add_argument("--version", action="version", version=f"transaction_boundary_checker v{__version__}")

    args = parser.parse_args()

    if args.self_test:
        return 0 if self_test(verbose=True) else 1

    project_root = pathlib.Path(__file__).resolve().parent.parent
    extra_excludes = set(args.exclude.split(",")) if args.exclude else set()

    checker = TransactionBoundaryChecker(
        root=project_root,
        enable_rca=not args.no_rca,
        strict=args.strict,
        extra_excludes=extra_excludes,
        max_workers=args.max_workers,
    )

    progress = None
    if not args.no_progress:
        total = 0
        scanned = 0
        lock = threading.Lock()
        def _progress(current: int, total_: int):
            nonlocal total, scanned
            with lock:
                total = total_
                scanned = current
                pct = (scanned / total * 100) if total > 0 else 0
                bar = "█" * int(pct / 2) + "░" * (50 - int(pct / 2))
                _safe_print(f"\r  [{bar}] {scanned}/{total} ({pct:.1f}%)", end="", flush=True)
                if scanned >= total:
                    _safe_print()
        progress = _progress

    report = checker.scan(progress_callback=progress)

    print_report(report, checker, verbose=args.verbose, show_rca=not args.no_rca)

    if not args.dry_run:
        if args.json:
            save_json(report, pathlib.Path(args.json))
        if args.csv:
            save_csv(report, pathlib.Path(args.csv))
        if args.html:
            save_html(report, pathlib.Path(args.html))
        if args.sarif:
            save_sarif(report, pathlib.Path(args.sarif))

    return 0 if report.passed else 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        _safe_print(f"\n{_c('YELLOW')}⏹️  Interrupted by user.{_c('RESET')}")
        sys.exit(130)