#!/usr/bin/env python3
"""
checker/pytest_checker.py – Pytest Quality Checker (Hardened, Forensic-Grade)
================================================================================
Versi   : 6.0.1
Standar : ISO/IEC 25010-informed static analysis heuristics (bukan audit forensik resmi)

Perubahan v6.0.1:
- FITUR BARU: opsi --list-metric-files <METRIC> untuk menampilkan semua file
  yang skornya di bawah --metric-threshold (default 70.0) untuk metrik tertentu.
  Memudahkan identifikasi file-file yang menyebabkan low score di metrik seperti
  negative_path, database_verification, domain_event, dll. File diurutkan dari
  skor terendah. Contoh: python checker/pytest_checker.py --list-metric-files database_verification

... (riwayat perubahan sebelumnya tetap sama, tapi di sini dipotong agar ringkas)
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import logging
import pathlib
import re
import shutil
import sys
import tempfile
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import wraps
from typing import Any, Literal

# ─── RCA INTEGRATION ──────────────────────────────────────────────────────────
_RCA_ENGINE = None
_RCA_AVAILABLE = False


def _init_rca() -> bool:
    global _RCA_ENGINE, _RCA_AVAILABLE
    if _RCA_AVAILABLE:
        return True
    for _ in range(2):
        try:
            from checker.core.rca import get_engine
            _RCA_ENGINE = get_engine()
            _RCA_AVAILABLE = True
            return True
        except ImportError:
            _root = pathlib.Path(__file__).resolve().parent.parent
            if str(_root) not in sys.path:
                sys.path.insert(0, str(_root))
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
_log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logger = logging.getLogger("pytest_checker")
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
        "RED": colorama.Fore.RED,
        "GREEN": colorama.Fore.GREEN,
        "YELLOW": colorama.Fore.YELLOW,
        "CYAN": colorama.Fore.CYAN,
        "MAGENTA": colorama.Fore.MAGENTA,
        "WHITE": colorama.Fore.WHITE,
        "BOLD": colorama.Style.BRIGHT,
        "DIM": colorama.Style.DIM,
        "RESET": colorama.Style.RESET_ALL,
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


__version__ = "6.0.1"

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
EXCLUDED_DIRS_DEFAULT = {
    "checker", "migrations", "__pycache__", ".git", "docs", "scripts",
    "deployment", "monitoring", "reports", "venv", ".venv", "node_modules",
    "dist", "build", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".benchmarks",
    "erp_frontend", "logs", "audit_logs", "audit_reports", "rate_cache", "data",
    "tools", "generators",
}

EXCLUDED_FILES_DEFAULT = {
    "fix_bom.py", "generate_contracts.py", "real_test_generator.py",
    "create_first_admin.py", "manage.py", "app.py", "wsgi.py",
    "asgi.py", "setup.py", "conftest.py", "__init__.py",
    "pytest_checker.py", "master_checker.py", "auto_test_generator.py",
    "generate_state_transition_tests.py",
}

COMMON_CONSTANTS = {0, 1, -1, 100, 1000, 255, 1024, 60, 24, 7, 30, 365, 12, 52, 10, 2, 3, 4, 5, 8, 16, 32, 64, 128, 256, 512}

DOMAIN_ROOT_DIRS = ("domain",)
USE_CASE_DIRS = (
    "application/use_cases",
    "application/commands_cqrs",
    "application/service_layer",
    "application/workflows",
    "application/sagas",
)

Confidence = Literal["confirmed", "heuristic"]
MatchConfidence = Literal["direct", "unique", "ambiguous", "none"]


# ─── DATA CLASSES ─────────────────────────────────────────────────────────────
@dataclass
class AssertInfo:
    op: str
    lineno: int
    has_literal_operand: bool = False
    has_message: bool = False
    raw: str = ""
    is_bool_literal_compare: bool = False


@dataclass
class SourceFunction:
    key: str
    name: str
    file: str
    lineno: int
    end_lineno: int
    is_method: bool = False
    class_name: str = ""
    is_private: bool = False
    is_property: bool = False
    is_dunder: bool = False
    decorators: list[str] = field(default_factory=list)
    raises: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    branches: int = 0
    has_status_transition: bool = False
    has_accounting_check: bool = False
    has_inventory_check: bool = False
    has_period_check: bool = False
    has_currency_convert: bool = False
    has_decimal_ops: bool = False
    has_retry_logic: bool = False
    has_cache_ops: bool = False
    has_file_ops: bool = False
    has_otel_ops: bool = False
    has_logging_ops: bool = False
    has_transaction: bool = False
    has_outbox: bool = False
    has_kafka_publish: bool = False
    domain: str = ""
    tested_by_direct: set[str] = field(default_factory=set)
    tested_by_unique: set[str] = field(default_factory=set)
    tested_by_ambiguous: set[str] = field(default_factory=set)

    @property
    def is_tested(self) -> bool:
        if self.is_dunder:
            return True
        return bool(self.tested_by_direct or self.tested_by_unique or self.tested_by_ambiguous)

    @property
    def is_tested_strict(self) -> bool:
        return bool(self.tested_by_direct or self.tested_by_unique)

    @property
    def match_confidence(self) -> MatchConfidence:
        if self.tested_by_direct:
            return "direct"
        if self.tested_by_unique:
            return "unique"
        if self.tested_by_ambiguous:
            return "ambiguous"
        return "none"


@dataclass
class TestFunction:
    key: str
    name: str
    file: str
    lineno: int
    end_lineno: int
    line_count: int
    source: str = ""
    assertions: list[AssertInfo] = field(default_factory=list)
    has_raises: bool = False
    raises_targets: list[str] = field(default_factory=list)
    has_parametrize: bool = False
    has_mock: bool = False
    has_db: bool = False
    has_event_assert: bool = False
    has_audit_assert: bool = False
    is_async: bool = False
    calls: list[str] = field(default_factory=list)
    real_calls: list[str] = field(default_factory=list)
    resolved_calls: list[tuple[str, MatchConfidence, list[str]]] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    markers: list[str] = field(default_factory=list)
    setup_fixtures: list[str] = field(default_factory=list)
    has_sleep: bool = False
    has_random: bool = False
    has_datetime_now: bool = False
    has_timeout: bool = False
    has_try_except: bool = False
    uses_decimal: bool = False
    has_rollback: bool = False
    has_commit: bool = False
    has_cache_hit: bool = False
    has_cache_set: bool = False
    has_file_upload: bool = False
    has_otel: bool = False
    has_logging: bool = False
    has_retry: bool = False
    tested_roles: set[str] = field(default_factory=set)
    struct_hash: str = ""
    body_dump: str = ""


@dataclass
class TestSmell:
    type: str
    file: str
    lineno: int
    detail: str
    test_key: str = ""


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str
    lineno: int
    confidence: Confidence = "heuristic"


@dataclass
class Report:
    total_tests: int = 0
    total_source_functions: int = 0
    tested_functions: int = 0
    tested_functions_direct: int = 0
    tested_functions_unique: int = 0
    untested_functions: int = 0
    overall_quality_score: float = 0.0
    tier1: dict[str, Any] = field(default_factory=dict)
    tier2: dict[str, Any] = field(default_factory=dict)
    tier3: dict[str, Any] = field(default_factory=dict)
    tier4: dict[str, Any] = field(default_factory=dict)
    tier5: dict[str, Any] = field(default_factory=dict)
    tier6: dict[str, Any] = field(default_factory=dict)
    scan_time: float = 0.0
    rca_results: list[dict] = field(default_factory=list)
    parse_errors: list[dict[str, str]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    top_offending_files: list[dict[str, Any]] = field(default_factory=list)
    source_functions: list[SourceFunction] = field(default_factory=list)
    test_functions: list[TestFunction] = field(default_factory=list)
    gate_score: float = 0.0
    gate_status: str = "ERROR"
    gate_failures: list[str] = field(default_factory=list)
    metric_errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.gate_status == "PASS"


# ─── AST UTILITIES ──────────────────────────────────────────────────────────
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


def _dedupe_parse_errors(errors: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for e in errors:
        f = e.get("file")
        if f in seen:
            continue
        seen.add(f)
        out.append(e)
    return out


def _get_ast(py_file: pathlib.Path) -> tuple[ast.AST | None, str | None, str]:
    src = _read_source(py_file)
    if src is None:
        return None, "Cannot read file", ""
    try:
        tree = ast.parse(src, filename=str(py_file))
        return tree, None, src
    except SyntaxError as e:
        return None, f"SyntaxError at line {e.lineno}: {e.msg}", ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}", ""


def _normalized_dump(node: ast.AST) -> str:
    parts: list[str] = []

    def walk(n, is_root: bool = False):
        if isinstance(n, ast.AST):
            parts.append(type(n).__name__)
            if isinstance(n, ast.Constant):
                parts.append(f"<{type(n.value).__name__}:{n.value!r}>")
                return
            if isinstance(n, ast.Name):
                parts.append(n.id)
                return
            if isinstance(n, ast.Attribute):
                parts.append(n.attr)
            if isinstance(n, ast.keyword) and n.arg:
                parts.append(f"kw:{n.arg}")
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not is_root:
                return
            for field_name, value in ast.iter_fields(n):
                if field_name in ("lineno", "col_offset", "end_lineno", "end_col_offset", "ctx"):
                    continue
                if isinstance(value, list):
                    for item in value:
                        walk(item)
                elif isinstance(value, ast.AST):
                    walk(value)
        elif isinstance(n, list):
            for item in n:
                walk(item)

    walk(node, is_root=True)
    return "|".join(parts)


def _deco_name(dec: ast.expr) -> str:
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Attribute):
        return dec.attr
    if isinstance(dec, ast.Call):
        if isinstance(dec.func, ast.Name):
            return dec.func.id
        if isinstance(dec.func, ast.Attribute):
            return dec.func.attr
    return ""


def _extract_pytestmark(body: list[ast.stmt]) -> list[str]:
    marks: list[str] = []
    for stmt in body:
        if isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets
        ):
            value = stmt.value
            if isinstance(value, (ast.List, ast.Tuple)):
                for elt in value.elts:
                    name = _deco_name(elt)
                    if name:
                        marks.append(name)
            else:
                name = _deco_name(value)
                if name:
                    marks.append(name)
    return marks


def _detect_asyncio_auto_mode(root: pathlib.Path) -> bool:
    for name in ("pytest.ini", "setup.cfg", "tox.ini", "pyproject.toml"):
        p = root / name
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r'asyncio_mode\s*=\s*["\']?(\w+)["\']?', text)
        if m and m.group(1).strip().lower() == "auto":
            return True
    return False


def _dotted_module_path(rel_posix: str) -> str:
    p = rel_posix[:-3] if rel_posix.endswith(".py") else rel_posix
    if p.endswith("/__init__"):
        p = p[: -len("/__init__")]
    return p.replace("/", ".")


def _discover_domain(rel_posix: str) -> str:
    parts = rel_posix.split("/")
    if len(parts) >= 2 and parts[0] == "domain":
        return parts[1]
    return ""


# ─── SOURCE FEATURE VISITOR ───────────────────────────────────────────────────
class SourceFeatureVisitor(ast.NodeVisitor):
    ACCOUNTING_CALLS = {"debit", "credit", "post_journal", "journal_entry", "post_journal_entry",
                         "create_journal_entry", "generate_trial_balance", "generate_general_ledger"}
    INVENTORY_CALLS = {"adjust_stock", "transfer_warehouse", "stock_opname", "receive_stock",
                        "issue_stock", "reserve_stock", "allocate_stock", "cogs", "calculate_cogs"}
    PERIOD_CALLS = {"close_period", "reopen_period", "fiscal_year", "period_end_closing", "lock_period"}
    CURRENCY_CALLS = {"convert_currency", "to_idr", "to_usd", "revalue_currency", "fx_rate", "forex_revaluation"}
    DECIMAL_CALLS = {"quantize", "quantize_decimal"}

    def __init__(self):
        self.raises: list[str] = []
        self.calls: list[str] = []
        self.branches = 0
        self.has_status_transition = False
        self.has_accounting = False
        self.has_inventory = False
        self.has_period = False
        self.has_currency = False
        self.has_decimal = False
        self.has_retry = False
        self.has_cache = False
        self.has_file = False
        self.has_otel = False
        self.has_logging = False
        self.has_transaction = False
        self.has_outbox = False
        self.has_kafka = False

    def visit_Raise(self, node):
        if isinstance(node.exc, ast.Call):
            if isinstance(node.exc.func, ast.Name):
                self.raises.append(node.exc.func.id)
            elif isinstance(node.exc.func, ast.Attribute):
                self.raises.append(node.exc.func.attr)
        elif isinstance(node.exc, ast.Name):
            self.raises.append(node.exc.id)
        self.generic_visit(node)

    def visit_If(self, node):
        self.branches += 1
        self.generic_visit(node)

    def visit_Try(self, node):
        self.branches += len(node.handlers)
        self.generic_visit(node)

    def visit_Call(self, node):
        attr = None
        if isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            self.calls.append(attr)
        elif isinstance(node.func, ast.Name):
            attr = node.func.id
            self.calls.append(attr)
        if attr:
            low = attr.lower()
            if attr in self.ACCOUNTING_CALLS:
                self.has_accounting = True
            if attr in self.INVENTORY_CALLS:
                self.has_inventory = True
            if attr in self.PERIOD_CALLS:
                self.has_period = True
            if attr in self.CURRENCY_CALLS:
                self.has_currency = True
            if attr in self.DECIMAL_CALLS or low == "decimal":
                self.has_decimal = True
            if "retry" in low:
                self.has_retry = True
            if "cache" in low or "redis" in low:
                self.has_cache = True
            if "upload" in low or "minio" in low or ("file" in low and "profile" not in low):
                self.has_file = True
            if "otel" in low or "tracer" in low or "span" in low:
                self.has_otel = True
            if low in ("info", "warning", "error", "debug", "exception") or "logger" in low:
                self.has_logging = True
            if attr in ("commit", "rollback", "begin"):
                self.has_transaction = True
            if "outbox" in low:
                self.has_outbox = True
            if "kafka" in low or low.startswith("publish"):
                self.has_kafka = True
        self.generic_visit(node)

    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, ast.Attribute) and target.attr in ("status", "state"):
                self.has_status_transition = True
            if isinstance(target, ast.Name) and target.id in ("status", "state"):
                self.has_status_transition = True
        self.generic_visit(node)


def _extract_raises_exception_names(node: ast.expr) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, (ast.Tuple, ast.List)):
        names: list[str] = []
        for elt in node.elts:
            names.extend(_extract_raises_exception_names(elt))
        return names
    return []


# ─── TEST BODY VISITOR ─────────────────────────────────────────────────────
class TestFeatureVisitor(ast.NodeVisitor):
    def __init__(self, imported_symbols: dict[str, tuple[str, str]], fixture_class_index: dict[str, str], param_names: list[str]):
        self.imported_symbols = imported_symbols
        self.fixture_class_index = fixture_class_index
        self.assertions: list[AssertInfo] = []
        self.raw_calls: list[tuple[ast.expr | None, str, int]] = []
        self.explicit_call_names: list[str] = []
        self.has_raises = False
        self.raises_targets: list[str] = []
        self.has_mock = False
        self.has_db = False
        self.has_event_assert = False
        self.has_audit_assert = False
        self.has_sleep = False
        self.has_random = False
        self.has_datetime_now = False
        self.has_timeout = False
        self.has_try_except = False
        self.uses_decimal = False
        self.has_rollback = False
        self.has_commit = False
        self.has_cache_hit = False
        self.has_cache_set = False
        self.has_file_upload = False
        self.has_otel = False
        self.has_logging = False
        self.has_retry = False
        self.tested_roles: set[str] = set()
        self.var_types: dict[str, str] = {}
        self._call_func_attr_ids: set[int] | None = None
        for p in param_names:
            if p in fixture_class_index:
                self.var_types[p] = fixture_class_index[p]

    _UNITTEST_ASSERT_OPS = {
        "assertEqual": "eq", "assertEquals": "eq", "assertNotEqual": "ne",
        "assertTrue": "truthy", "assertFalse": "not",
        "assertIs": "is", "assertIsNot": "is_not",
        "assertIsNone": "is", "assertIsNotNone": "is_not",
        "assertIn": "in", "assertNotIn": "not_in",
        "assertGreater": "gt", "assertGreaterEqual": "ge",
        "assertLess": "lt", "assertLessEqual": "le",
        "assertRaises": "raises", "assertRaisesRegex": "raises",
        "assertAlmostEqual": "eq", "assertNotAlmostEqual": "ne",
    }

    def _record_call_assert(self, node: ast.Call, attr: str):
        op = self._UNITTEST_ASSERT_OPS.get(attr)
        if op is None:
            op = "other"
        has_literal = any(isinstance(a, ast.Constant) for a in node.args)
        try:
            raw = ast.unparse(node)
        except Exception:
            raw = "assert(...)"
        self.assertions.append(AssertInfo(op=op, lineno=node.lineno, has_literal_operand=has_literal,
                                           has_message=len(node.args) >= (3 if op not in ("truthy", "not") else 2),
                                           raw=raw, is_bool_literal_compare=False))
        for a in node.args:
            self._check_datetime_now_in_assert(a)
        if op == "raises":
            self.has_raises = True
            if node.args:
                self.raises_targets.extend(_extract_raises_exception_names(node.args[0]))

    def _record_assert(self, node: ast.Assert):
        op = "truthy"
        has_literal = False
        is_bool_lit = False
        test_node = node.test
        if isinstance(test_node, ast.Compare) and len(test_node.ops) == 1:
            o = test_node.ops[0]
            op = {
                ast.Eq: "eq", ast.NotEq: "ne", ast.Is: "is", ast.IsNot: "is_not",
                ast.In: "in", ast.NotIn: "not_in", ast.Gt: "gt", ast.Lt: "lt",
                ast.GtE: "ge", ast.LtE: "le",
            }.get(type(o), "other")
            operands = [test_node.left, *test_node.comparators]
            has_literal = any(isinstance(x, ast.Constant) for x in operands)
            is_bool_lit = op in ("eq", "ne") and any(
                isinstance(x, ast.Constant) and isinstance(x.value, bool) for x in operands
            )
        elif isinstance(test_node, ast.Call):
            fn = test_node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
            if name == "raises":
                op = "raises"
        elif isinstance(test_node, ast.UnaryOp) and isinstance(test_node.op, ast.Not):
            op = "not"
        try:
            raw = ast.unparse(node)
        except Exception:
            raw = "assert(...)"
        self.assertions.append(AssertInfo(op=op, lineno=node.lineno, has_literal_operand=has_literal,
                                           has_message=node.msg is not None, raw=raw,
                                           is_bool_literal_compare=is_bool_lit))

    def visit(self, node):
        if self._call_func_attr_ids is None:
            self._call_func_attr_ids = {
                id(n.func) for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            }
        return super().visit(node)

    def visit_Attribute(self, node):
        if id(node) not in self._call_func_attr_ids:
            self.raw_calls.append((node.value, node.attr, getattr(node, "lineno", 0)))
            self._check_keyword_flags(node.attr)
        self.generic_visit(node)

    def visit_Assert(self, node):
        self._record_assert(node)
        for n in ast.walk(node.test):
            if isinstance(n, ast.Name):
                self._check_keyword_flags(n.id)
        self._check_datetime_now_in_assert(node.test)
        self.generic_visit(node)

    def _check_datetime_now_in_assert(self, expr: ast.expr):
        for n in ast.walk(expr):
            if not isinstance(n, ast.Call):
                continue
            fn = n.func
            if (isinstance(fn, ast.Attribute) and fn.attr.lower() in ("now", "utcnow")) or (isinstance(fn, ast.Name) and fn.id.lower() in ("now", "utcnow")):
                self.has_datetime_now = True


    def visit_Assign(self, node):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Call):
            fn = node.value.func
            cls_name = None
            if isinstance(fn, ast.Name):
                if fn.id in self.imported_symbols and self.imported_symbols[fn.id][0] == "class":
                    cls_name = self.imported_symbols[fn.id][1]
                elif fn.id[:1].isupper():
                    cls_name = fn.id
            elif isinstance(fn, ast.Attribute) and fn.attr in ("create", "build", "new"):
                if isinstance(fn.value, ast.Name):
                    cls_name = fn.value.id
            if cls_name:
                self.var_types[node.targets[0].id] = cls_name
        self.generic_visit(node)

    def visit_With(self, node):
        for item in node.items:
            if isinstance(item.context_expr, ast.Call) and item.optional_vars is not None:
                fn = item.context_expr.func
                if (isinstance(fn, ast.Attribute) and fn.attr == "raises") or (isinstance(fn, ast.Name) and fn.id == "raises"):
                    self.has_raises = True
                    args = item.context_expr.args
                    if args:
                        self.raises_targets.extend(_extract_raises_exception_names(args[0]))
        self.generic_visit(node)

    def _check_keyword_flags(self, attr: str):
        low = attr.lower()
        if attr in ("patch", "MagicMock", "Mock", "AsyncMock", "create_autospec", "spy"):
            self.has_mock = True
        if "event" in low:
            self.has_event_assert = True
        if "audit" in low:
            self.has_audit_assert = True
        if low == "sleep":
            self.has_sleep = True
        if low.startswith("rand") or low == "choice" or low == "uniform":
            self.has_random = True
        if "timeout" in low:
            self.has_timeout = True
        if attr == "rollback":
            self.has_rollback = True
        if attr == "commit":
            self.has_commit = True
        if "cache" in low:
            if "get" in low or "hit" in low:
                self.has_cache_hit = True
            if "set" in low or "put" in low:
                self.has_cache_set = True
        if "upload" in low or "minio" in low:
            self.has_file_upload = True
        if "otel" in low or "tracer" in low or "span" in low:
            self.has_otel = True
        if low in ("info", "warning", "error", "debug", "exception") or "logger" in low:
            self.has_logging = True
        if "retry" in low:
            self.has_retry = True
        if "decimal" in low or "quantize" in low:
            self.uses_decimal = True
        if attr in ("session", "execute", "query", "select", "insert", "update_", "get_db",
                     "save", "persist", "flush", "merge", "delete", "scalar", "scalars",
                     "first", "one", "one_or_none", "refresh", "repository", "repo",
                     "find_by_id", "find", "fetch"):
            self.has_db = True
        if low in ("admin", "manager", "staff", "auditor", "accounting_role", "warehouse_role"):
            self.tested_roles.add(attr)

    def visit_Call(self, node):
        owner_expr = None
        attr = None
        if isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            owner_expr = node.func.value
            self.raw_calls.append((owner_expr, attr, node.lineno))
            self.explicit_call_names.append(attr)
            if attr == "raises":
                self.has_raises = True
                if node.args:
                    self.raises_targets.extend(_extract_raises_exception_names(node.args[0]))
            if attr.startswith("assert") and attr != "assert_type":
                self._record_call_assert(node, attr)
            root = node.func.value
            while isinstance(root, ast.Attribute):
                if root.attr in ("patch", "MagicMock", "Mock", "AsyncMock", "create_autospec", "spy"):
                    self.has_mock = True
                root = root.value
            if isinstance(root, ast.Name) and root.id in (
                "patch", "MagicMock", "Mock", "AsyncMock", "create_autospec", "spy", "mock", "mocker",
            ):
                self.has_mock = True
        elif isinstance(node.func, ast.Name):
            attr = node.func.id
            self.raw_calls.append((None, attr, node.lineno))
            self.explicit_call_names.append(attr)
            if attr == "raises":
                self.has_raises = True
                if node.args:
                    self.raises_targets.extend(_extract_raises_exception_names(node.args[0]))

        if attr:
            self._check_keyword_flags(attr)
        self.generic_visit(node)

    def visit_Try(self, node):
        self.has_try_except = True
        self.generic_visit(node)


# ─── FIXTURE RETURN-TYPE RESOLUTION ───────────────────────────────────────────
def _resolve_fixture_class(func_node: ast.FunctionDef | ast.AsyncFunctionDef, imported_symbols: dict[str, tuple[str, str]]) -> str | None:
    if func_node.returns is not None:
        ann = func_node.returns
        if isinstance(ann, ast.Name):
            return ann.id
        if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
            return ann.value.strip().strip("'\"")
    for n in ast.walk(func_node):
        if isinstance(n, (ast.Return, ast.Expr)) and isinstance(getattr(n, "value", None), ast.Call):
            fn = n.value.func
            if isinstance(fn, ast.Name) and fn.id[:1].isupper():
                return fn.id
        if isinstance(n, ast.Yield) and isinstance(n.value, ast.Call):
            fn = n.value.func
            if isinstance(fn, ast.Name) and fn.id[:1].isupper():
                return fn.id
    return None


# ─── PER-FILE WORKER ──────────────────────────────────────────────────────────
def _classify_file(root: str, py_file: str, excluded_dirs: set[str], excluded_files: set[str]) -> str | None:
    rel = pathlib.Path(py_file).relative_to(root).as_posix()
    parts = rel.split("/")
    parts_lower = [p.lower() for p in parts]
    excluded_dirs_lower = {d.lower() for d in excluded_dirs}
    for d in excluded_dirs_lower:
        if d in parts_lower:
            return None
    filename = pathlib.Path(py_file).name
    excluded_files_lower = {f.lower() for f in excluded_files}
    if filename.lower() in excluded_files_lower:
        return None
    if "tests" in parts_lower or "test" in parts_lower or filename.lower().startswith(("test_", "conftest")):
        return "test"
    if "scripts" in parts_lower or "deployment" in parts_lower:
        return None
    return "source"


def _parse_source_file(args: tuple[str, str, set[str], set[str]]) -> dict:
    root, file_str, excluded_dirs, excluded_files = args
    if _classify_file(root, file_str, excluded_dirs, excluded_files) != "source":
        return {"file": file_str, "error": "Skipped (not source)"}
    py_file = pathlib.Path(file_str)
    rel = py_file.relative_to(root).as_posix()
    tree, err, _src = _get_ast(py_file)
    result: dict = {"file": rel, "error": err, "functions": [], "module_exports": {}}
    if err or tree is None:
        return result
    module_dotted = _dotted_module_path(rel)
    domain = _discover_domain(rel)

    def emit(node: ast.FunctionDef, class_name: str):
        if node.name.startswith("_") and not node.name.startswith("__"):
            is_private = True
        else:
            is_private = False
        visitor = SourceFeatureVisitor()
        visitor.visit(node)
        key = f"{rel}::{class_name}.{node.name}" if class_name else f"{rel}::{node.name}"
        decorators = [_deco_name(d) for d in node.decorator_list]
        func = {
            "key": key, "name": node.name, "file": rel,
            "lineno": node.lineno, "end_lineno": node.end_lineno or node.lineno,
            "is_method": bool(class_name), "class_name": class_name, "is_private": is_private,
            "decorators": decorators, "raises": visitor.raises, "calls": visitor.calls,
            "branches": visitor.branches, "has_status_transition": visitor.has_status_transition,
            "has_accounting_check": visitor.has_accounting, "has_inventory_check": visitor.has_inventory,
            "has_period_check": visitor.has_period, "has_currency_convert": visitor.has_currency,
            "has_decimal_ops": visitor.has_decimal, "has_retry_logic": visitor.has_retry,
            "has_cache_ops": visitor.has_cache, "has_file_ops": visitor.has_file,
            "has_otel_ops": visitor.has_otel, "has_logging_ops": visitor.has_logging,
            "has_transaction": visitor.has_transaction, "has_outbox": visitor.has_outbox,
            "has_kafka_publish": visitor.has_kafka, "domain": domain,
        }
        result["functions"].append(func)
        if not class_name and not is_private:
            result["module_exports"].setdefault(node.name, key)

    top_classes = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef):
            emit(node, "")
        elif isinstance(node, ast.ClassDef):
            top_classes.append(node.name)
            result["module_exports"].setdefault(node.name, f"{rel}::class::{node.name}")
            for child in node.body:
                if isinstance(child, ast.FunctionDef):
                    emit(child, node.name)
    result["module_dotted"] = module_dotted
    result["top_classes"] = top_classes
    return result


def _parse_test_file(args: tuple[str, str, set[str], set[str]]) -> dict:
    root, file_str, excluded_dirs, excluded_files = args
    if _classify_file(root, file_str, excluded_dirs, excluded_files) != "test":
        return {"file": file_str, "error": "Skipped (not test)"}
    py_file = pathlib.Path(file_str)
    rel = py_file.relative_to(root).as_posix()
    tree, err, _src = _get_ast(py_file)
    result: dict = {"file": rel, "error": err, "imports": [], "fixtures": [], "test_nodes_src": None}
    if err or tree is None:
        return result

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names = [(a.name, a.asname or a.name) for a in node.names]
            result["imports"].append({"module": node.module, "level": node.level, "names": names})
        elif isinstance(node, ast.Import):
            for a in node.names:
                result["imports"].append({"module": a.name, "level": 0, "names": [(a.name.split(".")[0], a.asname or a.name.split(".")[0])], "whole": True})

    local_imported: dict[str, tuple[str, str]] = {}
    for imp in result["imports"]:
        if imp.get("whole"):
            continue
        for orig, alias in imp["names"]:
            local_imported[alias] = ("unknown", orig)

    fixtures = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            deco_names = [_deco_name(d) for d in node.decorator_list]
            if "fixture" in deco_names:
                cls_guess = _resolve_fixture_class(node, local_imported)
                fixtures.append({"name": node.name, "class_guess": cls_guess})
    result["fixtures"] = fixtures
    return result


# ─── PROJECT INDEX ─────────────────────────────────────────────────────────────
class ProjectIndex:
    def __init__(self, root: pathlib.Path, extra_excludes_dirs: set[str], extra_excludes_files: set[str], max_workers: int = 4):
        self.root = root
        self.excluded_dirs = EXCLUDED_DIRS_DEFAULT | extra_excludes_dirs
        self.excluded_files = EXCLUDED_FILES_DEFAULT | extra_excludes_files
        self.max_workers = max(1, max_workers)
        self.source_functions: dict[str, SourceFunction] = {}
        self.test_files_meta: dict[str, dict] = {}
        self.source_files: list[pathlib.Path] = []
        self.test_files: list[pathlib.Path] = []
        self.parse_errors: list[dict[str, str]] = []
        self.class_methods_index: dict[str, list[str]] = defaultdict(list)
        self.class_validator_methods_index: dict[str, list[str]] = defaultdict(list)
        self.bare_name_index: dict[str, list[str]] = defaultdict(list)
        self.module_exports_index: dict[str, dict[str, str]] = {}
        self.fixture_class_index: dict[str, dict[str, str]] = defaultdict(dict)
        self.conftest_fixture_class_index: dict[str, str] = {}
        self.asyncio_auto_mode = _detect_asyncio_auto_mode(root)

    def scan_files(self):
        for py_file in self.root.rglob("*.py"):
            kind = _classify_file(str(self.root), str(py_file), self.excluded_dirs, self.excluded_files)
            if kind == "source":
                self.source_files.append(py_file)
            elif kind == "test":
                self.test_files.append(py_file)

    def _run_parallel(self, fn, items, progress_callback=None, progress_offset=0, progress_total=0):
        results = []
        args = [(str(self.root), str(f), self.excluded_dirs, self.excluded_files) for f in items]
        if not args:
            return results
        if self.max_workers <= 1 or len(args) < 64:
            for i, a in enumerate(args):
                results.append(fn(a))
                if progress_callback:
                    progress_callback(progress_offset + i + 1, progress_total)
            return results
        try:
            with ProcessPoolExecutor(max_workers=self.max_workers) as ex:
                futures = {ex.submit(fn, a): a for a in args}
                done = 0
                for fut in as_completed(futures):
                    try:
                        results.append(fut.result())
                    except Exception as e:
                        results.append({"file": futures[fut][1], "error": f"WorkerError: {e}"})
                    done += 1
                    if progress_callback:
                        progress_callback(progress_offset + done, progress_total)
        except Exception as e:
            logger.warning(f"ProcessPoolExecutor gagal ({e}), fallback ke mode serial untuk {len(args)} file.")
            results = []
            for i, a in enumerate(args):
                results.append(fn(a))
                if progress_callback:
                    progress_callback(progress_offset + i + 1, progress_total)
        return results

    def parse_all(self, progress_callback=None):
        total = len(self.source_files) + len(self.test_files)
        src_results = self._run_parallel(_parse_source_file, self.source_files, progress_callback, 0, total)
        for r in src_results:
            if r.get("error"):
                self.parse_errors.append({"file": r["file"], "error": r["error"]})
                continue
            self.module_exports_index[r.get("module_dotted", "")] = r.get("module_exports", {})
            for f in r["functions"]:
                sf = SourceFunction(
                    key=f["key"], name=f["name"], file=f["file"], lineno=f["lineno"],
                    end_lineno=f["end_lineno"], is_method=f["is_method"], class_name=f["class_name"],
                    is_private=f["is_private"], decorators=f["decorators"], raises=f["raises"],
                    calls=f["calls"], branches=f["branches"], has_status_transition=f["has_status_transition"],
                    has_accounting_check=f["has_accounting_check"], has_inventory_check=f["has_inventory_check"],
                    has_period_check=f["has_period_check"], has_currency_convert=f["has_currency_convert"],
                    has_decimal_ops=f["has_decimal_ops"], has_retry_logic=f["has_retry_logic"],
                    has_cache_ops=f["has_cache_ops"], has_file_ops=f["has_file_ops"],
                    has_otel_ops=f["has_otel_ops"], has_logging_ops=f["has_logging_ops"],
                    has_transaction=f["has_transaction"], has_outbox=f["has_outbox"],
                    has_kafka_publish=f["has_kafka_publish"], domain=f["domain"],
                    is_property=any(d in ("property", "cached_property", "functools.cached_property")
                                     for d in f["decorators"]),
                    is_dunder=f["name"].startswith("__") and f["name"].endswith("__") and f["name"] != "__init__",
                )
                self.source_functions[sf.key] = sf
                if sf.class_name:
                    self.class_methods_index[f"{sf.class_name}.{sf.name}"].append(sf.key)
                    if any(d in ("validator", "field_validator", "model_validator", "root_validator")
                           for d in sf.decorators):
                        self.class_validator_methods_index[sf.class_name].append(sf.key)
                self.bare_name_index[sf.name].append(sf.key)

        test_results = self._run_parallel(_parse_test_file, self.test_files, progress_callback, len(src_results), total)
        for r in test_results:
            if r.get("error"):
                self.parse_errors.append({"file": r["file"], "error": r["error"]})
                continue
            self.test_files_meta[r["file"]] = r
            is_conftest = pathlib.Path(r["file"]).name == "conftest.py"
            for fx in r.get("fixtures", []):
                if fx["class_guess"]:
                    if is_conftest:
                        self.conftest_fixture_class_index[fx["name"]] = fx["class_guess"]
                    else:
                        self.fixture_class_index[r["file"]][fx["name"]] = fx["class_guess"]

    def resolve_module(self, current_file_rel: str, module: str | None, level: int) -> str | None:
        if level and level > 0:
            cur_parts = current_file_rel.split("/")[:-1]
            base = cur_parts[: max(0, len(cur_parts) - (level - 1))]
            mod_parts = module.split(".") if module else []
            dotted = ".".join([*base, *mod_parts])
            if dotted in self.module_exports_index:
                return dotted
            return None
        if not module:
            return None
        if module in self.module_exports_index:
            return module
        candidates = [m for m in self.module_exports_index if m.endswith("." + module) or m == module]
        if len(candidates) == 1:
            return candidates[0]
        candidates2 = [m for m in self.module_exports_index if m.split(".")[-1] == module.split(".")[-1]]
        if len(candidates2) == 1:
            return candidates2[0]
        return None

    def imported_symbols_for(self, test_file_rel: str) -> dict[str, tuple[str, str]]:
        meta = self.test_files_meta.get(test_file_rel)
        out: dict[str, tuple[str, str]] = {}
        if not meta:
            return out
        for imp in meta.get("imports", []):
            if imp.get("whole"):
                continue
            resolved_mod = self.resolve_module(test_file_rel, imp.get("module"), imp.get("level", 0))
            if not resolved_mod:
                continue
            exports = self.module_exports_index.get(resolved_mod, {})
            for orig, alias in imp["names"]:
                target_key = exports.get(orig)
                if not target_key:
                    continue
                if target_key.endswith(f"::class::{orig}"):
                    out[alias] = ("class", orig)
                else:
                    out[alias] = ("function", target_key)
        return out


# ─── CALL RESOLUTION ────────────────────────────────────────────────────────
def _resolve_calls(
    raw_calls: list[tuple[ast.expr | None, str, int]],
    var_types: dict[str, str],
    imported_symbols: dict[str, tuple[str, str]],
    index: ProjectIndex,
) -> list[tuple[str, MatchConfidence, list[str]]]:
    resolved: list[tuple[str, MatchConfidence, list[str]]] = []
    NOISE = {
        "append", "join", "format", "keys", "values", "items", "pop",
        "copy", "strip", "split", "lower", "upper", "str", "int",
        "float", "len", "range", "isinstance", "print", "dict", "list", "sorted",
        "assert_called", "assert_called_with", "assert_called_once", "assert_not_called",
        "called_once_with", "return_value", "side_effect", "patch", "MagicMock", "Mock",
        "fixture", "mark", "parametrize", "raises", "approx", "skip", "skipif",
    }
    for owner_expr, attr, _lineno in raw_calls:
        class_name = None
        if owner_expr is not None and isinstance(owner_expr, ast.Name):
            if owner_expr.id in var_types:
                class_name = var_types[owner_expr.id]
            elif owner_expr.id in imported_symbols and imported_symbols[owner_expr.id][0] == "class":
                class_name = imported_symbols[owner_expr.id][1]
        if class_name:
            candidates = index.class_methods_index.get(f"{class_name}.{attr}", [])
            if candidates:
                resolved.append((attr, "direct", candidates))
                continue
        if owner_expr is None and attr:
            ctor_class = None
            if attr in imported_symbols and imported_symbols[attr][0] == "class":
                ctor_class = imported_symbols[attr][1]
            elif attr[:1].isupper() and attr not in imported_symbols:
                ctor_class = attr
            if ctor_class:
                init_candidates = index.class_methods_index.get(f"{ctor_class}.__init__", [])
                if init_candidates:
                    resolved.append((attr, "direct", init_candidates))
                validator_candidates = index.class_validator_methods_index.get(ctor_class, [])
                if validator_candidates:
                    resolved.append((attr, "direct", validator_candidates))
                if init_candidates or validator_candidates:
                    continue
        if owner_expr is None and attr in imported_symbols and imported_symbols[attr][0] == "function":
            resolved.append((attr, "direct", [imported_symbols[attr][1]]))
            continue
        if attr in NOISE:
            continue
        candidates = index.bare_name_index.get(attr, [])
        if len(candidates) == 1:
            resolved.append((attr, "unique", candidates))
        elif len(candidates) > 1:
            resolved.append((attr, "ambiguous", candidates))
    return resolved


def _build_test_functions(
    index: ProjectIndex, progress_callback=None, already_failed_files: set[str] | None = None
) -> tuple[dict[str, TestFunction], list[dict]]:
    test_functions: dict[str, TestFunction] = {}
    parse_errors: list[dict] = []
    already_failed_files = already_failed_files or set()
    total = len(index.test_files)
    for i, py_file in enumerate(index.test_files):
        rel = py_file.relative_to(index.root).as_posix()
        if rel in already_failed_files:
            if progress_callback:
                progress_callback(i + 1, total)
            continue
        tree, err, src_text = _get_ast(py_file)
        if err or tree is None:
            if err:
                parse_errors.append({"file": rel, "error": err})
            if progress_callback:
                progress_callback(i + 1, total)
            continue
        imported_symbols = index.imported_symbols_for(rel)
        src_lines = src_text.splitlines() if src_text else []
        module_marks = _extract_pytestmark(tree.body)
        effective_fixture_class_index = {**index.conftest_fixture_class_index, **index.fixture_class_index.get(rel, {})}

        def handle(node: ast.FunctionDef | ast.AsyncFunctionDef, class_prefix: str = "", extra_marks: list[str] | None = None):
            if not node.name.startswith("test_"):
                return
            param_names = [a.arg for a in node.args.args if a.arg != "self"]
            visitor = TestFeatureVisitor(imported_symbols, effective_fixture_class_index, param_names)
            visitor.visit(node)
            resolved = _resolve_calls(visitor.raw_calls, visitor.var_types, imported_symbols, index)
            decorators = [_deco_name(d) for d in node.decorator_list]
            markers = [d for d in decorators if d] + (extra_marks or [])
            try:
                source_text = ast.unparse(node)
            except Exception:
                source_text = ""
            end_lineno = node.end_lineno or node.lineno
            struct_hash = _normalized_dump(node)
            key = f"{rel}::{class_prefix}{node.name}::{node.lineno}"
            tf = TestFunction(
                key=key, name=node.name, file=rel, lineno=node.lineno, end_lineno=end_lineno,
                line_count=end_lineno - node.lineno + 1, source=source_text,
                assertions=visitor.assertions, has_raises=visitor.has_raises or bool(visitor.raises_targets),
                raises_targets=visitor.raises_targets,
                has_parametrize=any("parametrize" in d for d in decorators),
                has_mock=visitor.has_mock, has_db=visitor.has_db, has_event_assert=visitor.has_event_assert,
                has_audit_assert=visitor.has_audit_assert, is_async=isinstance(node, ast.AsyncFunctionDef),
                calls=[a for _, a, _ in visitor.raw_calls], real_calls=visitor.explicit_call_names,
                resolved_calls=resolved, decorators=decorators,
                markers=markers, setup_fixtures=param_names, has_sleep=visitor.has_sleep,
                has_random=visitor.has_random, has_datetime_now=visitor.has_datetime_now,
                has_timeout=visitor.has_timeout, has_try_except=visitor.has_try_except,
                uses_decimal=visitor.uses_decimal, has_rollback=visitor.has_rollback,
                has_commit=visitor.has_commit, has_cache_hit=visitor.has_cache_hit,
                has_cache_set=visitor.has_cache_set, has_file_upload=visitor.has_file_upload,
                has_otel=visitor.has_otel, has_logging=visitor.has_logging, has_retry=visitor.has_retry,
                tested_roles=visitor.tested_roles, struct_hash=struct_hash,
            )
            test_functions[key] = tf

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                handle(node, extra_marks=module_marks)
            elif isinstance(node, ast.ClassDef):
                class_marks = module_marks + _extract_pytestmark(node.body)
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        handle(child, class_prefix=f"{node.name}.", extra_marks=class_marks)
        if progress_callback:
            progress_callback(i + 1, total)
    return test_functions, parse_errors


def _link_tests_to_sources(index: ProjectIndex, test_functions: dict[str, TestFunction]) -> None:
    for t in test_functions.values():
        for bare_name, confidence, candidates in t.resolved_calls:
            for key in candidates:
                sf = index.source_functions.get(key)
                if sf is None:
                    continue
                if confidence == "direct":
                    sf.tested_by_direct.add(t.key)
                elif confidence == "unique":
                    sf.tested_by_unique.add(t.key)
                elif confidence == "ambiguous":
                    sf.tested_by_ambiguous.add(t.key)


# ─── BUSINESS FLOW DISCOVERY ──────────────────────────────────────────────
def _discover_business_flows(index: ProjectIndex) -> dict[str, list[SourceFunction]]:
    buckets: dict[str, list[SourceFunction]] = defaultdict(list)
    for sf in index.source_functions.values():
        parts = sf.file.split("/")
        bucket = None
        if parts and parts[0] == "domain" and len(parts) >= 3 and not parts[1].endswith(".py"):
            bucket = parts[1]
        elif parts and parts[0] == "application" and len(parts) >= 2 and parts[1] in (
            "use_cases", "commands_cqrs", "service_layer", "workflows", "sagas"
        ):
            stem = pathlib.Path(sf.file).stem.lower()
            bucket = f"application:{stem}"
        if bucket and not sf.is_private and sf.name not in ("__init__", "__repr__", "__str__", "__eq__"):
            buckets[bucket].append(sf)
    return buckets


# ─── QUALITY ANALYZER ─────────────────────────────────────────────────────────
def _memoize_analyzer_method(fn):
    name = fn.__name__

    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        cache = self.__dict__.setdefault("_metric_cache", {})
        cache_key = (name, args, tuple(sorted(kwargs.items())))
        if cache_key not in cache:
            cache[cache_key] = fn(self, *args, **kwargs)
        return cache[cache_key]
    return wrapper


class QualityAnalyzer:
    def __init__(self, index: ProjectIndex, test_funcs: dict[str, TestFunction]):
        self.index = index
        self.test_funcs = test_funcs
        self.source_funcs = index.source_functions
        self._metric_cache: dict[tuple, Any] = {}
        self.features = {
            "accounting": any(f.has_accounting_check for f in self.source_funcs.values()),
            "inventory": any(f.has_inventory_check for f in self.source_funcs.values()),
            "period": any(f.has_period_check for f in self.source_funcs.values()),
            "currency": any(f.has_currency_convert for f in self.source_funcs.values()),
            "decimal": any(f.has_decimal_ops for f in self.source_funcs.values()),
            "status_transition": any(f.has_status_transition for f in self.source_funcs.values()),
            "event": any("event" in f.name.lower() for f in self.source_funcs.values()),
            "audit": any("audit" in f.name.lower() for f in self.source_funcs.values()),
            "db": any(f.has_transaction for f in self.source_funcs.values()),
            "outbox": any(f.has_outbox for f in self.source_funcs.values()),
        }
        self.findings: list[Finding] = []

    def _add_finding(self, rule: str, severity: str, message: str, file: str, lineno: int, confidence: Confidence = "heuristic"):
        self.findings.append(Finding(rule=rule, severity=severity, message=message, file=file, lineno=lineno, confidence=confidence))

    def _is_constant(self, num: int) -> bool:
        return num in COMMON_CONSTANTS

    def _file_metric_scores(self, metric_name: str) -> dict[str, float]:
        from collections import defaultdict
        file_scores: dict[str, list[float]] = defaultdict(list)

        if metric_name == "assertion_quality":
            _meaningful_ops = ("eq", "ne", "is", "is_not", "in", "not_in", "raises",
                                "gt", "lt", "ge", "le", "truthy", "not")
            for t in self.test_funcs.values():
                if t.assertions:
                    meaningful = sum(
                        1 for a in t.assertions
                        if a.op in _meaningful_ops and not a.is_bool_literal_compare
                    )
                    score = (meaningful / len(t.assertions)) * 100 if t.assertions else 0.0
                else:
                    score = 0.0
                file_scores[t.file].append(score)

        elif metric_name == "negative_path_coverage":
            for t in self.test_funcs.values():
                has_error = t.has_raises
                if not has_error and t.source:
                    has_error = bool(re.search(r'pytest\.raises|assertRaises|raises\(', t.source))
                if not has_error:
                    has_error = any(kw in t.name.lower() for kw in ("error", "invalid", "exception", "fail", "bad", "reject"))
                score = 100.0 if has_error else 0.0
                file_scores[t.file].append(score)

        elif metric_name == "mock_quality":
            for t in self.test_funcs.values():
                score = 100.0 if t.has_mock else 0.0
                file_scores[t.file].append(score)

        elif metric_name == "duplicate_test_detector":
            by_file = defaultdict(list)
            for t in self.test_funcs.values():
                by_file[t.file].append(t)
            for file, tests in by_file.items():
                seen = set()
                dups = 0
                for t in tests:
                    sig = f"{t.struct_hash}#{len(t.assertions)}"
                    if sig in seen:
                        dups += 1
                    else:
                        seen.add(sig)
                total = len(tests)
                score = ((total - dups) / total) * 100 if total else 100
                file_scores[file].append(score)

        elif metric_name in ("accounting_checker", "inventory_checker", "fiscal_period_checker",
                             "multi_currency_checker", "precision_checker"):
            flag_map = {
                "accounting_checker": "has_accounting_check",
                "inventory_checker": "has_inventory_check",
                "fiscal_period_checker": "has_period_check",
                "multi_currency_checker": "has_currency_convert",
                "precision_checker": "has_decimal_ops",
            }
            flag = flag_map.get(metric_name)
            if flag:
                by_file = defaultdict(list)
                for f in self.source_funcs.values():
                    if getattr(f, flag):
                        by_file[f.file].append(f)
                for file, funcs in by_file.items():
                    tested = sum(1 for sf in funcs if sf.is_tested)
                    score = (tested / len(funcs)) * 100 if funcs else 100.0
                    file_scores[file].append(score)

        return {f: sum(scores)/len(scores) for f, scores in file_scores.items() if scores}

    @_memoize_analyzer_method
    def assertion_quality(self) -> dict:
        total = len(self.test_funcs)
        if total == 0:
            return {"score": 0, "good": 0, "bad": 0, "details": [], "confidence": "confirmed", "file_scores": {}}
        good = bad = 0
        details = []
        for key, t in self.test_funcs.items():
            if not t.assertions:
                if t.has_raises:
                    good += 1
                    continue
                bad += 1
                details.append(f"{t.file}:{t.lineno} {t.name} — 0 assertions")
                self._add_finding("NO-ASSERTION", "error", f"Test '{t.name}' tidak punya assertion sama sekali", t.file, t.lineno, "confirmed")
                continue
            meaningful_ops = ("eq", "ne", "is", "is_not", "in", "not_in", "raises",
                               "gt", "lt", "ge", "le", "truthy", "not")
            meaningful = sum(
                1 for a in t.assertions
                if a.op in meaningful_ops and not a.is_bool_literal_compare
            )
            if meaningful >= len(t.assertions) * 0.7:
                good += 1
            else:
                bad += 1
                details.append(f"{t.file}:{t.lineno} {t.name} — low specificity ({meaningful}/{len(t.assertions)})")
        score = (good / total) * 100
        result = {"score": round(score, 1), "good": good, "bad": bad, "details": details, "confidence": "confirmed"}
        result["file_scores"] = self._file_metric_scores("assertion_quality")
        return result

    @_memoize_analyzer_method
    def negative_path_coverage(self) -> dict:
        relevant = [f for f in self.source_funcs.values() if f.raises or f.branches > 0]
        if not relevant:
            return {
                "score": 100.0,
                "verified": 0,
                "total": 0,
                "relevant_source_functions": 0,
                "confidence": "confirmed",
                "note": "N/A: tidak ada source function dengan branch/raise yang relevan.",
                "file_scores": {},
            }
        verified = 0
        unverified = []
        for sf in relevant:
            linked = sf.tested_by_direct | sf.tested_by_unique | sf.tested_by_ambiguous
            evidence = False
            for key in linked:
                t = self.test_funcs.get(key)
                if not t:
                    continue
                if t.has_raises or t.raises_targets or any(a.op == "raises" for a in t.assertions):
                    evidence = True
                    break
                low = t.name.lower()
                if any(k in low for k in ("error", "invalid", "exception", "reject", "denied", "forbidden", "rollback", "timeout")):
                    evidence = True
                    break
            if evidence:
                verified += 1
            else:
                unverified.append(f"{sf.file}:{sf.lineno} {(sf.class_name + '.') if sf.class_name else ''}{sf.name}")
        score = (verified / len(relevant)) * 100
        result = {"score": round(score, 1), "verified": verified, "total": len(relevant),
                  "relevant_source_functions": len(relevant), "untested_sample": unverified,
                  "confidence": "heuristic"}
        result["file_scores"] = self._file_metric_scores("negative_path_coverage")
        return result

    @_memoize_analyzer_method
    def exception_coverage(self) -> dict:
        all_raises: set[str] = set()
        raise_locations: dict[str, list[str]] = defaultdict(list)
        for f in self.source_funcs.values():
            for exc in f.raises:
                all_raises.add(exc)
                raise_locations[exc].append(f"{f.file}:{f.lineno}")
        if not all_raises:
            return {"score": 100.0, "tested": 0, "total": 0, "untested": [], "confidence": "confirmed"}
        tested: set[str] = set()
        for t in self.test_funcs.values():
            tested.update(x for x in t.raises_targets if x in all_raises)
        untested = sorted(all_raises - tested)
        for exc in untested:
            for loc in raise_locations[exc][:1]:
                file, line = loc.split(":")
                self._add_finding("UNTESTED-EXCEPTION", "warning", f"Exception '{exc}' di-raise tapi tidak pernah diuji via pytest.raises({exc})", file, int(line), "confirmed")
        score = (len(tested) / len(all_raises)) * 100
        return {"score": round(score, 1), "tested": len(tested), "total": len(all_raises), "untested": untested, "confidence": "confirmed"}

    @_memoize_analyzer_method
    def edge_case_detector(self) -> dict:
        edge_ops = {"eq", "ne", "is", "is_not", "gt", "lt", "ge", "le"}
        covered_tests = 0
        for t in self.test_funcs.values():
            has_edge = False
            for a in t.assertions:
                if a.op in edge_ops and a.has_literal_operand:
                    has_edge = True
                    break
            if not has_edge and any(kw in t.source for kw in ("None", "''", '""', "[]", "{}", "Decimal('0')")):
                has_edge = True
            if has_edge:
                covered_tests += 1
        total = len(self.test_funcs)
        score = (covered_tests / max(1, total)) * 100
        return {"score": round(score, 1), "covered": covered_tests, "total": total, "confidence": "heuristic"}

    @_memoize_analyzer_method
    def magic_number_detector(self) -> dict:
        magic_count = 0
        offenders: list[str] = []
        for t in self.test_funcs.values():
            for a in t.assertions:
                nums = re.findall(r'(?<![\w.])(\d{2,})(?![\w.])', a.raw)
                for num in nums:
                    n = int(num)
                    if self._is_constant(n):
                        continue
                    magic_count += 1
                    offenders.append(f"{t.file}:{a.lineno} {t.name} — angka '{n}' tanpa nama konstanta")
        total = max(1, len(self.test_funcs))
        penalty = min(100, (magic_count / total) * 30)
        score = max(0, 100 - penalty)
        return {"magic_numbers": magic_count, "score": round(score, 1), "details": offenders, "confidence": "heuristic"}

    @_memoize_analyzer_method
    def mock_quality(self) -> dict:
        total = len(self.test_funcs)
        if total == 0:
            return {"score": 100.0, "mock_count": 0, "avg_mock": 0.0, "has_spec": 0, "confidence": "heuristic", "file_scores": {}}
        mock_count = sum(1 for t in self.test_funcs.values() if t.has_mock)
        ratio = mock_count / total
        if ratio <= 0.60:
            base = 100.0
        elif ratio <= 0.80:
            base = 90.0
        else:
            base = 80.0
        has_spec = sum(1 for t in self.test_funcs.values() if any(x in t.source.lower() for x in ("autospec", "spec_set", "spec=")))
        score = min(100.0, base + min(10.0, (has_spec / total) * 10.0))
        result = {
            "score": round(score, 1),
            "mock_count": mock_count,
            "avg_mock": round(ratio, 3),
            "has_spec": has_spec,
            "confidence": "heuristic",
            "note": "Mock density adalah indikator strategi, bukan bukti kualitas behavior.",
        }
        result["file_scores"] = self._file_metric_scores("mock_quality")
        return result

    @_memoize_analyzer_method
    def fixture_quality(self) -> dict:
        fixtures = [fx for t in self.test_funcs.values() for fx in t.setup_fixtures]
        unique = set(fixtures)
        total = len(fixtures)
        heavy = sorted({f for f in unique if any(k in f.lower() for k in ("db", "session", "client"))})
        score = 100.0 if total == 0 else 90.0 + (10.0 * min(1.0, len(unique) / total))
        return {"score": round(score, 1), "total_fixtures": total, "unique": len(unique), "heavy": heavy, "confidence": "heuristic"}

    @_memoize_analyzer_method
    def duplicate_test_detector(self) -> dict:
        by_file: dict[str, list[TestFunction]] = defaultdict(list)
        for t in self.test_funcs.values():
            by_file[t.file].append(t)
        duplicates: list[tuple[str, str, str]] = []
        for file, tests in by_file.items():
            seen: dict[str, TestFunction] = {}
            for t in tests:
                sig = f"{t.struct_hash}#{len(t.assertions)}"
                if sig in seen and sig:
                    prev = seen[sig]
                    duplicates.append((f"{file}:{prev.lineno} {prev.name}", f"{file}:{t.lineno} {t.name}", sig[:40]))
                    self._add_finding("DUPLICATE-TEST", "warning",
                                       f"Test '{t.name}' terlihat identik secara struktural dengan '{prev.name}' (kemungkinan copy-paste)",
                                       t.file, t.lineno, "heuristic")
                else:
                    seen[sig] = t
        total = max(1, len(self.test_funcs))
        score = max(0, 100 - (len(duplicates) / total) * 100)
        result = {"score": round(score, 1), "duplicates": len(duplicates), "details": duplicates, "confidence": "heuristic"}
        result["file_scores"] = self._file_metric_scores("duplicate_test_detector")
        return result

    @_memoize_analyzer_method
    def test_naming(self) -> dict:
        good = 0.0
        bad = 0
        details = []
        for t in self.test_funcs.values():
            name = t.name
            if not name.startswith("test_"):
                bad += 1
                details.append(f"{t.file}:{t.lineno} {name} — tidak diawali test_")
                continue
            tokens = [p for p in name[5:].split("_") if p]
            if len(tokens) >= 3:
                good += 1
            elif len(tokens) == 2:
                good += 0.5
            else:
                bad += 1
                details.append(f"{t.file}:{t.lineno} {name} — nama terlalu generik")
        total = len(self.test_funcs)
        return {"score": round((good / max(1, total)) * 100, 1), "good": good, "bad": bad, "details": details, "confidence": "heuristic"}

    @_memoize_analyzer_method
    def aaa_pattern(self) -> dict:
        count_aaa = 0
        total = len(self.test_funcs)
        for t in self.test_funcs.values():
            low = t.source.lower()
            has_arrange = bool(t.setup_fixtures) or bool(re.search(r"\b(given|when|arrange|setup|fixture)\b", low)) or bool(re.search(r"\b\w+\s*=\s*", t.source))
            has_act = bool(t.calls)
            has_assert = bool(t.assertions)
            if has_arrange and has_act and has_assert:
                count_aaa += 1
        return {"score": round((count_aaa / max(1, total)) * 100, 1), "count": count_aaa, "total": total, "confidence": "heuristic"}

    def _relevant_test_keys_for(self, predicate) -> tuple[set[str], list]:
        relevant_sources = [f for f in self.source_funcs.values() if predicate(f)]
        relevant_keys: set[str] = set()
        for sf in relevant_sources:
            relevant_keys |= sf.tested_by_direct | sf.tested_by_unique
        return relevant_keys, relevant_sources

    def _domain_verification_scores(self, pred, evidence_fn):
        relevant_sources = [f for f in self.source_funcs.values() if pred(f)]
        verified = 0
        total = 0
        any_linked = False
        file_scores: dict[str, list[float]] = defaultdict(list)
        for f in relevant_sources:
            linked_keys = f.tested_by_direct | f.tested_by_unique
            linked_tests = [self.test_funcs[k] for k in linked_keys if k in self.test_funcs]
            if not linked_tests:
                continue
            any_linked = True
            total += 1
            if any(evidence_fn(t) for t in linked_tests):
                verified += 1
            by_test_file: dict[str, list] = defaultdict(list)
            for t in linked_tests:
                by_test_file[t.file].append(t)
            for file, tests_here in by_test_file.items():
                file_scores[file].append(100.0 if any(evidence_fn(t) for t in tests_here) else 0.0)
        avg_file_scores = {f: sum(s) / len(s) for f, s in file_scores.items() if s}
        return verified, total, any_linked, avg_file_scores, len(relevant_sources)

    @_memoize_analyzer_method
    def database_verification(self) -> dict:
        def _has_db_operation(f) -> bool:
            return (f.has_transaction or
                    "subprocess" in f.name.lower() or
                    "pg_dump" in f.name.lower() or
                    "psql" in f.name.lower() or
                    "backup" in f.name.lower() or
                    "restore" in f.name.lower() or
                    "migration" in f.name.lower())
        evidence_fn = lambda t: t.has_db or t.has_commit or t.has_rollback or t.has_mock
        verified, total, any_linked, file_scores, relevant_count = self._domain_verification_scores(_has_db_operation, evidence_fn)
        if relevant_count == 0:
            return {"score": 100.0, "has_db": 0, "total": 0, "confidence": "confirmed",
                     "note": "Tidak ada source function dengan operasi transaksi/DB (has_transaction) -- N/A untuk scope ini.",
                     "file_scores": {}}
        if not any_linked:
            return {"score": 0.0, "has_db": 0, "total": relevant_count, "confidence": "heuristic",
                     "note": f"{relevant_count} source function melakukan operasi DB, tapi tidak ada test yang ter-link ke fungsi tersebut.",
                     "file_scores": {}}
        return {"score": round((verified / total) * 100, 1), "has_db": verified, "total": total,
                "relevant_source_functions": relevant_count, "confidence": "heuristic", "file_scores": file_scores}

    @_memoize_analyzer_method
    def domain_event_verification(self) -> dict:
        pred = lambda f: f.has_outbox or f.has_kafka_publish or "event" in f.name.lower()
        evidence_fn = lambda t: t.has_event_assert
        verified, total, any_linked, file_scores, relevant_count = self._domain_verification_scores(pred, evidence_fn)
        if relevant_count == 0:
            return {"score": 100.0, "has_event": 0, "total": 0, "confidence": "confirmed",
                     "note": "Tidak ada source function terkait domain event (outbox/kafka/nama mengandung 'event') -- N/A untuk scope ini.",
                     "file_scores": {}}
        if not any_linked:
            return {"score": 0.0, "has_event": 0, "total": relevant_count, "confidence": "heuristic",
                     "note": f"{relevant_count} source function terkait domain event, tapi tidak ada test yang ter-link ke fungsi tersebut.",
                     "file_scores": {}}
        return {"score": round((verified / total) * 100, 1), "has_event": verified, "total": total,
                "relevant_source_functions": relevant_count, "confidence": "heuristic", "file_scores": file_scores}

    @_memoize_analyzer_method
    def audit_log_verification(self) -> dict:
        pred = lambda f: "audit" in f.name.lower()
        evidence_fn = lambda t: t.has_audit_assert
        verified, total, any_linked, file_scores, relevant_count = self._domain_verification_scores(pred, evidence_fn)
        if relevant_count == 0:
            return {"score": 100.0, "has_audit": 0, "total": 0, "confidence": "confirmed",
                     "note": "Tidak ada source function terkait audit (nama mengandung 'audit') -- N/A untuk scope ini.",
                     "file_scores": {}}
        if not any_linked:
            return {"score": 0.0, "has_audit": 0, "total": relevant_count, "confidence": "heuristic",
                     "note": f"{relevant_count} source function terkait audit, tapi tidak ada test yang ter-link ke fungsi tersebut.",
                     "file_scores": {}}
        return {"score": round((verified / total) * 100, 1), "has_audit": verified, "total": total,
                "relevant_source_functions": relevant_count, "confidence": "heuristic", "file_scores": file_scores}

    @_memoize_analyzer_method
    def idempotency_verification(self) -> dict:
        pred = lambda f: f.has_transaction or f.has_outbox or f.has_kafka_publish or f.has_retry_logic

        def evidence_fn(t):
            has_keyword = ("twice" in t.source.lower() or "idempotent" in t.source.lower()
                           or "duplicate" in t.name.lower() or "retry" in t.name.lower()
                           or "retries" in t.name.lower())
            if has_keyword:
                return True
            if len(t.calls) >= 2:
                seen: dict[str, int] = {}
                for c in t.calls:
                    seen[c] = seen.get(c, 0) + 1
                return any(n >= 2 for c, n in seen.items() if c not in ("assert_called", "raises"))
            return False

        verified, total, any_linked, file_scores, relevant_count = self._domain_verification_scores(pred, evidence_fn)
        if relevant_count == 0:
            return {"score": 100.0, "count": 0, "total": 0, "confidence": "confirmed",
                     "note": "Tidak ada source function yang mutasi state / retry-sensitive -- N/A untuk scope ini.",
                     "file_scores": {}}
        if not any_linked:
            return {"score": 0.0, "count": 0, "total": relevant_count, "confidence": "heuristic",
                     "note": f"{relevant_count} source function retry/mutasi-sensitive, tapi tidak ada test yang ter-link ke fungsi tersebut.",
                     "file_scores": {}}
        return {"score": round((verified / total) * 100, 1), "count": verified, "total": total,
                "relevant_source_functions": relevant_count, "confidence": "heuristic", "file_scores": file_scores}


    @_memoize_analyzer_method
    def permission_test(self) -> dict:
        roles = set()
        for t in self.test_funcs.values():
            roles.update(t.tested_roles)
            for r in ("admin", "manager", "staff", "auditor"):
                if r in t.name.lower():
                    roles.add(r)
        return {"unique_roles": len(roles), "roles": sorted(roles), "confidence": "heuristic"}

    def _domain_metric(self, flag_attr: str, metric_name: str) -> dict:
        relevant = [f for f in self.source_funcs.values() if getattr(f, flag_attr)]
        if not relevant:
            return {"score": 100.0, "relevant": 0, "tested": 0, "untested_sample": [], "confidence": "confirmed"}
        tested = [f for f in relevant if f.is_tested]
        untested = [f for f in relevant if not f.is_tested]
        for f in untested:
            self._add_finding("UNTESTED-DOMAIN-FUNC", "warning",
                               f"Fungsi domain-sensitive '{f.name}' (class {f.class_name or '-'}) tidak terdeteksi dipanggil test manapun",
                               f.file, f.lineno, "heuristic")
        score = (len(tested) / len(relevant)) * 100
        result = {
            "score": round(score, 1), "relevant": len(relevant), "tested": len(tested),
            "untested_sample": [f"{f.file}:{f.lineno} {f.class_name+'.' if f.class_name else ''}{f.name}" for f in untested],
            "confidence": "confirmed",
        }
        result["file_scores"] = self._file_metric_scores(metric_name)
        return result

    @_memoize_analyzer_method
    def accounting_checker(self) -> dict:
        d = self._domain_metric("has_accounting_check", "accounting_checker")
        return {**d, "has_acct": d["relevant"], "test_acct": d["tested"]}

    @_memoize_analyzer_method
    def inventory_checker(self) -> dict:
        d = self._domain_metric("has_inventory_check", "inventory_checker")
        return {**d, "has_inv": d["relevant"], "test_inv": d["tested"]}

    @_memoize_analyzer_method
    def fiscal_period_checker(self) -> dict:
        d = self._domain_metric("has_period_check", "fiscal_period_checker")
        return {**d, "has_period": d["relevant"], "test_period": d["tested"]}

    @_memoize_analyzer_method
    def multi_currency_checker(self) -> dict:
        d = self._domain_metric("has_currency_convert", "multi_currency_checker")
        return {**d, "has_curr": d["relevant"], "test_curr": d["tested"]}

    @_memoize_analyzer_method
    def precision_checker(self) -> dict:
        d = self._domain_metric("has_decimal_ops", "precision_checker")
        return {**d, "has_decimal": d["relevant"], "test_decimal": d["tested"]}

    @_memoize_analyzer_method
    def mutation_score_estimation(self) -> tuple[float, float, float]:
        total_points = 0.0
        covered = 0.0
        for sf in self.source_funcs.values():
            points = sf.branches + len(sf.raises) + (1 if sf.has_status_transition else 0)
            points = max(points, 1)
            total_points += points
            linking_tests = sf.tested_by_direct | sf.tested_by_unique | sf.tested_by_ambiguous
            if linking_tests:
                best_strength = 0
                for t_key in linking_tests:
                    t = self.test_funcs.get(t_key)
                    if not t:
                        continue
                    strength = sum(2 if a.op in ("eq", "ne", "gt", "lt", "ge", "le") else 1 for a in t.assertions)
                    best_strength = max(best_strength, strength)
                covered += points if best_strength >= 2 else points * 0.3
        if total_points == 0:
            return 0.0, 0.0, 0.0
        score = min(100.0, (covered / total_points) * 100)
        return score, covered, total_points

    def test_strength_score(self, ignore_metrics: set[str] | None = None) -> float:
        ignore_metrics = ignore_metrics or set()
        metrics = []
        base_metrics = [
            ("assertion_quality", self.assertion_quality()["score"]),
            ("negative_path", self.negative_path_coverage()["score"]),
            ("exception_coverage", self.exception_coverage()["score"]),
            ("edge_case", self.edge_case_detector()["score"]),
            ("magic_number", self.magic_number_detector()["score"]),
            ("mock_quality", self.mock_quality()["score"]),
            ("test_naming", self.test_naming()["score"]),
            ("aaa_pattern", self.aaa_pattern()["score"]),
            ("mutation", self.mutation_score_estimation()[0]),
        ]
        for name, val in base_metrics:
            if name not in ignore_metrics:
                metrics.append(val)
        if self.features.get("db"):
            metrics.append(self.database_verification()["score"])
        if self.features.get("event"):
            metrics.append(self.domain_event_verification()["score"])
        if self.features.get("audit"):
            metrics.append(self.audit_log_verification()["score"])
        if "idempotency" not in ignore_metrics:
            metrics.append(self.idempotency_verification()["score"])
        if self.features.get("accounting"):
            metrics.append(self.accounting_checker()["score"])
        if self.features.get("inventory"):
            metrics.append(self.inventory_checker()["score"])
        if self.features.get("period"):
            metrics.append(self.fiscal_period_checker()["score"])
        if self.features.get("currency"):
            metrics.append(self.multi_currency_checker()["score"])
        if self.features.get("decimal"):
            metrics.append(self.precision_checker()["score"])
        extra = [
            ("flaky", self.flaky_test_detector()["count"]),
            ("slow", self.slow_test_detector()["count"]),
            ("dead", self.dead_code_test_detector()["count"]),
            ("orphan", self.orphan_test_checker()["orphans"]),
        ]
        for name, count in extra:
            if name not in ignore_metrics:
                total = max(1, len(self.test_funcs))
                metrics.append(max(0, 100 - (count / total * 50)))
        return round(sum(metrics) / len(metrics), 1) if metrics else 0.0

    def confidence_score(self, strength_score: float) -> float:
        base = 50 + (strength_score / 2)
        test_ratio = len(self.test_funcs) / max(1, len(self.source_funcs))
        return min(99.5, base + min(20, test_ratio * 10))

    @_memoize_analyzer_method
    def flaky_test_detector(self) -> dict:
        flaky = []
        for k, t in self.test_funcs.items():
            if (t.has_sleep or t.has_random or t.has_datetime_now) and not t.has_mock:
                flaky.append(f"{t.file}:{t.lineno} {t.name}")
                self._add_finding("FLAKY-TEST", "warning",
                                   f"Test '{t.name}' memakai sleep/random/datetime.now() tanpa mock -> berpotensi flaky",
                                   t.file, t.lineno, "confirmed")
        return {"count": len(flaky), "details": flaky}

    @_memoize_analyzer_method
    def slow_test_detector(self) -> dict:
        slow = [f"{t.file}:{t.lineno} {t.name}" for t in self.test_funcs.values() if t.has_sleep]
        return {"count": len(slow), "details": slow}

    def test_isolation_checker(self) -> dict:
        shared_state = sum(1 for t in self.test_funcs.values() if "global " in t.source or "class_var" in t.source.lower())
        return {"count": shared_state, "total": len(self.test_funcs)}

    def random_order_checker(self) -> dict:
        order_dependent = sum(1 for t in self.test_funcs.values() if re.search(r'\btest_\d', t.name))
        return {"count": order_dependent, "total": len(self.test_funcs)}

    @_memoize_analyzer_method
    def dead_code_test_detector(self) -> dict:
        dead = []
        for k, t in self.test_funcs.items():
            body = t.source.strip()
            if (body.endswith("pass") and not t.assertions) or (len(t.assertions) == 0 and not t.calls):
                dead.append(f"{t.file}:{t.lineno} {t.name}")
        for d in dead:
            file, rest = d.split(":", 1)
            line = rest.split(" ", 1)[0]
            self._add_finding("DEAD-TEST", "error", "Test tidak melakukan apa-apa (tidak ada call maupun assertion nyata)", file, int(line), "confirmed")
        return {"count": len(dead), "details": dead}

    @_memoize_analyzer_method
    def orphan_test_checker(self) -> dict:
        orphans = []
        for t in self.test_funcs.values():
            if t.real_calls and not t.resolved_calls:
                orphans.append(f"{t.file}:{t.lineno} {t.name}")
        return {"orphans": len(orphans), "details": orphans}

    def untested_exception_checker(self) -> list[str]:
        return self.exception_coverage()["untested"]

    def parametrize_quality(self) -> dict:
        parametrized = [t for t in self.test_funcs.values() if t.has_parametrize]
        rich = sum(1 for t in parametrized if re.search(r'parametrize\([^)]*\[.*,.*,.*\]', t.source))
        return {"parametrized": len(parametrized), "rich": rich, "total": len(self.test_funcs)}

    @_memoize_analyzer_method
    def async_test_checker(self) -> dict:
        async_tests = [t for t in self.test_funcs.values() if t.is_async]
        if self.index.asyncio_auto_mode:
            return {"async_count": len(async_tests), "missing_marker": 0, "total": len(self.test_funcs)}
        missing_marker = [t for t in async_tests if "asyncio" not in " ".join(t.markers).lower() and "anyio" not in " ".join(t.markers).lower()]
        for t in missing_marker:
            self._add_finding("ASYNC-MISSING-MARKER", "warning",
                               f"Test async '{t.name}' tidak punya marker @pytest.mark.asyncio — kemungkinan tidak benar-benar dijalankan oleh pytest",
                               t.file, t.lineno, "confirmed")
        return {"async_count": len(async_tests), "missing_marker": len(missing_marker), "total": len(self.test_funcs)}

    def transaction_rollback_checker(self) -> dict:
        has_rb = sum(1 for t in self.test_funcs.values() if t.has_rollback)
        return {"count": has_rb, "total": len(self.test_funcs)}

    def event_consistency_checker(self) -> dict:
        has_event = sum(1 for t in self.test_funcs.values()
                         if t.has_event_assert and any(kw in t.source.lower() for kw in ("aggregate_id", "version", "timestamp")))
        total_event_tests = max(1, sum(1 for t in self.test_funcs.values() if t.has_event_assert))
        return {"score": round((has_event / total_event_tests) * 100, 1), "count": has_event, "total": total_event_tests}

    def outbox_checker(self) -> dict:
        has_outbox = sum(1 for t in self.test_funcs.values() if "outbox" in t.source.lower())
        total = len(self.test_funcs)
        return {"has_outbox_assert": has_outbox, "total": total, "score": round((has_outbox / max(1, total)) * 100, 1)}

    def kafka_publish_checker(self) -> dict:
        has_kafka = sum(1 for t in self.test_funcs.values()
                         if ("kafka" in t.source.lower() or "publish" in t.source.lower())
                         and any(kw in t.source.lower() for kw in ("topic", "key", "payload")))
        return {"has_kafka_assert": has_kafka, "total": len(self.test_funcs)}

    def opentelemetry_checker(self) -> dict:
        return {"has_otel": sum(1 for t in self.test_funcs.values() if t.has_otel), "total": len(self.test_funcs)}

    def logging_checker(self) -> dict:
        return {"has_logging": sum(1 for t in self.test_funcs.values() if t.has_logging), "total": len(self.test_funcs)}

    def retry_checker(self) -> dict:
        has_retry = sum(1 for t in self.test_funcs.values() if t.has_retry and ("success" in t.source.lower() or "fail" in t.source.lower()))
        return {"has_retry_tests": has_retry, "total": len(self.test_funcs)}

    def cache_checker(self) -> dict:
        return {"has_cache_tests": sum(1 for t in self.test_funcs.values() if t.has_cache_hit or t.has_cache_set), "total": len(self.test_funcs)}

    def file_upload_checker(self) -> dict:
        return {"has_file_upload": sum(1 for t in self.test_funcs.values() if t.has_file_upload), "total": len(self.test_funcs)}

    def timezone_checker(self) -> dict:
        has_tz = sum(1 for t in self.test_funcs.values() if any(x in t.source for x in ("UTC", "Asia/Jakarta", "timezone", "pytz")))
        return {"has_timezone_tests": has_tz, "total": len(self.test_funcs)}

    def permission_matrix_checker(self) -> dict:
        roles = set()
        for t in self.test_funcs.values():
            for r in ("admin", "manager", "staff", "accounting", "warehouse", "auditor"):
                if r in t.name.lower():
                    roles.add(r)
        return {"roles": sorted(roles), "count": len(roles)}

    def state_transition_checker(self) -> dict:
        relevant = [f for f in self.source_funcs.values() if f.has_status_transition]
        if not relevant:
            return {"score": 100.0, "total_trans": 0, "tested": 0}
        tested = 0
        for f in relevant:
            linking = f.tested_by_direct | f.tested_by_unique
            if any(("status" in a.raw or "state" in a.raw)
                   for t_key in linking for a in self.test_funcs.get(t_key, TestFunction("", "", "", 0, 0, 0)).assertions):
                tested += 1
        score = (tested / len(relevant)) * 100
        return {"score": round(score, 1), "total_trans": len(relevant), "tested": tested}

    def test_smell_detector(self) -> list[TestSmell]:
        smells = []
        for k, t in self.test_funcs.items():
            if t.line_count > 150:
                smells.append(TestSmell("long", t.file, t.lineno, f"{t.line_count} lines", k))
            if len(t.assertions) > 10:
                smells.append(TestSmell("many_asserts", t.file, t.lineno, f"{len(t.assertions)} assertions", k))
            if t.has_sleep:
                smells.append(TestSmell("sleep", t.file, t.lineno, "time.sleep dipakai langsung", k))
            if t.has_try_except:
                smells.append(TestSmell("try_except", t.file, t.lineno, "try/except di dalam test bisa menyembunyikan kegagalan", k))
            if not t.assertions and not t.calls:
                smells.append(TestSmell("empty_test", t.file, t.lineno, "test kosong / tidak melakukan apapun", k))
            if any(a.op == "truthy" and not a.has_literal_operand and "==" not in a.raw for a in t.assertions) and len(t.assertions) == 1:
                smells.append(TestSmell("weak_assert", t.file, t.lineno, "hanya assert truthy tanpa perbandingan nilai spesifik", k))
        return smells

    def business_flow_coverage(self) -> dict[str, dict[str, Any]]:
        buckets = _discover_business_flows(self.index)
        coverage: dict[str, dict[str, Any]] = {}
        for domain, funcs in buckets.items():
            covered = [f for f in funcs if f.is_tested]
            missing = [f for f in funcs if not f.is_tested]
            coverage[domain] = {
                "total": len(funcs),
                "covered": len(covered),
                "pct": round((len(covered) / len(funcs)) * 100, 1) if funcs else 0.0,
                "missing_functions": [f"{f.file}:{f.lineno} {(f.class_name+'.') if f.class_name else ''}{f.name}" for f in missing],
            }
        return coverage

    def business_flow_gaps(self, threshold: float = 100.0) -> list[dict[str, Any]]:
        buckets = _discover_business_flows(self.index)
        coverage = self.business_flow_coverage()
        gaps: list[dict[str, Any]] = []
        for domain, funcs in buckets.items():
            pct = coverage[domain]["pct"]
            if pct >= threshold:
                continue
            for f in funcs:
                if f.is_tested:
                    continue
                risk_flags = [name for name, flag in (
                    ("accounting", f.has_accounting_check),
                    ("inventory", f.has_inventory_check),
                    ("fiscal_period", f.has_period_check),
                    ("multi_currency", f.has_currency_convert),
                    ("decimal_precision", f.has_decimal_ops),
                    ("status_transition", f.has_status_transition),
                ) if flag]
                gaps.append({
                    "domain": domain, "domain_pct": pct,
                    "domain_covered": coverage[domain]["covered"], "domain_total": coverage[domain]["total"],
                    "file": f.file, "lineno": f.lineno, "name": f.name, "class_name": f.class_name,
                    "risk_flags": risk_flags,
                })
        gaps.sort(key=lambda g: (g["domain_pct"], g["domain"], 0 if g["risk_flags"] else 1, g["file"], g["lineno"]))
        return gaps

    def business_flow_summary(self) -> dict[str, dict[str, int | float]]:
        flow = self.business_flow_coverage()
        return {m: {"covered": v["covered"], "total": v["total"], "pct": v["pct"]} for m, v in flow.items()}

    def regression_risk(self) -> dict:
        by_file: dict[str, dict[str, int]] = defaultdict(lambda: {"loc": 0, "funcs": 0, "tested_funcs": 0})
        for f in self.source_funcs.values():
            by_file[f.file]["loc"] += (f.end_lineno - f.lineno + 1)
            by_file[f.file]["funcs"] += 1
            if f.is_tested:
                by_file[f.file]["tested_funcs"] += 1
        risks = {}
        for file, data in by_file.items():
            funcs = data["funcs"]
            tested_ratio = (data["tested_funcs"] / funcs) if funcs else 1.0
            if funcs >= 3 and tested_ratio < 0.10:
                risk = "HIGH"
            elif funcs >= 3 and tested_ratio < 0.40:
                risk = "MEDIUM"
            else:
                risk = "LOW"
            risks[file] = {
                "loc": data["loc"], "functions": funcs, "tested_functions": data["tested_funcs"],
                "test_density": round(tested_ratio * 100, 1), "risk": risk,
            }
        return risks

    def compute_weighted_score(self, ignore_metrics: set[str] | None = None) -> float:
        ignore = ignore_metrics or set()
        self.metric_errors = []

        def get_score(name: str):
            try:
                result = getattr(self, name)()
            except Exception as exc:
                self.metric_errors.append(f"{name}: {type(exc).__name__}: {exc}")
                return None
            if isinstance(result, dict) and isinstance(result.get("score"), (int, float)):
                return max(0.0, min(100.0, float(result["score"])))
            if name == "permission_test" and isinstance(result, dict):
                return min(100.0, len(result.get("roles", [])) / 5.0 * 100.0)
            self.metric_errors.append(f"{name}: metric tidak mengembalikan score numerik")
            return None

        def avg(names):
            vals = [get_score(n) for n in names if n not in ignore]
            vals = [v for v in vals if v is not None]
            return (sum(vals) / len(vals)) if vals else 0.0

        tier1 = avg(["assertion_quality", "negative_path_coverage", "exception_coverage", "edge_case_detector", "magic_number_detector"])
        tier2 = avg(["mock_quality", "fixture_quality", "duplicate_test_detector", "test_naming", "aaa_pattern"])
        tier3 = avg(["database_verification", "domain_event_verification", "audit_log_verification", "idempotency_verification", "permission_test"])
        tier4 = avg(["accounting_checker", "inventory_checker", "fiscal_period_checker", "multi_currency_checker", "precision_checker"])

        try:
            tier5 = float(self.mutation_score_estimation()[0])
        except Exception as exc:
            self.metric_errors.append(f"mutation_score_estimation: {type(exc).__name__}: {exc}")
            tier5 = 0.0

        total_tests = max(1, len(self.test_funcs))
        try:
            flaky = self.flaky_test_detector()["count"]
            slow = self.slow_test_detector()["count"]
            dead = self.dead_code_test_detector()["count"]
            orphan = self.orphan_test_checker()["orphans"]
        except Exception as exc:
            self.metric_errors.append(f"tier6: {type(exc).__name__}: {exc}")
            flaky = slow = dead = orphan = 0
        tier6 = max(0.0, 100.0 - min(40.0, ((flaky + slow + dead + orphan) / total_tests) * 20.0))

        total = (
            tier1 * 0.35 +
            tier2 * 0.10 +
            tier3 * 0.20 +
            tier4 * 0.25 +
            tier5 * 0.05 +
            tier6 * 0.05
        )
        return round(max(0.0, min(100.0, total)), 1)

    def untested_function_analyzer(self) -> tuple[list[str], list[str]]:
        tested, untested = [], []
        for key, f in self.source_funcs.items():
            label = f"{f.file}:{f.lineno} {(f.class_name + '.') if f.class_name else ''}{f.name}"
            if f.is_tested:
                tested.append(label)
            else:
                untested.append(label)
        return tested, untested

    def top_offending_files(self, limit: int = 40) -> list[dict[str, Any]]:
        risk = self.regression_risk()
        rows = [{"file": f, **d} for f, d in risk.items() if d["functions"] >= 2]
        rows.sort(key=lambda r: (r["functions"] - r["tested_functions"]), reverse=True)
        return rows[:limit]


# ─── ENGINE ──────────────────────────────────────────────────────────────────
class PytestQualityChecker:
    def __init__(
        self,
        root: pathlib.Path,
        enable_rca: bool = True,
        strict: bool = False,
        extra_excludes_dirs: set[str] | None = None,
        extra_excludes_files: set[str] | None = None,
        max_workers: int = 4,
        ignore_metrics: set[str] | None = None,
    ):
        self.root = root
        self.enable_rca = enable_rca and _RCA_AVAILABLE
        self.strict = strict
        self.extra_excludes_dirs = extra_excludes_dirs or set()
        self.extra_excludes_files = extra_excludes_files or set()
        self.max_workers = max_workers
        self.ignore_metrics = ignore_metrics or set()
        self.index = ProjectIndex(root, self.extra_excludes_dirs, self.extra_excludes_files, max_workers)

    def scan(self, progress_callback: Callable | None = None) -> Report:
        t0 = time.monotonic()
        self.index.scan_files()
        self.index.parse_all(progress_callback=progress_callback)
        already_failed = {e["file"] for e in self.index.parse_errors}
        test_funcs, extra_errors = _build_test_functions(self.index, already_failed_files=already_failed)
        for err in extra_errors:
            if err["file"] not in already_failed:
                self.index.parse_errors.append(err)
                already_failed.add(err["file"])
        _link_tests_to_sources(self.index, test_funcs)
        analyzer = QualityAnalyzer(self.index, test_funcs)

        t1 = {
            "assertion_quality": analyzer.assertion_quality(),
            "negative_path": analyzer.negative_path_coverage(),
            "exception_coverage": analyzer.exception_coverage(),
            "edge_case": analyzer.edge_case_detector(),
            "magic_number": analyzer.magic_number_detector(),
        }
        t2 = {
            "mock_quality": analyzer.mock_quality(),
            "fixture_quality": analyzer.fixture_quality(),
            "duplicate_test": analyzer.duplicate_test_detector(),
            "test_naming": analyzer.test_naming(),
            "aaa_pattern": analyzer.aaa_pattern(),
        }
        t3 = {
            "database_verification": analyzer.database_verification(),
            "domain_event": analyzer.domain_event_verification(),
            "audit_log": analyzer.audit_log_verification(),
            "idempotency": analyzer.idempotency_verification(),
            "permission_test": analyzer.permission_test(),
        }
        t4 = {
            "accounting": analyzer.accounting_checker(),
            "inventory": analyzer.inventory_checker(),
            "fiscal_period": analyzer.fiscal_period_checker(),
            "multi_currency": analyzer.multi_currency_checker(),
            "precision": analyzer.precision_checker(),
        }

        mut_score, mut_covered, mut_total = analyzer.mutation_score_estimation()
        strength = analyzer.test_strength_score(ignore_metrics=self.ignore_metrics)
        confidence = analyzer.confidence_score(strength)
        flow = analyzer.business_flow_coverage()
        flow_gaps = analyzer.business_flow_gaps()
        reg_risk = analyzer.regression_risk()
        t5 = {
            "mutation_score": round(mut_score, 1),
            "mutation_points_covered": round(mut_covered, 1),
            "mutation_points_total": round(mut_total, 1),
            "test_strength": strength,
            "confidence_score": round(confidence, 1),
            "business_flow": flow,
            "business_flow_summary": analyzer.business_flow_summary(),
            "business_flow_gaps": flow_gaps,
            "regression_risk": reg_risk,
            "mutation_score_type": "static-estimate-not-real-mutation-testing",
        }

        tested_funcs, untested_funcs = analyzer.untested_function_analyzer()
        smells = analyzer.test_smell_detector()
        t6 = {
            "flaky_tests": analyzer.flaky_test_detector(),
            "slow_tests": analyzer.slow_test_detector(),
            "test_isolation": analyzer.test_isolation_checker(),
            "random_order": analyzer.random_order_checker(),
            "dead_code": analyzer.dead_code_test_detector(),
            "orphan_tests": analyzer.orphan_test_checker(),
            "untested_functions": untested_funcs,
            "untested_exceptions": analyzer.untested_exception_checker(),
            "parametrize_quality": analyzer.parametrize_quality(),
            "async_tests": analyzer.async_test_checker(),
            "transaction_rollback": analyzer.transaction_rollback_checker(),
            "event_consistency": analyzer.event_consistency_checker(),
            "outbox": analyzer.outbox_checker(),
            "kafka_publish": analyzer.kafka_publish_checker(),
            "opentelemetry": analyzer.opentelemetry_checker(),
            "logging": analyzer.logging_checker(),
            "retry": analyzer.retry_checker(),
            "cache": analyzer.cache_checker(),
            "file_upload": analyzer.file_upload_checker(),
            "timezone": analyzer.timezone_checker(),
            "permission_matrix": analyzer.permission_matrix_checker(),
            "state_transition": analyzer.state_transition_checker(),
            "test_smells": [{"type": s.type, "file": s.file, "lineno": s.lineno, "detail": s.detail} for s in smells],
            "business_flow_summary": t5["business_flow_summary"],
        }

        quality_score = analyzer.compute_weighted_score(ignore_metrics=self.ignore_metrics)
        parse_errors = _dedupe_parse_errors(self.index.parse_errors)
        metric_errors = list(dict.fromkeys(analyzer.metric_errors))
        gate_failures = []
        if parse_errors:
            gate_failures.append(f"{len(parse_errors)} file gagal diparse")
        if metric_errors:
            gate_failures.append(f"{len(metric_errors)} metric gagal dieksekusi")
        if len(test_funcs) == 0 and len(self.index.source_functions) > 0:
            gate_failures.append("tidak ditemukan test function yang dapat dianalisis")
        if quality_score < 80.0:
            gate_failures.append(f"quality score {quality_score:.1f} di bawah threshold 80.0")
        gate_status = "PASS" if not gate_failures else "FAIL"
        gate_score = quality_score if gate_status == "PASS" else min(quality_score, 79.9)

        rca_results = []
        if self.enable_rca:
            checks = [
                ("Assertion Quality", t1["assertion_quality"].get("score", 100)),
                ("Negative Path", t1["negative_path"].get("score", 100)),
                ("Exception Coverage", t1["exception_coverage"].get("score", 100)),
                ("State Transition", t6["state_transition"].get("score", 100)),
                ("Mutation Score", t5["mutation_score"]),
            ]
            for name, score in checks:
                if score < 50:
                    try:
                        raise RuntimeError(f"Low {name} score: {score}%")
                    except RuntimeError as exc:
                        rca = _rca_analyze(exc, {"metric": name, "score": score})
                        if rca:
                            rca_results.append({"metric": name, "score": score, "rca": rca})

        direct_count = sum(1 for f in self.index.source_functions.values() if f.tested_by_direct)
        unique_count = sum(1 for f in self.index.source_functions.values() if not f.tested_by_direct and f.tested_by_unique)
        return Report(
            total_tests=len(test_funcs),
            total_source_functions=len(self.index.source_functions),
            tested_functions=len(tested_funcs),
            tested_functions_direct=direct_count,
            tested_functions_unique=unique_count,
            untested_functions=len(untested_funcs),
            overall_quality_score=quality_score,
            tier1=t1, tier2=t2, tier3=t3, tier4=t4, tier5=t5, tier6=t6,
            scan_time=time.monotonic() - t0,
            rca_results=rca_results,
            parse_errors=parse_errors,
            findings=analyzer.findings,
            top_offending_files=analyzer.top_offending_files(),
            source_functions=list(self.index.source_functions.values()),
            test_functions=list(test_funcs.values()),
            gate_score=round(gate_score, 1),
            gate_status=gate_status,
            gate_failures=gate_failures,
            metric_errors=metric_errors,
        )


# ─── REPORT PRINTING ───────────────────────────────────────────────────────
def print_report(r: Report, verbose: bool = False, show_rca: bool = True, full: bool = False) -> None:
    c = COLOR
    def score_color(v: float) -> str:
        return c["GREEN"] if v >= 80 else c["YELLOW"] if v >= 60 else c["RED"]
    _safe_print(f"\n{c['BOLD']}{c['CYAN']}╔{'═'*76}╗{c['RESET']}")
    title = f"   PYTEST QUALITY CHECKER v{__version__} — STATIC FORENSIC QUALITY GATE"
    _safe_print(f"{c['BOLD']}{c['CYAN']}║{c['RESET']}{c['BOLD']}{title:<76}{c['CYAN']}║{c['RESET']}")
    _safe_print(f"{c['BOLD']}{c['CYAN']}╚{'═'*76}╝{c['RESET']}\n")
    gate_col = c['GREEN'] if r.gate_status == 'PASS' else c['RED']
    _safe_print(f"📊 RAW QUALITY SCORE : {score_color(r.overall_quality_score)}{r.overall_quality_score:.1f}/100{c['RESET']}")
    _safe_print(f"🚦 QUALITY GATE       : {gate_col}{r.gate_status}{c['RESET']}  gate_score={r.gate_score:.1f}/100  threshold=80.0")
    _safe_print(f"  Total tests          : {r.total_tests}")
    _safe_print(f"  Source functions     : {r.total_source_functions}")
    _safe_print(f"  Tested direct        : {r.tested_functions_direct}")
    _safe_print(f"  Tested unique        : {r.tested_functions_unique}")
    _safe_print(f"  Untested functions   : {r.untested_functions}")
    _safe_print(f"  Scan time            : {r.scan_time:.2f}s")
    if r.gate_failures:
        _safe_print(f"\n{c['RED']}BLOCKING GATE FINDINGS{c['RESET']}")
        for x in r.gate_failures:
            _safe_print(f"  - {x}")
    if r.metric_errors:
        _safe_print(f"\n{c['RED']}METRIC EXECUTION ERRORS{c['RESET']}")
        for x in r.metric_errors:
            _safe_print(f"  - {x}")
    if r.parse_errors:
        _safe_print(f"\n{c['RED']}PARSE ERRORS: {len(r.parse_errors)}{c['RESET']}")
        rows = r.parse_errors if (full or verbose) else r.parse_errors[:40]
        for e in rows:
            _safe_print(f"  - {e['file']}: {e['error']}")
        if len(r.parse_errors) > len(rows):
            _safe_print(f"  ... and {len(r.parse_errors)-len(rows)} more")
    def group(title, data):
        _safe_print(f"\n{c['BOLD']}─── {title} ───{c['RESET']}")
        for key,val in data.items():
            if isinstance(val,dict) and 'score' in val:
                s=float(val['score']); conf=val.get('confidence','')
                _safe_print(f"  {key:<28}: {score_color(s)}{s:5.1f}%{c['RESET']} [{conf}]")
                if full and val.get('details'):
                    for item in val['details'][:50]: _safe_print(f"    - {item}")
    group('TIER 1 — BEHAVIORAL', r.tier1)
    group('TIER 2 — TEST STRUCTURE / STYLE', r.tier2)
    group('TIER 3 — INTEGRATION VERIFICATION', r.tier3)
    group('TIER 4 — ERP / ACCOUNTING', r.tier4)
    _safe_print(f"\n{c['BOLD']}─── TIER 5 — ADVANCED / STATIC ESTIMATES ───{c['RESET']}")
    _safe_print(f"  Mutation score estimate : {r.tier5.get('mutation_score',0):.1f}%")
    _safe_print(f"  Test strength          : {r.tier5.get('test_strength',0):.1f}%")
    _safe_print(f"  Confidence             : {r.tier5.get('confidence_score',0):.1f}%")
    _safe_print(f"  {c['DIM']}Mutation score is NOT real mutation testing; it is a static estimate.{c['RESET']}")
    if r.tier5.get('business_flow_summary'):
        _safe_print(f"\n{c['BOLD']}─── BUSINESS FLOW COVERAGE ───{c['RESET']}")
        for k,v in sorted(r.tier5['business_flow_summary'].items(), key=lambda kv: kv[1]['pct']):
            _safe_print(f"  {k:<30} {v['pct']:>5.1f}% ({v['covered']}/{v['total']})")
    _safe_print(f"\n{c['BOLD']}─── TIER 6 — ISSUES / SMELLS ───{c['RESET']}")
    for key in ('flaky_tests','slow_tests','dead_code','orphan_tests'):
        d=r.tier6.get(key,{})
        if isinstance(d,dict) and d.get('count',0):
            _safe_print(f"  {key:<28}: {d.get('count',0)}")
    _safe_print(f"  untested_functions       : {len(r.tier6.get('untested_functions',[]))}")
    _safe_print(f"  test_smells              : {len(r.tier6.get('test_smells',[]))}")
    if r.top_offending_files:
        _safe_print(f"\n{c['BOLD']}─── TOP OFFENDING FILES ───{c['RESET']}")
        for row in r.top_offending_files[:20]:
            gap=row['functions']-row['tested_functions']
            _safe_print(f"  {row['file']}: {row['risk']} — {row['tested_functions']}/{row['functions']} tested, gap={gap}")
    if show_rca and r.rca_results:
        _safe_print(f"\n{c['MAGENTA']}─── RCA ───{c['RESET']}")
        for rr in r.rca_results:
            _safe_print(f"  {rr['metric']}: {rr['score']:.1f}%")
            rc=rr.get('rca',{}).get('root_cause'); fix=rr.get('rca',{}).get('suggested_fix')
            if rc: _safe_print(f"    Root cause: {rc}")
            if fix: _safe_print(f"    Fix: {fix}")
    _safe_print(f"\n{c['BOLD']}WEIGHT MODEL{c['RESET']}: Tier1=35%, Tier2=10%, Tier3=20%, Tier4=25%, Tier5=5%, Tier6=5%")
    _safe_print(f"{c['BOLD']}VERDICT: {gate_col}{'LULUS' if r.passed else 'TIDAK LULUS'}{c['RESET']}")


def print_business_flow_gaps(r: Report, threshold: float = 100.0) -> None:
    c = COLOR
    gaps = [g for g in r.tier5.get("business_flow_gaps", []) if g["domain_pct"] < threshold]
    if not gaps:
        _safe_print(f"\n{c['GREEN']}Semua business flow domain sudah >= {threshold:.1f}%% -- tidak ada gap.{c['RESET']}")
        return
    _safe_print(f"\n{c['BOLD']}─── BUSINESS FLOW GAPS (domain < {threshold:.1f}%, paling lemah dulu; "
                f"🔺 = fungsi finansial-sensitif) ───{c['RESET']}")
    current_domain = None
    for g in gaps:
        if g["domain"] != current_domain:
            current_domain = g["domain"]
            _safe_print(f"\n  {c['YELLOW']}{g['domain']}{c['RESET']} — {g['domain_pct']:.1f}% "
                        f"({g['domain_covered']}/{g['domain_total']} tertest)")
        marker = "🔺" if g["risk_flags"] else "  "
        cls = f"{g['class_name']}." if g["class_name"] else ""
        risk_note = f" [{', '.join(g['risk_flags'])}]" if g["risk_flags"] else ""
        _safe_print(f"    {marker} {g['file']}:{g['lineno']} {cls}{g['name']}{risk_note}")
    total = len(gaps)
    risky = sum(1 for g in gaps if g["risk_flags"])
    _safe_print(f"\n  {c['BOLD']}Total: {total} fungsi belum tertest di domain < {threshold:.1f}% "
                f"({risky} di antaranya finansial-sensitif 🔺){c['RESET']}")


# ─── NEW: LIST FILES FOR A METRIC ─────────────────────────────────────────
def print_metric_file_scores(report: Report, metric_name: str, threshold: float = 70.0) -> None:
    """
    Menampilkan file-file yang memiliki skor di bawah threshold untuk metrik tertentu.
    Berguna untuk langsung tahu file mana yang menyebabkan low score di metrik seperti
    negative_path, database_verification, dll.
    """
    c = COLOR
    # Cari metrik di semua tier
    tiers = [report.tier1, report.tier2, report.tier3, report.tier4, report.tier5, report.tier6]
    tier_names = ["tier1", "tier2", "tier3", "tier4", "tier5", "tier6"]
    found = None
    for tier, tname in zip(tiers, tier_names, strict=False):
        if metric_name in tier:
            found = tier[metric_name]
            break
    if found is None:
        _safe_print(f"{c['RED']}Metric '{metric_name}' tidak ditemukan. Pastikan nama metrik benar (contoh: negative_path, database_verification).{c['RESET']}")
        return
    file_scores = found.get("file_scores", {})
    if not file_scores:
        _safe_print(f"{c['YELLOW']}Metric '{metric_name}' tidak memiliki data per-file.{c['RESET']}")
        return
    low_files = [(f, s) for f, s in file_scores.items() if s < threshold]
    if not low_files:
        _safe_print(f"{c['GREEN']}Semua file memiliki skor >= {threshold:.1f}% untuk metrik '{metric_name}'.{c['RESET']}")
        return
    low_files.sort(key=lambda x: x[1])  # urut dari terendah
    _safe_print(f"\n{c['BOLD']}─── File dengan skor {metric_name} di bawah {threshold:.1f}% ───{c['RESET']}")
    for f, s in low_files:
        _safe_print(f"  {s:5.1f}%  {f}")
    _safe_print(f"  {c['DIM']}Total: {len(low_files)} file bermasalah.{c['RESET']}")


# ─── NEW: LAPORAN PER FILE ────────────────────────────────────────────────
def print_by_file_report(report: Report, limit: int = 8, threshold: float = 70.0) -> None:
    files = build_file_grouped_report(report, threshold=threshold)
    if not files:
        _safe_print(f"\n✅ Tidak ada file yang bermasalah (semua skor >= threshold {threshold:.1f}%).")
        return

    def _issue_count(data: dict) -> int:
        return len(data["tier_scores"]) + sum(len(v) for v in data["lines"].values())

    ordered = sorted(files.items(), key=lambda kv: _issue_count(kv[1]), reverse=True)
    c = COLOR
    _safe_print(f"\n{c['BOLD']}{c['CYAN']}╔{'═'*76}╗{c['RESET']}")
    header = f"LAPORAN PER FILE (TOP {min(limit, len(ordered))} dari {len(ordered)} file bermasalah)"
    _safe_print(f"{c['BOLD']}{c['CYAN']}║{c['RESET']}{c['BOLD']} {header}{' ' * max(0, 75 - len(header))}{c['CYAN']}║{c['RESET']}")
    _safe_print(f"{c['BOLD']}{c['CYAN']}╚{'═'*76}╝{c['RESET']}")
    _safe_print(f"{c['DIM']}  (Metrik dengan skor >= {threshold:.1f}% dianggap sudah beres dan tidak ditampilkan lagi){c['RESET']}\n")

    for idx, (filepath, data) in enumerate(ordered[:limit], 1):
        _safe_print(f"{c['BOLD']}{c['MAGENTA']}File #{idx}: {filepath}{c['RESET']} {c['DIM']}({_issue_count(data)} isu){c['RESET']}")

        per_tier_scores: dict[int, list[tuple[str, float]]] = defaultdict(list)
        per_tier_lines: dict[int, list[tuple[str, str]]] = defaultdict(list)

        for label, score in data["tier_scores"].items():
            m = re.match(r'Tier (\d+) - (.+)', label)
            if m:
                per_tier_scores[int(m.group(1))].append((m.group(2), score))

        for label, items in data["lines"].items():
            m = re.match(r'Tier (\d+)(?: - (.+))?', label)
            if not m:
                continue
            tier_num = int(m.group(1))
            sub_label = m.group(2) or label
            for item in items:
                per_tier_lines[tier_num].append((sub_label, item))

        for tier_num in range(1, 7):
            _safe_print(f"  {c['BOLD']}{c['YELLOW']}Tier {tier_num}{c['RESET']} --->")
            scores = sorted(per_tier_scores.get(tier_num, []))
            lines = per_tier_lines.get(tier_num, [])
            if not scores and not lines:
                _safe_print(f"    {c['GREEN']}Tidak ada isu terdeteksi.{c['RESET']}")
                continue
            for sub_label, score in scores:
                _safe_print(f"    {c['DIM']}[skor]{c['RESET']} {sub_label}: {score:.1f}% (< threshold {threshold:.1f}%)")
            for sub_label, item in lines:
                _safe_print(f"    {c['DIM']}[{sub_label}]{c['RESET']} {item}")
        _safe_print("")


# ─── EXPORT FUNCTIONS ──────────────────────────────────────────────────────
def export_full_details(report: Report, path: pathlib.Path) -> bool:
    try:
        data = {
            "version": __version__,
            "timestamp": datetime.now(UTC).isoformat(),
            "overall_quality_score": report.overall_quality_score,
            "total_tests": report.total_tests,
            "total_source_functions": report.total_source_functions,
            "tested_functions_direct": report.tested_functions_direct,
            "tested_functions_unique": report.tested_functions_unique,
            "untested_functions": report.untested_functions,
            "parse_errors": report.parse_errors,
            "source_functions": [
                {
                    "key": f.key,
                    "name": f.name,
                    "file": f.file,
                    "lineno": f.lineno,
                    "end_lineno": f.end_lineno,
                    "class_name": f.class_name,
                    "is_method": f.is_method,
                    "is_private": f.is_private,
                    "decorators": f.decorators,
                    "raises": f.raises,
                    "calls": f.calls,
                    "branches": f.branches,
                    "domain": f.domain,
                    "has_accounting_check": f.has_accounting_check,
                    "has_inventory_check": f.has_inventory_check,
                    "has_period_check": f.has_period_check,
                    "has_currency_convert": f.has_currency_convert,
                    "has_decimal_ops": f.has_decimal_ops,
                    "has_status_transition": f.has_status_transition,
                    "has_retry_logic": f.has_retry_logic,
                    "has_cache_ops": f.has_cache_ops,
                    "has_file_ops": f.has_file_ops,
                    "has_otel_ops": f.has_otel_ops,
                    "has_logging_ops": f.has_logging_ops,
                    "has_transaction": f.has_transaction,
                    "has_outbox": f.has_outbox,
                    "has_kafka_publish": f.has_kafka_publish,
                    "is_tested": f.is_tested,
                    "match_confidence": f.match_confidence,
                    "tested_by_direct": list(f.tested_by_direct),
                    "tested_by_unique": list(f.tested_by_unique),
                    "tested_by_ambiguous": list(f.tested_by_ambiguous),
                }
                for f in report.source_functions
            ],
            "test_functions": [
                {
                    "key": t.key,
                    "name": t.name,
                    "file": t.file,
                    "lineno": t.lineno,
                    "end_lineno": t.end_lineno,
                    "line_count": t.line_count,
                    "assertions": [{"op": a.op, "lineno": a.lineno, "has_literal_operand": a.has_literal_operand, "has_message": a.has_message, "raw": a.raw} for a in t.assertions],
                    "has_raises": t.has_raises,
                    "raises_targets": t.raises_targets,
                    "has_parametrize": t.has_parametrize,
                    "has_mock": t.has_mock,
                    "has_db": t.has_db,
                    "has_event_assert": t.has_event_assert,
                    "has_audit_assert": t.has_audit_assert,
                    "is_async": t.is_async,
                    "calls": t.calls,
                    "resolved_calls": [(name, conf, candidates) for name, conf, candidates in t.resolved_calls],
                    "decorators": t.decorators,
                    "markers": t.markers,
                    "setup_fixtures": t.setup_fixtures,
                    "has_sleep": t.has_sleep,
                    "has_random": t.has_random,
                    "has_datetime_now": t.has_datetime_now,
                    "has_timeout": t.has_timeout,
                    "has_try_except": t.has_try_except,
                    "uses_decimal": t.uses_decimal,
                    "has_rollback": t.has_rollback,
                    "has_commit": t.has_commit,
                    "has_cache_hit": t.has_cache_hit,
                    "has_cache_set": t.has_cache_set,
                    "has_file_upload": t.has_file_upload,
                    "has_otel": t.has_otel,
                    "has_logging": t.has_logging,
                    "has_retry": t.has_retry,
                    "tested_roles": list(t.tested_roles),
                    "struct_hash": t.struct_hash,
                }
                for t in report.test_functions
            ],
            "findings": [
                {"rule": f.rule, "severity": f.severity, "confidence": f.confidence, "file": f.file, "line": f.lineno, "message": f.message}
                for f in report.findings
            ],
            "top_offending_files": report.top_offending_files,
            "tier1": report.tier1,
            "tier2": report.tier2,
            "tier3": report.tier3,
            "tier4": report.tier4,
            "tier5": report.tier5,
            "tier6": report.tier6,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        _safe_print(f"{_c('GREEN')}✅ Full details JSON saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save full details: {e}{_c('RESET')}")
        return False


def build_file_grouped_report(report: Report, threshold: float = 70.0) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = defaultdict(lambda: {"tier_scores": {}, "lines": defaultdict(list)})

    def _add_line_item(label: str, item: str):
        if " " in item:
            loc, rest = item.split(" ", 1)
        else:
            loc, rest = item, ""
        if ":" not in loc:
            return
        f, _, line = loc.rpartition(":")
        files[f]["lines"][label].append(f"L{line} {rest}".strip())

    for label, key in [("Assertion Quality", "assertion_quality"), ("Negative Path", "negative_path"),
                         ("Edge Case", "edge_case"), ("Magic Number", "magic_number")]:
        d = report.tier1.get(key, {})
        for f, score in d.get("file_scores", {}).items():
            if score < threshold:
                files[f]["tier_scores"][f"Tier 1 - {label}"] = score

    for label, key in [("Mock Quality", "mock_quality"), ("Duplicate Test", "duplicate_test")]:
        d = report.tier2.get(key, {})
        for f, score in d.get("file_scores", {}).items():
            if score < threshold:
                files[f]["tier_scores"][f"Tier 2 - {label}"] = score
    dup = report.tier2.get("duplicate_test", {})
    dup_groups: dict[str, list[str]] = defaultdict(list)
    for loc_a, loc_b, sig in dup.get("details", []):
        dup_groups[loc_a].append(loc_b)
    for loc_a, loc_bs in dup_groups.items():
        if " " in loc_a:
            anchor_loc, anchor_rest = loc_a.split(" ", 1)
        else:
            anchor_loc, anchor_rest = loc_a, ""
        if ":" not in anchor_loc:
            continue
        f, _, anchor_line = anchor_loc.rpartition(":")
        other_lines = []
        for loc_b in loc_bs:
            loc_part = loc_b.split(" ", 1)[0]
            other_lines.append(f"L{loc_part.rpartition(':')[2]}")
        summary = f"L{anchor_line} {anchor_rest}".strip()
        if len(other_lines) == 1:
            summary += f" — duplikat struktural dengan {other_lines[0]}"
        else:
            summary += f" — duplikat struktural dengan {len(other_lines)} test lain: {', '.join(other_lines[:15])}"
            if len(other_lines) > 15:
                summary += f", ... dan {len(other_lines) - 15} lagi"
        files[f]["lines"]["Tier 2 - Duplicate Test"].append(summary)

    for label, key in [("Database Verification", "database_verification"), ("Domain Event", "domain_event_verification"),
                         ("Audit Log", "audit_log_verification"), ("Idempotency", "idempotency_verification")]:
        d = report.tier3.get(key, {})
        for f, score in d.get("file_scores", {}).items():
            if score < threshold:
                files[f]["tier_scores"][f"Tier 3 - {label}"] = score

    for label, key in [("Accounting", "accounting"), ("Inventory", "inventory"), ("Fiscal Period", "fiscal_period"),
                         ("Multi Currency", "multi_currency"), ("Precision", "precision")]:
        d = report.tier4.get(key, {})
        for f, score in d.get("file_scores", {}).items():
            if score < threshold:
                files[f]["tier_scores"][f"Tier 4 - {label}"] = score
        for item in d.get("untested_sample", []):
            _add_line_item(f"Tier 4 - {label} (belum tertest)", item)

    for domain, d in report.tier5.get("business_flow", {}).items():
        if d.get("pct", 100) < threshold:
            for item in d.get("missing_functions", []):
                _add_line_item(f"Tier 5 - Business Flow ({domain})", item)

    for item in report.tier6.get("untested_functions", []):
        _add_line_item("Tier 6 - Untested Function", item)

    for fnd in report.findings:
        files[fnd.file]["lines"][f"Tier 6 - {fnd.rule}"].append(f"L{fnd.lineno} {fnd.message}")

    return files


def save_by_file_report(report: Report, path: pathlib.Path, threshold: float = 70.0) -> bool:
    try:
        files = build_file_grouped_report(report, threshold=threshold)
        path.parent.mkdir(parents=True, exist_ok=True)

        def _issue_count(data: dict) -> int:
            return len(data["tier_scores"]) + sum(len(v) for v in data["lines"].values())

        ordered = sorted(files.items(), key=lambda kv: _issue_count(kv[1]), reverse=True)

        lines_out: list[str] = []
        lines_out.append(f"# Laporan Per File — Pytest Quality Checker v{__version__}")
        lines_out.append("")
        lines_out.append(f"Total file bermasalah: **{len(ordered)}**")
        lines_out.append("")
        lines_out.append("Diurutkan dari file dengan jumlah masalah terbanyak. Setiap file menunjukkan")
        lines_out.append("SEMUA tier yang bermasalah sekaligus supaya bisa dibenahi dalam satu kali edit.")
        lines_out.append("")
        lines_out.append("---")
        lines_out.append("")

        for f, data in ordered:
            total_issues = _issue_count(data)
            tier_labels = sorted(set(data["tier_scores"].keys()) | set(data["lines"].keys()))
            tier_names_short = sorted({lbl.split(" - ")[0] for lbl in tier_labels})
            lines_out.append(f"## `{f}`")
            lines_out.append(f"**{total_issues} masalah** — mencakup: {', '.join(tier_names_short)}")
            lines_out.append("")
            if data["tier_scores"]:
                lines_out.append("**Skor agregat di bawah threshold:**")
                for label, score in sorted(data["tier_scores"].items()):
                    lines_out.append(f"- {label}: {score:.1f}%")
                lines_out.append("")
            if data["lines"]:
                for label in sorted(data["lines"].keys()):
                    items = data["lines"][label]
                    lines_out.append(f"**{label}** ({len(items)}):")
                    for item in items:
                        lines_out.append(f"- {item}")
                    lines_out.append("")
            lines_out.append("---")
            lines_out.append("")

        path.write_text("\n".join(lines_out), encoding="utf-8")
        _safe_print(f"{_c('GREEN')}✅ Laporan per-file saved: {path} ({len(ordered)} file){_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save by-file report: {e}{_c('RESET')}")
        return False


def save_json(report: Report, path: pathlib.Path) -> bool:
    try:
        data = {
            "version": __version__,
            "timestamp": datetime.now(UTC).isoformat(),
            "overall_score": report.gate_score,
            "overall_quality_score": report.overall_quality_score,
            "gate_score": report.gate_score,
            "gate_status": report.gate_status,
            "gate_failures": report.gate_failures,
            "metric_errors": report.metric_errors,
            "passed": report.passed,
            "scan_time": report.scan_time,
            "total_tests": report.total_tests,
            "total_source_functions": report.total_source_functions,
            "tested_functions": report.tested_functions,
            "tested_functions_direct": report.tested_functions_direct,
            "tested_functions_unique": report.tested_functions_unique,
            "untested_functions": report.untested_functions,
            "parse_errors": report.parse_errors,
            "tier1": report.tier1, "tier2": report.tier2, "tier3": report.tier3,
            "tier4": report.tier4, "tier5": report.tier5, "tier6": report.tier6,
            "rca_results": report.rca_results,
            "top_offending_files": report.top_offending_files,
            "findings": [
                {"rule": f.rule, "severity": f.severity, "message": f.message,
                 "file": f.file, "line": f.lineno, "confidence": f.confidence}
                for f in report.findings
            ],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
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
            writer.writerow(["metric", "value"])
            writer.writerow(["overall_quality_score", report.overall_quality_score])
            writer.writerow(["total_tests", report.total_tests])
            writer.writerow(["total_source_functions", report.total_source_functions])
            writer.writerow(["tested_functions_direct", report.tested_functions_direct])
            writer.writerow(["tested_functions_unique", report.tested_functions_unique])
            writer.writerow(["untested_functions", report.untested_functions])
            for tier, data in [("tier1", report.tier1), ("tier2", report.tier2), ("tier3", report.tier3),
                                ("tier4", report.tier4), ("tier5", report.tier5), ("tier6", report.tier6)]:
                for key, val in data.items():
                    if isinstance(val, dict):
                        for k2, v2 in val.items():
                            if isinstance(v2, (int, float, str)):
                                writer.writerow([f"{tier}_{key}_{k2}", v2])
            writer.writerow([])
            writer.writerow(["--- FINDINGS ---"])
            writer.writerow(["rule", "severity", "confidence", "file", "line", "message"])
            for f in report.findings:
                writer.writerow([f.rule, f.severity, f.confidence, f.file, f.lineno, f.message])
        _safe_print(f"{_c('GREEN')}✅ CSV saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save CSV: {e}{_c('RESET')}")
        return False


def save_html(report: Report, path: pathlib.Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        color = "green" if report.passed else "red"
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Pytest Quality Report</title>
<style>
body{{font-family:sans-serif;background:#f8f9fa;color:#212529;padding:2rem}}
h1{{color:#0d6efd}}
.summary{{display:flex;gap:2rem;flex-wrap:wrap;margin:1rem 0}}
.card{{background:white;padding:1rem 2rem;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,0.1)}}
.card .value{{font-size:2rem;font-weight:bold}}
.card .value.green{{color:#198754}}
.card .value.yellow{{color:#ffc107}}
.card .value.red{{color:#dc3545}}
.card .label{{color:#6c757d}}
.table{{width:100%;border-collapse:collapse}}
.table td, .table th{{padding:0.3rem 0.5rem;border-bottom:1px solid #e9ecef;text-align:left}}
.error{{color:red;font-weight:bold}}
.mono{{font-family:monospace;font-size:0.85rem}}
.tag{{font-size:0.7rem;padding:0.1rem 0.4rem;border-radius:4px;background:#e9ecef;color:#495057}}
</style>
</head>
<body>
<h1>Pytest Quality Checker Report (v{__version__})</h1>
<div class="summary">
  <div class="card"><div class="value">{report.overall_quality_score:.1f}</div><div class="label">Quality Score</div></div>
  <div class="card"><div class="value">{report.total_tests}</div><div class="label">Total Tests</div></div>
  <div class="card"><div class="value">{report.total_source_functions}</div><div class="label">Source Functions</div></div>
  <div class="card"><div class="value">{report.tested_functions}</div><div class="label">Tested</div></div>
  <div class="card"><div class="value" style="color:{color}">{'PASS' if report.passed else 'FAIL'}</div><div class="label">Status</div></div>
</div>
"""
        if report.parse_errors:
            html += "<h2>⚠️ Parse Errors</h2><ul>"
            for err in report.parse_errors:
                html += f"<li class='error'>{err['file']}: {err['error'][:150]}</li>"
            html += "</ul>"

        def tier_table(title, tier_dict, rows):
            out = f"<h2>{title}</h2><table class='table'><tr><th>Metric</th><th>Score</th><th>Confidence</th></tr>"
            for label, key in rows:
                d = tier_dict.get(key, {})
                if "score" in d:
                    out += f"<tr><td>{label}</td><td>{d['score']:.1f}%</td><td><span class='tag'>{d.get('confidence','-')}</span></td></tr>"
            return out + "</table>"

        html += tier_table("Tier 1 (Wajib)", report.tier1, [
            ("Assertion Quality", "assertion_quality"), ("Negative Path", "negative_path"),
            ("Exception Coverage", "exception_coverage"), ("Edge Case", "edge_case"), ("Magic Number", "magic_number")])
        html += tier_table("Tier 4 (ERP Specific)", report.tier4, [
            ("Accounting", "accounting"), ("Inventory", "inventory"), ("Fiscal Period", "fiscal_period"),
            ("Multi Currency", "multi_currency"), ("Precision", "precision")])

        html += "<h2>Business Flow Coverage (discovered from actual repo)</h2><table class='table'>"
        for flow, data in report.tier6["business_flow_summary"].items():
            colr = "green" if data["pct"] >= 80 else "yellow" if data["pct"] >= 50 else "red"
            html += f'<tr><td>{flow}</td><td style="color:{colr}">{data["pct"]:.1f}% ({data["covered"]}/{data["total"]})</td></tr>'
        html += "</table>"

        html += "<h2>Top Offending Files</h2><table class='table'><tr><th>File</th><th>Risk</th><th>Tested/Total funcs</th><th>LOC</th></tr>"
        for row in report.top_offending_files:
            html += f"<tr><td class='mono'>{row['file']}</td><td>{row['risk']}</td><td>{row['tested_functions']}/{row['functions']}</td><td>{row['loc']}</td></tr>"
        html += "</table>"

        html += "<h2>Findings</h2><table class='table'><tr><th>Rule</th><th>Severity</th><th>Confidence</th><th>Location</th><th>Message</th></tr>"
        for f in report.findings:
            html += f"<tr><td>{f.rule}</td><td>{f.severity}</td><td><span class='tag'>{f.confidence}</span></td><td class='mono'>{f.file}:{f.lineno}</td><td>{f.message}</td></tr>"
        html += "</table>"

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
            level = {"error": "error", "warning": "warning", "note": "note"}.get(f.severity, "warning")
            results.append({
                "ruleId": f.rule,
                "level": level,
                "message": {"text": f.message},
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {"uri": f.file},
                        "region": {"startLine": max(1, f.lineno)},
                    }
                }],
                "properties": {"confidence": f.confidence},
            })
        for err in report.parse_errors:
            results.append({
                "ruleId": "PARSE-ERROR",
                "level": "error",
                "message": {"text": err["error"]},
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": err["file"]}, "region": {"startLine": 1}}}],
            })
        rule_ids = sorted({f.rule for f in report.findings} | {"PARSE-ERROR"})
        sarif = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [{
                "tool": {
                    "driver": {
                        "name": "PytestQualityChecker",
                        "version": __version__,
                        "rules": [{"id": rid, "shortDescription": {"text": rid.replace("-", " ").title()}} for rid in rule_ids],
                    }
                },
                "results": results,
            }],
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
            if verbose:
                _safe_print(f"  ✅ {name}")
            passed += 1
        else:
            if verbose:
                _safe_print(f"  ❌ {name}" + (f": {detail}" if detail else ""))
            failed += 1

    if verbose:
        _safe_print(f"\nPytest Checker self-test v{__version__}…\n")

    sample_src = (
        "class JournalService:\n"
        "    def post_journal_entry(self, entry):\n"
        "        if entry.amount < 0:\n"
        "            raise ValueError('negative')\n"
        "        return entry\n"
    )
    tree = ast.parse(sample_src)
    cls = tree.body[0]
    fn = cls.body[0]
    v = SourceFeatureVisitor()
    v.visit(fn)
    check("SourceFeatureVisitor detects raises", "ValueError" in v.raises, str(v.raises))
    check("SourceFeatureVisitor counts branches", v.branches == 1, str(v.branches))

    sample_test = (
        "def test_post_journal_entry_rejects_negative():\n"
        "    svc = JournalService()\n"
        "    with pytest.raises(ValueError):\n"
        "        svc.post_journal_entry(entry)\n"
        "    assert svc.post_journal_entry(entry2) == entry2\n"
    )
    ttree = ast.parse(sample_test)
    tfn = ttree.body[0]
    tv = TestFeatureVisitor({"JournalService": ("class", "JournalService")}, {}, [])
    tv.visit(tfn)
    check("TestFeatureVisitor detects pytest.raises target", "ValueError" in tv.raises_targets, str(tv.raises_targets))
    check("TestFeatureVisitor tracks var type from constructor", tv.var_types.get("svc") == "JournalService", str(tv.var_types))
    check("TestFeatureVisitor records assertion op", any(a.op == "eq" for a in tv.assertions), str(tv.assertions))

    h1 = _normalized_dump(ast.parse("assert x == 5").body[0])
    h2 = _normalized_dump(ast.parse("assert y == 999").body[0])
    check("Normalized dump distinguishes different literal values AND different names",
          h1 != h2, f"{h1} vs {h2}")
    h1b = _normalized_dump(ast.parse("assert x == 5").body[0])
    check("Normalized dump is still deterministic/stable for identical code",
          h1 == h1b, f"{h1} vs {h1b}")
    h3 = _normalized_dump(ast.parse("assert x != 5").body[0])
    check("Normalized dump distinguishes different operators", h1 != h3, f"{h1} vs {h3}")

    check("Dotted module path conversion works", _dotted_module_path("domain/journal/entities.py") == "domain.journal.entities")
    check("Domain discovery works for domain/ files", _discover_domain("domain/fixed_asset/entity.py") == "fixed_asset")
    check("Domain discovery returns empty for non-domain files", _discover_domain("application/use_cases/foo.py") == "")

    fn_a = ast.parse("def test_a():\n    assert x == 5\n").body[0]
    fn_a2 = ast.parse("def test_a2():\n    assert x == 5\n").body[0]
    fn_b = ast.parse("def test_b():\n    assert y == 999\n").body[0]
    fn_c = ast.parse("def test_c():\n    assert x is not None\n").body[0]
    hash_a = _normalized_dump(fn_a)
    hash_a2 = _normalized_dump(fn_a2)
    hash_b = _normalized_dump(fn_b)
    hash_c = _normalized_dump(fn_c)
    check("normalized_dump on root FunctionDef is not just 'FunctionDef'", hash_a != "FunctionDef", hash_a)
    check("normalized_dump treats byte-for-byte-identical test bodies as equal",
          hash_a == hash_a2, f"{hash_a} vs {hash_a2}")
    check("normalized_dump distinguishes test bodies differing only by literal/name",
          hash_a != hash_b, f"{hash_a} vs {hash_b}")
    check("normalized_dump distinguishes structurally-different test bodies", hash_a != hash_c, f"{hash_a} vs {hash_c}")

    tv_bool = TestFeatureVisitor({}, {}, [])
    tv_bool.visit(ast.parse("def test_d():\n    assert x == True\n").body[0])
    check("assert x == True is flagged as bool-literal compare", tv_bool.assertions and tv_bool.assertions[0].is_bool_literal_compare)

    tv_gt = TestFeatureVisitor({}, {}, [])
    tv_gt.visit(ast.parse("def test_e():\n    assert x > 0\n").body[0])
    check("assert x > 0 is NOT flagged as bool-literal compare", tv_gt.assertions and not tv_gt.assertions[0].is_bool_literal_compare)

    tv_prop = TestFeatureVisitor({"PurchaseOrderLine": ("class", "PurchaseOrderLine")}, {}, [])
    tv_prop.visit(ast.parse(
        "def test_subtotal():\n"
        "    line = PurchaseOrderLine()\n"
        "    assert line.subtotal == 200\n"
    ).body[0])
    check("bare attribute access inside assert (property test) is captured as a call",
          any(attr == "subtotal" for _, attr, _ in tv_prop.raw_calls), str(tv_prop.raw_calls))
    check("attribute-that-is-a-call-target is NOT double counted",
          sum(1 for _, attr, _ in tv_prop.raw_calls if attr == "subtotal") == 1, str(tv_prop.raw_calls))

    sf_dunder = SourceFunction(key="k", name="__getattr__", file="f.py", lineno=1, end_lineno=2, is_dunder=True)
    check("dunder method (except __init__) is always considered tested", sf_dunder.is_tested)
    sf_init = SourceFunction(key="k2", name="__init__", file="f.py", lineno=1, end_lineno=2, is_dunder=False)
    check("__init__ is NOT auto-exempted (still trackable via constructor calls)", not sf_init.is_tested)

    idx_noise = ProjectIndex.__new__(ProjectIndex)
    idx_noise.source_functions = {}
    idx_noise.class_methods_index = defaultdict(list)
    idx_noise.class_validator_methods_index = defaultdict(list)
    idx_noise.bare_name_index = defaultdict(list)
    idx_noise.module_exports_index = {}
    idx_noise.fixture_class_index = {}
    idx_noise.class_methods_index["CustomerAggregate.update"].append("k")
    idx_noise.bare_name_index["update"].append("k")
    resolved_update = _resolve_calls(
        [(ast.Name(id="customer"), "update", 1)], {"customer": "CustomerAggregate"}, {}, idx_noise
    )
    check("entity.update(...) with known class resolves as 'direct' (not silently dropped as noise)",
          resolved_update and resolved_update[0] == ("update", "direct", ["k"]), str(resolved_update))

    tv_event = TestFeatureVisitor({}, {}, [])
    tv_event.visit(ast.parse("def test_x():\n    assert len(entity.domain_events) == 1\n").body[0])
    check("bare attribute read `entity.domain_events` inside assert sets has_event_assert",
          tv_event.has_event_assert)

    tv_audit = TestFeatureVisitor({}, {}, [])
    tv_audit.visit(ast.parse("def test_y():\n    assert entity.audit_log[-1].action == 'CREATE'\n").body[0])
    check("bare attribute read `entity.audit_log` inside assert sets has_audit_assert",
          tv_audit.has_audit_assert)

    tv_realcalls = TestFeatureVisitor({}, {}, [])
    tv_realcalls.visit(ast.parse(
        "def test_z():\n"
        "    result = handler.execute(cmd)\n"
        "    assert exc_info.value.args[0] == 'boom'\n"
    ).body[0])
    check("explicit_call_names only contains real Call (not attribute reads from assert)",
          tv_realcalls.explicit_call_names == ["execute"], str(tv_realcalls.explicit_call_names))
    check("raw_calls (used for resolution) includes both real calls and attribute reads",
          len(tv_realcalls.raw_calls) > len(tv_realcalls.explicit_call_names), str(tv_realcalls.raw_calls))

    tf_repeat = TestFunction(key="k", name="test_idempotent_call", file="f.py", lineno=1, end_lineno=5,
                              line_count=5, calls=["execute", "execute"])
    check("TestFunction with same call repeated 2x is available for idempotency repeated-call detection",
          tf_repeat.calls.count("execute") >= 2)

    mod_tree = ast.parse(
        "import pytest\n"
        "pytestmark = pytest.mark.asyncio\n"
        "async def test_a():\n"
        "    assert 1 == 1\n"
    )
    mod_marks = _extract_pytestmark(mod_tree.body)
    check("module-level `pytestmark = pytest.mark.asyncio` is extracted as a marker",
          "asyncio" in mod_marks, str(mod_marks))

    mod_tree_list = ast.parse(
        "import pytest\n"
        "pytestmark = [pytest.mark.asyncio, pytest.mark.slow]\n"
    )
    mod_marks_list = _extract_pytestmark(mod_tree_list.body)
    check("module-level `pytestmark = [mark.asyncio, mark.slow]` extracts both names",
          "asyncio" in mod_marks_list and "slow" in mod_marks_list, str(mod_marks_list))

    cls_tree = ast.parse(
        "import pytest\n"
        "class TestFoo:\n"
        "    pytestmark = pytest.mark.asyncio\n"
        "    async def test_b(self):\n"
        "        assert 1 == 1\n"
    )
    cls_node = cls_tree.body[1]
    cls_marks = _extract_pytestmark(cls_node.body)
    check("class-level `pytestmark = pytest.mark.asyncio` is extracted as a marker",
          "asyncio" in cls_marks, str(cls_marks))

    no_mark_tree = ast.parse("async def test_c():\n    assert 1 == 1\n")
    check("file with no pytestmark assignment yields no inherited markers",
          _extract_pytestmark(no_mark_tree.body) == [])

    _tmp_dir = pathlib.Path(tempfile.mkdtemp())
    try:
        (_tmp_dir / "pytest.ini").write_text("[pytest]\nasyncio_mode = auto\n", encoding="utf-8")
        check("asyncio_mode = auto in pytest.ini is detected", _detect_asyncio_auto_mode(_tmp_dir))
        (_tmp_dir / "pytest.ini").write_text("[pytest]\nasyncio_mode = strict\n", encoding="utf-8")
        check("asyncio_mode = strict in pytest.ini is NOT treated as auto mode",
              not _detect_asyncio_auto_mode(_tmp_dir))
        (_tmp_dir / "pytest.ini").unlink()
        check("no asyncio_mode config anywhere -> not auto mode", not _detect_asyncio_auto_mode(_tmp_dir))
    finally:
        shutil.rmtree(_tmp_dir, ignore_errors=True)

    idx_async = ProjectIndex.__new__(ProjectIndex)
    idx_async.asyncio_auto_mode = True
    analyzer_async = QualityAnalyzer.__new__(QualityAnalyzer)
    analyzer_async.index = idx_async
    analyzer_async.test_funcs = {
        "k1": TestFunction(key="k1", name="test_x", file="f.py", lineno=1, end_lineno=2, line_count=2, is_async=True)
    }
    analyzer_async._metric_cache = {}
    analyzer_async.findings = []
    result_auto = analyzer_async.async_test_checker()
    check("async_test_checker reports 0 missing_marker when asyncio_mode=auto is active",
          result_auto["missing_marker"] == 0, str(result_auto))

    idx_marked = ProjectIndex.__new__(ProjectIndex)
    idx_marked.asyncio_auto_mode = False
    analyzer_marked = QualityAnalyzer.__new__(QualityAnalyzer)
    analyzer_marked.index = idx_marked
    analyzer_marked.test_funcs = {
        "k1": TestFunction(key="k1", name="test_y", file="f.py", lineno=1, end_lineno=2, line_count=2,
                            is_async=True, decorators=[], markers=["asyncio"]),
    }
    analyzer_marked._metric_cache = {}
    analyzer_marked.findings = []
    result_marked = analyzer_marked.async_test_checker()
    check("async_test_checker does NOT flag async test whose marker came from inherited pytestmark "
          "(present in .markers but not .decorators)",
          result_marked["missing_marker"] == 0, str(result_marked))

    tv_unittest_assert = TestFeatureVisitor({}, {}, [])
    tv_unittest_assert.visit(ast.parse(
        "def test_validate_dates_valid(self):\n"
        "    entity = DividendDeclaration()\n"
        "    self.assertTrue(entity.validate_dates())\n"
        "    self.assertEqual(entity.status, 'valid')\n"
    ).body[0])
    check("unittest-style `self.assertTrue`/`self.assertEqual` calls are recorded as real "
          "assertions -- test must NOT be flagged NO-ASSERTION just because it uses no bare `assert`",
          len(tv_unittest_assert.assertions) == 2, str(tv_unittest_assert.assertions))

    tv_unittest_raises = TestFeatureVisitor({}, {}, [])
    tv_unittest_raises.visit(ast.parse(
        "def test_invalid(self):\n"
        "    with self.assertRaises(ValueError):\n"
        "        DividendDeclaration(amount=-1)\n"
    ).body[0])
    check("`self.assertRaises(...)` is recorded as an assertion and sets has_raises",
          len(tv_unittest_raises.assertions) == 1 and tv_unittest_raises.has_raises,
          f"{tv_unittest_raises.assertions} has_raises={tv_unittest_raises.has_raises}")

    tv_patch_obj = TestFeatureVisitor({}, {}, [])
    tv_patch_obj.visit(ast.parse(
        "def test_x():\n"
        "    with patch.object(datetime, 'now', return_value=FIXED):\n"
        "        assert do_thing() == 1\n"
    ).body[0])
    check("has_mock detects `patch.object(...)` (dotted chain, not just the leaf attr 'object')",
          tv_patch_obj.has_mock)

    tv_mocker_patch_obj = TestFeatureVisitor({}, {}, [])
    tv_mocker_patch_obj.visit(ast.parse(
        "def test_y(mocker):\n"
        "    mocker.patch.object(SomeClass, 'method', return_value=1)\n"
        "    assert do_thing() == 1\n"
    ).body[0])
    check("has_mock detects `mocker.patch.object(...)` (3-level dotted chain)",
          tv_mocker_patch_obj.has_mock)

    tv_now_setup_only = TestFeatureVisitor({}, {}, [])
    tv_now_setup_only.visit(ast.parse(
        "def test_is_overdue_true():\n"
        "    obligation = FinancialObligation(due_date=datetime.now(UTC) - timedelta(days=5))\n"
        "    assert obligation.is_overdue is True\n"
    ).body[0])
    check("datetime.now() used only to build setup/input data (not inside the assert "
          "expression itself) does NOT set has_datetime_now -- assertion here is "
          "deterministic regardless of when the test runs",
          not tv_now_setup_only.has_datetime_now, str(tv_now_setup_only.has_datetime_now))

    tv_now_in_assert = TestFeatureVisitor({}, {}, [])
    tv_now_in_assert.visit(ast.parse(
        "def test_created_recently():\n"
        "    obj = make_obj()\n"
        "    assert obj.created_at <= datetime.now(UTC)\n"
    ).body[0])
    check("datetime.now() used directly inside the `assert` expression DOES set "
          "has_datetime_now -- this is genuinely time-dependent verification",
          tv_now_in_assert.has_datetime_now)

    tv_now_in_unittest_assert = TestFeatureVisitor({}, {}, [])
    tv_now_in_unittest_assert.visit(ast.parse(
        "class T:\n"
        "    def test_created_recently(self):\n"
        "        obj = make_obj()\n"
        "        self.assertLessEqual(obj.created_at, datetime.now(UTC))\n"
    ).body[0].body[0])
    check("datetime.now() used inside a unittest-style self.assertX(...) call argument "
          "also sets has_datetime_now (not just bare `assert`)",
          tv_now_in_unittest_assert.has_datetime_now)

    tv_now_enum_member = TestFeatureVisitor({}, {}, [])
    tv_now_enum_member.visit(ast.parse(
        "def test_member_is_instance():\n"
        "    assert isinstance(SamplingStatus.NOW, SamplingStatus)\n"
    ).body[0])
    check("bare attribute/enum-member reference merely NAMED 'NOW' (e.g. an enum member "
          "SamplingStatus.NOW) does NOT set has_datetime_now -- only an actual CALL to "
          "now()/utcnow() should, not any identifier that happens to match the name",
          not tv_now_enum_member.has_datetime_now, str(tv_now_enum_member.has_datetime_now))

    tv_raises_tuple_with = TestFeatureVisitor({}, {}, [])
    tv_raises_tuple_with.visit(ast.parse(
        "def test_invalid_population_or_sampling():\n"
        "    with pytest.raises((InvalidPopulationError, SamplingError)):\n"
        "        do_something_risky()\n"
    ).body[0])
    check("`with pytest.raises((ExcA, ExcB)):` (tuple form) captures BOTH exception "
          "names into raises_targets, not zero (previously args[0] was an ast.Tuple, "
          "which neither the Name nor Attribute branch handled, so nothing was captured "
          "and both exceptions kept showing up as UNTESTED-EXCEPTION despite being tested)",
          set(tv_raises_tuple_with.raises_targets) == {"InvalidPopulationError", "SamplingError"},
          str(tv_raises_tuple_with.raises_targets))

    tv_raises_tuple_call = TestFeatureVisitor({}, {}, [])
    tv_raises_tuple_call.visit(ast.parse(
        "def test_invalid_population_or_sampling_call_form():\n"
        "    excinfo = pytest.raises((InvalidPopulationError, SamplingError))\n"
    ).body[0])
    check("bare `pytest.raises((ExcA, ExcB))` call-expression form also captures both "
          "exception names (same fix applied to the visit_Call branch)",
          set(tv_raises_tuple_call.raises_targets) == {"InvalidPopulationError", "SamplingError"},
          str(tv_raises_tuple_call.raises_targets))

    idx_ctor = ProjectIndex.__new__(ProjectIndex)
    idx_ctor.class_methods_index = defaultdict(list)
    idx_ctor.class_validator_methods_index = defaultdict(list)
    idx_ctor.bare_name_index = defaultdict(list)
    idx_ctor.class_methods_index["FixedAssetCollection.__init__"].append("src_init_key")
    imported_ctor = {"FixedAssetCollection": ("class", "FixedAssetCollection")}
    tv_ctor = TestFeatureVisitor(imported_ctor, {}, [])
    tv_ctor.visit(ast.parse(
        "def test_construction():\n"
        "    obj = FixedAssetCollection()\n"
        "    assert obj is not None\n"
    ).body[0])
    resolved_ctor = _resolve_calls(tv_ctor.raw_calls, tv_ctor.var_types, imported_ctor, idx_ctor)
    check("bare constructor call `Kelas()` (imported, no owner_expr) resolves to that class's __init__ "
          "-- test_construction pattern must NOT be an orphan test",
          any(c == "src_init_key" for _, _, cands in resolved_ctor for c in cands), str(resolved_ctor))

    idx_ctor_local = ProjectIndex.__new__(ProjectIndex)
    idx_ctor_local.class_methods_index = defaultdict(list)
    idx_ctor_local.class_validator_methods_index = defaultdict(list)
    idx_ctor_local.bare_name_index = defaultdict(list)
    idx_ctor_local.class_methods_index["ReloadResult.__init__"].append("src_init_key2")
    tv_ctor_local = TestFeatureVisitor({}, {}, [])
    tv_ctor_local.visit(ast.parse(
        "def test_construction():\n"
        "    obj = ReloadResult()\n"
        "    assert obj is not None\n"
    ).body[0])
    resolved_ctor_local = _resolve_calls(tv_ctor_local.raw_calls, tv_ctor_local.var_types, {}, idx_ctor_local)
    check("bare constructor call to a LOCAL/unimported class (capitalized-name heuristic, "
          "not present in imported_symbols) still resolves to that class's __init__",
          any(c == "src_init_key2" for _, _, cands in resolved_ctor_local for c in cands), str(resolved_ctor_local))

    idx_priv = ProjectIndex.__new__(ProjectIndex)
    idx_priv.source_functions = {}
    idx_priv.class_methods_index = defaultdict(list)
    idx_priv.class_validator_methods_index = defaultdict(list)
    idx_priv.bare_name_index = defaultdict(list)
    idx_priv.module_exports_index = {}
    idx_priv.fixture_class_index = {}
    idx_priv.class_methods_index["AccountingFailureRunbook._take_snapshot"].append("k_priv")
    idx_priv.bare_name_index["_take_snapshot"].append("k_priv")
    resolved_priv = _resolve_calls(
        [(ast.Name(id="runbook"), "_take_snapshot", 1)],
        {"runbook": "AccountingFailureRunbook"}, {}, idx_priv,
    )
    check("test explicitly calling a private method (instance._helper(...)) DOES resolve as 'direct' "
          "(private methods must stay indexed, otherwise they can never be marked tested)",
          resolved_priv and resolved_priv[0] == ("_take_snapshot", "direct", ["k_priv"]), str(resolved_priv))

    tv_assign_assert = TestFeatureVisitor({}, {}, [])
    tv_assign_assert.visit(ast.parse(
        "def test_total_pajak():\n"
        "    dto = FakturPajakKeluaranDTO()\n"
        "    hasil = dto.total_pajak\n"
        "    assert hasil == 100\n"
    ).body[0])
    check("bare property read assigned to a variable BEFORE assert (`x = obj.prop; assert x == ...`) "
          "is still captured -- not just reads written directly inside the assert expression",
          any(attr == "total_pajak" for _, attr, _ in tv_assign_assert.raw_calls),
          str(tv_assign_assert.raw_calls))

    tv_no_dup = TestFeatureVisitor({}, {}, [])
    tv_no_dup.visit(ast.parse(
        "def test_call_not_dup():\n"
        "    result = handler.execute(cmd)\n"
        "    assert result == 1\n"
    ).body[0])
    check("method CALL (`x.execute(...)`) is not also double-recorded as a bare attribute read",
          sum(1 for _, attr, _ in tv_no_dup.raw_calls if attr == "execute") == 1,
          str(tv_no_dup.raw_calls))

    check("pytest_checker.py, master_checker.py, auto_test_generator.py dikecualikan by "
          "default (meta-tooling, bukan production code)",
          {"pytest_checker.py", "master_checker.py", "auto_test_generator.py"} <= EXCLUDED_FILES_DEFAULT,
          str(EXCLUDED_FILES_DEFAULT))

    check("_classify_file mengecualikan direktori exclude walau casing berbeda "
          "(mis. 'Checker' vs 'checker') -- filesystem Windows case-insensitive, "
          "jadi matching-nya juga harus case-insensitive supaya tidak diam-diam gagal",
          _classify_file("/root", "/root/Checker/pytest_checker.py", {"checker"}, set()) is None)
    check("_classify_file mengecualikan file exclude walau casing berbeda "
          "(mis. 'Manage.PY' vs 'manage.py')",
          _classify_file("/root", "/root/Manage.PY", set(), {"manage.py"}) is None)

    qa_state = QualityAnalyzer.__new__(QualityAnalyzer)
    sf_state = SourceFunction(key="src1", name="set_status", file="saga_state.py", lineno=10, end_lineno=15,
                               has_status_transition=True,
                               tested_by_direct={"t1"}, tested_by_unique=set())
    t_state = TestFunction(key="t1", name="test_set_status_updates_state", file="test_saga.py", lineno=1,
                            end_lineno=5, line_count=5,
                            assertions=[AssertInfo(op="eq", lineno=3, has_literal_operand=True, has_message=False,
                                                    raw="obj.state == ProcurementState.PO_ISSUED",
                                                    is_bool_literal_compare=False)])
    qa_state.source_funcs = {"src1": sf_state}
    qa_state.test_funcs = {"t1": t_state}
    result_state = qa_state.state_transition_checker()
    check("state_transition_checker mengenali assertion yang menguji field 'state' "
          "(mis. `assert obj.state == ProcurementState.PO_ISSUED`) sebagai tertest -- "
          "sebelumnya hanya mencari kata 'status' di raw assertion, jadi field bernama "
          "'state' (umum di saga/workflow) tidak pernah dianggap tertest",
          result_state["tested"] == 1 and result_state["score"] == 100.0, str(result_state))

    qa_retry = QualityAnalyzer.__new__(QualityAnalyzer)
    sf_retry = SourceFunction(key="src2", name="retry_on_conflict", file="optimistic_lock.py",
                               lineno=20, end_lineno=40, has_retry_logic=True,
                               tested_by_direct={"t2"}, tested_by_unique=set())
    t_retry = TestFunction(key="t2", name="test_retries_then_succeeds", file="test_optimistic_lock.py",
                            lineno=1, end_lineno=10, line_count=10)
    qa_retry.source_funcs = {"src2": sf_retry}
    qa_retry.test_funcs = {"t2": t_retry}
    result_retry = qa_retry.idempotency_verification()
    check("idempotency_verification mengenali test bernama 'test_retries_then_succeeds' "
          "sebagai tertest untuk source function yang relevan lewat has_retry_logic -- "
          "sebelumnya keyword 'retry' tidak pernah dicek sama sekali, cuma "
          "'twice'/'idempotent'/'duplicate', jadi test retry yang lengkap sekalipun "
          "selalu dianggap 0% tertest",
          result_retry["score"] == 100.0, str(result_retry))

    qa_mut = QualityAnalyzer.__new__(QualityAnalyzer)
    sf_mut = SourceFunction(key="src3", name="calculate", file="calc.py", lineno=1, end_lineno=5,
                             branches=1, tested_by_direct=set(), tested_by_unique=set(),
                             tested_by_ambiguous={"t3"})
    t_mut = TestFunction(key="t3", name="test_calculate", file="test_calc.py", lineno=1, end_lineno=5,
                          line_count=5,
                          assertions=[AssertInfo(op="eq", lineno=3, has_literal_operand=True, has_message=False,
                                                  raw="result == 42", is_bool_literal_compare=False)])
    qa_mut.source_funcs = {"src3": sf_mut}
    qa_mut.test_funcs = {"t3": t_mut}
    mut_score, mut_covered, mut_total = qa_mut.mutation_score_estimation()
    check("mutation_score_estimation memberi kredit ke fungsi yang tertest HANYA lewat "
          "ambiguous match (tested_by_ambiguous) -- sebelumnya cuma "
          "tested_by_direct|tested_by_unique yang dihitung (is_tested_strict), jadi "
          "fungsi ambiguous-only selalu 0% ter-cover walau is_tested-nya True",
          mut_score == 100.0, f"score={mut_score}, covered={mut_covered}, total={mut_total}")

    idx_validator = ProjectIndex.__new__(ProjectIndex)
    idx_validator.class_methods_index = defaultdict(list)
    idx_validator.class_validator_methods_index = defaultdict(list)
    idx_validator.class_validator_methods_index["ARInvoiceLineSchema"].append("src_validator_key")
    idx_validator.bare_name_index = defaultdict(list)
    raw_calls_validator = [(None, "ARInvoiceLineSchema", 1)]
    resolved_validator = _resolve_calls(raw_calls_validator, {}, {}, idx_validator)
    check("constructor call `ARInvoiceLineSchema(...)` (bare, tanpa __init__ eksplisit di "
          "source -- pola umum Pydantic) meng-resolve method @field_validator milik class "
          "itu (mis. validate_amounts) sebagai tertest -- sebelumnya method validator selalu "
          "UNTESTED-DOMAIN-FUNC walau class-nya rutin di-construct di banyak test",
          any(cands == ["src_validator_key"] for _, _, cands in resolved_validator),
          str(resolved_validator))

    idx_fx = ProjectIndex.__new__(ProjectIndex)
    idx_fx.fixture_class_index = defaultdict(dict)
    idx_fx.conftest_fixture_class_index = {}
    fake_results = [
        {"file": "tests/b_file.py", "fixtures": [{"name": "sample_builder", "class_guess": "ClassB"}]},
        {"file": "tests/a_file.py", "fixtures": [{"name": "sample_builder", "class_guess": "ClassA"}]},
    ]
    for r in fake_results:
        is_conftest = pathlib.Path(r["file"]).name == "conftest.py"
        for fx in r["fixtures"]:
            if fx["class_guess"]:
                if is_conftest:
                    idx_fx.conftest_fixture_class_index[fx["name"]] = fx["class_guess"]
                else:
                    idx_fx.fixture_class_index[r["file"]][fx["name"]] = fx["class_guess"]
    eff_a = {**idx_fx.conftest_fixture_class_index, **idx_fx.fixture_class_index.get("tests/a_file.py", {})}
    eff_b = {**idx_fx.conftest_fixture_class_index, **idx_fx.fixture_class_index.get("tests/b_file.py", {})}
    check("fixture 'sample_builder' di tests/a_file.py (class_guess=ClassA) dan di "
          "tests/b_file.py (class_guess=ClassB) TIDAK saling menimpa -- masing-masing file "
          "resolve ke class-nya sendiri, tidak peduli urutan file diproses. Sebelumnya "
          "fixture_class_index adalah satu flat dict global keyed cuma oleh nama fixture, "
          "jadi file yang diproses TERAKHIR diam-diam menimpa definisi file lain, merusak "
          "resolusi constructor call untuk SEMUA file yang kebetulan pakai nama fixture sama",
          eff_a.get("sample_builder") == "ClassA" and eff_b.get("sample_builder") == "ClassB",
          f"eff_a={eff_a}, eff_b={eff_b}")

    if verbose:
        _safe_print(f"\nSelf-test: {passed} passed, {failed} failed {'✅' if failed == 0 else '❌'}")
    return failed == 0


