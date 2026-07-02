#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker/use_cases_checker.py
=============================
Sovereign ERP System — Use Case / Command Handler Compliance Checker v3.1.0

PERBAIKAN v3.1.0:
  - Deteksi Use Case yang lebih ketat (hanya true use case)
  - Filter false positive: Schema, Response, Request, Error, Exception, Policy, Registry, Middleware
  - Prioritaskan file di application/use_cases/
  - RCA Engine tetap terintegrasi
  - Laporan JSON, CSV, HTML, SARIF
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
logger = logging.getLogger("use_cases_checker")
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
__version__ = "3.1.0"

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
EXECUTE_METHODS = {"execute", "handle", "__call__", "process", "run", "invoke"}
BASE_CLASS_NAMES = {"BaseUseCase", "CommandHandler", "QueryHandler", "UseCase", "Handler"}
VALIDATION_KEYWORDS = {"validate", "is_valid", "valid", "pydantic", "base_model", "model_validate", "parse_obj"}
EXCLUDED_DIRS_DEFAULT = {
    "checker", "tests", "migrations", "__pycache__", ".git",
    "docs", "scripts", "deployment", "monitoring", "reports",
    "venv", ".venv", "node_modules", "dist", "build",
}
SEVERITY_WEIGHTS = {"CRITICAL": 20, "HIGH": 10, "MEDIUM": 5, "LOW": 2, "INFO": 0}

# ─── FALSE POSITIVE FILTERS ──────────────────────────────────────────────────
SKIP_CLASS_PATTERNS = {
    "Schema", "Response", "Request", "Error", "Exception",
    "Policy", "Registry", "Middleware", "Action", "ActionType",
    "Command", "Query", "DTO", "Dto", "Model", "Table",
}

# ─── DATA CLASSES ─────────────────────────────────────────────────────────────
@dataclass
class UseCaseViolation:
    severity: str
    file: str
    class_name: str
    line: int
    message: str
    suggestion: str
    rca: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {
            "severity": self.severity,
            "file": self.file,
            "class": self.class_name,
            "line": self.line,
            "message": self.message,
            "suggestion": self.suggestion,
            "rca": self.rca,
        }

@dataclass
class UseCaseInfo:
    file: str
    class_name: str
    line: int
    has_execute: bool
    has_type_hints: bool
    has_dependency_injection: bool
    has_error_handling: bool
    has_transaction_management: bool
    has_validation: bool
    is_async: bool
    has_return_annotation: bool
    violations: List[UseCaseViolation] = field(default_factory=list)

@dataclass
class Report:
    use_cases: List[UseCaseInfo] = field(default_factory=list)
    violations: List[UseCaseViolation] = field(default_factory=list)
    total_files_scanned: int = 0
    total_use_cases: int = 0
    score: float = 100.0
    scan_time: float = 0.0

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "CRITICAL" or v.severity == "HIGH")

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "MEDIUM")

    @property
    def info_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "LOW" or v.severity == "INFO")

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

def _get_method_names(node: ast.ClassDef) -> Set[str]:
    return {item.name for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))}

