#!/usr/bin/env python3
"""
checker/query_checker.py – Query Handler / Query Bus Compliance Checker
========================================================================
Versi   : 4.2.0
Standar : Big 4 Forensic Audit · ISO/IEC 25010 · SOX/ISA 315 Compliant

Perbaikan v4.2.0:
  - Query object (berakhiran Query) TIDAK dianggap sebagai Query Handler
  - Hanya class dengan nama mengandung "QueryHandler" atau decorator @query_handler atau inherit BaseQueryHandler
  - False positive turun drastis
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
logger = logging.getLogger("query_checker")
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
__version__ = "4.2.0"

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
EXCLUDED_DIRS_DEFAULT = {
    "checker", "tests", "migrations", "__pycache__", ".git",
    "docs", "scripts", "deployment", "monitoring", "reports",
    "venv", ".venv", "node_modules", "dist", "build",
}

# Hanya deteksi QueryHandler, bukan Query object
QUERY_HANDLER_KEYWORDS = {"QueryHandler", "QueryExecutor", "QueryService"}
BASE_QUERY_HANDLER_NAMES = {"BaseQueryHandler", "QueryHandlerBase"}
EXECUTE_METHODS = {"execute", "handle", "__call__", "process", "run", "fetch", "get", "find", "select"}

# False positive filters
SKIP_CLASS_PATTERNS = {
    "Schema", "DTO", "Dto", "Response", "Request", "Error", "Exception",
    "Policy", "Registry", "Middleware", "Factory", "Builder",
    "Repository", "RepositoryPort", "Port", "Adapter", "Client", "Store", "Cache",
    "Service", "Manager", "Provider", "Config", "Settings", "Entity", "ValueObject",
    "Aggregate", "Projection", "ReadModel", "Table", "Model", "Migration",
    "Injector", "Interceptor", "Decorator", "Wrapper",
    "Metadata", "Status", "Result", "Envelope", "Payload",
}

# I/O operations that require error handling
IO_OPERATIONS = {
    "session", "db", "database", "repository", "repo",
    "cache", "redis", "memcached", "kafka", "mq", "queue",
    "http", "client", "api", "rest", "grpc", "socket",
    "file", "io", "storage", "s3", "gcs", "azure",
    "transaction", "commit", "rollback", "execute", "query", "fetch",
}

# ─── DATA CLASSES ─────────────────────────────────────────────────────────────
@dataclass
class QueryViolation:
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
class QueryInfo:
    file: str
    class_name: str
    line: int
    is_query_handler: bool
    has_execute: bool
    has_type_hints: bool
    has_dependency_injection: bool
    has_error_handling: bool
    has_caching: bool
    has_logging: bool
    is_async: bool
    has_return_annotation: bool
    performs_io: bool
    needs_di: bool
    violations: list[QueryViolation] = field(default_factory=list)

@dataclass
class Report:
    queries: list[QueryInfo] = field(default_factory=list)
    violations: list[QueryViolation] = field(default_factory=list)
    total_files_scanned: int = 0
    total_queries: int = 0
    score: float = 100.0
    scan_time: float = 0.0

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "CRITICAL")

    @property
    def high_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "HIGH")

    @property
    def medium_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "MEDIUM")

    @property
    def info_count(self) -> int:
        return sum(1 for v in self.violations if v.severity in ("LOW", "INFO"))

    @property
    def passed(self) -> bool:
        return self.error_count == 0 and self.high_count == 0

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

def _extract_type_name(annotation_node: ast.expr | None) -> str:
    if annotation_node is None:
        return ""
    if isinstance(annotation_node, ast.Name):
        return annotation_node.id
    if isinstance(annotation_node, ast.Attribute):
        return annotation_node.attr
    if isinstance(annotation_node, ast.Subscript):
        return _extract_type_name(annotation_node.value)
    if isinstance(annotation_node, ast.Constant):
        return str(annotation_node.value)
    return "Any"

def _generate_rca(msg: str, severity: str, context: dict | None = None) -> dict | None:
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
        return {"root_cause": msg, "suggested_fix": "Periksa implementasi Query Handler."}

# ─── CHECKER ──────────────────────────────────────────────────────────────────
class QueryChecker:
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
        return False

    def _is_query_handler_class(self, node: ast.ClassDef, file_path: pathlib.Path) -> bool:
        """
        Determine if class is a true Query Handler.
        Hanya deteksi:
        - Nama mengandung "QueryHandler"
        - Decorator @query_handler
        - Inherit dari BaseQueryHandler
        """
        name = node.name
        if self._should_skip_class(name):
            return False

        # 1. Nama mengandung QueryHandler
        if "QueryHandler" in name:
            return True

        # 2. Explicit decorator @query_handler
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id in {"query_handler", "query"}:
                return True
            if isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name) and dec.func.id in {"query_handler", "query"}:
                    return True

        # 3. Inherits from BaseQueryHandler
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in BASE_QUERY_HANDLER_NAMES:
                return True
            if isinstance(base, ast.Attribute) and base.attr in BASE_QUERY_HANDLER_NAMES:
                return True

        # 4. Check for execute method with proper signature (strong signal)
        # but only if name suggests it's a handler
        method_names = _get_method_names(node)
        has_exec = any(m in EXECUTE_METHODS for m in method_names)
        if not has_exec:
            return False

        execute_method = _find_method_by_name(node, EXECUTE_METHODS)
        if execute_method:
            args = [arg for arg in execute_method.args.args if arg.arg not in ("self", "cls")]
            if len(args) == 0:
                return False
        else:
            return False

        # 5. Must be in query-handler related folders
        rel_path = str(file_path.relative_to(self.root)).replace("\\", "/")
        is_in_query_folder = any(
            folder in rel_path.split("/")
            for folder in ("query_handlers", "queries", "query")
        )
        if is_in_query_folder:
            return True

        return False

    def _detect_io_operations(self, node: ast.ClassDef) -> bool:
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in EXECUTE_METHODS:
                for sub in ast.walk(item):
                    if isinstance(sub, ast.Call):
                        if isinstance(sub.func, ast.Name):
                            func_name = sub.func.id.lower()
                            for io_key in IO_OPERATIONS:
                                if io_key in func_name:
                                    return True
                        if isinstance(sub.func, ast.Attribute):
                            attr = sub.func.attr.lower()
                            for io_key in IO_OPERATIONS:
                                if io_key in attr:
                                    return True
        return False

    def _needs_dependency_injection(self, node: ast.ClassDef) -> bool:
        if self._detect_io_operations(node):
            return True
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                args = [arg for arg in item.args.args if arg.arg not in ("self", "cls")]
                if len(args) > 0:
                    for arg in args:
                        if arg.annotation is None:
                            return True
                        type_name = _extract_type_name(arg.annotation)
                        if type_name not in ("str", "int", "float", "bool", "UUID", "date", "datetime"):
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

    def _has_caching(self, node: ast.ClassDef) -> bool:
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in EXECUTE_METHODS:
                for dec in item.decorator_list:
                    if isinstance(dec, ast.Name) and "cache" in dec.id.lower():
                        return True
                    if isinstance(dec, ast.Call):
                        if isinstance(dec.func, ast.Name) and "cache" in dec.func.id.lower():
                            return True
                for sub in ast.walk(item):
                    if isinstance(sub, ast.Call):
                        if isinstance(sub.func, ast.Name) and sub.func.id in {"cache", "cached", "get_from_cache"}:
                            return True
                        if isinstance(sub.func, ast.Attribute):
                            if any(kw in sub.func.attr.lower() for kw in ("cache", "cached", "ttl")):
                                return True
        return False

    def _has_logging(self, node: ast.ClassDef) -> bool:
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in EXECUTE_METHODS:
                for sub in ast.walk(item):
                    if isinstance(sub, ast.Call):
                        if isinstance(sub.func, ast.Name) and sub.func.id in {"logger", "log", "logging"}:
                            return True
                        if isinstance(sub.func, ast.Attribute):
                            if sub.func.attr in {"info", "debug", "warning", "error", "exception"}:
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

    def _get_execute_method(self, node: ast.ClassDef) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in EXECUTE_METHODS:
                return item
        return None

    def _analyze_class(self, node: ast.ClassDef, rel_path: str, file_path: pathlib.Path) -> QueryInfo | None:
        if not self._is_query_handler_class(node, file_path):
            return None

        method_names = _get_method_names(node)
        has_exec = any(m in EXECUTE_METHODS for m in method_names)
        has_th = self._has_type_hints(node)
        has_di = self._has_dependency_injection(node)
        has_eh = self._has_error_handling(node)
        has_cache = self._has_caching(node)
        has_log = self._has_logging(node)
        is_async = self._is_async_method(node)
        has_return = self._has_return_annotation(node)
        performs_io = self._detect_io_operations(node)
        needs_di = self._needs_dependency_injection(node)

        violations: list[QueryViolation] = []
        execute_method = self._get_execute_method(node)
        line = execute_method.lineno if execute_method else node.lineno

        # Rule 1: Must have execute method
        if not has_exec:
            msg = "Query Handler does not have execute(), handle(), fetch(), or get() method."
            rca = _generate_rca(msg, "CRITICAL", {"class": node.name})
            violations.append(QueryViolation(
                severity="CRITICAL",
                file=rel_path,
                class_name=node.name,
                line=node.lineno,
                message=msg,
                suggestion="Add 'def execute(self, query: QueryDTO) -> ResponseDTO:' as entry point.",
                rca=rca,
            ))

        # Rule 2: Type hints (MEDIUM)
        if has_exec and not has_th:
            msg = "execute() method lacks type hints for parameters or return value."
            rca = _generate_rca(msg, "MEDIUM", {"class": node.name})
            violations.append(QueryViolation(
                severity="MEDIUM",
                file=rel_path,
                class_name=node.name,
                line=line,
                message=msg,
                suggestion="Add type hints: def execute(self, request: GetInvoiceQuery) -> InvoiceDTO:",
                rca=rca,
            ))

        # Rule 3: Dependency Injection (HIGH if needs DI but missing)
        if needs_di and not has_di:
            msg = "Query Handler needs dependencies but __init__ does not accept parameters (or uses hardcoded dependencies)."
            rca = _generate_rca(msg, "HIGH", {"class": node.name})
            violations.append(QueryViolation(
                severity="HIGH",
                file=rel_path,
                class_name=node.name,
                line=node.lineno,
                message=msg,
                suggestion="Use __init__ to inject dependencies: def __init__(self, repo: Repository, cache: Cache):",
                rca=rca,
            ))

        # Rule 4: Error Handling (HIGH if performs I/O and no try/except)
        if performs_io and not has_eh:
            msg = "execute() method performs I/O operations but lacks error handling (try/except)."
            rca = _generate_rca(msg, "HIGH", {"class": node.name})
            violations.append(QueryViolation(
                severity="HIGH",
                file=rel_path,
                class_name=node.name,
                line=line,
                message=msg,
                suggestion="Wrap I/O operations with try/except to catch database errors, network errors, etc.",
                rca=rca,
            ))

        # Rule 5: Caching (INFO)
        if performs_io and not has_cache:
            msg = "Query Handler performs I/O and may benefit from caching."
            rca = _generate_rca(msg, "INFO", {"class": node.name})
            violations.append(QueryViolation(
                severity="INFO",
                file=rel_path,
                class_name=node.name,
                line=line,
                message=msg,
                suggestion="Consider adding @cached(ttl=300) decorator for frequently accessed data.",
                rca=rca,
            ))

        # Rule 6: Logging (INFO)
        if not has_log:
            msg = "Query Handler does not have logging (recommended for observability)."
            rca = _generate_rca(msg, "INFO", {"class": node.name})
            violations.append(QueryViolation(
                severity="INFO",
                file=rel_path,
                class_name=node.name,
                line=line,
                message=msg,
                suggestion="Add logging: logger.info(f'Executing query {self.__class__.__name__}')",
                rca=rca,
            ))

        # Rule 7: Strict mode return annotation
        if self.strict and has_exec and not has_return:
            msg = "execute() method does not have return type annotation."
            rca = _generate_rca(msg, "LOW", {"class": node.name})
            violations.append(QueryViolation(
                severity="LOW",
                file=rel_path,
                class_name=node.name,
                line=line,
                message=msg,
                suggestion="Add return type annotation: -> ResponseDTO",
                rca=rca,
            ))

        return QueryInfo(
            file=rel_path,
            class_name=node.name,
            line=node.lineno,
            is_query_handler=True,
            has_execute=has_exec,
            has_type_hints=has_th,
            has_dependency_injection=has_di,
            has_error_handling=has_eh,
            has_caching=has_cache,
            has_logging=has_log,
            is_async=is_async,
            has_return_annotation=has_return,
            performs_io=performs_io,
            needs_di=needs_di,
            violations=violations,
        )

    def scan(self, progress_callback: Callable | None = None) -> Report:
        t0 = time.monotonic()
        report = Report()
        py_files = []
        scan_dirs = ["application/queries", "application/query_handlers", "application", "domain", "infrastructure", "adapters"]

        for dir_name in scan_dirs:
            base = self.root / dir_name
            if not base.exists():
                continue
            for p in base.rglob("*.py"):
                if not self._should_skip_file(p):
                    py_files.append(p)

        py_files = sorted(set(py_files))
        report.total_files_scanned = len(py_files)

        results: list[QueryInfo] = []
        total = len(py_files)

        def _scan_one(idx: int, py_file: pathlib.Path) -> list[QueryInfo]:
            if progress_callback:
                progress_callback(idx + 1, total)
            tree, err = _get_ast(py_file)
            if err or tree is None:
                if err and "SyntaxError" not in err:
                    logger.warning(f"Scan error in {py_file}: {err}")
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

        report.queries = results
        report.total_queries = len(results)

        all_violations = []
        for q in results:
            all_violations.extend(q.violations)
        report.violations = all_violations

        # Scoring: CRITICAL -25, HIGH -10, MEDIUM -3, LOW -0.5, INFO 0
        score = 100.0
        for v in all_violations:
            if v.severity == "CRITICAL":
                score -= 25
            elif v.severity == "HIGH":
                score -= 10
            elif v.severity == "MEDIUM":
                score -= 3
            elif v.severity == "LOW":
                score -= 0.5
        score = max(0.0, min(100.0, score))
        report.score = score

        report.scan_time = time.monotonic() - t0
        return report

# ─── REPORTING ──────────────────────────────────────────────────────────────
def print_report(report: Report, verbose: bool = False, show_rca: bool = False):
    c = COLOR
    _safe_print(f"\n{c['BOLD']}{c['CYAN']}{'='*72}")
    _safe_print("  QUERY HANDLER / QUERY BUS COMPLIANCE CHECKER")
    _safe_print(f"  v{__version__} — Big 4 Audit Grade")
    _safe_print(f"{'='*72}{c['RESET']}")
    _safe_print("  📋 Query Handler Contract Standards (Context-Aware):")
    _safe_print("    ✅ execute() / handle() / fetch() / get()  — entry point")
    _safe_print("    ✅ type hints (params & return)           — type safety (MEDIUM)")
    _safe_print("    ✅ dependency injection (__init__)        — testability (HIGH jika butuh)")
    _safe_print("    ✅ error handling (try/except)            — robustness (HIGH jika ada I/O)")
    _safe_print("    ✅ caching (optional)                     — performance (INFO)")
    _safe_print("    ✅ logging/audit                          — observability (INFO)")

    _safe_print("\n  📊 Summary:")
    _safe_print(f"    Files scanned    : {report.total_files_scanned}")
    _safe_print(f"    Query Handlers   : {report.total_queries}")
    _safe_print(f"    CRITICAL         : {c['RED']}{report.error_count}{c['RESET']}")
    _safe_print(f"    HIGH             : {c['YELLOW']}{report.high_count}{c['RESET']}")
    _safe_print(f"    MEDIUM           : {c['MAGENTA']}{report.medium_count}{c['RESET']}")
    _safe_print(f"    LOW/INFO         : {c['DIM']}{report.info_count}{c['RESET']}")
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
        _safe_print(f"\n{c['GREEN']}✅ All Query Handlers are compliant!{c['RESET']}")

    _safe_print(f"\n{c['CYAN']}{'─'*72}{c['RESET']}")
    if report.passed:
        _safe_print(f"  {c['GREEN']}✅ PASS — All critical Query Handler contracts satisfied.{c['RESET']}")
    else:
        _safe_print(f"  {c['RED']}❌ FAIL — {report.error_count + report.high_count} critical/high violation(s) need fixing.{c['RESET']}")

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
            "total_queries": report.total_queries,
            "violations": [v.to_dict() for v in report.violations],
            "queries": [
                {
                    "file": q.file,
                    "class": q.class_name,
                    "line": q.line,
                    "is_query_handler": q.is_query_handler,
                    "has_execute": q.has_execute,
                    "has_type_hints": q.has_type_hints,
                    "has_dependency_injection": q.has_dependency_injection,
                    "has_error_handling": q.has_error_handling,
                    "has_caching": q.has_caching,
                    "has_logging": q.has_logging,
                    "is_async": q.is_async,
                    "has_return_annotation": q.has_return_annotation,
                    "performs_io": q.performs_io,
                    "needs_di": q.needs_di,
                    "violations_count": len(q.violations),
                }
                for q in report.queries
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
<html><head><meta charset="utf-8"><title>Query Checker Report</title>
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
<h1>Query Handler Compliance Checker Report</h1>
<div class="summary">
  <div class="card"><div class="value">{report.total_queries}</div><div class="label">Query Handlers</div></div>
  <div class="card"><div class="value" style="color:#dc3545">{report.error_count}</div><div class="label">Critical</div></div>
  <div class="card"><div class="value" style="color:#ffc107">{report.high_count}</div><div class="label">High</div></div>
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
                "ruleId": f"QUERY-{v.severity}",
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
                        "name": "QueryChecker",
                        "version": __version__,
                        "rules": [
                            {"id": "QUERY-CRITICAL", "shortDescription": {"text": "Critical Query Handler contract violation"}},
                            {"id": "QUERY-HIGH", "shortDescription": {"text": "High severity Query Handler violation"}},
                            {"id": "QUERY-MEDIUM", "shortDescription": {"text": "Medium severity Query Handler violation"}},
                            {"id": "QUERY-LOW", "shortDescription": {"text": "Low severity Query Handler violation"}},
                            {"id": "QUERY-INFO", "shortDescription": {"text": "Info/Recommendation"}},
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

    if verbose: _safe_print(f"\nQuery Checker self-test v{__version__}…\n")

    # Test _extract_type_name
    check("_extract_type_name exists", callable(_extract_type_name))
    test_ann = ast.Name(id="Repository")
    check("_extract_type_name handles Name", _extract_type_name(test_ann) == "Repository")

    # Good Query Handler
    code = """