# ─── MAIN ────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description=f"Pytest Quality Checker v{__version__} (Forensic-Grade)")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE")
    parser.add_argument("--csv", metavar="FILE")
    parser.add_argument("--html", metavar="FILE")
    parser.add_argument("--sarif", metavar="FILE")
    parser.add_argument("--full-details", metavar="FILE", help="Export all raw data (source & test functions) to JSON")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--no-rca", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--exclude", default="", help="Comma-separated directory names to exclude")
    parser.add_argument("--exclude-files", default="", help="Comma-separated file names (exact name) to exclude")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--no-progress", action="store_true")
    parser.add_argument("--ignore-metrics", default="", help="Comma-separated metric names to ignore")
    parser.add_argument("--full", action="store_true", help="Cetak laporan super lengkap (semua daftar, tanpa batasan)")
    parser.add_argument("--per-file", type=int, nargs="?", const=8, default=0,
                         help="Tampilkan laporan per file (Tier 1-6 + baris) untuk N file teratas. "
                              "Panggil tanpa angka untuk TOP 8 (default). 0/tidak dipakai = nonaktif.")
    parser.add_argument("--per-file-threshold", type=float, default=70.0,
                         help="Ambang skor (0-100) untuk laporan --per-file. Metrik dengan skor DI BAWAH "
                              "nilai ini dianggap masih bermasalah; metrik yang sudah >= nilai ini dianggap "
                              "sudah diperbaiki dan tidak akan muncul lagi. Default: 70.0")
    parser.add_argument("--business-flow-gaps", action="store_true",
                         help="Tampilkan semua fungsi belum-tested di domain BUSINESS FLOW COVERAGE "
                              "yang skornya di bawah threshold (default: semua yang < 100%%), "
                              "diurutkan dari domain paling lemah, fungsi finansial-sensitif ditandai 🔺")
    parser.add_argument("--business-flow-gaps-threshold", type=float, default=100.0,
                         help="Ambang persen untuk --business-flow-gaps (default: 100.0)")
    parser.add_argument("--root", type=str, default=None,
                         help="Override lokasi project root secara eksplisit. Default (tanpa opsi ini): "
                              "dua level di atas lokasi file pytest_checker.py itu sendiri -- asumsi "
                              "layout <project_root>/checker/pytest_checker.py. Kalau checker dipindah "
                              "atau dipanggil dari lokasi lain, default itu bisa salah TANPA ERROR "
                              "(diam-diam scan direktori yang salah) -- pakai --root untuk memastikan.")
    parser.add_argument("--version", action="version", version=f"pytest_checker v{__version__}")
    # BARU: list file per metrik
    parser.add_argument("--list-metric-files", metavar="METRIC",
                         help="Tampilkan semua file yang skornya di bawah --metric-threshold untuk metrik tertentu, "
                              "misalnya 'negative_path', 'database_verification', 'domain_event', dll. "
                              "Menampilkan file dan skornya secara ascending.")
    parser.add_argument("--metric-threshold", type=float, default=70.0,
                         help="Ambang skor (0-100) untuk --list-metric-files. Default: 70.0")

    args = parser.parse_args()

    if args.self_test:
        return 0 if self_test(verbose=True) else 1

    project_root = pathlib.Path(args.root).resolve() if args.root else pathlib.Path(__file__).resolve().parent.parent
    extra_excludes_dirs = set(args.exclude.split(",")) if args.exclude else set()
    extra_excludes_files = set(args.exclude_files.split(",")) if args.exclude_files else set()
    ignore_metrics = set(args.ignore_metrics.split(",")) if args.ignore_metrics else set()

    checker = PytestQualityChecker(
        root=project_root, enable_rca=not args.no_rca, strict=args.strict,
        extra_excludes_dirs=extra_excludes_dirs,
        extra_excludes_files=extra_excludes_files,
        max_workers=args.max_workers, ignore_metrics=ignore_metrics,
    )

    progress = None
    if not args.no_progress:
        lock = threading.Lock()

        def _progress(current: int, total_: int):
            with lock:
                pct = (current / total_ * 100) if total_ > 0 else 0
                bar = "█" * int(pct / 2) + "░" * (50 - int(pct / 2))
                _safe_print(f"\r  [{bar}] {current}/{total_} ({pct:.1f}%)", end="", flush=True)
                if current >= total_:
                    _safe_print()
        progress = _progress

    report = checker.scan(progress_callback=progress)

    # Selalu cetak laporan utama
    print_report(report, verbose=args.verbose, show_rca=not args.no_rca, full=args.full)

    # Fitur per-file
    if args.per_file > 0:
        print_by_file_report(report, limit=args.per_file, threshold=args.per_file_threshold)

    # Fitur business-flow-gaps
    if args.business_flow_gaps:
        print_business_flow_gaps(report, threshold=args.business_flow_gaps_threshold)

    # BARU: list file per metrik
    if args.list_metric_files:
        print_metric_file_scores(report, args.list_metric_files, args.metric_threshold)

    if not args.dry_run:
        if args.json:
            save_json(report, pathlib.Path(args.json))
        if args.csv:
            save_csv(report, pathlib.Path(args.csv))
        if args.html:
            save_html(report, pathlib.Path(args.html))
        if args.sarif:
            save_sarif(report, pathlib.Path(args.sarif))
        if args.full_details:
            export_full_details(report, pathlib.Path(args.full_details))

    return 0 if report.passed else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        _safe_print(f"\n{_c('YELLOW')}⏹️  Interrupted by user.{_c('RESET')}")
        sys.exit(130)