# ─── CHECKER ──────────────────────────────────────────────────────────────────
class UseCaseChecker:
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
        self.use_cases: List[UseCaseInfo] = []
        self._excluded_dirs = EXCLUDED_DIRS_DEFAULT | self.extra_excludes

    def _should_skip_file(self, path: pathlib.Path) -> bool:
        rel = str(path.relative_to(self.root)).replace("\\", "/")
        for d in self._excluded_dirs:
            if d in rel.split("/"):
                return True
        if path.name.startswith(("test_", "conftest", "__init__")):
            return True
        if path.name.endswith(("_test.py", "_tests.py")):
            return True
        return False

    def _get_python_files(self) -> List[pathlib.Path]:
        py_files = []
        # Priority: application/use_cases
        use_cases_dir = self.root / "application" / "use_cases"
        if use_cases_dir.exists():
            for p in use_cases_dir.rglob("*.py"):
                if not self._should_skip_file(p):
                    py_files.append(p)

        # Also scan other folders
        scan_dirs = ["application", "domain", "infrastructure", "bootstrap", "adapters"]
        for dir_name in scan_dirs:
            base = self.root / dir_name
            if not base.exists():
                continue
            for p in base.rglob("*.py"):
                if p.parent == use_cases_dir:
                    continue
                if not self._should_skip_file(p):
                    py_files.append(p)

        return sorted(set(py_files))

    def _should_skip_class(self, name: str) -> bool:
        """Filter false positive classes."""
        for pattern in SKIP_CLASS_PATTERNS:
            if pattern in name:
                return True
        return False

    def _is_use_case_class(self, node: ast.ClassDef, file_path: pathlib.Path) -> bool:
        """Determine if a class is a true Use Case."""
        name = node.name

        # Skip false positives
        if self._should_skip_class(name):
            return False

        rel_path = str(file_path.relative_to(self.root)).replace("\\", "/")

        # 1. If in use_cases directory, it's a use case
        if "application/use_cases/" in rel_path:
            return True

        # 2. Check base classes
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in BASE_CLASS_NAMES:
                return True
            if isinstance(base, ast.Attribute) and base.attr in BASE_CLASS_NAMES:
                return True

        # 3. Check decorators
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id in {"command_handler", "query_handler", "use_case", "handler"}:
                return True
            if isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name) and dec.func.id in {"command_handler", "query_handler"}:
                    return True

        # 4. Check for execute/handle method (strong indicator)
        method_names = _get_method_names(node)
        if any(m in EXECUTE_METHODS for m in method_names):
            return True

        return False

    def _has_type_hints(self, node: ast.ClassDef) -> bool:
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in EXECUTE_METHODS:
                has_return = item.returns is not None
                has_params = any(
                    arg.annotation is not None for arg in item.args.args if arg.arg not in ("self", "cls")
                )
                return has_return and has_params
        return False

    def _has_dependency_injection(self, node: ast.ClassDef) -> bool:
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                args = [arg for arg in item.args.args if arg.arg not in ("self", "cls")]
                return len(args) > 0
        return False

    def _has_error_handling(self, node: ast.ClassDef) -> bool:
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in EXECUTE_METHODS:
                for sub in ast.walk(item):
                    if isinstance(sub, ast.Try):
                        return True
        return False

    def _has_transaction_management(self, node: ast.ClassDef) -> bool:
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in EXECUTE_METHODS:
                for sub in ast.walk(item):
                    if isinstance(sub, ast.Call):
                        if isinstance(sub.func, ast.Attribute):
                            attr = sub.func.attr
                            if attr in {"commit", "rollback", "save", "flush", "begin"}:
                                return True
                        if isinstance(sub.func, ast.Name) and sub.func.id in {"commit", "rollback", "save"}:
                            return True
        return False

    def _has_validation(self, node: ast.ClassDef) -> bool:
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in EXECUTE_METHODS:
                for sub in ast.walk(item):
                    if isinstance(sub, ast.Call):
                        if isinstance(sub.func, ast.Attribute):
                            attr = sub.func.attr
                            if attr in {"parse_obj", "model_validate", "validate", "check_valid", "validate_python"}:
                                return True
                        if isinstance(sub.func, ast.Name) and sub.func.id in {"validate", "is_valid"}:
                            return True
        return False

    def _is_async_method(self, node: ast.ClassDef) -> bool:
        for item in node.body:
            if isinstance(item, ast.AsyncFunctionDef) and item.name in EXECUTE_METHODS:
                return True
        return False

    def _has_return_annotation(self, node: ast.ClassDef) -> bool:
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in EXECUTE_METHODS:
                return item.returns is not None
        return False

    def _get_execute_method(self, node: ast.ClassDef) -> Optional[Union[ast.FunctionDef, ast.AsyncFunctionDef]]:
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in EXECUTE_METHODS:
                return item
        return None

    def _generate_rca(self, violation_msg: str, severity: str, context: Optional[Dict] = None) -> Optional[Dict]:
        if not self.enable_rca:
            return None
        try:
            if severity in ("CRITICAL", "HIGH"):
                exc = RuntimeError(violation_msg)
            else:
                exc = ValueError(violation_msg)
            ctx = {"severity": severity, "violation": violation_msg, **(context or {})}
            return _rca_analyze(exc, ctx)
        except Exception:
            return {"root_cause": violation_msg, "suggested_fix": "Periksa implementasi Use Case."}

    def _analyze_class(self, node: ast.ClassDef, rel_path: str, file_path: pathlib.Path) -> Optional[UseCaseInfo]:
        if not self._is_use_case_class(node, file_path):
            return None

        has_exec = any(
            isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in EXECUTE_METHODS
            for item in node.body
        )
        has_th = self._has_type_hints(node)
        has_di = self._has_dependency_injection(node)
        has_eh = self._has_error_handling(node)
        has_tm = self._has_transaction_management(node)
        has_val = self._has_validation(node)
        is_async = self._is_async_method(node)
        has_return = self._has_return_annotation(node)

        violations: List[UseCaseViolation] = []
        execute_method = self._get_execute_method(node)
        line = execute_method.lineno if execute_method else node.lineno

        # Rule 1: Must have execute method
        if not has_exec:
            msg = "Use Case does not have execute(), handle(), or __call__() method."
            rca = self._generate_rca(msg, "CRITICAL", {"class": node.name})
            violations.append(UseCaseViolation(
                severity="CRITICAL",
                file=rel_path,
                class_name=node.name,
                line=node.lineno,
                message=msg,
                suggestion="Add 'def execute(self, request: RequestDTO) -> ResponseDTO:' as entry point.",
                rca=rca,
            ))

        # Rule 2: Must have type hints
        if has_exec and not has_th:
            msg = "execute() method lacks type hints for parameters or return value."
            rca = self._generate_rca(msg, "HIGH", {"class": node.name})
            violations.append(UseCaseViolation(
                severity="HIGH",
                file=rel_path,
                class_name=node.name,
                line=line,
                message=msg,
                suggestion="Add type hints: def execute(self, request: CreateInvoiceRequest) -> InvoiceResponse:",
                rca=rca,
            ))

        # Rule 3: Should have dependency injection
        if not has_di:
            msg = "Use Case lacks dependency injection (__init__ does not accept parameters)."
            rca = self._generate_rca(msg, "MEDIUM", {"class": node.name})
            violations.append(UseCaseViolation(
                severity="MEDIUM",
                file=rel_path,
                class_name=node.name,
                line=node.lineno,
                message=msg,
                suggestion="Use __init__ to inject dependencies: def __init__(self, repo: Repository, uow: UoW):",
                rca=rca,
            ))

        # Rule 4: Should have error handling
        if has_exec and not has_eh:
            msg = "execute() method does not have error handling (try/except) for domain errors."
            rca = self._generate_rca(msg, "HIGH", {"class": node.name})
            violations.append(UseCaseViolation(
                severity="HIGH",
                file=rel_path,
                class_name=node.name,
                line=line,
                message=msg,
                suggestion="Wrap business logic with try/except to catch DomainError, ValidationError, etc.",
                rca=rca,
            ))

        # Rule 5: Should have transaction management
        if has_exec and not has_tm:
            msg = "Use Case does not have transaction management (commit/rollback) in execute()."
            rca = self._generate_rca(msg, "MEDIUM", {"class": node.name})
            violations.append(UseCaseViolation(
                severity="MEDIUM",
                file=rel_path,
                class_name=node.name,
                line=line,
                message=msg,
                suggestion="Use Unit of Work: self.uow.commit() on success, rollback in except.",
                rca=rca,
            ))

        # Rule 6: Should have validation
        if has_exec and not has_val:
            msg = "execute() does not validate input (Pydantic or manual validation)."
            rca = self._generate_rca(msg, "LOW", {"class": node.name})
            violations.append(UseCaseViolation(
                severity="LOW",
                file=rel_path,
                class_name=node.name,
                line=line,
                message=msg,
                suggestion="Validate input DTO using Pydantic model_validate() or custom validation function.",
                rca=rca,
            ))

        # Rule 7 (strict): Should have return annotation
        if self.strict and has_exec and not has_return:
            msg = "execute() method does not have return type annotation."
            rca = self._generate_rca(msg, "LOW", {"class": node.name})
            violations.append(UseCaseViolation(
                severity="LOW",
                file=rel_path,
                class_name=node.name,
                line=line,
                message=msg,
                suggestion="Add return type annotation: -> OutputDTO",
                rca=rca,
            ))

        return UseCaseInfo(
            file=rel_path,
            class_name=node.name,
            line=node.lineno,
            has_execute=has_exec,
            has_type_hints=has_th,
            has_dependency_injection=has_di,
            has_error_handling=has_eh,
            has_transaction_management=has_tm,
            has_validation=has_val,
            is_async=is_async,
            has_return_annotation=has_return,
            violations=violations,
        )

    def scan(self, progress_callback: Optional[Callable] = None) -> Report:
        t0 = time.monotonic()
        report = Report()
        py_files = self._get_python_files()
        report.total_files_scanned = len(py_files)

        results: List[UseCaseInfo] = []
        total = len(py_files)

        def _scan_one(idx: int, py_file: pathlib.Path) -> List[UseCaseInfo]:
            if progress_callback:
                progress_callback(idx + 1, total)
            tree, err = _get_ast(py_file)
            if err or tree is None:
                return []
            rel = str(py_file.relative_to(self.root)).replace("\\", "/")
            found = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    info = self._analyze_class(node, rel, py_file)
                    if info:
                        found.append(info)
            return found

        if len(py_files) <= self.max_workers * 2:
            for idx, py_file in enumerate(py_files):
                results.extend(_scan_one(idx, py_file))
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {executor.submit(_scan_one, idx, py_file): py_file for idx, py_file in enumerate(py_files)}
                for future in concurrent.futures.as_completed(futures):
                    try:
                        results.extend(future.result())
                    except Exception as e:
                        logger.warning("Scan error: %s", e)

        report.use_cases = results
        report.total_use_cases = len(results)

        all_violations = []
        for uc in results:
            all_violations.extend(uc.violations)
        report.violations = all_violations

        # Compute score
        errors = report.error_count
        warnings = report.warning_count
        infos = report.info_count
        score = 100.0 - errors * 10 - warnings * 2 - infos * 0.5
        report.score = max(0.0, min(100.0, score))

        report.scan_time = time.monotonic() - t0
        return report

