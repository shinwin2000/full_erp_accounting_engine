#!/usr/bin/env python3
"""
checker/use_cases_checker.py
=============================
Sovereign ERP System — Use Case / Command Handler Compliance Checker v5.0.0

PERBAIKAN v5.0.0:
  - Context-aware transaction detection (@transactional, async with uow, session.begin)
  - Validasi input: hanya diwajibkan jika ada operasi write tanpa validasi
  - Error handling: deteksi decorator/middleware, tidak wajib if try/except for read-only
  - Dependency injection: detect @inject, base class, factory pattern
  - Scoring proporsional: CRITICAL -20, HIGH -10, MEDIUM -3, LOW -1
  - Perbaiki inkonsistensi severity rendering
  - RCA spesifik per jenis violation
  - False positive minimal
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import csv
import json
import logging
import pathlib
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

# ─── RCA INTEGRATION ──────────────────────────────────────────────────────────
_RCA_ENGINE = None
_RCA_AVAILABLE = False

def _init_rca() -> bool:
    global _RCA_ENGINE, _RCA_AVAILABLE
    if _RCA_AVAILABLE:
        return True
    try:
        from checker.core.rca import Severity, analyze_exception, get_engine
        _RCA_ENGINE = get_engine()
        _RCA_AVAILABLE = True
        return True
    except ImportError:
        pass
    _root = pathlib.Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    try:
        from checker.core.rca import Severity, analyze_exception, get_engine
        _RCA_ENGINE = get_engine()
        _RCA_AVAILABLE = True
        return True
    except ImportError:
        pass
    return False

_init_rca()

def _rca_analyze(exc: Exception, context: dict | None = None) -> dict | None:
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
COLOR: dict[str, str] = {
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
__version__ = "5.0.0"

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
EXECUTE_METHODS = {"execute", "handle", "__call__", "process", "run", "invoke"}
BASE_CLASS_NAMES = {"BaseUseCase", "CommandHandler", "QueryHandler", "UseCase", "Handler"}
EXCLUDED_DIRS_DEFAULT = {
    "checker", "tests", "migrations", "__pycache__", ".git",
    "docs", "scripts", "deployment", "monitoring", "reports",
    "venv", ".venv", "node_modules", "dist", "build",
}

# Filter false positive
SKIP_CLASS_PATTERNS = {
    "Result", "Status", "DTO", "Dto", "Schema", "Enum", "Event", "Command", "Query",
    "Action", "Error", "Exception", "Policy", "Registry", "Middleware",
    "Handler", "BaseHandler", "Base", "Metadata", "Config", "Settings",
    "Response", "Request", "Payload", "Envelope", "Wrapper",
    "Record", "Entry", "Line", "Item", "Summary", "Report",
    "Aging", "Bucket", "Card", "Projection", "ReadModel", "Snapshot",
    "Import", "Export", "Adapter", "Factory", "Builder", "Provider",
    "Manager", "Service", "Repository", "Store", "Cache", "Queue",
}
SKIP_PREFIXES = {"_", "get_", "set_", "is_", "has_", "to_", "from_"}
SKIP_SUFFIXES = {"Mixin", "Base", "Abstract", "Interface", "Protocol", "Port"}

# Transaction patterns
TRANSACTION_DECORATORS = {"transactional", "with_transaction", "transaction", "uow"}
TRANSACTION_MANAGER_CALLS = {"commit", "rollback", "save", "flush", "begin"}
UNIT_OF_WORK_PATTERNS = {"async with", "with", "begin", "transaction"}

# Validation patterns
VALIDATION_FUNCTIONS = {"validate", "is_valid", "check", "parse_obj", "model_validate", "validate_python", "validate_model"}

# ─── DATA CLASSES ─────────────────────────────────────────────────────────────
@dataclass
class UseCaseViolation:
    severity: str
    file: str
    class_name: str
    line: int
    message: str
    suggestion: str
    rca: dict | None = None

    def to_dict(self) -> dict:
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
    is_read_only: bool  # true if only SELECT queries, no writes
    violations: list[UseCaseViolation] = field(default_factory=list)

@dataclass
class Report:
    use_cases: list[UseCaseInfo] = field(default_factory=list)
    violations: list[UseCaseViolation] = field(default_factory=list)
    total_files_scanned: int = 0
    total_use_cases: int = 0
    score: float = 100.0
    scan_time: float = 0.0

    @property
    def critical_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "CRITICAL")

    @property
    def high_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "HIGH")

    @property
    def medium_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "MEDIUM")

    @property
    def low_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "LOW")

    @property
    def info_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "INFO")

    @property
    def error_count(self) -> int:
        return self.critical_count + self.high_count

    @property
    def passed(self) -> bool:
        return self.error_count == 0

# ─── AST UTILITIES ──────────────────────────────────────────────────────────
_AST_CACHE: dict[str, tuple[ast.AST | None, str | None]] = {}
_CACHE_LOCK = threading.Lock()

def _read_source(py_file: pathlib.Path) -> str | None:
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

def _get_ast(py_file: pathlib.Path) -> tuple[ast.AST | None, str | None]:
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

def _get_method_names(node: ast.ClassDef) -> set[str]:
    return {item.name for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))}

def _find_method_by_name(node: ast.ClassDef, names: set[str]) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name in names:
                return item
    return None

def _extract_type_name(ann: ast.expr | None) -> str:
    if ann is None:
        return ""
    if isinstance(ann, ast.Name):
        return ann.id
    if isinstance(ann, ast.Attribute):
        return ann.attr
    if isinstance(ann, ast.Subscript):
        return _extract_type_name(ann.value)
    return "Any"

def _has_decorator(func_node: ast.FunctionDef, decorator_names: set[str]) -> bool:
    for dec in func_node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id in decorator_names:
            return True
        if isinstance(dec, ast.Call):
            if isinstance(dec.func, ast.Name) and dec.func.id in decorator_names:
                return True
            if isinstance(dec.func, ast.Attribute) and dec.func.attr in decorator_names:
                return True
    return False

def _get_rca_for_violation(violation_type: str, class_name: str) -> dict:
    """Return specific RCA for each violation type."""
    rca_map = {
        "no_di": {
            "root_cause": "Use Case tidak memiliki dependency injection; dependensi dibuat secara langsung di dalam execute atau __init__ tanpa parameter.",
            "suggested_fix": "Tambahkan parameter __init__ untuk inject repository, unit of work, dan service. Atau gunakan decorator @inject.",
            "confidence": 0.85,
        },
        "no_type_hints": {
            "root_cause": "Method execute() tidak memiliki type hints untuk parameter dan return value.",
            "suggested_fix": "Tambahkan type hints: def execute(self, request: CreateInvoiceRequest) -> InvoiceResponse:",
            "confidence": 0.95,
        },
        "no_error_handling": {
            "root_cause": "execute() tidak memiliki error handling; exception akan bubble up ke caller tanpa log atau rollback.",
            "suggested_fix": "Tambahkan try/except dengan log error dan rollback transaksi. Atau gunakan decorator @transactional.",
            "confidence": 0.80,
        },
        "no_transaction": {
            "root_cause": "Use Case melakukan operasi write (save/update/delete) tetapi tidak ada manajemen transaksi (commit/rollback).",
            "suggested_fix": "Gunakan Unit of Work pattern: self.uow.commit() pada success, self.uow.rollback() pada error. Atau gunakan decorator @transactional.",
            "confidence": 0.75,
        },
        "no_validation": {
            "root_cause": "Input dari external tidak divalidasi sebelum digunakan di business logic.",
            "suggested_fix": "Gunakan Pydantic model_validate() atau custom validation untuk memvalidasi input DTO.",
            "confidence": 0.70,
        },
        "no_return_annotation": {
            "root_cause": "execute() tidak memiliki return type annotation.",
            "suggested_fix": "Tambahkan return type annotation: -> OutputDTO",
            "confidence": 0.90,
        },
    }
    return rca_map.get(violation_type, {
        "root_cause": f"Violation pada Use Case {class_name}",
        "suggested_fix": "Periksa implementasi Use Case sesuai contract.",
        "confidence": 0.50,
    })

# ─── CHECKER ──────────────────────────────────────────────────────────────────
class UseCaseChecker:
    def __init__(
        self,
        root: pathlib.Path,
        enable_rca: bool = True,
        strict: bool = False,
        extra_excludes: set[str] | None = None,
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

    def _should_skip_class(self, name: str) -> bool:
        for pattern in SKIP_CLASS_PATTERNS:
            if pattern in name:
                return True
        for prefix in SKIP_PREFIXES:
            if name.startswith(prefix):
                return True
        for suffix in SKIP_SUFFIXES:
            if name.endswith(suffix):
                return True
        return False

    def _get_python_files(self) -> list[pathlib.Path]:
        """Only scan application/use_cases/ and optionally application/* if contains use cases."""
        py_files = []
        use_cases_dir = self.root / "application" / "use_cases"
        if use_cases_dir.exists():
            for p in use_cases_dir.rglob("*.py"):
                if not self._should_skip_file(p):
                    py_files.append(p)
        # Also scan application/ (for use cases not in use_cases subfolder)
        app_dir = self.root / "application"
        if app_dir.exists():
            for p in app_dir.rglob("*.py"):
                if p.parent == use_cases_dir:
                    continue
                if not self._should_skip_file(p):
                    # Only include if likely contains UseCase classes
                    if "use_case" in p.stem.lower() or "command" in p.stem.lower() or "handler" in p.stem.lower():
                        py_files.append(p)
        return sorted(set(py_files))

    def _is_use_case_class(self, node: ast.ClassDef, file_path: pathlib.Path) -> bool:
        """Determine if a class is a true Use Case."""
        name = node.name
        if self._should_skip_class(name):
            return False

        # Must have execute/handle method
        method_names = _get_method_names(node)
        has_exec = any(m in EXECUTE_METHODS for m in method_names)
        if not has_exec:
            return False

        exec_method = _find_method_by_name(node, EXECUTE_METHODS)
        if exec_method:
            args = [arg for arg in exec_method.args.args if arg.arg not in ("self", "cls")]
            if len(args) == 0:
                return False

        # Check if in use_cases folder
        rel_path = str(file_path.relative_to(self.root)).replace("\\", "/")
        if "application/use_cases/" in rel_path:
            return True

        # Check base classes
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in BASE_CLASS_NAMES:
                return True
            if isinstance(base, ast.Attribute) and base.attr in BASE_CLASS_NAMES:
                return True

        # Check decorators
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id in {"command_handler", "query_handler", "use_case"}:
                return True
            if isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name) and dec.func.id in {"command_handler", "query_handler"}:
                    return True

        return False

    def _has_type_hints(self, node: ast.ClassDef) -> bool:
        exec_method = _find_method_by_name(node, EXECUTE_METHODS)
        if not exec_method:
            return False
        has_return = exec_method.returns is not None
        has_params = any(
            arg.annotation is not None for arg in exec_method.args.args if arg.arg not in ("self", "cls")
        )
        return has_return and has_params

    def _has_dependency_injection(self, node: ast.ClassDef) -> bool:
        # Check __init__ parameters
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                args = [arg for arg in item.args.args if arg.arg not in ("self", "cls")]
                if len(args) > 0:
                    return True
        # Check @inject decorator on class or method
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id in {"inject", "injectable"}:
                return True
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id in {"inject", "injectable"}:
                return True
        # Check class-level __init_subclass__ or dependency injection via base class
        for base in node.bases:
            if isinstance(base, ast.Name) and "DI" in base.id:
                return True
        return False

    def _has_error_handling(self, node: ast.ClassDef) -> bool:
        exec_method = _find_method_by_name(node, EXECUTE_METHODS)
        if not exec_method:
            return False
        # Check for try/except
        for sub in ast.walk(exec_method):
            if isinstance(sub, ast.Try):
                return True
        # Check for decorators that handle errors
        if _has_decorator(exec_method, {"transactional", "retry", "with_retry"}):
            return True
        # Check if method is wrapped with error handling via class decorator
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id in {"transactional", "retry"}:
                return True
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id in {"transactional", "retry"}:
                return True
        return False

    def _has_transaction_management(self, node: ast.ClassDef) -> bool:
        exec_method = _find_method_by_name(node, EXECUTE_METHODS)
        if not exec_method:
            return False

        # Check for commit/rollback calls
        for sub in ast.walk(exec_method):
            if isinstance(sub, ast.Call):
                if isinstance(sub.func, ast.Attribute):
                    attr = sub.func.attr
                    if attr in TRANSACTION_MANAGER_CALLS:
                        return True
                    if attr in {"uow", "unit_of_work"} and hasattr(sub.func.value, "id") and sub.func.value.id == "self":
                        return True
                if isinstance(sub.func, ast.Name) and sub.func.id in TRANSACTION_MANAGER_CALLS:
                    return True

        # Check for decorators that handle transaction
        if _has_decorator(exec_method, TRANSACTION_DECORATORS):
            return True

        # Check for async with or with statement for uow
        for sub in ast.walk(exec_method):
            if isinstance(sub, ast.With):
                for item in sub.items:
                    if isinstance(item.context_expr, ast.Call):
                        if isinstance(item.context_expr.func, ast.Attribute):
                            if "uow" in item.context_expr.func.attr or "begin" in item.context_expr.func.attr:
                                return True
                        if isinstance(item.context_expr.func, ast.Name) and item.context_expr.func.id in {"uow", "unit_of_work"}:
                            return True

        # Check for class-level transaction decorator
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id in TRANSACTION_DECORATORS:
                return True
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id in TRANSACTION_DECORATORS:
                return True

        return False

    def _has_validation(self, node: ast.ClassDef) -> bool:
        exec_method = _find_method_by_name(node, EXECUTE_METHODS)
        if not exec_method:
            return False
        for sub in ast.walk(exec_method):
            if isinstance(sub, ast.Call):
                if isinstance(sub.func, ast.Attribute):
                    attr = sub.func.attr
                    if attr in VALIDATION_FUNCTIONS:
                        return True
                if isinstance(sub.func, ast.Name) and sub.func.id in VALIDATION_FUNCTIONS:
                    return True
        return False

    def _is_async_method(self, node: ast.ClassDef) -> bool:
        exec_method = _find_method_by_name(node, EXECUTE_METHODS)
        return isinstance(exec_method, ast.AsyncFunctionDef)

    def _has_return_annotation(self, node: ast.ClassDef) -> bool:
        exec_method = _find_method_by_name(node, EXECUTE_METHODS)
        return exec_method is not None and exec_method.returns is not None

    def _is_read_only(self, node: ast.ClassDef) -> bool:
        """Determine if use case only reads data (no write operations)."""
        exec_method = _find_method_by_name(node, EXECUTE_METHODS)
        if not exec_method:
            return True
        write_operations = {"save", "update", "delete", "remove", "insert", "create", "commit", "flush"}
        for sub in ast.walk(exec_method):
            if isinstance(sub, ast.Call):
                if isinstance(sub.func, ast.Attribute):
                    attr = sub.func.attr
                    if attr in write_operations:
                        return False
                if isinstance(sub.func, ast.Name) and sub.func.id in write_operations:
                    return False
        return True

    def _get_execute_method(self, node: ast.ClassDef) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        return _find_method_by_name(node, EXECUTE_METHODS)

    def _generate_rca(self, violation_type: str, class_name: str) -> dict | None:
        if not self.enable_rca:
            return None
        rca_info = _get_rca_for_violation(violation_type, class_name)
        return {
            "root_cause": rca_info["root_cause"],
            "suggested_fix": rca_info["suggested_fix"],
            "confidence": rca_info["confidence"],
        }

    def _analyze_class(self, node: ast.ClassDef, rel_path: str, file_path: pathlib.Path) -> UseCaseInfo | None:
        if not self._is_use_case_class(node, file_path):
            return None

        has_exec = self._get_execute_method(node) is not None
        has_th = self._has_type_hints(node)
        has_di = self._has_dependency_injection(node)
        has_eh = self._has_error_handling(node)
        has_tm = self._has_transaction_management(node)
        has_val = self._has_validation(node)
        is_async = self._is_async_method(node)
        has_return = self._has_return_annotation(node)
        read_only = self._is_read_only(node)

        violations: list[UseCaseViolation] = []
        exec_method = self._get_execute_method(node)
        line = exec_method.lineno if exec_method else node.lineno

        # Rule 1: Must have execute method (CRITICAL)
        if not has_exec:
            msg = "Use Case does not have execute(), handle(), or __call__() method."
            rca = self._generate_rca("no_execute", node.name)
            violations.append(UseCaseViolation(
                severity="CRITICAL",
                file=rel_path,
                class_name=node.name,
                line=node.lineno,
                message=msg,
                suggestion="Add 'def execute(self, request: RequestDTO) -> ResponseDTO:' as entry point.",
                rca=rca,
            ))

        # Rule 2: Type hints (MEDIUM)
        if has_exec and not has_th:
            msg = "execute() method lacks type hints for parameters or return value."
            rca = self._generate_rca("no_type_hints", node.name)
            violations.append(UseCaseViolation(
                severity="MEDIUM",
                file=rel_path,
                class_name=node.name,
                line=line,
                message=msg,
                suggestion="Add type hints: def execute(self, request: CreateInvoiceRequest) -> InvoiceResponse:",
                rca=rca,
            ))

        # Rule 3: Dependency Injection (HIGH)
        if not has_di:
            msg = "Use Case lacks dependency injection (__init__ does not accept parameters or no @inject decorator)."
            rca = self._generate_rca("no_di", node.name)
            violations.append(UseCaseViolation(
                severity="HIGH",
                file=rel_path,
                class_name=node.name,
                line=node.lineno,
                message=msg,
                suggestion="Use __init__ to inject dependencies: def __init__(self, repo: Repository, uow: UoW): or use @inject.",
                rca=rca,
            ))

        # Rule 4: Error handling (HIGH only if not read_only)
        if has_exec and not has_eh and not read_only:
            msg = "execute() method does not have error handling (try/except) for domain errors."
            rca = self._generate_rca("no_error_handling", node.name)
            violations.append(UseCaseViolation(
                severity="HIGH",
                file=rel_path,
                class_name=node.name,
                line=line,
                message=msg,
                suggestion="Wrap business logic with try/except to catch DomainError, ValidationError, etc.",
                rca=rca,
            ))

        # Rule 5: Transaction management (MEDIUM for read-write, skip for read-only)
        if has_exec and not has_tm and not read_only:
            msg = "Use Case performs write operations but does not have transaction management (commit/rollback)."
            rca = self._generate_rca("no_transaction", node.name)
            violations.append(UseCaseViolation(
                severity="MEDIUM",
                file=rel_path,
                class_name=node.name,
                line=line,
                message=msg,
                suggestion="Use Unit of Work: self.uow.commit() on success, rollback in except. Or use @transactional.",
                rca=rca,
            ))

        # Rule 6: Validation (LOW only if write and no validation)
        if has_exec and not has_val and not read_only:
            msg = "execute() does not validate input (Pydantic or manual validation)."
            rca = self._generate_rca("no_validation", node.name)
            violations.append(UseCaseViolation(
                severity="LOW",
                file=rel_path,
                class_name=node.name,
                line=line,
                message=msg,
                suggestion="Validate input DTO using Pydantic model_validate() or custom validation function.",
                rca=rca,
            ))

        # Rule 7: Return annotation (LOW if strict)
        if self.strict and has_exec and not has_return:
            msg = "execute() method does not have return type annotation."
            rca = self._generate_rca("no_return_annotation", node.name)
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
            is_read_only=read_only,
            violations=violations,
        )

    def scan(self, progress_callback: Callable | None = None) -> Report:
        t0 = time.monotonic()
        report = Report()
        py_files = self._get_python_files()
        report.total_files_scanned = len(py_files)

        results: list[UseCaseInfo] = []
        total = len(py_files)

        def _scan_one(idx: int, py_file: pathlib.Path) -> list[UseCaseInfo]:
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

        # Scoring: CRITICAL -20, HIGH -10, MEDIUM -3, LOW -1
        score = 100.0
        for v in all_violations:
            if v.severity == "CRITICAL":
                score -= 20
            elif v.severity == "HIGH":
                score -= 10
            elif v.severity == "MEDIUM":
                score -= 3
            elif v.severity == "LOW":
                score -= 1
        report.score = max(0.0, min(100.0, score))

        report.scan_time = time.monotonic() - t0
        return report

# ─── REPORTING ──────────────────────────────────────────────────────────────
def print_report(report: Report, verbose: bool = False, show_rca: bool = False):
    c = COLOR
    _safe_print(f"\n{c['BOLD']}{c['CYAN']}{'='*72}")
    _safe_print("  USE CASE / COMMAND HANDLER CONTRACT REPORT")
    _safe_print(f"  v{__version__} — Big 4 Audit Grade")
    _safe_print(f"{'='*72}{c['RESET']}")
    _safe_print("  📋 Use Case Contract Standards (Context-Aware):")
    _safe_print("    ✅ execute() / handle() / __call__()  — entry point (CRITICAL)")
    _safe_print("    ✅ type hints (params & return)      — type safety (MEDIUM)")
    _safe_print("    ✅ dependency injection (__init__)   — testability (HIGH)")
    _safe_print("    ✅ error handling (try/except)       — robustness (HIGH jika write)")
    _safe_print("    ✅ transaction management            — data consistency (MEDIUM jika write)")
    _safe_print("    ✅ input validation                  — security (LOW jika write)")

    _safe_print("\n  📊 Summary:")
    _safe_print(f"    Files scanned    : {report.total_files_scanned}")
    _safe_print(f"    Use Cases found  : {report.total_use_cases}")
    _safe_print(f"    CRITICAL         : {c['RED']}{report.critical_count}{c['RESET']}")
    _safe_print(f"    HIGH             : {c['YELLOW']}{report.high_count}{c['RESET']}")
    _safe_print(f"    MEDIUM           : {c['MAGENTA']}{report.medium_count}{c['RESET']}")
    _safe_print(f"    LOW              : {c['DIM']}{report.low_count}{c['RESET']}")
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
            sev_color = c["RED"] if sev in ("CRITICAL", "HIGH") else c["MAGENTA"] if sev == "MEDIUM" else c["DIM"]
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
        _safe_print(f"\n{c['GREEN']}✅ All Use Cases are compliant!{c['RESET']}")

    _safe_print(f"\n{c['CYAN']}{'─'*72}{c['RESET']}")
    if report.passed:
        _safe_print(f"  {c['GREEN']}✅ PASS — All Use Cases contract satisfied.{c['RESET']}")
    else:
        _safe_print(f"  {c['RED']}❌ FAIL — {report.error_count} critical/high violation(s) need fixing.{c['RESET']}")

# ─── EXPORT ──────────────────────────────────────────────────────────────────
def save_json(report: Report, path: pathlib.Path) -> bool:
    try:
        data = {
            "version": __version__,
            "timestamp": datetime.now(UTC).isoformat(),
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
                    "is_read_only": uc.is_read_only,
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
  <div class="card"><div class="value" style="color:#dc3545">{report.error_count}</div><div class="label">Critical/High</div></div>
  <div class="card"><div class="value" style="color:#ffc107">{report.medium_count}</div><div class="label">Medium</div></div>
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

    # Good Use Case
    code = """
class CreateInvoiceUseCase:
    def __init__(self, repo: Repository, uow: UoW):
        self.repo = repo
        self.uow = uow

    def execute(self, request: CreateInvoiceRequest) -> InvoiceResponse:
        try:
            invoice = self.repo.create(request)
            self.uow.commit()
            return InvoiceResponse(invoice_id=invoice.id)
        except Exception:
            self.uow.rollback()
            raise
"""
    tree = ast.parse(code)
    node = next((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)), None)
    checker = UseCaseChecker(pathlib.Path.cwd(), enable_rca=False)
    if node:
        info = checker._analyze_class(node, "test.py", pathlib.Path("application/use_cases/test.py"))
        if info:
            check("detects use case", True)
            check("has_execute", info.has_execute)
            check("has_type_hints", info.has_type_hints)
            check("has_di", info.has_dependency_injection)
            check("has_eh", info.has_error_handling)
            check("has_tm", info.has_transaction_management)
            check("has_val", info.has_validation)

    # False positive filters
    for name in ("InvoiceResult", "PaymentStatus", "CreateInvoiceDTO"):
        check(f"skip {name}", checker._should_skip_class(name))

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
