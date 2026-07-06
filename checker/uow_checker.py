#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
uow_checker.py – Unit of Work Pattern Validator
================================================
Versi   : 4.2.0
Standar : Big 4 Forensic Audit · ISO/IEC 25010 · SOX/ISA 315 Compliant

Perbaikan v4.2.0:
  - Klasifikasi Write/Read lebih akurat: deteksi repository/session methods
  - Deteksi CommandBus dispatch: dianggap write tapi UoW ditangani bus
  - Service call write hanya jika method name jelas write (post, approve, close, etc.)
  - Heuristic nama kelas hanya sebagai fallback
  - Informasi tambahan: apakah use case menggunakan CommandBus
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
logger = logging.getLogger("uow_checker")
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
__version__ = "4.2.0"

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
EXCLUDED_DIRS_DEFAULT = {
    "checker", "tests", "migrations", "__pycache__", ".git",
    "docs", "scripts", "deployment", "monitoring", "reports",
    "venv", ".venv", "node_modules", "dist", "build",
}
UOW_PORT_FILENAME = "unit_of_work_port.py"
UOW_IMPL_PATTERNS = ("*unit_of_work*.py", "*uow*.py")
UOW_CONTEXT_MANAGER_METHODS = {"__enter__", "__exit__", "__aenter__", "__aexit__"}
UOW_REQUIRED_METHODS = {"begin", "commit", "rollback"}

# Repository/session write methods (100% write)
WRITE_REPO_METHODS = {
    "add", "save", "update", "delete", "remove", "persist", "flush",
    "merge", "create", "insert", "destroy", "purge", "bulk_insert", "bulk_update",
    "bulk_delete", "commit", "rollback"
}

# Service method names that clearly write
WRITE_SERVICE_METHODS = {
    "post_journal", "approve_invoice", "reject_invoice", "close_period", "reopen_period",
    "execute_payment", "create_invoice", "update_invoice", "delete_invoice", "record_payment",
    "post", "approve", "reject", "close", "reopen", "submit",
    "execute_payment_run", "generate_payment_run", "depreciate_assets",
    "amortize_assets", "revalue", "impair", "dispose", "transfer",
    "save", "update", "delete", "persist", "flush", "commit", "rollback"
}

REPO_INDICATORS = {"repo", "repository", "session", "adapter", "gateway", "client", "manager"}

SKIP_CLASS_PATTERNS = {"Factory", "Builder", "Provider", "Registry", "Error", "Exception", "Config", "Constants", "Schema", "DTO"}

# ─── DATA CLASSES ─────────────────────────────────────────────────────────────
@dataclass
class Finding:
    severity: str  # ERROR, WARNING, INFO
    file: str
    line: int
    category: str  # port, implementation, usage, bypass, read_write
    message: str
    detail: str = ""
    rca: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "category": self.category,
            "message": self.message,
            "detail": self.detail,
            "rca": self.rca,
        }

@dataclass
class UseCaseSummary:
    file: str
    class_name: str
    line: int
    has_uow: bool
    has_transactional_decorator: bool
    has_direct_session_commit: bool
    has_repository_calls: bool
    has_service_write: bool
    has_command_bus: bool
    is_write: bool
    violations: List[Finding] = field(default_factory=list)

@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    use_case_summaries: List[UseCaseSummary] = field(default_factory=list)
    score: float = 100.0
    scan_time: float = 0.0
    total_files_scanned: int = 0
    total_uow_classes: int = 0
    total_use_cases_scanned: int = 0
    use_cases_with_uow: int = 0
    use_cases_without_uow: int = 0
    use_cases_readonly: int = 0

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "ERROR")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "WARNING")

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "INFO")

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

def _get_methods(node: ast.ClassDef) -> Set[str]:
    return {item.name for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))}

def _has_method(node: ast.ClassDef, name: str) -> bool:
    return any(
        isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
        for item in node.body
    )

def _is_exception_class(node: ast.ClassDef) -> bool:
    name = node.name
    if "Error" in name or "Exception" in name:
        return True
    for base in node.bases:
        if isinstance(base, ast.Name) and ("Error" in base.id or "Exception" in base.id):
            return True
    return False

def _is_factory_class(node: ast.ClassDef) -> bool:
    name = node.name
    if any(p in name for p in SKIP_CLASS_PATTERNS):
        return True
    return False