# ─── REPORTING ──────────────────────────────────────────────────────────────
def print_report(report: Report, checker: UseCaseChecker, verbose: bool = False, show_rca: bool = False):
    c = COLOR
    _safe_print(f"\n{c['BOLD']}{c['CYAN']}{'='*72}")
    _safe_print("  USE CASE / COMMAND HANDLER CONTRACT REPORT")
    _safe_print(f"  v{__version__} — Big 4 Audit Grade")
    _safe_print(f"{'='*72}{c['RESET']}")
    _safe_print("  📋 Use Case Contract Standards:")
    _safe_print("    ✅ execute() / handle() / __call__()  — entry point")
    _safe_print("    ✅ type hints (params & return)      — type safety")
    _safe_print("    ✅ dependency injection (__init__)   — testability")
    _safe_print("    ✅ error handling (try/except)       — robustness")
    _safe_print("    ✅ transaction management            — data consistency")
    _safe_print("    ✅ input validation                  — security & integrity")

    _safe_print(f"\n  📊 Summary:")
    _safe_print(f"    Files scanned    : {report.total_files_scanned}")
    _safe_print(f"    Use Cases found  : {report.total_use_cases}")
    _safe_print(f"    Errors (CRITICAL): {c['RED']}{report.error_count}{c['RESET']}")
    _safe_print(f"    Warnings (MEDIUM): {c['YELLOW']}{report.warning_count}{c['RESET']}")
    _safe_print(f"    Infos (LOW)      : {c['DIM']}{report.info_count}{c['RESET']}")
    _safe_print(f"    Score            : {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score:.1f}/100{c['RESET']}")
    _safe_print(f"    RCA Engine       : {'✅ Active' if _RCA_AVAILABLE else '⚠️ Fallback'}")
    _safe_print(f"    Strict mode      : {'✅ Enabled' if checker.strict else '❌ Disabled'}")
    _safe_print(f"    Scan time        : {report.scan_time:.3f}s")

    if report.violations:
        by_sev = {"CRITICAL": [], "HIGH": [], "MEDIUM": [], "LOW": [], "INFO": []}
        for v in report.violations:
            by_sev.setdefault(v.severity, []).append(v)

        _safe_print(f"\n{c['RED']}─── VIOLATIONS ───{c['RESET']}")
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
            items = by_sev.get(sev, [])
            if not items:
                continue
            sev_color = c["RED"] if sev in ("CRITICAL", "HIGH") else c["YELLOW"] if sev == "MEDIUM" else c["DIM"]
            _safe_print(f"\n  {sev_color}[{sev}] {len(items)} violations{sev_color}")

            for v in items[:20]:
                _safe_print(f"    {v.class_name} @ {v.file}:{v.line}")
                _safe_print(f"      {v.message}")
                _safe_print(f"      💡 {v.suggestion}")
                if verbose and v.rca:
                    rc = v.rca.get("root_cause", "")
                    fix = v.rca.get("suggested_fix", "")
                    conf = v.rca.get("confidence", 0)
                    if rc:
                        _safe_print(f"      {c['MAGENTA']}🔍 RCA: {rc[:120]}{c['RESET']}")
                    if fix:
                        _safe_print(f"      {c['MAGENTA']}🔧 Fix: {fix[:120]}{c['RESET']}")
                    if conf:
                        _safe_print(f"      {c['DIM']}📊 Confidence: {conf:.0%}{c['RESET']}")

            if len(items) > 20:
                _safe_print(f"    ... and {len(items)-20} more")

    else:
        _safe_print(f"\n{c['GREEN']}✅ All Use Cases are compliant with contract!{c['RESET']}")

    _safe_print(f"\n{c['CYAN']}{'─'*72}{c['RESET']}")
    if report.passed:
        _safe_print(f"  {c['GREEN']}✅ PASS — All Use Cases contract compliant.{c['RESET']}")
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
            "total_files_scanned": report.total_files_scanned,
            "total_use_cases": report.total_use_cases,
            "violations": [v.to_dict() for v in report.violations],
            "use_cases": [
                {
                    "file": uc.file,
                    "class": uc.class_name,
                    "line": uc.line,
                    "has_execute": uc.has_execute,
                    "has_type_hints": uc.has_type_hints,
                    "has_dependency_injection": uc.has_dependency_injection,
                    "has_error_handling": uc.has_error_handling,
                    "has_transaction_management": uc.has_transaction_management,
                    "has_validation": uc.has_validation,
                    "is_async": uc.is_async,
                    "has_return_annotation": uc.has_return_annotation,
                    "violations_count": len(uc.violations),
                }
                for uc in report.use_cases
            ],
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
            writer.writerow(["severity", "file", "class", "line", "message", "suggestion"])
            for v in report.violations:
                writer.writerow([v.severity, v.file, v.class_name, v.line, v.message, v.suggestion])
        _safe_print(f"{_c('GREEN')}✅ CSV saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save CSV: {e}{_c('RESET')}")
        return False

