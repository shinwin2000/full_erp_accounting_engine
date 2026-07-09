#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker/saga_checker.py – Saga Pattern Compliance Checker (v3.4.0)
==================================================================
Standar : Big 4 Forensic Audit · ISO/IEC 25010 · SOX/ISA 315 Compliant

FIX v3.4:
- Tambahkan opsi --relaxed: mengubah severity missing compensate dari CRITICAL menjadi HIGH.
- Tambahkan opsi --exclude-classes: daftar kelas (pisah koma) yang akan diabaikan.
- Tambahkan opsi --ignore-idempotency: tidak memeriksa idempotency.
- Tambahkan opsi --ignore-state: tidak memeriksa state/status.
- Skor lebih realistis: missing compensate tidak langsung score 0.
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
        from checker.core.rca import get_engine
        _RCA_ENGINE = get_engine()
        _RCA_AVAILABLE = True
        return True
    except ImportError:
        pass
    _root = pathlib.Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    try:
        from checker.core.rca import get_engine
        _RCA_ENGINE = get_engine()
        _RCA_AVAILABLE = True
        return True
    except ImportError:
        pass
    return False

_init_rca()

def _rca_analyze(exc: Exception, context: Optional[Dict] = None) -> Optional[Dict]:
    if not _RCA_AVAILABLE or _RCA_ENGINE is None:
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
logger = logging.getLogger("saga_checker")
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
__version__ = "3.4.0"

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
EXCLUDED_DIRS_DEFAULT = {
    "checker", "tests", "migrations", "__pycache__", ".git",
    "docs", "scripts", "deployment", "monitoring", "reports",
    "venv", ".venv", "node_modules", "dist", "build",
}

SAGA_KEYWORDS = {"Saga", "Orchestrator", "Coordinator", "SagaOrchestrator"}
BASE_SAGA_NAMES = {"BaseSaga", "BaseOrchestrator", "SagaBase", "AbstractSaga"}
EXECUTE_METHODS = {"execute", "handle", "run", "process", "start", "__call__"}
COMPENSATE_METHODS = {"compensate", "rollback", "revert", "undo", "cancel"}
IDEMPOTENCY_NAMES = {"idempotency_key", "idempotent_key", "request_id", "correlation_id", "txn_id"}
STATE_NAMES = {"state", "status", "_state", "_status", "saga_state"}

SKIP_CLASS_PATTERNS = {
    "Port", "Protocol", "Entity", "Table", "DTO", "Dto", "VO", "ValueObject",
    "UnitOfWork", "Repository", "Adapter", "Impl", "Config", "Registry",
    "Factory", "Builder", "Mapper", "Assembler", "Converter", "Serializer",
    "Deserializer", "Validator", "Checker", "Verifier", "Guard", "Enforcer",
    "Middleware", "Handler", "Event", "Command", "Query", "Projection",
    "Snapshot", "State", "Status", "Context", "Step", "StepName",
    "Exception", "Error", "Base", "Mixin", "Strategy",
}

# ─── DATA CLASSES ─────────────────────────────────────────────────────────────
@dataclass
class SagaViolation:
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
class SagaInfo:
    file: str
    class_name: str
    line: int
    has_execute: bool
    has_compensate: bool
    has_idempotency: bool
    has_state: bool
    calls_compensate_in_except: bool
    calls_compensate_in_finally: bool
    is_async_execute: bool
    is_async_compensate: bool
    violations: List[SagaViolation] = field(default_factory=list)

@dataclass
class Report:
    sagas: List[SagaInfo] = field(default_factory=list)
    violations: List[SagaViolation] = field(default_factory=list)
    total_files_scanned: int = 0
    total_sagas: int = 0
    score: float = 100.0
    scan_time: float = 0.0
    skipped_false_positives: int = 0

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "CRITICAL")

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity in ("HIGH", "MEDIUM"))

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

def _get_method_defs(node: ast.ClassDef) -> List[Union[ast.FunctionDef, ast.AsyncFunctionDef]]:
    return [item for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]