def _find_exit_method(node: ast.ClassDef) -> Optional[Union[ast.FunctionDef, ast.AsyncFunctionDef]]:
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name in ("__exit__", "__aexit__"):
                return item
    return None

def _analyze_exit_method(node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> Tuple[bool, bool, bool]:
    has_commit = False
    has_rollback = False
    has_rollback_on_error = False

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.in_error_branch = False

        def visit_If(self, node):
            test = node.test
            is_error_check = False
            if isinstance(test, ast.Name) and test.id in ("exc_type", "exc_val", "exc_tb"):
                is_error_check = True
            elif isinstance(test, ast.Call) and isinstance(test.func, ast.Name) and test.func.id == "isinstance":
                is_error_check = True
            elif isinstance(test, ast.Compare):
                is_error_check = True

            if is_error_check:
                old = self.in_error_branch
                self.in_error_branch = True
                self.generic_visit(node)
                self.in_error_branch = old
                if node.orelse:
                    for stmt in node.orelse:
                        self.visit(stmt)
                return
            self.generic_visit(node)

        def visit_Call(self, node):
            func = node.func
            if isinstance(func, ast.Attribute):
                attr = func.attr.lower()
                if attr == "commit":
                    nonlocal has_commit
                    has_commit = True
                elif attr == "rollback":
                    nonlocal has_rollback
                    has_rollback = True
                    if self.in_error_branch:
                        nonlocal has_rollback_on_error
                        has_rollback_on_error = True
                if isinstance(func.value, ast.Attribute):
                    if isinstance(func.value.value, ast.Name) and func.value.value.id == "self":
                        if func.value.attr in ("_transaction_manager", "_session", "_uow"):
                            if attr == "commit":
                                has_commit = True
                            elif attr == "rollback":
                                has_rollback = True
                                if self.in_error_branch:
                                    has_rollback_on_error = True
                    if isinstance(func.value, ast.Name) and func.value.id == "self":
                        if attr == "commit":
                            has_commit = True
                        elif attr == "rollback":
                            has_rollback = True
                            if self.in_error_branch:
                                has_rollback_on_error = True
            self.generic_visit(node)

        def visit_Await(self, node):
            self.visit(node.value)

    Visitor().visit(node)
    return has_commit, has_rollback, has_rollback_on_error

def _is_factory_function(name: str) -> bool:
    return name.startswith(("create_", "build_", "make_", "new_", "get_", "setup_", "__init__", "_init"))

def _has_repository_write(node: ast.AST) -> bool:
    """Check if node contains any repository/session write method."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            if isinstance(sub.func, ast.Attribute):
                attr = sub.func.attr.lower()
                if attr in WRITE_REPO_METHODS:
                    # Check if called on repository/session object
                    if isinstance(sub.func.value, ast.Name):
                        obj = sub.func.value.id.lower()
                        if any(ind in obj for ind in REPO_INDICATORS):
                            return True
                    if isinstance(sub.func.value, ast.Attribute):
                        if isinstance(sub.func.value.value, ast.Name) and sub.func.value.value.id == "self":
                            obj_attr = sub.func.value.attr.lower()
                            if any(ind in obj_attr for ind in REPO_INDICATORS):
                                return True
    return False

def _has_service_write(node: ast.AST) -> bool:
    """Check if node contains service call with clearly write method name."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            if isinstance(sub.func, ast.Attribute):
                attr = sub.func.attr.lower()
                if attr in WRITE_SERVICE_METHODS:
                    # Check if called on service object
                    if isinstance(sub.func.value, ast.Name):
                        obj = sub.func.value.id.lower()
                        if "service" in obj or "handler" in obj:
                            return True
                    if isinstance(sub.func.value, ast.Attribute):
                        if isinstance(sub.func.value.value, ast.Name) and sub.func.value.value.id == "self":
                            obj_attr = sub.func.value.attr.lower()
                            if "service" in obj_attr or "handler" in obj_attr:
                                return True
    return False

def _has_command_bus_dispatch(node: ast.AST) -> bool:
    """Check if node dispatches to command bus (UoW handled by bus)."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            if isinstance(sub.func, ast.Attribute):
                attr = sub.func.attr.lower()
                if attr in ("dispatch", "send", "execute", "publish"):
                    if isinstance(sub.func.value, ast.Name):
                        obj = sub.func.value.id.lower()
                        if "command_bus" in obj or "bus" in obj:
                            return True
                    if isinstance(sub.func.value, ast.Attribute):
                        if isinstance(sub.func.value.value, ast.Name) and sub.func.value.value.id == "self":
                            obj_attr = sub.func.value.attr.lower()
                            if "command_bus" in obj_attr or "bus" in obj_attr:
                                return True
    return False

def _has_direct_session_commit(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            if isinstance(sub.func, ast.Attribute):
                attr = sub.func.attr.lower()
                if attr == "commit":
                    if isinstance(sub.func.value, ast.Name):
                        obj = sub.func.value.id.lower()
                        if obj in ("session", "db", "conn", "connection"):
                            return True
                    if isinstance(sub.func.value, ast.Attribute):
                        if isinstance(sub.func.value.value, ast.Name):
                            if sub.func.value.value.id.lower() in ("self", "db"):
                                if sub.func.value.attr.lower() in ("session", "connection", "db"):
                                    return True
    return False

def _has_uow_usage(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.With):
            for item in sub.items:
                context_expr = ast.unparse(item.context_expr).lower()
                if "uow" in context_expr or "unit_of_work" in context_expr:
                    return True
        if isinstance(sub, ast.Call):
            if isinstance(sub.func, ast.Attribute):
                attr = sub.func.attr.lower()
                if attr in ("commit", "rollback"):
                    if isinstance(sub.func.value, ast.Name) and sub.func.value.id.lower() in ("uow", "unit_of_work"):
                        return True
                    if isinstance(sub.func.value, ast.Attribute):
                        if isinstance(sub.func.value.value, ast.Name) and sub.func.value.value.id == "self":
                            if sub.func.value.attr in ("_uow", "uow"):
                                return True
    return False

def _has_transactional_decorator(node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> bool:
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == "transactional":
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == "transactional":
            return True
        if isinstance(dec, ast.Call):
            if isinstance(dec.func, ast.Name) and dec.func.id == "transactional":
                return True
            if isinstance(dec.func, ast.Attribute) and dec.func.attr == "transactional":
                return True
    return False

def _has_repository_calls(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            if isinstance(sub.func, ast.Attribute):
                if isinstance(sub.func.value, ast.Name):
                    obj = sub.func.value.id.lower()
                    if any(ind in obj for ind in REPO_INDICATORS):
                        return True
                if isinstance(sub.func.value, ast.Attribute):
                    if isinstance(sub.func.value.value, ast.Name) and sub.func.value.value.id == "self":
                        attr = sub.func.value.attr.lower()
                        if any(ind in attr for ind in REPO_INDICATORS):
                            return True
    return False

# ─── CHECKER ──────────────────────────────────────────────────────────────────
class UoWChecker:
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
        if path.name.endswith(("_test.py", "_tests.py")):
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
            return {"root_cause": msg, "suggested_fix": "Periksa implementasi UoW."}

    # ─── PORT CHECK ────────────────────────────────────────────────────────────
    def check_port(self) -> List[Finding]:
        findings = []
        port_file = self.root / "ports" / "primary" / UOW_PORT_FILENAME
        if not port_file.exists():
            findings.append(Finding(
                severity="ERROR",
                file=str(port_file),
                line=0,
                category="port",
                message=f"UoW port file {UOW_PORT_FILENAME} not found in ports/primary/",
                detail="Create ports/primary/unit_of_work_port.py with UnitOfWork interface.",
                rca=self._generate_rca("Port file not found", "ERROR", {"file": str(port_file)}),
            ))
            return findings

        tree, err = _get_ast(port_file)
        if err or tree is None:
            findings.append(Finding(
                severity="ERROR",
                file=str(port_file),
                line=0,
                category="port",
                message=f"Failed to parse port file: {err}",
                rca=self._generate_rca(f"Parse error: {err}", "ERROR"),
            ))
            return findings

        uow_classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if "unit" in node.name.lower() and "work" in node.name.lower():
                    uow_classes.append(node)

        if not uow_classes:
            findings.append(Finding(
                severity="ERROR",
                file=str(port_file),
                line=0,
                category="port",
                message="No UnitOfWork class found in port file",
                detail="Add class UnitOfWork (or UnitOfWorkPort) with commit, rollback, begin/context manager.",
                rca=self._generate_rca("No UoW class in port", "ERROR"),
            ))
            return findings

        for cls in uow_classes:
            methods = _get_methods(cls)
            has_cm = any(m in methods for m in UOW_CONTEXT_MANAGER_METHODS)

            if has_cm:
                findings.append(Finding(
                    severity="INFO",
                    file=str(port_file),
                    line=cls.lineno,
                    category="port",
                    message=f"✅ UoW port '{cls.name}' has context manager",
                    detail="",
                ))
            else:
                missing = UOW_REQUIRED_METHODS - methods
                if missing:
                    findings.append(Finding(
                        severity="ERROR",
                        file=str(port_file),
                        line=cls.lineno,
                        category="port",
                        message=f"UoW port '{cls.name}' missing methods: {', '.join(missing)}",
                        detail="Implement begin, commit, rollback or use context manager.",
                        rca=self._generate_rca(f"Missing methods: {missing}", "ERROR", {"class": cls.name}),
                    ))
                else:
                    findings.append(Finding(
                        severity="INFO",
                        file=str(port_file),
                        line=cls.lineno,
                        category="port",
                        message=f"✅ UoW port '{cls.name}' complete (begin, commit, rollback)",
                        detail="",
                    ))

        return findings

    # ─── IMPLEMENTATION CHECK ──────────────────────────────────────────────
    def check_implementation(self) -> List[Finding]:
        findings = []
        impl_dir = self.root / "adapters" / "secondary_impl"
        if not impl_dir.exists():
            findings.append(Finding(
                severity="ERROR",
                file=str(impl_dir),
                line=0,
                category="implementation",
                message="adapters/secondary_impl/ directory not found",
                detail="Create adapters/secondary_impl/ for UoW implementation.",
                rca=self._generate_rca("Impl directory missing", "ERROR"),
            ))
            return findings

        impl_files = []
        for pattern in UOW_IMPL_PATTERNS:
            impl_files.extend(impl_dir.glob(pattern))
        impl_files = list(set(impl_files))

        if not impl_files:
            findings.append(Finding(
                severity="ERROR",
                file=str(impl_dir),
                line=0,
                category="implementation",
                message="No UoW implementation found in adapters/secondary_impl/",
                detail="Create file like sqlalchemy_unit_of_work_impl.py",
                rca=self._generate_rca("No UoW impl", "ERROR"),
            ))
            return findings

        for impl_file in impl_files:
            rel = str(impl_file.relative_to(self.root)).replace("\\", "/")
            tree, err = _get_ast(impl_file)
            if err or tree is None:
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                if _is_exception_class(node) or _is_factory_class(node):
                    continue
                if "unit" not in node.name.lower() or "work" not in node.name.lower():
                    continue

                methods = _get_methods(node)
                has_cm = any(m in methods for m in UOW_CONTEXT_MANAGER_METHODS)

                if has_cm:
                    exit_method = _find_exit_method(node)
                    if exit_method:
                        has_commit, has_rollback, has_rollback_on_error = _analyze_exit_method(exit_method)
                        has_commit_method = _has_method(node, "commit")
                        has_rollback_method = _has_method(node, "rollback")

                        if has_commit or has_rollback:
                            findings.append(Finding(
                                severity="INFO",
                                file=rel,
                                line=node.lineno,
                                category="implementation",
                                message=f"✅ UoW '{node.name}' uses context manager with commit/rollback in __exit__",
                                detail="",
                            ))
                        elif has_commit_method and has_rollback_method:
                            if has_rollback_on_error:
                                findings.append(Finding(
                                    severity="INFO",
                                    file=rel,
                                    line=node.lineno,
                                    category="implementation",
                                    message=f"✅ UoW '{node.name}' uses explicit commit pattern",
                                    detail="commit called explicitly by user, __exit__ handles rollback on error.",
                                ))
                            else:
                                findings.append(Finding(
                                    severity="WARNING" if not self.strict else "ERROR",
                                    file=rel,
                                    line=exit_method.lineno,
                                    category="implementation",
                                    message=f"UoW '{node.name}' __exit__ does not call rollback in error branch",
                                    detail="Ensure error branch calls rollback, or ignore if design is correct.",
                                    rca=self._generate_rca("No rollback in error branch", "WARNING", {"class": node.name}),
                                ))
                        else:
                            findings.append(Finding(
                                severity="WARNING" if not self.strict else "ERROR",
                                file=rel,
                                line=exit_method.lineno,
                                category="implementation",
                                message=f"UoW '{node.name}' __exit__ does not call commit or rollback",
                                detail="Ensure __exit__ calls session.commit() or session.rollback(), or use explicit commit pattern.",
                                rca=self._generate_rca("No commit/rollback in __exit__", "WARNING", {"class": node.name}),
                            ))
                    else:
                        findings.append(Finding(
                            severity="ERROR",
                            file=rel,
                            line=node.lineno,
                            category="implementation",
                            message=f"UoW '{node.name}' has context manager but no __exit__",
                            detail="Implement __exit__ or __aexit__.",
                            rca=self._generate_rca("No __exit__", "ERROR", {"class": node.name}),
                        ))
                else:
                    missing = UOW_REQUIRED_METHODS - methods
                    if missing:
                        findings.append(Finding(
                            severity="ERROR",
                            file=rel,
                            line=node.lineno,
                            category="implementation",
                            message=f"UoW '{node.name}' missing methods: {', '.join(missing)}",
                            detail=f"Implement {', '.join(missing)} or use context manager.",
                            rca=self._generate_rca(f"Missing methods: {missing}", "ERROR", {"class": node.name}),
                        ))
                    else:
                        findings.append(Finding(
                            severity="INFO",
                            file=rel,
                            line=node.lineno,
                            category="implementation",
                            message=f"✅ UoW '{node.name}' complete",
                            detail="",
                        ))

        return findings

    # ─── USE CASE ANALYSIS (enhanced) ──────────────────────────────────────
    def analyze_use_cases(self) -> Tuple[List[Finding], List[UseCaseSummary]]:
        findings = []
        summaries = []
        use_cases_dir = self.root / "application" / "use_cases"
        if not use_cases_dir.exists():
            return findings, summaries

        for py_file in use_cases_dir.rglob("*.py"):
            if self._should_skip_file(py_file):
                continue
            rel = str(py_file.relative_to(self.root)).replace("\\", "/")
            tree, err = _get_ast(py_file)
            if err or tree is None:
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                if _is_exception_class(node) or _is_factory_class(node):
                    continue
                methods = _get_methods(node)
                if not any(m in {"execute", "handle", "__call__"} for m in methods):
                    continue

                has_uow = False
                has_tx_decorator = False
                has_direct_commit = False
                has_repo_calls = False
                has_service_write = False
                has_command_bus = False
                is_write = False
                class_violations = []

                for item in node.body:
                    if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    if item.name not in ("execute", "handle", "__call__"):
                        continue

                    # Decorator
                    if _has_transactional_decorator(item):
                        has_tx_decorator = True
                        has_uow = True

                    # UoW usage
                    if _has_uow_usage(item):
                        has_uow = True

                    # Direct session commit
                    if _has_direct_session_commit(item):
                        has_direct_commit = True

                    # Repository calls (may include read and write)
                    if _has_repository_calls(item):
                        has_repo_calls = True

                    # Repository write (100% write)
                    if _has_repository_write(item):
                        is_write = True

                    # Service write (clearly write methods)
                    if _has_service_write(item):
                        is_write = True
                        has_service_write = True

                    # Command bus dispatch (write, but UoW handled by bus)
                    if _has_command_bus_dispatch(item):
                        has_command_bus = True
                        # Jika menggunakan command bus, anggap use case tidak perlu UoW sendiri
                        # Tapi tetap tandai sebagai write
                        is_write = True
                        # UoW sudah ditangani oleh command bus, jadi tidak perlu violation
                        # Kita tidak set has_uow, tapi kita akan bypass error untuk command bus.

                # Jika hanya command bus dan tidak ada repository write/service write, kita anggap write tapi tidak perlu UoW
                # Karena command bus yang menangani transaksi.
                # Tapi kita tetap cek jika ada repository write tanpa UoW.

                # Kasus: ada repository write tanpa UoW dan tanpa command bus
                if is_write and (has_repo_calls or has_service_write) and not has_uow and not has_tx_decorator and not has_command_bus:
                    # Jika ada repository write, harus ada UoW atau transactional decorator
                    class_violations.append(Finding(
                        severity="ERROR",
                        file=rel,
                        line=node.lineno,
                        category="usage",
                        message=f"Use case '{node.name}' does write operations without UoW",
                        detail="Add @transactional decorator or use 'with self.uow:' context.",
                        rca=self._generate_rca("Write without UoW", "ERROR", {"class": node.name}),
                    ))

                if has_direct_commit and not has_uow and not has_command_bus:
                    class_violations.append(Finding(
                        severity="ERROR",
                        file=rel,
                        line=node.lineno,
                        category="bypass",
                        message=f"Use case '{node.name}' calls session.commit() directly, bypassing UoW",
                        detail="Use UoW.commit() instead of direct session commit.",
                        rca=self._generate_rca("Direct session commit", "ERROR", {"class": node.name}),
                    ))

                # Jika write tapi hanya command bus, tidak perlu violation
                if is_write and has_command_bus and not has_repo_calls and not has_service_write:
                    # Command bus handles transaction, no violation
                    pass

                summary = UseCaseSummary(
                    file=rel,
                    class_name=node.name,
                    line=node.lineno,
                    has_uow=has_uow,
                    has_transactional_decorator=has_tx_decorator,
                    has_direct_session_commit=has_direct_commit,
                    has_repository_calls=has_repo_calls,
                    has_service_write=has_service_write,
                    has_command_bus=has_command_bus,
                    is_write=is_write,
                    violations=class_violations,
                )
                summaries.append(summary)
                findings.extend(class_violations)

        return findings, summaries

    def scan(self, progress_callback: Optional[Callable] = None) -> Report:
        t0 = time.monotonic()
        report = Report()

        all_files = []
        for d in [self.root / "ports" / "primary", self.root / "adapters" / "secondary_impl",
                  self.root / "application" / "use_cases"]:
            if d.exists():
                all_files.extend(d.rglob("*.py"))
        report.total_files_scanned = len(all_files)

        findings = []
        findings.extend(self.check_port())
        findings.extend(self.check_implementation())

        use_case_findings, summaries = self.analyze_use_cases()
        findings.extend(use_case_findings)
        report.use_case_summaries = summaries
        report.total_use_cases_scanned = len(summaries)
        # Use cases with UoW: either has_uow or tx_decorator or command_bus (handled by bus)
        report.use_cases_with_uow = sum(1 for s in summaries if s.is_write and (s.has_uow or s.has_transactional_decorator or s.has_command_bus))
        # Use cases without UoW: write without any of the above
        report.use_cases_without_uow = sum(1 for s in summaries if s.is_write and not s.has_uow and not s.has_transactional_decorator and not s.has_command_bus)
        report.use_cases_readonly = sum(1 for s in summaries if not s.is_write)

        report.findings = findings

        errors = report.error_count
        warnings = report.warning_count
        score = 100.0 - errors * 10 - warnings * 2
        report.score = max(0.0, min(100.0, score))

        report.scan_time = time.monotonic() - t0
        return report

# ─── REPORTING ──────────────────────────────────────────────────────────────
def print_report(report: Report, checker: UoWChecker, verbose: bool = False, show_rca: bool = False):
    c = COLOR
    _safe_print(f"\n{c['BOLD']}{c['CYAN']}{'='*72}")
    _safe_print("  UNIT OF WORK (UoW) PATTERN CHECKER")
    _safe_print(f"  v{__version__} — Big 4 Audit Grade")
    _safe_print(f"{'='*72}{c['RESET']}")
    _safe_print("  📋 UoW Contract Standards:")
    _safe_print("    ✅ UoW Port defines begin/commit/rollback or context manager")
    _safe_print("    ✅ UoW Implementation has context manager or explicit commit/rollback")
    _safe_print("    ✅ Use Cases use @transactional or 'with uow:' context for writes")
    _safe_print("    ✅ No direct repository write calls bypassing UoW")
    _safe_print("    ✅ CommandBus dispatch considered UoW-aware")
    _safe_print("    ✅ Read/Write awareness: read-only use cases don't need UoW")

    _safe_print(f"\n  📊 Summary:")
    _safe_print(f"    Files scanned    : {report.total_files_scanned}")
    _safe_print(f"    Use Cases scanned: {report.total_use_cases_scanned}")
    _safe_print(f"      ✅ With UoW    : {report.use_cases_with_uow}")
    _safe_print(f"      ❌ Without UoW : {report.use_cases_without_uow}")
    _safe_print(f"      📖 Read-only   : {report.use_cases_readonly}")
    _safe_print(f"    Findings         : {len(report.findings)}")
    _safe_print(f"    Errors (CRITICAL): {c['RED']}{report.error_count}{c['RESET']}")
    _safe_print(f"    Warnings (MEDIUM): {c['YELLOW']}{report.warning_count}{c['RESET']}")
    _safe_print(f"    Infos (LOW)      : {c['DIM']}{report.info_count}{c['RESET']}")
    _safe_print(f"    Score            : {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score:.1f}/100{c['RESET']}")
    _safe_print(f"    RCA Engine       : {'✅ Active' if _RCA_AVAILABLE else '⚠️ Fallback'}")
    _safe_print(f"    Strict mode      : {'✅ Enabled' if checker.strict else '❌ Disabled'}")
    _safe_print(f"    Scan time        : {report.scan_time:.3f}s")

    if report.findings:
        by_cat = {}
        for f in report.findings:
            by_cat.setdefault(f.category, []).append(f)

        _safe_print(f"\n{c['CYAN']}By Category:{c['RESET']}")
        cat_labels = {"port": "UoW Port", "implementation": "UoW Implementation", "usage": "UoW Usage", "bypass": "Bypass Detection"}
        for cat, items in by_cat.items():
            label = cat_labels.get(cat, cat)
            err = sum(1 for i in items if i.severity == "ERROR")
            warn = sum(1 for i in items if i.severity == "WARNING")
            color = c["RED"] if err else c["YELLOW"] if warn else c["GREEN"]
            _safe_print(f"  {label}: {color}{err} errors, {warn} warnings{c['RESET']}")

        _safe_print(f"\n{c['RED'] if report.error_count else c['YELLOW']}Findings (first 30):{c['RESET']}")
        for f in report.findings[:30]:
            color = c["RED"] if f.severity == "ERROR" else c["YELLOW"]
            _safe_print(f"  {color}[{f.severity}]{c['RESET']} [{f.category}] {f.file}:{f.line}")
            _safe_print(f"     {f.message}")
            if verbose and f.detail:
                _safe_print(f"     {c['CYAN']}→ {f.detail}{c['RESET']}")
            if show_rca and f.rca:
                rc = f.rca.get("root_cause", "")
                fix = f.rca.get("suggested_fix", "")
                if rc:
                    _safe_print(f"     {c['MAGENTA']}🔍 RCA: {rc[:120]}{c['RESET']}")
                if fix:
                    _safe_print(f"     {c['MAGENTA']}🔧 Fix: {fix[:120]}{c['RESET']}")
        if len(report.findings) > 30:
            _safe_print(f"  ... and {len(report.findings)-30} more")

    else:
        _safe_print(f"\n{c['GREEN']}✅ All UoW contracts satisfied!{c['RESET']}")

    if report.use_case_summaries:
        _safe_print(f"\n{c['CYAN']}─── USE CASE UoW USAGE ───{c['RESET']}")
        for s in report.use_case_summaries:
            if s.is_write and (s.has_uow or s.has_transactional_decorator or s.has_command_bus):
                status = f"{c['GREEN']}✅ with UoW{c['RESET']}"
            elif s.is_write and not s.has_uow and not s.has_transactional_decorator and not s.has_command_bus:
                status = f"{c['RED']}❌ NO UoW{c['RESET']}"
            elif not s.is_write:
                status = f"{c['CYAN']}📖 read-only{c['RESET']}"
            else:
                status = f"{c['YELLOW']}⚠️ unknown{c['RESET']}"
            _safe_print(f"  {s.class_name} @ {s.file}:{s.line} {status}")

    _safe_print(f"\n{c['CYAN']}{'─'*72}{c['RESET']}")
    if report.passed:
        _safe_print(f"  {c['GREEN']}✅ PASS — All UoW contracts satisfied.{c['RESET']}")
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
            "total_use_cases_scanned": report.total_use_cases_scanned,
            "use_cases_with_uow": report.use_cases_with_uow,
            "use_cases_without_uow": report.use_cases_without_uow,
            "use_cases_readonly": report.use_cases_readonly,
            "findings": [f.to_dict() for f in report.findings],
            "use_case_summaries": [
                {
                    "file": s.file,
                    "class": s.class_name,
                    "line": s.line,
                    "has_uow": s.has_uow,
                    "has_transactional_decorator": s.has_transactional_decorator,
                    "has_direct_session_commit": s.has_direct_session_commit,
                    "has_repository_calls": s.has_repository_calls,
                    "has_service_write": s.has_service_write,
                    "has_command_bus": s.has_command_bus,
                    "is_write": s.is_write,
                    "violations": [v.to_dict() for v in s.violations],
                }
                for s in report.use_case_summaries
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
            writer.writerow(["severity", "file", "line", "category", "message", "detail"])
            for fnd in report.findings:
                writer.writerow([fnd.severity, fnd.file, fnd.line, fnd.category, fnd.message, fnd.detail])
        _safe_print(f"{_c('GREEN')}✅ CSV saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save CSV: {e}{_c('RESET')}")
        return False

def save_html(report: Report, path: pathlib.Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>UoW Checker Report</title>
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
<h1>Unit of Work Pattern Checker Report</h1>
<div class="summary">
  <div class="card"><div class="value">{len(report.findings)}</div><div class="label">Findings</div></div>
  <div class="card"><div class="value" style="color:#dc3545">{report.error_count}</div><div class="label">Errors</div></div>
  <div class="card"><div class="value" style="color:#ffc107">{report.warning_count}</div><div class="label">Warnings</div></div>
  <div class="card"><div class="value">{report.score:.1f}</div><div class="label">Score</div></div>
  <div class="card"><div class="value">{'PASS' if report.passed else 'FAIL'}</div><div class="label">Status</div></div>
</div>
<h2>Findings</h2>
"""
        for f in report.findings:
            cls = "error" if f.severity == "ERROR" else "warning" if f.severity == "WARNING" else "info"
            html += f'<div class="finding {cls}"><strong>{f.severity}</strong> [{f.category}] {f.message}<br><small>{f.file}:{f.line}</small>{f.detail and f" <small>{f.detail}</small>" or ""}</div>'
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
        for f in report.findings:
            if f.severity in ("ERROR", "WARNING"):
                results.append({
                    "ruleId": f"UOW-{f.severity}",
                    "level": "error" if f.severity == "ERROR" else "warning",
                    "message": {"text": f.message},
                    "locations": [{
                        "physicalLocation": {
                            "artifactLocation": {"uri": f.file},
                            "region": {"startLine": max(1, f.line)},
                        }
                    }],
                })
        sarif = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [{
                "tool": {
                    "driver": {
                        "name": "UoWChecker",
                        "version": __version__,
                        "rules": [
                            {"id": "UOW-ERROR", "shortDescription": {"text": "UoW contract violation"}},
                            {"id": "UOW-WARNING", "shortDescription": {"text": "UoW best practice warning"}},
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

    if verbose: _safe_print(f"\nUoW Checker self-test v{__version__}…\n")

    # Test _has_repository_write
    code = """
class MyUseCase:
    def execute(self):
        self.repo.save(data)
"""
    tree = ast.parse(code)
    func = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)), None)
    if func:
        check("_has_repository_write detects repo.save", _has_repository_write(func))

    # Test _has_service_write
    code2 = """
class MyUseCase:
    def execute(self):
        self.journal_service.post_journal(data)
"""
    tree2 = ast.parse(code2)
    func2 = next((n for n in ast.walk(tree2) if isinstance(n, ast.FunctionDef)), None)
    if func2:
        check("_has_service_write detects service.post_journal", _has_service_write(func2))

    # Test _has_command_bus_dispatch
    code3 = """
class MyUseCase:
    def execute(self):
        self.command_bus.dispatch(command)
"""
    tree3 = ast.parse(code3)
    func3 = next((n for n in ast.walk(tree3) if isinstance(n, ast.FunctionDef)), None)
    if func3:
        check("_has_command_bus_dispatch detects command_bus.dispatch", _has_command_bus_dispatch(func3))

    # Test _has_uow_usage
    code4 = """
class MyUseCase:
    def execute(self):
        with self.uow:
            self.repo.save(data)
"""
    tree4 = ast.parse(code4)
    func4 = next((n for n in ast.walk(tree4) if isinstance(n, ast.FunctionDef)), None)
    if func4:
        check("_has_uow_usage detects with self.uow", _has_uow_usage(func4))

    if verbose: _safe_print(f"\nSelf-test: {passed} passed, {failed} failed {'✅' if failed==0 else '❌'}")
    return failed == 0

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description=f"UoW Checker v{__version__}")
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
    parser.add_argument("--version", action="version", version=f"uow_checker v{__version__}")

    args = parser.parse_args()

    if args.self_test:
        return 0 if self_test(verbose=True) else 1

    project_root = pathlib.Path(__file__).resolve().parent.parent
    extra_excludes = set(args.exclude.split(",")) if args.exclude else set()

    checker = UoWChecker(
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