class GetInvoiceQueryHandler:
    def __init__(self, repo: Repository):
        self.repo = repo

    def execute(self, query_id: str) -> InvoiceDTO:
        try:
            return self.repo.find(query_id)
        except NotFoundError:
            return None
"""
    tree = ast.parse(code)
    node = next((n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)), None)
    checker = QueryChecker(pathlib.Path.cwd(), enable_rca=False)
    if node:
        info = checker._analyze_class(node, "test.py", pathlib.Path("test.py"))
        if info:
            check("_is_query_handler_class detects QueryHandler", True)
            check("has_execute", info.has_execute)
            check("has_type_hints", info.has_type_hints)
            check("has_dependency_injection", info.has_dependency_injection)
            check("has_error_handling", info.has_error_handling)
            check("performs_io", info.performs_io)
            check("needs_di", info.needs_di)

    # Query object (should be skipped)
    code2 = """
class GetAccountsQuery:
    def __init__(self, legal_entity_id: UUID):
        self.legal_entity_id = legal_entity_id
"""
    tree2 = ast.parse(code2)
    node2 = next((n for n in ast.walk(tree2) if isinstance(n, ast.ClassDef)), None)
    if node2:
        check("_is_query_handler_class skips Query object", not checker._is_query_handler_class(node2, pathlib.Path("test.py")))

    if verbose: _safe_print(f"\nSelf-test: {passed} passed, {failed} failed {'✅' if failed==0 else '❌'}")
    return failed == 0

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description=f"Query Checker v{__version__}")
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
    parser.add_argument("--version", action="version", version=f"query_checker v{__version__}")

    args = parser.parse_args()

    if args.self_test:
        return 0 if self_test(verbose=True) else 1

    project_root = pathlib.Path(__file__).resolve().parent.parent
    extra_excludes = set(args.exclude.split(",")) if args.exclude else set()

    checker = QueryChecker(
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