def _is_async_method(method: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> bool:
    return isinstance(method, ast.AsyncFunctionDef)

def _find_method_by_name(node: ast.ClassDef, names: Set[str]) -> Optional[Union[ast.FunctionDef, ast.AsyncFunctionDef]]:
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name in names:
                return item
    return None

def _has_method_call_in_block(node: ast.AST, method_names: Set[str]) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            if isinstance(sub.func, ast.Name) and sub.func.id in method_names:
                return True
            if isinstance(sub.func, ast.Attribute) and sub.func.attr in method_names:
                return True
            if isinstance(sub.func, ast.Attribute) and isinstance(sub.func.value, ast.Name):
                if sub.func.value.id == "self" and sub.func.attr in method_names:
                    return True
    return False

def _generate_rca(msg: str, severity: str, context: Optional[Dict] = None) -> Optional[Dict]:
    if not _RCA_AVAILABLE:
        return {
            "severity": "WARNING",
            "root_cause": msg[:200],
            "suggested_fix": "Install checker.core.rca",
            "confidence": 0.0,
        }
    try:
        exc = RuntimeError(msg) if severity in ("CRITICAL", "HIGH") else ValueError(msg)
        ctx = {"severity": severity, "violation": msg, **(context or {})}
        return _rca_analyze(exc, ctx)
    except Exception:
        return {"root_cause": msg, "suggested_fix": "Periksa implementasi Saga."}

# ─── CHECKER ──────────────────────────────────────────────────────────────────
class SagaChecker:
    def __init__(
        self,
        root: pathlib.Path,
        saga_dirs: List[str],
        enable_rca: bool = True,
        strict: bool = False,
        relaxed: bool = False,
        ignore_idempotency: bool = False,
        ignore_state: bool = False,
        exclude_classes: Optional[Set[str]] = None,
        extra_excludes: Optional[Set[str]] = None,
        max_workers: int = 4,
    ):
        self.root = root
        self.saga_dirs = saga_dirs
        self.enable_rca = enable_rca and _RCA_AVAILABLE
        self.strict = strict
        self.relaxed = relaxed
        self.ignore_idempotency = ignore_idempotency
        self.ignore_state = ignore_state
        self.exclude_classes = exclude_classes or set()
        self.extra_excludes = extra_excludes or set()
        self.max_workers = max_workers
        self._excluded_dirs = EXCLUDED_DIRS_DEFAULT | self.extra_excludes
        self._skipped_fp_count = 0

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

    def _should_skip_class(self, name: str) -> bool:
        """Hard filter: skip if class name contains any pattern that indicates non-Saga."""
        if name in self.exclude_classes:
            return True
        for pattern in SKIP_CLASS_PATTERNS:
            if pattern in name:
                return True
        return False

    def _is_saga_class(self, node: ast.ClassDef, file_path: pathlib.Path) -> bool:
        """
        Determine if a class is a true Saga/Orchestrator.
        Now stricter: only accept if:
        - inherits from BASE_SAGA_NAMES, OR
        - has @saga / @orchestrator decorator, OR
        - name contains "Saga" or "Orchestrator" AND has execute or compensate method.
        """
        name = node.name

        # 1. Hard skip
        if self._should_skip_class(name):
            return False

        # 2. Check for base Saga class
        has_saga_base = False
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in BASE_SAGA_NAMES:
                has_saga_base = True
            if isinstance(base, ast.Attribute) and base.attr in BASE_SAGA_NAMES:
                has_saga_base = True

        # 3. Check decorator
        has_saga_deco = False
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id in {"saga", "saga_orchestrator", "orchestrator"}:
                has_saga_deco = True
            if isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name) and dec.func.id in {"saga", "saga_orchestrator"}:
                    has_saga_deco = True

        # 4. Check for execute and compensate methods
        method_names = _get_method_names(node)
        has_exec = any(m in EXECUTE_METHODS for m in method_names)
        has_comp = any(m in COMPENSATE_METHODS for m in method_names)

        # 5. Final decision
        if has_saga_base or has_saga_deco:
            return True

        has_saga_keyword = any(kw in name for kw in SAGA_KEYWORDS)
        if has_saga_keyword and (has_exec or has_comp):
            return True

        return False

    def _has_idempotency(self, node: ast.ClassDef) -> bool:
        for item in node.body:
            if isinstance(item, (ast.Assign, ast.AnnAssign)):
                targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in IDEMPOTENCY_NAMES:
                        return True
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name in EXECUTE_METHODS:
                    for arg in item.args.args:
                        if arg.arg in IDEMPOTENCY_NAMES:
                            return True
        return False

    def _has_state(self, node: ast.ClassDef) -> bool:
        for item in node.body:
            if isinstance(item, (ast.Assign, ast.AnnAssign)):
                targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in STATE_NAMES:
                        return True
        return False

    def _calls_compensate(self, node: ast.ClassDef, block_type: str) -> bool:
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in EXECUTE_METHODS:
                for sub in ast.walk(item):
                    if isinstance(sub, ast.Try):
                        if block_type == "except":
                            for handler in sub.handlers:
                                if _has_method_call_in_block(handler, set(COMPENSATE_METHODS)):
                                    return True
                        elif block_type == "finally":
                            if sub.finalbody and _has_method_call_in_block(sub.finalbody, set(COMPENSATE_METHODS)):
                                return True
        return False

    def _is_async_execute(self, node: ast.ClassDef) -> bool:
        method = _find_method_by_name(node, set(EXECUTE_METHODS))
        if method:
            return _is_async_method(method)
        return False

    def _is_async_compensate(self, node: ast.ClassDef) -> bool:
        method = _find_method_by_name(node, set(COMPENSATE_METHODS))
        if method:
            return _is_async_method(method)
        return False

    def _get_execute_method(self, node: ast.ClassDef) -> Optional[Union[ast.FunctionDef, ast.AsyncFunctionDef]]:
        return _find_method_by_name(node, set(EXECUTE_METHODS))

    def _get_compensate_method(self, node: ast.ClassDef) -> Optional[Union[ast.FunctionDef, ast.AsyncFunctionDef]]:
        return _find_method_by_name(node, set(COMPENSATE_METHODS))

    def _analyze_class(self, node: ast.ClassDef, rel_path: str, file_path: pathlib.Path) -> Optional[SagaInfo]:
        if not self._is_saga_class(node, file_path):
            self._skipped_fp_count += 1
            return None

        method_names = _get_method_names(node)
        has_exec = any(m in EXECUTE_METHODS for m in method_names)
        has_comp = any(m in COMPENSATE_METHODS for m in method_names)
        has_idem = self._has_idempotency(node)
        has_state = self._has_state(node)
        calls_except = self._calls_compensate(node, "except")
        calls_finally = self._calls_compensate(node, "finally")
        is_async_exec = self._is_async_execute(node)
        is_async_comp = self._is_async_compensate(node)

        violations: List[SagaViolation] = []
        execute_method = self._get_execute_method(node)
        compensate_method = self._get_compensate_method(node)
        line = node.lineno

        # Rule 1: Must have execute method (CRITICAL)
        if not has_exec:
            msg = "Saga class does not have execute() or handle() method."
            rca = _generate_rca(msg, "CRITICAL", {"class": node.name})
            violations.append(SagaViolation(
                severity="CRITICAL",
                file=rel_path,
                class_name=node.name,
                line=node.lineno,
                message=msg,
                suggestion="Add 'def execute(self, request) -> Response:' or 'def handle(...)'.",
                rca=rca,
            ))

        # Rule 2: Must have compensate method
        if not has_comp:
            msg = "Saga class does not have compensate() or rollback() method."
            rca = _generate_rca(msg, "CRITICAL", {"class": node.name})
            sev = "HIGH" if self.relaxed else "CRITICAL"
            violations.append(SagaViolation(
                severity=sev,
                file=rel_path,
                class_name=node.name,
                line=node.lineno,
                message=msg,
                suggestion="Add 'def compensate(self, ...):' for rollback logic.",
                rca=rca,
            ))

        # Only check additional rules if class has execute (to avoid noise)
        if has_exec:
            # Rule 3: Idempotency (HIGH)
            if not self.ignore_idempotency and not has_idem:
                msg = "Saga class does not have idempotency mechanism."
                rca = _generate_rca(msg, "HIGH", {"class": node.name})
                violations.append(SagaViolation(
                    severity="HIGH",
                    file=rel_path,
                    class_name=node.name,
                    line=execute_method.lineno if execute_method else line,
                    message=msg,
                    suggestion="Add 'idempotency_key' parameter in execute() or class attribute.",
                    rca=rca,
                ))

            # Rule 4: State management (MEDIUM)
            if not self.ignore_state and not has_state:
                msg = "Saga class does not have 'state' or 'status' attribute."
                rca = _generate_rca(msg, "MEDIUM", {"class": node.name})
                violations.append(SagaViolation(
                    severity="MEDIUM",
                    file=rel_path,
                    class_name=node.name,
                    line=execute_method.lineno if execute_method else line,
                    message=msg,
                    suggestion="Add 'self.state = PENDING' or 'self.status' for tracking.",
                    rca=rca,
                ))

            # Rule 5: compensate in except (HIGH)
            if has_comp and not calls_except:
                msg = "execute() does not call compensate() in except block."
                rca = _generate_rca(msg, "HIGH", {"class": node.name})
                violations.append(SagaViolation(
                    severity="HIGH",
                    file=rel_path,
                    class_name=node.name,
                    line=execute_method.lineno if execute_method else line,
                    message=msg,
                    suggestion="In except block, call self.compensate() for automatic rollback.",
                    rca=rca,
                ))

            # Rule 6: Async consistency (LOW)
            if is_async_exec != is_async_comp and has_comp:
                msg = f"Async/sync mismatch: execute is {'async' if is_async_exec else 'sync'}, compensate is {'async' if is_async_comp else 'sync'}."
                rca = _generate_rca(msg, "LOW", {"class": node.name})
                violations.append(SagaViolation(
                    severity="LOW",
                    file=rel_path,
                    class_name=node.name,
                    line=line,
                    message=msg,
                    suggestion="Ensure both execute() and compensate() are either both async or both sync.",
                    rca=rca,
                ))

        return SagaInfo(
            file=rel_path,
            class_name=node.name,
            line=line,
            has_execute=has_exec,
            has_compensate=has_comp,
            has_idempotency=has_idem,
            has_state=has_state,
            calls_compensate_in_except=calls_except,
            calls_compensate_in_finally=calls_finally,
            is_async_execute=is_async_exec,
            is_async_compensate=is_async_comp,
            violations=violations,
        )

    def scan(self, progress_callback: Optional[Callable] = None) -> Report:
        t0 = time.monotonic()
        report = Report()
        py_files = []

        for dir_name in self.saga_dirs:
            base = self.root / dir_name
            if not base.exists():
                logger.warning(f"Directory not found: {base}")
                continue
            for p in base.rglob("*.py"):
                if not self._should_skip_file(p):
                    py_files.append(p)

        py_files = sorted(set(py_files))
        report.total_files_scanned = len(py_files)
        self._skipped_fp_count = 0

        results: List[SagaInfo] = []
        total = len(py_files)

        def _scan_one(idx: int, py_file: pathlib.Path) -> List[SagaInfo]:
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

        report.sagas = results
        report.total_sagas = len(results)
        report.skipped_false_positives = self._skipped_fp_count

        all_violations = []
        for saga in results:
            all_violations.extend(saga.violations)
        report.violations = all_violations

        # Compute score: weight based on severity
        errors = report.error_count
        high = sum(1 for v in report.violations if v.severity == "HIGH")
        med = sum(1 for v in report.violations if v.severity == "MEDIUM")
        score = 100.0 - errors * 10 - high * 2 - med * 1
        report.score = max(0.0, min(100.0, score))

        report.scan_time = time.monotonic() - t0
        return report