def save_html(report: Report, path: pathlib.Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        violations_html = ""
        for v in report.violations:
            cls = "error" if v.severity in ("CRITICAL", "HIGH") else "warning" if v.severity == "MEDIUM" else "info"
            violations_html += f'<div class="finding {cls}"><strong>{v.severity}</strong> {v.class_name}@{v.file}:{v.line}<br>{v.message}<br><small>💡 {v.suggestion}</small></div>'

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Use Case Checker Report</title>
<style>
body{{font-family:sans-serif;background:#f8f9fa;color:#212529;padding:2rem}}
h1{{color:#0d6efd}}
.summary{{display:flex;gap:2rem;flex-wrap:wrap;margin:1rem 0}}
.card{{background:white;padding:1rem 2rem;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,0.1)}}
.card .value{{font-size:2rem;font-weight:bold}}
.card .label{{color:#6c757d}}
.finding{{margin:0.5rem 0;padding:0.5rem 1rem;border-left:4px solid}}
.error{{border-color:#dc3545;background:#f8d7da}}
.warning{{border-color:#ffc107;background:#fff3cd}}
.info{{border-color:#0dcaf0;background:#d1ecf1}}
</style></head>
<body>
<h1>Use Case / Command Handler Contract Report</h1>
<div class="summary">
  <div class="card"><div class="value">{report.total_use_cases}</div><div class="label">Use Cases</div></div>
  <div class="card"><div class="value" style="color:#dc3545">{report.error_count}</div><div class="label">Errors</div></div>
  <div class="card"><div class="value" style="color:#ffc107">{report.warning_count}</div><div class="label">Warnings</div></div>
  <div class="card"><div class="value">{report.score:.1f}</div><div class="label">Score</div></div>
  <div class="card"><div class="value">{'PASS' if report.passed else 'FAIL'}</div><div class="label">Status</div></div>
</div>
<h2>Violations</h2>
{violations_html}
</body></html>"""
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
        for v in report.violations:
            results.append({
                "ruleId": f"USECASE-{v.severity}",
                "level": "error" if v.severity in ("CRITICAL", "HIGH") else "warning",
                "message": {"text": v.message},
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {"uri": v.file},
                        "region": {"startLine": max(1, v.line)},
                    }
                }],
            })
        sarif = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [{
                "tool": {
                    "driver": {
                        "name": "UseCaseChecker",
                        "version": __version__,
                        "rules": [
                            {"id": "USECASE-CRITICAL", "shortDescription": {"text": "Critical Use Case contract violation"}},
                            {"id": "USECASE-HIGH", "shortDescription": {"text": "High severity Use Case violation"}},
                            {"id": "USECASE-MEDIUM", "shortDescription": {"text": "Medium severity Use Case violation"}},
                            {"id": "USECASE-LOW", "shortDescription": {"text": "Low severity Use Case violation"}},
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

    if verbose: _safe_print(f"\nUse Case Checker self-test v{__version__}…\n")

    code = """
class CreateInvoiceUseCase:
    def execute(self, request):
        pass
"""
    tree = ast.parse(code)
    node = next((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)), None)
    checker = UseCaseChecker(pathlib.Path.cwd(), enable_rca=False)
    if node:
        check("_is_use_case_class detects naming", checker._is_use_case_class(node, pathlib.Path("application/use_cases/test.py")))
        check("_should_skip_class false", not checker._should_skip_class("CreateInvoiceUseCase"))

    code2 = """
class APInvoiceActionResponseSchema:
    pass
"""
    tree2 = ast.parse(code2)
    node2 = next((n for n in ast.walk(tree2) if isinstance(n, ast.ClassDef)), None)
    if node2:
        check("_should_skip_class filters Schema", checker._should_skip_class("APInvoiceActionResponseSchema"))

    code3 = """
class SimpleRetryPolicy:
    def execute(self):
        pass
"""
    tree3 = ast.parse(code3)
    node3 = next((n for n in ast.walk(tree3) if isinstance(n, ast.ClassDef)), None)
    if node3:
        check("_should_skip_class filters Policy", checker._should_skip_class("SimpleRetryPolicy"))

    if verbose: _safe_print(f"\nSelf-test: {passed} passed, {failed} failed {'✅' if failed==0 else '❌'}")
    return failed == 0

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description=f"Use Case Checker v{__version__}")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE")
    parser.add_argument("--csv", metavar="FILE")
    parser.add_argument("--html", metavar="FILE")
    parser.add_argument("--sarif", metavar="FILE")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--no-rca", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--exclude", default="")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--no-progress", action="store_true")
    parser.add_argument("--version", action="version", version=f"use_cases_checker v{__version__}")

    args = parser.parse_args()

    if args.self_test:
        return 0 if self_test(verbose=True) else 1

    project_root = pathlib.Path(__file__).resolve().parent.parent
    extra_excludes = set(args.exclude.split(",")) if args.exclude else set()

    checker = UseCaseChecker(
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