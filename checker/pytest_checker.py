#!/usr/bin/env python3
"""
checker/pytest_checker.py – Pytest Quality Checker (Hardened, Forensic-Grade)
================================================================================
Versi   : 5.1.7 (Fixed & Accurate)
Standar : ISO/IEC 25010-informed static analysis heuristics (bukan audit forensik resmi)

Perubahan v5.1.7:
- FIX (BUG NYATA, ditemukan dari run di proyek 2226 file sungguhan): _run_parallel()
  membungkus SELURUH blok ProcessPoolExecutor dengan satu except Exception. Kalau
  executor gagal SETELAH sebagian file sukses diproses (mis. satu worker crash),
  fallback-nya memproses ULANG SEMUA file secara serial TANPA mengosongkan hasil
  yang sudah terkumpul — file yang sudah sukses ikut terduplikasi. Paling kentara
  di parse_errors (list biasa, jadi 4 error unik tercetak 8x), tapi diam-diam juga
  menggandakan pekerjaan untuk source/test functions (untung di-dedup otomatis
  karena disimpan sebagai dict keyed by key). Sekarang results direset sebelum
  fallback serial dijalankan.
- IMPROVE: tampilan Duplicate Test di laporan --per-file dulu mencetak baris
  "anchor" yang sama berulang-ulang (bisa puluhan kali untuk copy-paste massal).
  Sekarang dikelompokkan jadi satu baris ringkas per anchor.
- FIX (BUG NYATA): print_by_file_report() punya default threshold=101.0 sehingga
  kondisi "score < threshold" SELALU True — file yang sudah 100% diperbaiki tetap
  dianggap bermasalah dan terus muncul di laporan. Diperbaiki ke 70.0, dan sekarang
  bisa diatur via --per-file-threshold.
- FIX (BUG NYATA, akar masalah "error yang sama muncul berulang"): changelog v5.1.6
  mengklaim "compute_weighted_score menggunakan cache" tapi klaim itu TIDAK BENAR —
  tidak ada cache sama sekali. assertion_quality(), duplicate_test_detector(), dan
  23 metode analyzer lain dipanggil ulang 2-3x dari scan(), test_strength_score(),
  dan compute_weighted_score(). Karena metode-metode ini menambah Finding lewat
  self._add_finding() sebagai efek samping, tiap panggilan ulang menduplikasi
  finding yang SAMA PERSIS. Sekarang benar-benar di-memoize per instance analyzer.
- FIX: build_file_grouped_report() tidak pernah menyertakan Tier 2 (Mock Quality,
  Duplicate Test) sama sekali, padahal fitur --per-file diklaim mencakup Tier 1-6.
- IMPROVE: print_by_file_report() sekarang SELALU menampilkan Tier 1 s.d. Tier 6
  untuk tiap file (termasuk tier yang sudah bersih, ditandai "Tidak ada isu
  terdeteksi"), bukan cuma tier yang kebetulan masih bermasalah.
- IMPROVE: --per-file kini bisa dipanggil tanpa angka untuk otomatis TOP 8 file.

Perubahan v5.1.6:
- FIX: duplicate_test_detector sekarang menggunakan struct_hash yang benar
- FIX: assertion_quality() mendeteksi assert x == True sebagai tidak meaningful
- FIX: negative_path_coverage mengecek pytest.raises/assertRaises secara real
- FIX: edge_case_detector lebih akurat
- FIX: compute_weighted_score menggunakan cache
- FIX: _normalized_dump() sekarang tidak skip root FunctionDef
- FIX: orphan_test_checker menggunakan real_calls (bukan calls gabungan)
- IMPROVE: idempotency_verification mendeteksi repeated call
- IMPROVE: database_verification keyword diperluas
- IMPROVE: RCA integration lebih spesifik
- NEW: opsi --per-file untuk menampilkan laporan per file (Tier 1–6 + baris)

"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import logging
import pathlib
import re
import sys
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


__version__ = "5.1.7"

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
EXCLUDED_DIRS_DEFAULT = {
    "checker", "migrations", "__pycache__", ".git", "docs", "scripts",
    "deployment", "monitoring", "reports", "venv", ".venv", "node_modules",
    "dist", "build", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".benchmarks",
    "erp_frontend", "logs", "audit_logs", "audit_reports", "rate_cache", "data",
}

EXCLUDED_FILES_DEFAULT = {
    "fix_bom.py", "generate_contracts.py", "real_test_generator.py",
    "create_first_admin.py", "manage.py", "app.py", "wsgi.py",
    "asgi.py", "setup.py", "conftest.py", "__init__.py",
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

    @property
    def passed(self) -> bool:
        return self.overall_quality_score >= 70.0


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
    """Dedupe parse_errors by file path, keeping the first occurrence.

    Root cause dari duplikasi lama sudah diperbaiki di _build_test_functions
    (lihat docstring-nya) dan di PytestQualityChecker.scan(). Fungsi ini
    adalah lapisan pengaman tambahan (defense-in-depth) supaya kalau pun ada
    jalur lain di masa depan yang menambahkan error untuk file yang sama dua
    kali, laporan akhir tetap menampilkan tiap file HANYA SEKALI.
    """
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
                parts.append(f"<{type(n.value).__name__}>")
                return
            if isinstance(n, ast.Name):
                return
            if isinstance(n, ast.Attribute):
                parts.append(n.attr)
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
        for p in param_names:
            if p in fixture_class_index:
                self.var_types[p] = fixture_class_index[p]

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

    def visit_Assert(self, node):
        self._record_assert(node)
        call_func_ids = {id(n.func) for n in ast.walk(node.test) if isinstance(n, ast.Call)}
        for n in ast.walk(node.test):
            if isinstance(n, ast.Attribute) and id(n) not in call_func_ids:
                self.raw_calls.append((n.value, n.attr, node.lineno))
                self._check_keyword_flags(n.attr)
            elif isinstance(n, ast.Name):
                self._check_keyword_flags(n.id)
        self.generic_visit(node)

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
                    if args and isinstance(args[0], ast.Name):
                        self.raises_targets.append(args[0].id)
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
        if low == "now" or low == "utcnow":
            self.has_datetime_now = True
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
                if node.args and isinstance(node.args[0], ast.Name):
                    self.raises_targets.append(node.args[0].id)
                elif node.args and isinstance(node.args[0], ast.Attribute):
                    self.raises_targets.append(node.args[0].attr)
        elif isinstance(node.func, ast.Name):
            attr = node.func.id
            self.raw_calls.append((None, attr, node.lineno))
            self.explicit_call_names.append(attr)
            if attr == "raises":
                self.has_raises = True
                if node.args and isinstance(node.args[0], ast.Name):
                    self.raises_targets.append(node.args[0].id)

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
    for d in excluded_dirs:
        if d in parts:
            return None
    filename = pathlib.Path(py_file).name
    if filename in excluded_files:
        return None
    if "tests" in parts or "test" in parts or filename.startswith(("test_", "conftest")):
        return "test"
    if "scripts" in parts or "deployment" in parts:
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
        self.bare_name_index: dict[str, list[str]] = defaultdict(list)
        self.module_exports_index: dict[str, dict[str, str]] = {}
        self.fixture_class_index: dict[str, str] = {}

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
            # BUGFIX: HARUS reset `results` sebelum fallback serial. Tanpa ini,
            # file yang sudah selesai diproses secara paralel (sebelum executor-nya
            # gagal, mis. karena satu worker crash) akan diproses ULANG dan
            # ditambahkan lagi ke `results`, menghasilkan entri dobel (paling
            # kentara di parse_errors, tapi sebenarnya terjadi di semua data).
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
                if sf.is_private:
                    continue
                if sf.class_name:
                    self.class_methods_index[f"{sf.class_name}.{sf.name}"].append(sf.key)
                self.bare_name_index[sf.name].append(sf.key)

        test_results = self._run_parallel(_parse_test_file, self.test_files, progress_callback, len(src_results), total)
        for r in test_results:
            if r.get("error"):
                self.parse_errors.append({"file": r["file"], "error": r["error"]})
                continue
            self.test_files_meta[r["file"]] = r
            for fx in r.get("fixtures", []):
                if fx["class_guess"]:
                    self.fixture_class_index[fx["name"]] = fx["class_guess"]

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
    """Bangun objek TestFunction dengan me-reparse tiap file test secara serial
    (dibutuhkan karena parse_all() berjalan di worker process yang hanya
    mengembalikan dict yang bisa di-pickle, bukan node ast.FunctionDef mentah
    yang dipakai TestFeatureVisitor di sini).

    PENTING: `already_failed_files` berisi rel-path file yang SUDAH diketahui
    gagal di-parse pada tahap 1 (parse_all -> _parse_test_file, lihat
    ProjectIndex.parse_errors). File yang sama, dengan isi yang sama, akan
    SELALU gagal dengan error yang SAMA PERSIS kalau di-parse ulang di sini --
    jadi kita skip total (bukan cuma skip pencatatan errornya) supaya tidak
    membuang waktu parsing yang hasilnya sudah pasti gagal, dan supaya
    parse_errors tidak pernah dobel dari 2 sumber independen untuk file yang
    sama.
    """
    test_functions: dict[str, TestFunction] = {}
    parse_errors: list[dict] = []
    already_failed_files = already_failed_files or set()
    total = len(index.test_files)
    for i, py_file in enumerate(index.test_files):
        rel = py_file.relative_to(index.root).as_posix()
        if rel in already_failed_files:
            # Sudah tercatat gagal di tahap 1 (parse_all). Jangan reparse,
            # jangan catat ulang -- itulah sumber duplikasi lama.
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

        def handle(node: ast.FunctionDef | ast.AsyncFunctionDef, class_prefix: str = ""):
            if not node.name.startswith("test_"):
                return
            param_names = [a.arg for a in node.args.args if a.arg != "self"]
            visitor = TestFeatureVisitor(imported_symbols, index.fixture_class_index, param_names)
            visitor.visit(node)
            resolved = _resolve_calls(visitor.raw_calls, visitor.var_types, imported_symbols, index)
            decorators = [_deco_name(d) for d in node.decorator_list]
            markers = [d for d in decorators if d]
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
                handle(node)
            elif isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        handle(child, class_prefix=f"{node.name}.")
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
    """
    BUGFIX (v5.1.6 changelog claimed this already existed — it did not):
    QualityAnalyzer metrics like assertion_quality(), duplicate_test_detector(), etc.
    are each invoked from THREE separate places (scan()'s tier dict construction,
    test_strength_score(), and compute_weighted_score()). Several of them append to
    self.findings via self._add_finding(...) as a side effect. Without memoization,
    every extra call re-appends the SAME finding, so the exact same error/line shows
    up duplicated (or triplicated) in reports, making already-fixed issues look like
    they're still outstanding. This decorator caches the result per-instance (per scan
    run) so each metric is computed exactly once, regardless of how many call sites use it.
    """
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

        elif metric_name == "database_verification":
            relevant_keys, _ = self._relevant_test_keys_for(lambda f: f.has_transaction)
            for t in self.test_funcs.values():
                if t.key not in relevant_keys:
                    continue
                score = 100.0 if (t.has_db or t.has_commit or t.has_rollback) else 0.0
                file_scores[t.file].append(score)

        elif metric_name == "domain_event_verification":
            relevant_keys, _ = self._relevant_test_keys_for(
                lambda f: f.has_outbox or f.has_kafka_publish or "event" in f.name.lower()
            )
            for t in self.test_funcs.values():
                if t.key not in relevant_keys:
                    continue
                score = 100.0 if t.has_event_assert else 0.0
                file_scores[t.file].append(score)

        elif metric_name == "audit_log_verification":
            relevant_keys, _ = self._relevant_test_keys_for(lambda f: "audit" in f.name.lower())
            for t in self.test_funcs.values():
                if t.key not in relevant_keys:
                    continue
                score = 100.0 if t.has_audit_assert else 0.0
                file_scores[t.file].append(score)

        elif metric_name == "idempotency_verification":
            relevant_keys, _ = self._relevant_test_keys_for(
                lambda f: f.has_transaction or f.has_outbox or f.has_kafka_publish or f.has_retry_logic
            )
            for t in self.test_funcs.values():
                if t.key not in relevant_keys:
                    continue
                has_id = "twice" in t.source.lower() or "idempotent" in t.source.lower() or "duplicate" in t.name.lower()
                score = 100.0 if has_id else 0.0
                file_scores[t.file].append(score)

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
        total = len(self.test_funcs)
        if total == 0:
            return {"score": 0, "has_error": 0, "total": 0, "confidence": "heuristic", "file_scores": {}}
        has_error_count = 0
        for t in self.test_funcs.values():
            has_raises_call = t.has_raises
            if not has_raises_call and t.source:
                has_raises_call = bool(re.search(r'pytest\.raises|assertRaises|raises\(', t.source))
            has_error_keyword = any(kw in t.name.lower() for kw in ("error", "invalid", "exception", "fail", "bad", "reject"))
            if has_raises_call or has_error_keyword:
                has_error_count += 1
        score = (has_error_count / total) * 100
        result = {"score": round(score, 1), "has_error": has_error_count, "total": total, "confidence": "heuristic"}
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
            return {"score": 0, "avg_mock": 0, "confidence": "heuristic"}
        mock_count = sum(1 for t in self.test_funcs.values() if t.has_mock)
        avg_mock = mock_count / max(1, total)
        if avg_mock <= 0.3:
            mock_score = 100
        elif avg_mock <= 0.6:
            mock_score = 85
        else:
            mock_score = 65
        has_spec = sum(1 for t in self.test_funcs.values() if "spec" in t.source.lower() or "autospec" in t.source.lower())
        bonus = min(15, (has_spec / max(1, total)) * 15)
        score = min(100, mock_score + bonus)
        result = {"score": round(score, 1), "mock_count": mock_count, "avg_mock": round(avg_mock, 2), "has_spec": has_spec, "confidence": "heuristic"}
        result["file_scores"] = self._file_metric_scores("mock_quality")
        return result

    @_memoize_analyzer_method
    def fixture_quality(self) -> dict:
        fixtures = []
        for t in self.test_funcs.values():
            fixtures.extend(t.setup_fixtures)
        unique = set(fixtures)
        total = len(fixtures)
        heavy = sorted({f for f in unique if "db" in f or "session" in f or "client" in f})
        score = 100.0 if total == 0 else min(100, (len(unique) / total) * 100)
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
        good = bad = 0
        for t in self.test_funcs.values():
            if re.match(r'test_[a-z0-9]+(_[a-z0-9]+){2,}', t.name):
                good += 1
            elif re.match(r'test_[a-z0-9]+_[a-z0-9]+', t.name):
                good += 0.5
            else:
                bad += 1
        total = len(self.test_funcs)
        score = (good / max(1, total)) * 100
        return {"score": round(score, 1), "good": int(good), "bad": bad, "confidence": "heuristic"}

    @_memoize_analyzer_method
    def aaa_pattern(self) -> dict:
        count_aaa = 0
        for t in self.test_funcs.values():
            has_arrange = bool(t.setup_fixtures) or any(w in t.source.lower() for w in ("=", "given"))
            has_act = any(bn in ("execute", "handle", "call", "run", "process") for _, bn, _ in []) or bool(t.calls)
            has_assert = bool(t.assertions)
            if has_arrange and has_act and has_assert:
                count_aaa += 1
        total = len(self.test_funcs)
        score = (count_aaa / max(1, total)) * 100
        return {"score": round(score, 1), "count": count_aaa, "total": total, "confidence": "heuristic"}

    def _relevant_test_keys_for(self, predicate) -> tuple[set[str], list]:
        """Sama seperti pola yang sudah benar di _domain_metric (Tier 4): saring
        dulu ke source function yang predicate-nya True, lalu ambil test yang
        BENAR-BENAR ter-link ke fungsi itu (tested_by_direct/unique). Dipakai
        untuk memperbaiki Tier 3 (database/event/audit/idempotency) yang
        sebelumnya menilai SEMUA test tanpa pandang bulu -- termasuk test DTO/
        value-object yang memang tidak seharusnya menyentuh DB/event/audit sama
        sekali, sehingga skor Tier 3 turun bukan karena kualitas test buruk,
        tapi karena metrik diterapkan ke tempat yang tidak relevan.
        """
        relevant_sources = [f for f in self.source_funcs.values() if predicate(f)]
        relevant_keys: set[str] = set()
        for sf in relevant_sources:
            relevant_keys |= sf.tested_by_direct | sf.tested_by_unique
        return relevant_keys, relevant_sources

    @_memoize_analyzer_method
    def database_verification(self) -> dict:
        relevant_keys, relevant_sources = self._relevant_test_keys_for(lambda f: f.has_transaction)
        if not relevant_sources:
            return {"score": 100.0, "has_db": 0, "total": 0, "confidence": "confirmed",
                     "note": "Tidak ada source function dengan operasi transaksi/DB (has_transaction) -- N/A untuk scope ini.",
                     "file_scores": {}}
        relevant_tests = [self.test_funcs[k] for k in relevant_keys if k in self.test_funcs]
        if not relevant_tests:
            return {"score": 0.0, "has_db": 0, "total": 0, "confidence": "heuristic",
                     "note": f"{len(relevant_sources)} source function melakukan operasi DB, tapi tidak ada test yang ter-link ke fungsi tersebut.",
                     "file_scores": {}}
        has_db = sum(1 for t in relevant_tests if t.has_db or t.has_commit or t.has_rollback)
        total = len(relevant_tests)
        result = {"score": round((has_db / total) * 100, 1), "has_db": has_db, "total": total,
                   "relevant_source_functions": len(relevant_sources), "confidence": "heuristic"}
        result["file_scores"] = self._file_metric_scores("database_verification")
        return result

    @_memoize_analyzer_method
    def domain_event_verification(self) -> dict:
        pred = lambda f: f.has_outbox or f.has_kafka_publish or "event" in f.name.lower()
        relevant_keys, relevant_sources = self._relevant_test_keys_for(pred)
        if not relevant_sources:
            return {"score": 100.0, "has_event": 0, "total": 0, "confidence": "confirmed",
                     "note": "Tidak ada source function terkait domain event (outbox/kafka/nama mengandung 'event') -- N/A untuk scope ini.",
                     "file_scores": {}}
        relevant_tests = [self.test_funcs[k] for k in relevant_keys if k in self.test_funcs]
        if not relevant_tests:
            return {"score": 0.0, "has_event": 0, "total": 0, "confidence": "heuristic",
                     "note": f"{len(relevant_sources)} source function terkait domain event, tapi tidak ada test yang ter-link ke fungsi tersebut.",
                     "file_scores": {}}
        has_event = sum(1 for t in relevant_tests if t.has_event_assert)
        total = len(relevant_tests)
        result = {"score": round((has_event / total) * 100, 1), "has_event": has_event, "total": total,
                   "relevant_source_functions": len(relevant_sources), "confidence": "heuristic"}
        result["file_scores"] = self._file_metric_scores("domain_event_verification")
        return result

    @_memoize_analyzer_method
    def audit_log_verification(self) -> dict:
        pred = lambda f: "audit" in f.name.lower()
        relevant_keys, relevant_sources = self._relevant_test_keys_for(pred)
        if not relevant_sources:
            return {"score": 100.0, "has_audit": 0, "total": 0, "confidence": "confirmed",
                     "note": "Tidak ada source function terkait audit (nama mengandung 'audit') -- N/A untuk scope ini.",
                     "file_scores": {}}
        relevant_tests = [self.test_funcs[k] for k in relevant_keys if k in self.test_funcs]
        if not relevant_tests:
            return {"score": 0.0, "has_audit": 0, "total": 0, "confidence": "heuristic",
                     "note": f"{len(relevant_sources)} source function terkait audit, tapi tidak ada test yang ter-link ke fungsi tersebut.",
                     "file_scores": {}}
        has_audit = sum(1 for t in relevant_tests if t.has_audit_assert)
        total = len(relevant_tests)
        result = {"score": round((has_audit / total) * 100, 1), "has_audit": has_audit, "total": total,
                   "relevant_source_functions": len(relevant_sources), "confidence": "heuristic"}
        result["file_scores"] = self._file_metric_scores("audit_log_verification")
        return result

    @_memoize_analyzer_method
    def idempotency_verification(self) -> dict:
        # Idempotency paling relevan untuk operasi yang mutasi state & bisa
        # di-retry/di-replay: transaksi DB, outbox, publish kafka, dan apa pun
        # yang sudah punya retry logic.
        pred = lambda f: f.has_transaction or f.has_outbox or f.has_kafka_publish or f.has_retry_logic
        relevant_keys, relevant_sources = self._relevant_test_keys_for(pred)
        if not relevant_sources:
            return {"score": 100.0, "count": 0, "total": 0, "confidence": "confirmed",
                     "note": "Tidak ada source function yang mutasi state / retry-sensitive -- N/A untuk scope ini.",
                     "file_scores": {}}
        relevant_tests = [self.test_funcs[k] for k in relevant_keys if k in self.test_funcs]
        if not relevant_tests:
            return {"score": 0.0, "count": 0, "total": 0, "confidence": "heuristic",
                     "note": f"{len(relevant_sources)} source function retry/mutasi-sensitive, tapi tidak ada test yang ter-link ke fungsi tersebut.",
                     "file_scores": {}}
        count = 0
        for t in relevant_tests:
            has_keyword = ("twice" in t.source.lower() or "idempotent" in t.source.lower()
                            or "duplicate" in t.name.lower())
            has_repeated_call = False
            if len(t.calls) >= 2:
                seen: dict[str, int] = {}
                for c in t.calls:
                    seen[c] = seen.get(c, 0) + 1
                has_repeated_call = any(n >= 2 for c, n in seen.items() if c not in ("assert_called", "raises"))
            if has_keyword or has_repeated_call:
                count += 1
        total = len(relevant_tests)
        result = {"score": round((count / total) * 100, 1), "count": count, "total": total,
                   "relevant_source_functions": len(relevant_sources), "confidence": "heuristic"}
        result["file_scores"] = self._file_metric_scores("idempotency_verification")
        return result

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
            linking_tests = sf.tested_by_direct | sf.tested_by_unique
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
        missing_marker = [t for t in async_tests if "asyncio" not in " ".join(t.decorators).lower() and "anyio" not in " ".join(t.decorators).lower()]
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
            if any("status" in a.raw for t_key in linking for a in self.test_funcs.get(t_key, TestFunction("", "", "", 0, 0, 0)).assertions):
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

        def get_score(method_name):
            try:
                result = getattr(self, method_name)()
                if isinstance(result, dict) and "score" in result:
                    return result["score"]
                if method_name == "permission_test":
                    return min(100, len(result.get("roles", [])) / 5 * 100)
                return 0
            except Exception:
                return 0

        t1_names = ["assertion_quality", "negative_path_coverage", "exception_coverage", "edge_case_detector", "magic_number_detector"]
        t1_scores = [get_score(n) for n in t1_names if n not in ignore]
        tier1_avg = sum(t1_scores) / len(t1_scores) if t1_scores else 0

        t2_names = ["mock_quality", "fixture_quality", "duplicate_test_detector", "test_naming", "aaa_pattern"]
        t2_scores = [get_score(n) for n in t2_names if n not in ignore]
        tier2_avg = sum(t2_scores) / len(t2_scores) if t2_scores else 0

        t3_names = ["database_verification", "domain_event_verification", "audit_log_verification", "idempotency_verification", "permission_test"]
        t3_scores = [get_score(n) for n in t3_names if n not in ignore]
        tier3_avg = sum(t3_scores) / len(t3_scores) if t3_scores else 0

        t4_names = ["accounting_checker", "inventory_checker", "fiscal_period_checker", "multi_currency_checker", "precision_checker"]
        t4_scores = [get_score(n) for n in t4_names if n not in ignore]
        tier4_avg = sum(t4_scores) / len(t4_scores) if t4_scores else 0

        tier5_avg = self.mutation_score_estimation()[0]

        flaky = self.flaky_test_detector()["count"]
        slow = self.slow_test_detector()["count"]
        dead = self.dead_code_test_detector()["count"]
        orphan = self.orphan_test_checker()["orphans"]
        total_tests = max(1, len(self.test_funcs))
        penalty = (flaky + slow + dead + orphan) / total_tests * 50
        tier6_score = max(0, 100 - penalty)

        weights = {"tier1": 0.40, "tier2": 0.25, "tier3": 0.15, "tier4": 0.10, "tier5": 0.05, "tier6": 0.05}
        total = (tier1_avg * weights["tier1"] + tier2_avg * weights["tier2"] + tier3_avg * weights["tier3"]
                 + tier4_avg * weights["tier4"] + tier5_avg * weights["tier5"] + tier6_score * weights["tier6"])
        return round(min(100, total), 1)

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
        # File yang sudah gagal di tahap 1 (parse_all) TIDAK dikirim ulang ke
        # _build_test_functions -- lihat docstring _build_test_functions untuk
        # penjelasan root cause duplikasi parse_errors yang lama.
        already_failed = {e["file"] for e in self.index.parse_errors}
        test_funcs, extra_errors = _build_test_functions(self.index, already_failed_files=already_failed)
        # Defense-in-depth: dedupe by file path saat merge, walau secara desain
        # extra_errors seharusnya sudah tidak overlap dengan already_failed lagi.
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
        reg_risk = analyzer.regression_risk()
        t5 = {
            "mutation_score": round(mut_score, 1),
            "mutation_points_covered": round(mut_covered, 1),
            "mutation_points_total": round(mut_total, 1),
            "test_strength": strength,
            "confidence_score": round(confidence, 1),
            "business_flow": flow,
            "business_flow_summary": analyzer.business_flow_summary(),
            "regression_risk": reg_risk,
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

        overall_score = analyzer.compute_weighted_score(ignore_metrics=self.ignore_metrics)

        rca_results = []
        if self.enable_rca:
            checks = [
                ("Assertion Quality", t1["assertion_quality"]["score"]),
                ("Exception Coverage", t1["exception_coverage"]["score"]),
                ("State Transition", t6["state_transition"]["score"]),
                ("Mutation Score", t5["mutation_score"]),
            ]
            for name, score in checks:
                if score < 50:
                    try:
                        raise RuntimeError(f"Low {name} score: {score}%")
                    except RuntimeError as e:
                        rca = _rca_analyze(e, {"metric": name, "score": score})
                        if rca:
                            rca_results.append({"metric": name, "score": score, "rca": rca})

        direct_count = sum(1 for f in self.index.source_functions.values() if f.tested_by_direct)
        unique_count = sum(1 for f in self.index.source_functions.values() if not f.tested_by_direct and f.tested_by_unique)

        report = Report(
            total_tests=len(test_funcs),
            total_source_functions=len(self.index.source_functions),
            tested_functions=len(tested_funcs),
            tested_functions_direct=direct_count,
            tested_functions_unique=unique_count,
            untested_functions=len(untested_funcs),
            overall_quality_score=overall_score,
            tier1=t1, tier2=t2, tier3=t3, tier4=t4, tier5=t5, tier6=t6,
            scan_time=time.monotonic() - t0,
            rca_results=rca_results,
            parse_errors=_dedupe_parse_errors(self.index.parse_errors),
            findings=analyzer.findings,
            top_offending_files=analyzer.top_offending_files(),
            source_functions=list(self.index.source_functions.values()),
            test_functions=list(test_funcs.values()),
        )
        return report


# ─── REPORT PRINTING ───────────────────────────────────────────────────────
def print_report(r: Report, verbose: bool = False, show_rca: bool = True, full: bool = False) -> None:
    c = COLOR

    def score_color(v: float) -> str:
        return c["GREEN"] if v >= 70 else c["YELLOW"] if v >= 40 else c["RED"]

    def print_file_issues(label: str, data: dict, threshold: float = 70.0, limit: int = 40):
        scores = data.get("file_scores")
        if not scores:
            return
        bad = [(f, s) for f, s in scores.items() if s < threshold]
        if not bad:
            return
        bad.sort(key=lambda x: x[1])
        total = len(bad)
        _safe_print(f"    {_c('RED')}⚠️ {total} file bermasalah (skor < {threshold:.0f}%){_c('RESET')}")
        for idx, (f, s) in enumerate(bad[:limit]):
            _safe_print(f"      - {f}: {s:.1f}%")
        if total > limit:
            _safe_print(f"      ... dan {total - limit} file lainnya")

    _safe_print(f"\n{c['BOLD']}{c['CYAN']}╔{'═'*76}╗{c['RESET']}")
    _safe_print(f"{c['BOLD']}{c['CYAN']}║{c['RESET']}{c['BOLD']}   PYTEST QUALITY CHECKER v{__version__} (Forensic-Grade){' '*17}{c['CYAN']}║{c['RESET']}")
    _safe_print(f"{c['BOLD']}{c['CYAN']}╚{'═'*76}╝{c['RESET']}\n")

    sc = score_color(r.overall_quality_score)
    _safe_print(f"📊 {c['BOLD']}OVERALL QUALITY SCORE{c['RESET']}: {sc}{r.overall_quality_score:.1f}/100{c['RESET']}")
    _safe_print(f"  🎯 Confidence Score          : {r.tier5.get('confidence_score', 0):.1f}%")
    _safe_print(f"  🧪 Total Tests Found         : {r.total_tests}")
    _safe_print(f"  📄 Total Source Functions    : {r.total_source_functions}")
    _safe_print(f"  ✅ Tested (direct match)     : {r.tested_functions_direct}")
    _safe_print(f"  🟡 Tested (unique-name match): {r.tested_functions_unique}")
    _safe_print(f"  ❌ Untested Functions        : {r.untested_functions}")
    _safe_print(f"  ⏱️  Scan time                 : {r.scan_time:.2f}s")
    _safe_print(f"  RCA Engine                   : {'✅ Active' if show_rca and _RCA_AVAILABLE else '⚪ Fallback (heuristic only)'}")
    if r.parse_errors:
        _safe_print(f"  {c['RED']}⚠️  Parse errors               : {len(r.parse_errors)} file(s) gagal di-parse{c['RESET']}")
        if full or verbose:
            for e in r.parse_errors:
                _safe_print(f"      - {e['file']}: {e['error']}")
        else:
            for e in r.parse_errors[:40]:
                _safe_print(f"      - {e['file']}: {e['error']}")
            if len(r.parse_errors) > 40:
                _safe_print(f"      ... and {len(r.parse_errors)-40} more")

    def print_tier(title: str, data: dict, keys: list[tuple[str, str]]):
        _safe_print(f"\n{c['BOLD']}─── {title} ───{c['RESET']}")
        for label, key in keys:
            d = data.get(key, {})
            score = d.get("score")
            conf = d.get("confidence", "")
            conf_tag = f" {c['DIM']}[{conf}]{c['RESET']}" if conf else ""
            if score is not None:
                _safe_print(f"  {label:<24}: {score_color(score)}{score:.1f}%{c['RESET']}{conf_tag}")
                if score < 70:
                    print_file_issues(label, d)
            if full and "details" in d and d["details"]:
                _safe_print(f"    {c['DIM']}Details (total {len(d['details'])}):{c['RESET']}")
                for item in d["details"][:40]:
                    _safe_print(f"      - {item}")
                if len(d["details"]) > 40:
                    _safe_print(f"      ... and {len(d['details'])-40} more")

    print_tier("TIER 1 (Wajib)", r.tier1, [
        ("Assertion Quality", "assertion_quality"), ("Negative Path", "negative_path"),
        ("Exception Coverage", "exception_coverage"), ("Edge Case", "edge_case"), ("Magic Number", "magic_number"),
    ])
    print_tier("TIER 2 (Mock & Structure)", r.tier2, [
        ("Mock Quality", "mock_quality"), ("Duplicate Test", "duplicate_test"),
        ("Test Naming", "test_naming"), ("AAA Pattern", "aaa_pattern"),
    ])
    _safe_print(f"  {'Fixture Quality':<24}: {r.tier2['fixture_quality']['unique']} unique fixtures {c['DIM']}[heuristic]{c['RESET']}")
    dup_data = r.tier2['duplicate_test']
    _safe_print(f"  {'Duplicate pairs found':<24}: {dup_data['duplicates']}")
    if full and dup_data['details']:
        _safe_print(f"    {c['DIM']}All duplicate pairs:{c['RESET']}")
        for pair in dup_data['details'][:50]:
            _safe_print(f"      - {pair[0]} <-> {pair[1]} (hash: {pair[2]})")
        if len(dup_data['details']) > 50:
            _safe_print(f"      ... and {len(dup_data['details'])-50} more")

    print_tier("TIER 3 (Integration)", r.tier3, [
        ("Database Verification", "database_verification"), ("Domain Event", "domain_event"),
        ("Audit Log", "audit_log"), ("Idempotency", "idempotency"),
    ])
    _safe_print(f"  {'Permission Test':<24}: {r.tier3['permission_test']['unique_roles']} roles detected {c['DIM']}[heuristic]{c['RESET']}")

    print_tier("TIER 4 (ERP Specific — confirmed via call-graph)", r.tier4, [
        ("Accounting", "accounting"), ("Inventory", "inventory"), ("Fiscal Period", "fiscal_period"),
        ("Multi Currency", "multi_currency"), ("Precision (Decimal)", "precision"),
    ])
    if full or verbose:
        for label, key in [("Accounting", "accounting"), ("Inventory", "inventory"), ("Fiscal Period", "fiscal_period"),
                            ("Multi Currency", "multi_currency"), ("Precision", "precision")]:
            d = r.tier4[key]
            if d.get("untested_sample"):
                _safe_print(f"    {c['DIM']}{label} — belum tertest (total {len(d['untested_sample'])}):{c['RESET']}")
                for u in d["untested_sample"][:40]:
                    _safe_print(f"      - {u}")
                if len(d["untested_sample"]) > 40:
                    _safe_print(f"      ... and {len(d['untested_sample'])-40} more")

    t5 = r.tier5
    _safe_print(f"\n{c['BOLD']}─── TIER 5 (Advanced) ───{c['RESET']}")
    _safe_print(f"  🧬 Mutation Score (estimasi statis, BUKAN mutation testing sungguhan): {score_color(t5['mutation_score'])}{t5['mutation_score']:.1f}%{c['RESET']}")
    _safe_print(f"  📈 Test Strength       : {t5['test_strength']:.1f}%")
    _safe_print(f"  🎯 Confidence          : {t5['confidence_score']:.1f}%")

    flow_sum = t5["business_flow_summary"]
    _safe_print(f"\n{c['BOLD']}─── BUSINESS FLOW COVERAGE (di-discover dari struktur repo Anda — bukan daftar generik) ───{c['RESET']}")
    for module, data in sorted(flow_sum.items(), key=lambda kv: kv[1]["pct"]):
        col = c["GREEN"] if data["pct"] >= 80 else c["YELLOW"] if data["pct"] >= 50 else c["RED"]
        _safe_print(f"  {module:<28} {col}{data['pct']:>5.1f}%{c['RESET']} ({data['covered']}/{data['total']})")

    if full or verbose:
        _safe_print(f"\n{c['DIM']}─── Missing Flow Functions (fungsi domain yang belum ada test-nya, dgn lokasi) ───{c['RESET']}")
        flow_detail = t5["business_flow"]
        for module, data in flow_detail.items():
            if data["pct"] < 80 and data["missing_functions"]:
                _safe_print(f"  {c['YELLOW']}{module}{c['RESET']}:")
                for mf in data["missing_functions"][:40]:
                    _safe_print(f"      - {mf}")
                if len(data["missing_functions"]) > 40:
                    _safe_print(f"      ... and {len(data['missing_functions'])-40} more")

    t6 = r.tier6
    _safe_print(f"\n{c['BOLD']}─── TIER 6 (Issues & Smells) ───{c['RESET']}")
    if t6["flaky_tests"]["count"] > 0:
        _safe_print(f"  {c['RED']}⚠️ Flaky tests (confirmed): {t6['flaky_tests']['count']}{c['RESET']}")
        if full:
            for d in t6["flaky_tests"]["details"]:
                _safe_print(f"      - {d}")
        else:
            for d in t6["flaky_tests"]["details"][:40]:
                _safe_print(f"      - {d}")
            if len(t6["flaky_tests"]["details"]) > 40:
                _safe_print(f"      ... and {len(t6['flaky_tests']['details'])-40} more")
    if t6["slow_tests"]["count"] > 0:
        _safe_print(f"  {c['YELLOW']}⚠️ Slow tests (time.sleep): {t6['slow_tests']['count']}{c['RESET']}")
        if full:
            for d in t6["slow_tests"]["details"]:
                _safe_print(f"      - {d}")
    if t6["dead_code"]["count"] > 0:
        _safe_print(f"  {c['RED']}❌ Dead test code (confirmed, no assertion/call): {t6['dead_code']['count']}{c['RESET']}")
        if full:
            for d in t6["dead_code"]["details"]:
                _safe_print(f"      - {d}")
        else:
            for d in t6["dead_code"]["details"][:40]:
                _safe_print(f"      - {d}")
            if len(t6["dead_code"]["details"]) > 40:
                _safe_print(f"      ... and {len(t6['dead_code']['details'])-40} more")
    if t6["orphan_tests"]["orphans"] > 0:
        _safe_print(f"  {c['YELLOW']}⚠️ Orphan tests (tidak menyentuh source function manapun): {t6['orphan_tests']['orphans']}{c['RESET']}")
        if full:
            for d in t6["orphan_tests"]["details"][:50]:
                _safe_print(f"      - {d}")
            if len(t6["orphan_tests"]["details"]) > 50:
                _safe_print(f"      ... and {len(t6['orphan_tests']['details'])-50} more")
        else:
            for d in t6["orphan_tests"]["details"][:40]:
                _safe_print(f"      - {d}")
            if len(t6["orphan_tests"]["details"]) > 40:
                _safe_print(f"      ... and {len(t6['orphan_tests']['details'])-40} more")
    if t6["untested_functions"]:
        _safe_print(f"  {c['RED']}❌ Untested functions: {len(t6['untested_functions'])}{c['RESET']}")
        if full:
            for f in t6["untested_functions"][:50]:
                _safe_print(f"      - {f}")
            if len(t6["untested_functions"]) > 50:
                _safe_print(f"      ... and {len(t6['untested_functions'])-50} more")
        else:
            for f in t6["untested_functions"][:40]:
                _safe_print(f"      - {f}")
            if len(t6["untested_functions"]) > 40:
                _safe_print(f"      ... and {len(t6['untested_functions'])-40} more")
    if t6["test_smells"]:
        _safe_print(f"  {c['YELLOW']}⚠️ Test smells: {len(t6['test_smells'])}{c['RESET']}")
        by_type = defaultdict(int)
        for s in t6["test_smells"]:
            by_type[s["type"]] += 1
        for stype, n in sorted(by_type.items(), key=lambda kv: -kv[1]):
            _safe_print(f"      - {stype}: {n}")
        if full:
            for s in t6["test_smells"]:
                _safe_print(f"        {s['file']}:{s['lineno']} — {s['detail']}")
        else:
            for s in t6["test_smells"][:8]:
                _safe_print(f"        {s['file']}:{s['lineno']} — {s['detail']}")
            if len(t6["test_smells"]) > 8:
                _safe_print(f"        ... and {len(t6['test_smells'])-8} more")
    if t6["state_transition"]["score"] < 80:
        _safe_print(f"  {c['YELLOW']}⚠️ State transition score: {t6['state_transition']['score']:.1f}% ({t6['state_transition']['tested']}/{t6['state_transition']['total_trans']} confirmed){c['RESET']}")
    if t6["event_consistency"]["score"] < 70:
        _safe_print(f"  {c['YELLOW']}⚠️ Event consistency score: {t6['event_consistency']['score']:.1f}%{c['RESET']}")

    if r.top_offending_files:
        _safe_print(f"\n{c['RED']}⚠️ TOP OFFENDING FILES (paling banyak fungsi belum ditest):{c['RESET']}")
        for row in r.top_offending_files[:40]:
            gap = row["functions"] - row["tested_functions"]
            _safe_print(f"  {row['file']}: {row['risk']} risk — {row['tested_functions']}/{row['functions']} functions tested ({gap} belum), LOC={row['loc']}")

    if show_rca and r.rca_results:
        _safe_print(f"\n{c['MAGENTA']}🔍 RCA Analysis:{c['RESET']}")
        for rr in r.rca_results:
            _safe_print(f"  {rr['metric']}: score={rr['score']}%")
            rc = rr["rca"].get("root_cause", "")
            fix = rr["rca"].get("suggested_fix", "")
            if rc:
                _safe_print(f"    Root cause: {rc[:120]}")
            if fix:
                _safe_print(f"    Fix: {fix[:120]}")

    _safe_print(f"\n{c['BOLD']}─── RECOMMENDATIONS ───{c['RESET']}")
    recs = []
    if r.tier1["assertion_quality"]["score"] < 70:
        recs.append(f"🔧 {r.tier1['assertion_quality']['bad']} test punya assertion lemah/kosong. Ganti assert truthy generik dengan assert nilai spesifik (==, in, raises).")
    if t5["mutation_score"] < 70:
        recs.append("🔧 Mutation Score (estimasi) rendah. Perkuat assertion pada nilai/status/length, bukan hanya cek 'tidak error'.")
    if t6["state_transition"]["score"] < 80 and t6["state_transition"]["total_trans"] > 0:
        recs.append(f"🔧 {t6['state_transition']['total_trans'] - t6['state_transition']['tested']} status-transition function belum diverifikasi perubahan status-nya secara eksplisit.")
    if r.tier2["duplicate_test"]["duplicates"] > 0:
        recs.append(f"🔧 {r.tier2['duplicate_test']['duplicates']} pasang test terdeteksi duplikat struktural — cek apakah itu copy-paste yang perlu di-parametrize saja.")
    if t6["flaky_tests"]["count"] > 0:
        recs.append(f"🔧 {t6['flaky_tests']['count']} test berpotensi flaky (sleep/random/datetime.now tanpa mock). Mock dependency waktu/random.")
    if r.untested_functions > 0:
        recs.append(f"🔧 {r.untested_functions} function source tidak terhubung ke test manapun (langsung/unik). Lihat 'TOP OFFENDING FILES' di atas untuk prioritas.")
    if not recs:
        recs.append("✅ Tidak ada rekomendasi kritis — kualitas test sudah di atas ambang batas pada seluruh tier.")
    for rec in recs:
        _safe_print(f"  {c['YELLOW']}{rec}{c['RESET']}")

    _safe_print(f"\n{c['BOLD']}─── WEIGHTED SCORE BREAKDOWN ───{c['RESET']}")

    def _safe_tier_average(tier_dict):
        scores = []
        for key, value in tier_dict.items():
            if isinstance(value, dict):
                if "score" in value:
                    scores.append(value["score"])
                elif key == "permission_test":
                    scores.append(min(100, len(value.get("roles", [])) / 5 * 100))
        return sum(scores) / len(scores) if scores else 0

    t1_avg = _safe_tier_average(r.tier1)
    t2_avg = _safe_tier_average(r.tier2)
    t3_avg = _safe_tier_average(r.tier3)
    t4_avg = _safe_tier_average(r.tier4)
    t5_avg = r.tier5.get("mutation_score", 0)
    flaky = t6.get("flaky_tests", {}).get("count", 0)
    slow = t6.get("slow_tests", {}).get("count", 0)
    dead = t6.get("dead_code", {}).get("count", 0)
    orphan = t6.get("orphan_tests", {}).get("orphans", 0)
    total_tests = max(1, r.total_tests)
    penalty = (flaky + slow + dead + orphan) / total_tests * 50
    t6_score = max(0, 100 - penalty)

    _safe_print(f"  Tier1 (40%): {t1_avg:.1f}")
    _safe_print(f"  Tier2 (25%): {t2_avg:.1f}")
    _safe_print(f"  Tier3 (15%): {t3_avg:.1f}")
    _safe_print(f"  Tier4 (10%): {t4_avg:.1f}")
    _safe_print(f"  Tier5 ( 5%): {t5_avg:.1f}")
    _safe_print(f"  Tier6 ( 5%): {t6_score:.1f} (penalti)")
    _safe_print(f"\n{c['DIM']}Legend: [confirmed] = dibuktikan langsung dari struktur AST (pasti).{c['RESET']}")
    _safe_print(f"{c['DIM']}        [heuristic] = deteksi berbasis pola/kata kunci, verifikasi manual disarankan.{c['RESET']}")


# ─── NEW: LAPORAN PER FILE ────────────────────────────────────────────────
def print_by_file_report(report: Report, limit: int = 8, threshold: float = 70.0) -> None:
    """
    Cetak laporan per file, dikelompokkan per Tier 1-6, untuk sejumlah file teratas
    yang memiliki paling banyak issue.

    Untuk tiap file, SEMUA 6 tier ditampilkan secara eksplisit (Tier 1 ... Tier 6),
    termasuk tier yang tidak punya masalah (ditandai "Tidak ada isu terdeteksi"),
    supaya progres perbaikan tiap tier terlihat jelas.

    threshold: ambang skor per-metrik (0-100). Hanya metrik dengan skor DI BAWAH
    threshold ini yang dianggap masih bermasalah dan ditampilkan. File/metrik yang
    sudah diperbaiki (skornya naik >= threshold) otomatis tidak akan muncul lagi
    di sini pada scan berikutnya.
    """
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

        # Kelompokkan tier_scores dan lines per nomor Tier (1..6), supaya SETIAP
        # file selalu menampilkan Tier 1 s.d. Tier 6, walau sebagian kosong.
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

    # BUGFIX: blok Tier 2 sebelumnya tidak ada sama sekali di sini, sehingga
    # laporan per-file selalu "bolong" di Tier 2 walau di dokumentasi disebut Tier 1-6.
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
            "overall_quality_score": report.overall_quality_score,
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
                {"rule": f.rule, "severity": f.severity, "message": f.message, "file": f.file, "line": f.lineno, "confidence": f.confidence}
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
    check("Normalized dump ignores literal values/names (structural duplicate hash)", h1 == h2, f"{h1} vs {h2}")
    h3 = _normalized_dump(ast.parse("assert x != 5").body[0])
    check("Normalized dump distinguishes different operators", h1 != h3, f"{h1} vs {h3}")

    check("Dotted module path conversion works", _dotted_module_path("domain/journal/entities.py") == "domain.journal.entities")
    check("Domain discovery works for domain/ files", _discover_domain("domain/fixed_asset/entity.py") == "fixed_asset")
    check("Domain discovery returns empty for non-domain files", _discover_domain("application/use_cases/foo.py") == "")

    fn_a = ast.parse("def test_a():\n    assert x == 5\n").body[0]
    fn_b = ast.parse("def test_b():\n    assert y == 999\n").body[0]
    fn_c = ast.parse("def test_c():\n    assert x is not None\n").body[0]
    hash_a, hash_b, hash_c = _normalized_dump(fn_a), _normalized_dump(fn_b), _normalized_dump(fn_c)
    check("normalized_dump on root FunctionDef is not just 'FunctionDef'", hash_a != "FunctionDef", hash_a)
    check("normalized_dump treats structurally-identical test bodies as equal", hash_a == hash_b, f"{hash_a} vs {hash_b}")
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
    # MODIFIKASI: tambahkan opsi --per-file
    parser.add_argument("--per-file", type=int, nargs="?", const=8, default=0,
                         help="Tampilkan laporan per file (Tier 1-6 + baris) untuk N file teratas. "
                              "Panggil tanpa angka untuk TOP 8 (default). 0/tidak dipakai = nonaktif.")
    parser.add_argument("--per-file-threshold", type=float, default=70.0,
                         help="Ambang skor (0-100) untuk laporan --per-file. Metrik dengan skor DI BAWAH "
                              "nilai ini dianggap masih bermasalah; metrik yang sudah >= nilai ini dianggap "
                              "sudah diperbaiki dan tidak akan muncul lagi. Default: 70.0")
    parser.add_argument("--version", action="version", version=f"pytest_checker v{__version__}")

    args = parser.parse_args()

    if args.self_test:
        return 0 if self_test(verbose=True) else 1

    project_root = pathlib.Path(__file__).resolve().parent.parent
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
    print_report(report, verbose=args.verbose, show_rca=not args.no_rca, full=args.full)

    # MODIFIKASI: cetak laporan per file jika diminta
    if args.per_file > 0:
        print_by_file_report(report, limit=args.per_file, threshold=args.per_file_threshold)

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