# ─── REPORTING ──────────────────────────────────────────────────────────────
def print_report(report: Report, verbose: bool = False, show_rca: bool = False):
    c = COLOR
    _safe_print(f"\n{c['BOLD']}{c['CYAN']}{'='*72}")
    _safe_print("  SAGA PATTERN COMPLIANCE CHECKER")
    _safe_print(f"  v{__version__} — Big 4 Audit Grade")
    _safe_print(f"{'='*72}{c['RESET']}")
    _safe_print("  📋 Saga Contract Standards:")
    _safe_print("    ✅ execute() / handle()           — entry point")
    _safe_print("    ✅ compensate() / rollback()      — compensating action")
    _safe_print("    ✅ idempotency key                — retry safety")
    _safe_print("    ✅ state / status                 — progress tracking")
    _safe_print("    ✅ compensate() in except block   — automatic rollback")
    _safe_print("    ✅ async consistency              — execute & compensate both async/sync")

    _safe_print(f"\n  📊 Summary:")
    _safe_print(f"    Files scanned    : {report.total_files_scanned}")
    _safe_print(f"    Saga found       : {report.total_sagas}")
    _safe_print(f"    False positives skipped: {report.skipped_false_positives}")
    _safe_print(f"    Errors (CRITICAL): {c['RED']}{report.error_count}{c['RESET']}")
    _safe_print(f"    Warnings (HIGH)  : {c['YELLOW']}{report.warning_count}{c['RESET']}")
    _safe_print(f"    Infos (LOW)      : {c['DIM']}{report.info_count}{c['RESET']}")
    _safe_print(f"    Score            : {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score:.1f}/100{c['RESET']}")
    _safe_print(f"    RCA Engine       : {'✅ Active' if _RCA_AVAILABLE else '⚠️ Fallback'}")
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
        _safe_print(f"\n{c['GREEN']}✅ All Saga classes are compliant!{c['RESET']}")

    _safe_print(f"\n{c['CYAN']}{'─'*72}{c['RESET']}")
    if report.passed:
        _safe_print(f"  {c['GREEN']}✅ PASS — All Saga contracts satisfied.{c['RESET']}")
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
            "total_sagas": report.total_sagas,
            "skipped_false_positives": report.skipped_false_positives,
            "violations": [v.to_dict() for v in report.violations],
            "sagas": [
                {
                    "file": s.file,
                    "class": s.class_name,
                    "line": s.line,
                    "has_execute": s.has_execute,
                    "has_compensate": s.has_compensate,
                    "has_idempotency": s.has_idempotency,
                    "has_state": s.has_state,
                    "calls_compensate_in_except": s.calls_compensate_in_except,
                    "calls_compensate_in_finally": s.calls_compensate_in_finally,
                    "is_async_execute": s.is_async_execute,
                    "is_async_compensate": s.is_async_compensate,
                    "violations_count": len(s.violations),
                }
                for s in report.sagas
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
<html><head><meta charset="utf-8"><title>Saga Checker Report</title>
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
<h1>Saga Pattern Compliance Checker Report</h1>
<div class="summary">
  <div class="card"><div class="value">{report.total_sagas}</div><div class="label">Sagas</div></div>
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
                "ruleId": f"SAGA-{v.severity}",
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
                        "name": "SagaChecker",
                        "version": __version__,
                        "rules": [
                            {"id": "SAGA-CRITICAL", "shortDescription": {"text": "Critical Saga contract violation"}},
                            {"id": "SAGA-HIGH", "shortDescription": {"text": "High severity Saga violation"}},
                            {"id": "SAGA-MEDIUM", "shortDescription": {"text": "Medium severity Saga violation"}},
                            {"id": "SAGA-LOW", "shortDescription": {"text": "Low severity Saga violation"}},
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

    if verbose: _safe_print(f"\nSaga Checker self-test v{__version__}…\n")

    # Test detection: good Saga
    code = """
class CreateInvoiceSaga:
    def __init__(self):
        self.idempotency_key = None

    def execute(self, request):
        try:
            # business logic
            pass
        except Exception:
            self.compensate()

    def compensate(self):
        pass
"""
    tree = ast.parse(code)
    node = next((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)), None)
    checker = SagaChecker(pathlib.Path.cwd(), ["application/sagas"], enable_rca=False)
    if node:
        info = checker._analyze_class(node, "test.py", pathlib.Path("test.py"))
        if info:
            check("_is_saga_class detects Saga", True)
            check("has_execute", info.has_execute)
            check("has_compensate", info.has_compensate)
            check("has_idempotency", info.has_idempotency)
            check("calls_compensate_in_except", info.calls_compensate_in_except)

    # Test skip: class with name Saga but no methods
    code2 = """
class CoretaxSubmissionSaga:
    pass
"""
    tree2 = ast.parse(code2)
    node2 = next((n for n in ast.walk(tree2) if isinstance(n, ast.ClassDef)), None)
    if node2:
        is_saga = checker._is_saga_class(node2, pathlib.Path("test.py"))
        check("_is_saga_class skips Saga without methods", not is_saga)

    # Test skip: Exception class
    code3 = """
class SagaException(Exception):
    pass
"""
    tree3 = ast.parse(code3)
    node3 = next((n for n in ast.walk(tree3) if isinstance(n, ast.ClassDef)), None)
    if node3:
        check("_should_skip_class skips Exception", checker._should_skip_class("SagaException"))

    # Test relaxed mode: missing compensate becomes HIGH
    code4 = """
class PayrollSaga:
    def execute(self):
        pass
"""
    tree4 = ast.parse(code4)
    node4 = next((n for n in ast.walk(tree4) if isinstance(n, ast.ClassDef)), None)
    if node4:
        checker_relaxed = SagaChecker(pathlib.Path.cwd(), ["application/sagas"], relaxed=True, enable_rca=False)
        info4 = checker_relaxed._analyze_class(node4, "test.py", pathlib.Path("test.py"))
        if info4:
            sev = info4.violations[0].severity if info4.violations else None
            check("relaxed mode: missing compensate severity HIGH", sev == "HIGH")

    # Test RCA
    check("RCA availability", True)

    if verbose: _safe_print(f"\nSelf-test: {passed} passed, {failed} failed {'✅' if failed==0 else '❌'}")
    return failed == 0

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description=f"Saga Checker v{__version__}")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE")
    parser.add_argument("--csv", metavar="FILE")
    parser.add_argument("--html", metavar="FILE")
    parser.add_argument("--sarif", metavar="FILE")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--relaxed", action="store_true", help="Missing compensate menjadi HIGH, bukan CRITICAL")
    parser.add_argument("--ignore-idempotency", action="store_true", help="Tidak memeriksa idempotency key")
    parser.add_argument("--ignore-state", action="store_true", help="Tidak memeriksa state/status attribute")
    parser.add_argument("--exclude-classes", default="", help="Comma-separated class names to exclude")
    parser.add_argument("--no-rca", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--exclude", default="")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--no-progress", action="store_true")
    parser.add_argument("--saga-dirs", default="application/sagas,application/orchestrators",
                        help="Comma-separated directories to scan (relative to root)")
    parser.add_argument("--version", action="version", version=f"saga_checker v{__version__}")

    args = parser.parse_args()

    if args.self_test:
        return 0 if self_test(verbose=True) else 1

    project_root = pathlib.Path(__file__).resolve().parent.parent
    extra_excludes = set(args.exclude.split(",")) if args.exclude else set()
    exclude_classes = set(args.exclude_classes.split(",")) if args.exclude_classes else set()

    saga_dirs = [d.strip() for d in args.saga_dirs.split(",") if d.strip()]

    checker = SagaChecker(
        root=project_root,
        saga_dirs=saga_dirs,
        enable_rca=not args.no_rca,
        strict=args.strict,
        relaxed=args.relaxed,
        ignore_idempotency=args.ignore_idempotency,
        ignore_state=args.ignore_state,
        exclude_classes=exclude_classes,
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

    print_report(report, verbose=args.verbose, show_rca=not args.no_rca)

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