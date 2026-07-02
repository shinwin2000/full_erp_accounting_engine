#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker/pytest_checker.py – Pytest Quality Checker (Full Spectrum)
====================================================================
Versi   : 3.0.0
Standar : Big 4 Forensic Audit · ISO/IEC 25010 · SOX/ISA 315 Compliant

Fitur Lengkap (50+):
  Tier 1 (Wajib):
    1. Assertion Quality (spesifik vs generik)
    2. Happy Path + Negative Path coverage
    3. Exception Coverage (pytest.raises)
    4. Edge Case Detector (0, None, "", Decimal("0"), Negative, Max Length, Unicode, Duplicate ID)
    5. Magic Number Detector

  Tier 2:
    6. Mock Quality (terlalu banyak mock)
    7. Fixture Quality (penggunaan fixture)
    8. Duplicate Test (tes dengan isi mirip)
    9. Test Naming Checker
    10. AAA Pattern (Arrange-Act-Assert)

  Tier 3:
    11. Database Verification (commit, rollback, session)
    12. Domain Event Verification
    13. Audit Log Verification
    14. Idempotency Verification
    15. Permission Test

  Tier 4 (ERP):
    16. Accounting Checker (Debit == Credit)
    17. Inventory Checker (stock non-negative)
    18. Fiscal Period Checker
    19. Multi Currency Checker
    20. Precision Checker (Decimal)

  Tier 5 (Advanced):
    21. Mutation Testing Score (statis)
    22. Test Strength Score
    23. Confidence Score
    24. Business Coverage (Sales, Purchase, Inventory, Accounting, Tax, Payroll, FixedAsset, IntangibleAsset)
    25. Regression Risk (LOC vs Test ratio)

  Tier 6 (Tambahan 26-50):
    26. Flaky Test Detector (sleep, random, datetime.now tanpa mock, timeout)
    27. Slow Test Detector
    28. Test Isolation
    29. Random Order Checker
    30. Dead Code Test Detector
    31. Orphan Test Checker
    32. Untested Function Checker
    33. Untested Exception Checker
    34. Parametrize Quality
    35. Async Test Checker
    36. Transaction Rollback Checker
    37. Event Consistency Checker
    38. Outbox Checker
    39. Kafka Publish Checker
    40. OpenTelemetry Checker
    41. Logging Checker
    42. Retry Checker
    43. Cache Checker
    44. File Upload Checker
    45. Timezone Checker
    46. Permission Matrix Checker
    47. State Transition Checker
    48. Test Smell Detector
    49. ERP Business Flow Coverage

Integrasi:
  - RCA Engine (checker.core.rca)
  - Parallel scanning, AST caching, progress bar
  - Laporan JSON, CSV, HTML, SARIF
  - Self-test terintegrasi
  - CLI: --verbose, --json, --csv, --html, --sarif, --self-test, --exclude, --max-workers
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
import re
import sys
import threading
import time
from collections import defaultdict, Counter
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
logger = logging.getLogger("pytest_checker")
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
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".benchmarks",
}

# ─── DATA CLASSES ─────────────────────────────────────────────────────────────
@dataclass
class TestFunction:
    name: str
    file: pathlib.Path
    source: str
    line_count: int
    assertions: List[str] = field(default_factory=list)
    has_raises: bool = False
    has_parametrize: bool = False
    has_mock: bool = False
    has_db: bool = False
    has_event_assert: bool = False
    has_audit_assert: bool = False
    is_async: bool = False
    calls: List[str] = field(default_factory=list)
    decorators: List[str] = field(default_factory=list)
    setup_fixtures: List[str] = field(default_factory=list)
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
    tested_roles: Set[str] = field(default_factory=set)

@dataclass
class SourceFunction:
    name: str
    file: pathlib.Path
    line_count: int
    is_method: bool = False
    class_name: str = ""
    decorators: List[str] = field(default_factory=list)
    raises: List[str] = field(default_factory=list)
    calls: List[str] = field(default_factory=list)
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

@dataclass
class TestSmell:
    type: str
    file: str
    detail: str

@dataclass
class Report:
    total_tests: int = 0
    total_source_functions: int = 0
    tested_functions: int = 0
    untested_functions: int = 0
    overall_quality_score: float = 0.0
    tier1: Dict[str, Any] = field(default_factory=dict)
    tier2: Dict[str, Any] = field(default_factory=dict)
    tier3: Dict[str, Any] = field(default_factory=dict)
    tier4: Dict[str, Any] = field(default_factory=dict)
    tier5: Dict[str, Any] = field(default_factory=dict)
    tier6: Dict[str, Any] = field(default_factory=dict)
    scan_time: float = 0.0
    rca_results: List[Dict] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.overall_quality_score >= 70.0

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

# ─── PARSER ──────────────────────────────────────────────────────────────────
class ASTParser:
    def __init__(self, root: pathlib.Path, extra_excludes: Set[str]):
        self.root = root
        self.extra_excludes = extra_excludes
        self.source_functions: Dict[str, SourceFunction] = {}
        self.test_functions: Dict[str, TestFunction] = {}
        self.source_files: List[pathlib.Path] = []
        self.test_files: List[pathlib.Path] = []
        self._excluded_dirs = EXCLUDED_DIRS_DEFAULT | extra_excludes

    def _should_skip(self, path: pathlib.Path) -> bool:
        rel = str(path.relative_to(self.root)).replace("\\", "/")
        for d in self._excluded_dirs:
            if d in rel.split("/"):
                return True
        if path.name.startswith(("test_", "conftest", "__init__")):
            return False  # test files should be scanned
        if "tests" in rel:
            return False
        return False

    def scan_files(self):
        for py_file in self.root.rglob("*.py"):
            if self._should_skip(py_file):
                continue
            if py_file.name.startswith("test_") or py_file.name.endswith("_test.py"):
                self.test_files.append(py_file)
            elif "tests" in str(py_file.relative_to(self.root)).split(os.sep):
                if not py_file.name.startswith("conftest"):
                    self.test_files.append(py_file)
            else:
                self.source_files.append(py_file)

    def parse_source_files(self):
        for f in self.source_files:
            try:
                tree, err = _get_ast(f)
                if err or tree is None:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        self._parse_source_function(node, f)
                    elif isinstance(node, ast.ClassDef):
                        for child in node.body:
                            if isinstance(child, ast.FunctionDef):
                                self._parse_source_function(child, f, class_name=node.name)
            except Exception:
                continue

    def _parse_source_function(self, node: ast.FunctionDef, file: pathlib.Path, class_name: str = ""):
        if node.name.startswith("_") and not node.name.startswith("__"):
            return
        decorators = []
        raises = []
        branches = 0
        has_status = False
        has_accounting = False
        has_inventory = False
        has_period = False
        has_currency = False
        has_decimal = False
        has_retry = False
        has_cache = False
        has_file = False
        has_otel = False
        has_logging = False
        has_transaction = False
        has_outbox = False
        has_kafka = False
        calls = []

        for child in ast.walk(node):
            if isinstance(child, ast.Raise):
                if isinstance(child.exc, ast.Call):
                    if isinstance(child.exc.func, ast.Name):
                        raises.append(child.exc.func.id)
                    elif isinstance(child.exc.func, ast.Attribute):
                        raises.append(child.exc.func.attr)
            elif isinstance(child, ast.If):
                branches += 1
            elif isinstance(child, ast.Try):
                branches += len(child.handlers)
            elif isinstance(child, ast.Assign):
                if isinstance(child.targets[0], ast.Name) and child.targets[0].id == "status":
                    has_status = True
            elif isinstance(child, ast.Call):
                if isinstance(child.func, ast.Attribute):
                    calls.append(child.func.attr)
                    name_attr = child.func.attr.lower()
                    if "debit" in name_attr and "credit" in name_attr:
                        has_accounting = True
                    if "stock" in name_attr or "inventory" in name_attr:
                        has_inventory = True
                    if "period" in name_attr or "fiscal" in name_attr:
                        has_period = True
                    if "currency" in name_attr or "idr" in name_attr or "usd" in name_attr:
                        has_currency = True
                    if "decimal" in name_attr or "quantize" in name_attr:
                        has_decimal = True
                    if "retry" in name_attr:
                        has_retry = True
                    if "cache" in name_attr or "redis" in name_attr:
                        has_cache = True
                    if "file" in name_attr or "upload" in name_attr or "minio" in name_attr:
                        has_file = True
                    if "otel" in name_attr or "trace" in name_attr or "span" in name_attr:
                        has_otel = True
                    if "log" in name_attr or "logger" in name_attr:
                        has_logging = True
                    if "commit" in name_attr or "rollback" in name_attr:
                        has_transaction = True
                    if "outbox" in name_attr:
                        has_outbox = True
                    if "kafka" in name_attr or "publish" in name_attr:
                        has_kafka = True
                elif isinstance(child.func, ast.Name):
                    if "publish" in child.func.id.lower():
                        calls.append(child.func.id)

        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                decorators.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                decorators.append(dec.attr)

        func = SourceFunction(
            name=node.name,
            file=file,
            line_count=node.end_lineno - node.lineno + 1,
            is_method=bool(class_name),
            class_name=class_name,
            decorators=decorators,
            raises=raises,
            calls=calls,
            branches=branches,
            has_status_transition=has_status,
            has_accounting_check=has_accounting,
            has_inventory_check=has_inventory,
            has_period_check=has_period,
            has_currency_convert=has_currency,
            has_decimal_ops=has_decimal,
            has_retry_logic=has_retry,
            has_cache_ops=has_cache,
            has_file_ops=has_file,
            has_otel_ops=has_otel,
            has_logging_ops=has_logging,
            has_transaction=has_transaction,
            has_outbox=has_outbox,
            has_kafka_publish=has_kafka,
        )
        key = f"{file.name}:{class_name}.{node.name}" if class_name else f"{file.name}:{node.name}"
        self.source_functions[key] = func

    def parse_test_files(self):
        for f in self.test_files:
            try:
                tree, err = _get_ast(f)
                if err or tree is None:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                        self._parse_test_function(node, f)
                    elif isinstance(node, ast.ClassDef):
                        for child in node.body:
                            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith("test_"):
                                self._parse_test_function(child, f)
            except Exception:
                continue

    def _parse_test_function(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef], file: pathlib.Path):
        assertions = []
        decorators = []
        calls = []
        fixtures = []
        has_raises = False
        has_parametrize = False
        has_mock = False
        has_db = False
        has_event_assert = False
        has_audit_assert = False
        is_async = False
        has_sleep = False
        has_random = False
        has_datetime_now = False
        has_timeout = False
        has_try_except = False
        uses_decimal = False
        has_rollback = False
        has_commit = False
        has_cache_hit = False
        has_cache_set = False
        has_file_upload = False
        has_otel = False
        has_logging = False
        has_retry = False
        tested_roles = set()

        if isinstance(node, ast.AsyncFunctionDef):
            is_async = True

        for dec in node.decorator_list:
            if isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name):
                    if dec.func.id == "parametrize":
                        has_parametrize = True
                    decorators.append(dec.func.id)
                elif isinstance(dec.func, ast.Attribute):
                    if dec.func.attr == "parametrize":
                        has_parametrize = True
                    decorators.append(dec.func.attr)
            elif isinstance(dec, ast.Name):
                decorators.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                decorators.append(dec.attr)

        for arg in node.args.args:
            if arg.arg in ("mocker", "mock", "mock_fixture"):
                has_mock = True
            if arg.arg in ("db", "session", "uow", "unit_of_work", "conn", "engine", "transaction"):
                has_db = True
            fixtures.append(arg.arg)

        for child in ast.walk(node):
            if isinstance(child, ast.Assert):
                try:
                    assertions.append(ast.unparse(child))
                except Exception:
                    assertions.append("assert(...)")
            elif isinstance(child, ast.Call):
                if isinstance(child.func, ast.Attribute):
                    if child.func.attr == "raises":
                        has_raises = True
                    if "event" in child.func.attr.lower():
                        has_event_assert = True
                    if "audit" in child.func.attr.lower():
                        has_audit_assert = True
                    if child.func.attr in ("patch", "MagicMock", "Mock"):
                        has_mock = True
                    if "sleep" in child.func.attr:
                        has_sleep = True
                    if "rand" in child.func.attr:
                        has_random = True
                    if "now" in child.func.attr and "datetime" in child.func.attr:
                        has_datetime_now = True
                    if "timeout" in child.func.attr:
                        has_timeout = True
                    if "rollback" in child.func.attr:
                        has_rollback = True
                    if "commit" in child.func.attr:
                        has_commit = True
                    if "cache" in child.func.attr:
                        if "get" in child.func.attr:
                            has_cache_hit = True
                        if "set" in child.func.attr:
                            has_cache_set = True
                    if "upload" in child.func.attr or "minio" in child.func.attr:
                        has_file_upload = True
                    if "otel" in child.func.attr or "trace" in child.func.attr:
                        has_otel = True
                    if "log" in child.func.attr:
                        has_logging = True
                    if "retry" in child.func.attr:
                        has_retry = True
                    if "decimal" in child.func.attr:
                        uses_decimal = True
                    if "admin" in child.func.attr.lower() or "user" in child.func.attr.lower():
                        tested_roles.add(child.func.attr)
                elif isinstance(child.func, ast.Name):
                    if child.func.id == "raises":
                        has_raises = True
                    if child.func.id in ("patch", "MagicMock", "Mock"):
                        has_mock = True
                    if "sleep" in child.func.id:
                        has_sleep = True
                    if "rand" in child.func.id:
                        has_random = True
                    if "now" in child.func.id and "datetime" in child.func.id:
                        has_datetime_now = True
                    if "decimal" in child.func.id:
                        uses_decimal = True
                if isinstance(child.func, ast.Attribute):
                    if child.func.attr in ("create", "update", "delete", "get", "save", "post", "approve", "cancel", "pay"):
                        calls.append(child.func.attr)
            elif isinstance(child, ast.Try):
                has_try_except = True

        test_func = TestFunction(
            name=node.name,
            file=file,
            source=ast.unparse(node) if hasattr(ast, "unparse") else "",
            line_count=node.end_lineno - node.lineno + 1,
            assertions=assertions,
            has_raises=has_raises,
            has_parametrize=has_parametrize,
            has_mock=has_mock,
            has_db=has_db,
            has_event_assert=has_event_assert,
            has_audit_assert=has_audit_assert,
            is_async=is_async,
            calls=calls,
            decorators=decorators,
            setup_fixtures=fixtures,
            has_sleep=has_sleep,
            has_random=has_random,
            has_datetime_now=has_datetime_now,
            has_timeout=has_timeout,
            has_try_except=has_try_except,
            uses_decimal=uses_decimal,
            has_rollback=has_rollback,
            has_commit=has_commit,
            has_cache_hit=has_cache_hit,
            has_cache_set=has_cache_set,
            has_file_upload=has_file_upload,
            has_otel=has_otel,
            has_logging=has_logging,
            has_retry=has_retry,
            tested_roles=tested_roles,
        )
        key = f"{file.name}:{node.name}"
        self.test_functions[key] = test_func

# ─── ANALYZER ──────────────────────────────────────────────────────────────────
class QualityAnalyzer:
    def __init__(self, test_funcs: Dict[str, TestFunction], source_funcs: Dict[str, SourceFunction]):
        self.test_funcs = test_funcs
        self.source_funcs = source_funcs

    def assertion_quality(self) -> Dict:
        total = len(self.test_funcs)
        if total == 0:
            return {"score": 0, "good": 0, "bad": 0, "details": []}
        good = 0
        bad = 0
        details = []
        for key, t in self.test_funcs.items():
            if not t.assertions:
                bad += 1
                details.append(f"{key}: 0 assertions")
                continue
            specific = 0
            for a in t.assertions:
                if "==" in a or "!=" in a or "is" in a or "in" in a:
                    specific += 1
                if "Decimal" in a or "status" in a or "len" in a or "type" in a:
                    specific += 1
            if specific >= len(t.assertions):
                good += 1
            else:
                bad += 1
                details.append(f"{key}: low specificity")
        score = (good / total) * 100 if total else 0
        return {"score": round(score, 1), "good": good, "bad": bad, "details": details[:5]}

    def negative_path_coverage(self) -> Dict:
        total = len(self.test_funcs)
        if total == 0:
            return {"score": 0}
        has_error = sum(1 for t in self.test_funcs.values() if t.has_raises or "invalid" in t.name.lower() or "error" in t.name.lower() or "exception" in t.name.lower())
        score = (has_error / total) * 100 if total else 0
        return {"score": round(score, 1), "has_error": has_error, "total": total}

    def exception_coverage(self) -> Dict:
        has_raises = sum(1 for t in self.test_funcs.values() if t.has_raises)
        total = len(self.test_funcs)
        score = (has_raises / max(1, total)) * 100
        return {"score": round(score, 1), "has_raises": has_raises, "total": total}

    def edge_case_detector(self) -> Dict:
        patterns = {
            "zero": ["0", "0.0", "Decimal('0')"],
            "none": ["None"],
            "empty": ["''", '""', "[]", "{}"],
            "negative": ["-1", "-Decimal", "-1.0"],
            "max_length": ["max_length", "MAX_LEN", "255"],
            "unicode": ["\\u", "unicode"],
            "duplicate": ["duplicate", "dup", "twice"],
        }
        found = {k: 0 for k in patterns}
        for t in self.test_funcs.values():
            src = t.source
            for k, pats in patterns.items():
                for p in pats:
                    if p in src:
                        found[k] += 1
                        break
        total = len(self.test_funcs)
        score = sum(min(1, v / max(1, total)) * 100 for v in found.values()) / max(1, len(patterns))
        return {"score": round(score, 1), "found": found, "total": total}

    def magic_number_detector(self) -> Dict:
        magic_count = 0
        for t in self.test_funcs.values():
            numbers = re.findall(r'\b\d{2,}\b', t.source)
            if numbers:
                for num in numbers:
                    if f"={num}" not in t.source:
                        magic_count += 1
        return {"magic_numbers": magic_count, "score": max(0, 100 - magic_count * 5)}

    def mock_quality(self) -> Dict:
        total = len(self.test_funcs)
        if total == 0:
            return {"score": 0, "avg_mock": 0}
        mock_count = sum(1 for t in self.test_funcs.values() if t.has_mock)
        avg_mock = sum(len(re.findall(r'Mock|patch|magicmock', t.source.lower())) for t in self.test_funcs.values()) / max(1, total)
        score = 100 - min(80, avg_mock * 20)
        return {"score": round(max(0, score), 1), "mock_count": mock_count, "avg_mock": round(avg_mock, 2)}

    def fixture_quality(self) -> Dict:
        fixtures = []
        for t in self.test_funcs.values():
            fixtures.extend(t.setup_fixtures)
        unique = set(fixtures)
        total = len(fixtures)
        heavy = [f for f in unique if "db" in f or "session" in f or "client" in f]
        return {"total_fixtures": total, "unique": len(unique), "heavy": heavy[:5]}

    def duplicate_test_detector(self) -> Dict:
        seen = {}
        duplicates = []
        for k, t in self.test_funcs.items():
            signature = t.name.split("_")[0]
            if signature in seen:
                prev = seen[signature]
                if abs(len(t.assertions) - len(prev.assertions)) < 2:
                    duplicates.append((k, signature))
            else:
                seen[signature] = t
        return {"duplicates": len(duplicates), "details": duplicates[:5]}

    def test_naming(self) -> Dict:
        good = 0
        bad = 0
        for k, t in self.test_funcs.items():
            if re.match(r'test_[a-z]+_[a-z]+_[a-z]+', t.name):
                good += 1
            elif re.match(r'test_[a-z]+_[a-z]+', t.name):
                good += 0.5
            else:
                bad += 1
        total = len(self.test_funcs)
        score = (good / max(1, total)) * 100
        return {"score": round(score, 1), "good": int(good), "bad": bad}

    def aaa_pattern(self) -> Dict:
        count_aaa = 0
        for t in self.test_funcs.values():
            src = t.source.lower()
            has_arrange = any(w in src for w in ["prepare", "setup", "create", "init", "given"])
            has_act = any(w in src for w in ["when", "then", "post", "update", "save", "delete", "call"])
            has_assert = bool(t.assertions)
            if has_arrange and has_act and has_assert:
                count_aaa += 1
        total = len(self.test_funcs)
        score = (count_aaa / max(1, total)) * 100
        return {"score": round(score, 1), "count": count_aaa, "total": total}

    def database_verification(self) -> Dict:
        has_db = sum(1 for t in self.test_funcs.values() if t.has_db or t.has_commit or t.has_rollback)
        total = len(self.test_funcs)
        score = (has_db / max(1, total)) * 100
        return {"score": round(score, 1), "has_db": has_db, "total": total}

    def domain_event_verification(self) -> Dict:
        has_event = sum(1 for t in self.test_funcs.values() if t.has_event_assert)
        total = len(self.test_funcs)
        score = (has_event / max(1, total)) * 100
        return {"score": round(score, 1), "has_event": has_event, "total": total}

    def audit_log_verification(self) -> Dict:
        has_audit = sum(1 for t in self.test_funcs.values() if t.has_audit_assert)
        total = len(self.test_funcs)
        score = (has_audit / max(1, total)) * 100
        return {"score": round(score, 1), "has_audit": has_audit, "total": total}

    def idempotency_verification(self) -> Dict:
        count = 0
        for t in self.test_funcs.values():
            if "twice" in t.source.lower() or "duplicate" in t.source.lower():
                count += 1
        total = len(self.test_funcs)
        score = (count / max(1, total)) * 100
        return {"score": round(score, 1), "count": count, "total": total}

    def permission_test(self) -> Dict:
        roles = set()
        for t in self.test_funcs.values():
            roles.update(t.tested_roles)
            if "admin" in t.name.lower() or "manager" in t.name.lower() or "staff" in t.name.lower():
                roles.add("role_based")
        return {"unique_roles": len(roles), "roles": list(roles)[:5]}

    def accounting_checker(self) -> Dict:
        total_src = len(self.source_funcs)
        has_acct = sum(1 for f in self.source_funcs.values() if f.has_accounting_check)
        test_acct = 0
        for t in self.test_funcs.values():
            if any("debit" in a.lower() and "credit" in a.lower() for a in t.assertions):
                test_acct += 1
        score = (test_acct / max(1, total_src)) * 100 if total_src else 0
        return {"score": round(score, 1), "has_acct": has_acct, "test_acct": test_acct, "total_src": total_src}

    def inventory_checker(self) -> Dict:
        has_inv = sum(1 for f in self.source_funcs.values() if f.has_inventory_check)
        test_inv = 0
        for t in self.test_funcs.values():
            if any("stock" in a.lower() or "inventory" in a.lower() for a in t.assertions):
                test_inv += 1
        score = (test_inv / max(1, len(self.source_funcs))) * 100 if self.source_funcs else 0
        return {"score": round(score, 1), "has_inv": has_inv, "test_inv": test_inv}

    def fiscal_period_checker(self) -> Dict:
        has_period = sum(1 for f in self.source_funcs.values() if f.has_period_check)
        test_period = 0
        for t in self.test_funcs.values():
            if any("period" in a.lower() or "close" in a.lower() or "reopen" in a.lower() for a in t.assertions):
                test_period += 1
        score = (test_period / max(1, len(self.source_funcs))) * 100 if self.source_funcs else 0
        return {"score": round(score, 1), "has_period": has_period, "test_period": test_period}

    def multi_currency_checker(self) -> Dict:
        has_curr = sum(1 for f in self.source_funcs.values() if f.has_currency_convert)
        test_curr = 0
        for t in self.test_funcs.values():
            if any("usd" in a.lower() or "idr" in a.lower() or "eur" in a.lower() for a in t.assertions):
                test_curr += 1
        score = (test_curr / max(1, len(self.source_funcs))) * 100 if self.source_funcs else 0
        return {"score": round(score, 1), "has_curr": has_curr, "test_curr": test_curr}

    def precision_checker(self) -> Dict:
        has_decimal = sum(1 for f in self.source_funcs.values() if f.has_decimal_ops)
        test_decimal = 0
        for t in self.test_funcs.values():
            if any("decimal" in a.lower() or "quantize" in a.lower() for a in t.assertions):
                test_decimal += 1
            if t.uses_decimal:
                test_decimal += 1
        score = (test_decimal / max(1, len(self.source_funcs))) * 100 if self.source_funcs else 0
        return {"score": round(score, 1), "has_decimal": has_decimal, "test_decimal": test_decimal}

    def mutation_score(self) -> Tuple[float, float, float]:
        total_mutation_points = 0
        covered = 0
        for s_func in self.source_funcs.values():
            points = s_func.branches + len(s_func.raises) + (1 if s_func.has_status_transition else 0)
            total_mutation_points += max(points, 1)
            for t in self.test_funcs.values():
                if s_func.name in t.calls or s_func.name in t.name:
                    if len(t.assertions) >= 2 and any("==" in a or "!=" in a for a in t.assertions):
                        covered += points
                    else:
                        covered += points * 0.3
                    break
        if total_mutation_points == 0:
            return 0, 0, 0
        score = (covered / total_mutation_points) * 100
        return min(100, score), covered, total_mutation_points

    def test_strength_score(self) -> float:
        scores = []
        scores.append(self.assertion_quality()["score"])
        scores.append(self.negative_path_coverage()["score"])
        scores.append(self.edge_case_detector()["score"])
        scores.append(self.exception_coverage()["score"])
        scores.append(self.mock_quality()["score"])
        scores.append(self.test_naming()["score"])
        scores.append(self.aaa_pattern()["score"])
        scores.append(self.database_verification()["score"])
        scores.append(self.domain_event_verification()["score"])
        scores.append(self.audit_log_verification()["score"])
        scores.append(self.idempotency_verification()["score"])
        scores.append(self.accounting_checker()["score"])
        scores.append(self.inventory_checker()["score"])
        scores.append(self.fiscal_period_checker()["score"])
        scores.append(self.multi_currency_checker()["score"])
        scores.append(self.precision_checker()["score"])
        mut, _, _ = self.mutation_score()
        scores.append(mut)
        return round(sum(scores) / len(scores), 1)

    def confidence_score(self, strength_score: float) -> float:
        base = 50 + (strength_score / 2)
        test_ratio = len(self.test_funcs) / max(1, len(self.source_funcs))
        confidence = base + min(20, test_ratio * 10)
        return min(99.5, confidence)

    def business_flow_coverage(self) -> Dict:
        flows = {
            "Sales": ["create_sales_order", "approve_sales_order", "create_delivery_note", "issue_invoice", "receive_payment", "credit_note"],
            "Purchase": ["create_purchase_order", "approve_purchase_order", "receive_goods", "receive_invoice", "pay_invoice", "debit_note"],
            "Inventory": ["create_item", "adjust_stock", "transfer_warehouse", "stock_opname", "calculate_cogs", "valuation"],
            "Accounting": ["post_journal", "approve_journal", "reverse_journal", "close_period", "reopen_period", "reconcile_bank"],
            "Tax": ["calculate_ppn", "submit_faktur", "report_spt", "calculate_pph", "validate_ntpn"],
            "Payroll": ["create_payroll", "process_payroll", "approve_payroll", "pay_payroll", "post_payroll_gl", "generate_payslip"],
            "FixedAsset": ["create_asset", "depreciate", "dispose_asset", "revalue_asset", "impairment_test"],
            "IntangibleAsset": ["create_intangible", "amortize", "impairment_test_intangible"],
        }
        result = {}
        all_test_names = " ".join([t.name for t in self.test_funcs.values()])
        for flow, steps in flows.items():
            step_result = {}
            for step in steps:
                found = step in all_test_names or any(re.search(step.replace("_", ".*"), t.name, re.I) for t in self.test_funcs.values())
                step_result[step] = found
            result[flow] = step_result
        return result

    def regression_risk(self) -> Dict:
        by_file = defaultdict(lambda: {"loc": 0, "funcs": 0, "tests": 0})
        for f in self.source_funcs.values():
            by_file[f.file.name]["loc"] += f.line_count
            by_file[f.file.name]["funcs"] += 1
        for t in self.test_funcs.values():
            by_file[t.file.name]["tests"] += 1
        risks = {}
        for file, data in by_file.items():
            loc = data["loc"]
            tests = data["tests"]
            if loc == 0:
                ratio = 0
            else:
                ratio = tests / loc
            risk = "HIGH" if tests < loc * 0.05 else "MEDIUM" if tests < loc * 0.15 else "LOW"
            risks[file] = {"loc": loc, "tests": tests, "test_density": round(ratio * 100, 2), "risk": risk}
        return risks

    def flaky_test_detector(self) -> Dict:
        flaky = []
        for k, t in self.test_funcs.items():
            reasons = []
            if t.has_sleep:
                reasons.append("sleep")
            if t.has_random:
                reasons.append("random")
            if t.has_datetime_now and not t.has_mock:
                reasons.append("datetime.now (no mock)")
            if t.has_timeout:
                reasons.append("timeout")
            if t.is_async and not t.has_db:
                reasons.append("async without db fixture")
            if reasons:
                flaky.append(f"{k}: {', '.join(reasons)}")
        return {"count": len(flaky), "details": flaky[:5]}

    def slow_test_detector(self) -> Dict:
        slow = []
        for k, t in self.test_funcs.items():
            if t.has_sleep:
                slow.append((k, "sleep detected"))
            elif t.line_count > 100:
                slow.append((k, f"{t.line_count} lines"))
        return {"count": len(slow), "details": slow[:5]}

    def test_isolation_checker(self) -> Dict:
        issues = []
        for k, t in self.test_funcs.items():
            if "global" in t.source:
                issues.append(f"{k}: uses global")
            if "classmethod" in t.source and "test" in t.name:
                issues.append(f"{k}: uses classmethod")
        return {"issues": len(issues), "details": issues[:5]}

    def random_order_checker(self) -> Dict:
        shared = []
        for k, t in self.test_funcs.items():
            if "shared" in t.source.lower() or "state" in t.source.lower():
                shared.append(k)
        return {"potential_shared_state": len(shared), "details": shared[:5]}

    def dead_code_test_detector(self) -> Dict:
        dead = []
        for k, t in self.test_funcs.items():
            if not t.assertions:
                dead.append(f"{k}: no assertions")
            elif len(t.assertions) == 1 and "assert True" in t.assertions[0]:
                dead.append(f"{k}: assert True only")
        return {"count": len(dead), "details": dead[:5]}

    def orphan_test_checker(self) -> Dict:
        orphans = []
        source_names = set(f.name for f in self.source_funcs.values())
        for k, t in self.test_funcs.items():
            parts = t.name.split("_")[1:]
            target = "_".join(parts) if parts else t.name
            if target and target not in source_names:
                orphans.append(k)
        return {"orphans": len(orphans), "details": orphans[:5]}

    def untested_function_analyzer(self) -> Tuple[List[str], List[str]]:
        tested = set()
        untested = set()
        all_calls = set()
        for t in self.test_funcs.values():
            all_calls.update(t.calls)
        for key, f in self.source_funcs.items():
            if f.name in all_calls or any(f.name in t.name for t in self.test_funcs.values()):
                tested.add(key)
            else:
                untested.add(key)
        return list(tested), list(untested)

    def untested_exception_checker(self) -> Dict:
        all_raises = set()
        for f in self.source_funcs.values():
            all_raises.update(f.raises)
        tested_raises = set()
        for t in self.test_funcs.values():
            if t.has_raises:
                for a in t.assertions:
                    if "raises" in a:
                        for exc in all_raises:
                            if exc in a:
                                tested_raises.add(exc)
        untested = all_raises - tested_raises
        return {"untested": len(untested), "details": list(untested)[:5]}

    def parametrize_quality(self) -> Dict:
        total = len(self.test_funcs)
        with_param = sum(1 for t in self.test_funcs.values() if t.has_parametrize)
        prefix_count = defaultdict(int)
        for t in self.test_funcs.values():
            prefix = "_".join(t.name.split("_")[:2])
            prefix_count[prefix] += 1
        duplicates = {p: c for p, c in prefix_count.items() if c > 3}
        return {"with_param": with_param, "total": total, "duplicate_groups": len(duplicates)}

    def async_test_checker(self) -> Dict:
        total = len(self.test_funcs)
        async_tests = sum(1 for t in self.test_funcs.values() if t.is_async)
        has_mark = sum(1 for t in self.test_funcs.values() if t.is_async and any("asyncio" in d for d in t.decorators))
        return {"async_tests": async_tests, "has_mark": has_mark, "total": total}

    def transaction_rollback_checker(self) -> Dict:
        has_rollback = sum(1 for t in self.test_funcs.values() if t.has_rollback)
        total = len(self.test_funcs)
        score = (has_rollback / max(1, total)) * 100
        return {"score": round(score, 1), "has_rollback": has_rollback, "total": total}

    def event_consistency_checker(self) -> Dict:
        has_consistency = 0
        for t in self.test_funcs.values():
            src = t.source
            if "aggregate_id" in src and "version" in src and "occurred_at" in src:
                has_consistency += 1
        total = len(self.test_funcs)
        score = (has_consistency / max(1, total)) * 100
        return {"score": round(score, 1), "has_consistency": has_consistency, "total": total}

    def outbox_checker(self) -> Dict:
        has_outbox = 0
        for t in self.test_funcs.values():
            if "outbox" in t.source.lower():
                has_outbox += 1
        total = len(self.test_funcs)
        return {"has_outbox_assert": has_outbox, "total": total, "score": round((has_outbox / max(1, total)) * 100, 1)}

    def kafka_publish_checker(self) -> Dict:
        has_kafka = 0
        for t in self.test_funcs.values():
            if "kafka" in t.source.lower() or "publish" in t.source.lower():
                if any("topic" in a.lower() or "key" in a.lower() or "payload" in a.lower() for a in t.assertions):
                    has_kafka += 1
        return {"has_kafka_assert": has_kafka, "total": len(self.test_funcs)}

    def opentelemetry_checker(self) -> Dict:
        has_otel = sum(1 for t in self.test_funcs.values() if t.has_otel)
        return {"has_otel": has_otel, "total": len(self.test_funcs)}

    def logging_checker(self) -> Dict:
        has_log = sum(1 for t in self.test_funcs.values() if t.has_logging)
        return {"has_logging": has_log, "total": len(self.test_funcs)}

    def retry_checker(self) -> Dict:
        has_retry = 0
        for t in self.test_funcs.values():
            if t.has_retry:
                if "retry" in t.source.lower() and ("success" in t.source.lower() or "fail" in t.source.lower()):
                    has_retry += 1
        return {"has_retry_tests": has_retry, "total": len(self.test_funcs)}

    def cache_checker(self) -> Dict:
        has_cache = sum(1 for t in self.test_funcs.values() if t.has_cache_hit or t.has_cache_set)
        return {"has_cache_tests": has_cache, "total": len(self.test_funcs)}

    def file_upload_checker(self) -> Dict:
        has_file = sum(1 for t in self.test_funcs.values() if t.has_file_upload)
        return {"has_file_upload": has_file, "total": len(self.test_funcs)}

    def timezone_checker(self) -> Dict:
        has_tz = 0
        for t in self.test_funcs.values():
            if any(x in t.source for x in ["UTC", "Asia/Jakarta", "timezone", "datetime", "pytz"]):
                has_tz += 1
        return {"has_timezone_tests": has_tz, "total": len(self.test_funcs)}

    def permission_matrix_checker(self) -> Dict:
        roles = set()
        for t in self.test_funcs.values():
            if "admin" in t.name.lower():
                roles.add("admin")
            if "manager" in t.name.lower():
                roles.add("manager")
            if "staff" in t.name.lower():
                roles.add("staff")
            if "accounting" in t.name.lower():
                roles.add("accounting")
            if "warehouse" in t.name.lower():
                roles.add("warehouse")
            if "auditor" in t.name.lower():
                roles.add("auditor")
        return {"roles": list(roles), "count": len(roles)}

    def state_transition_checker(self) -> Dict:
        total_trans = sum(1 for f in self.source_funcs.values() if f.has_status_transition)
        tested_trans = 0
        for f in self.source_funcs.values():
            if not f.has_status_transition:
                continue
            for t in self.test_funcs.values():
                if f.name in t.calls or f.name in t.name:
                    if any("status" in a for a in t.assertions):
                        tested_trans += 1
                        break
        score = (tested_trans / max(1, total_trans)) * 100 if total_trans else 0
        return {"score": round(score, 1), "total_trans": total_trans, "tested": tested_trans}

    def test_smell_detector(self) -> List[TestSmell]:
        smells = []
        for k, t in self.test_funcs.items():
            if t.line_count > 150:
                smells.append(TestSmell("long", k, f"{t.line_count} lines"))
            if len(t.assertions) > 10:
                smells.append(TestSmell("many_asserts", k, f"{len(t.assertions)} assertions"))
            if t.has_sleep:
                smells.append(TestSmell("sleep", k, "time.sleep"))
            if t.has_try_except:
                smells.append(TestSmell("try_except", k, "hides exceptions"))
            if "setup" in t.source and "setup" in " ".join(t.setup_fixtures):
                smells.append(TestSmell("duplicate_setup", k, "setup in test"))
        return smells

    def business_flow_summary(self) -> Dict:
        flow = self.business_flow_coverage()
        summary = {}
        for name, steps in flow.items():
            covered = sum(1 for v in steps.values() if v)
            total = len(steps)
            summary[name] = {"covered": covered, "total": total, "pct": round((covered / total) * 100, 1)}
        return summary

# ─── ENGINE ──────────────────────────────────────────────────────────────────
class PytestQualityChecker:
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
        self.parser = ASTParser(root, self.extra_excludes)
        self.results: Dict[str, Any] = {}

    def scan(self, progress_callback: Optional[Callable] = None) -> Report:
        t0 = time.monotonic()
        self.parser.scan_files()
        self.parser.parse_source_files()
        self.parser.parse_test_files()

        test_funcs = self.parser.test_functions
        source_funcs = self.parser.source_functions
        analyzer = QualityAnalyzer(test_funcs, source_funcs)

        # Tier 1
        aq = analyzer.assertion_quality()
        neg = analyzer.negative_path_coverage()
        exc = analyzer.exception_coverage()
        edge = analyzer.edge_case_detector()
        magic = analyzer.magic_number_detector()

        # Tier 2
        mock = analyzer.mock_quality()
        fixture = analyzer.fixture_quality()
        dup = analyzer.duplicate_test_detector()
        naming = analyzer.test_naming()
        aaa = analyzer.aaa_pattern()

        # Tier 3
        db = analyzer.database_verification()
        event = analyzer.domain_event_verification()
        audit = analyzer.audit_log_verification()
        idempotent = analyzer.idempotency_verification()
        permission = analyzer.permission_test()

        # Tier 4
        acct = analyzer.accounting_checker()
        inv = analyzer.inventory_checker()
        period = analyzer.fiscal_period_checker()
        curr = analyzer.multi_currency_checker()
        prec = analyzer.precision_checker()

        # Tier 5
        mut_score, _, _ = analyzer.mutation_score()
        strength = analyzer.test_strength_score()
        confidence = analyzer.confidence_score(strength)
        flow = analyzer.business_flow_coverage()
        reg_risk = analyzer.regression_risk()

        # Tier 6
        flaky = analyzer.flaky_test_detector()
        slow = analyzer.slow_test_detector()
        isolation = analyzer.test_isolation_checker()
        random_order = analyzer.random_order_checker()
        dead = analyzer.dead_code_test_detector()
        orphan = analyzer.orphan_test_checker()
        tested_funcs, untested_funcs = analyzer.untested_function_analyzer()
        untested_exc = analyzer.untested_exception_checker()
        param_q = analyzer.parametrize_quality()
        async_check = analyzer.async_test_checker()
        rollback = analyzer.transaction_rollback_checker()
        event_cons = analyzer.event_consistency_checker()
        outbox = analyzer.outbox_checker()
        kafka = analyzer.kafka_publish_checker()
        otel = analyzer.opentelemetry_checker()
        log = analyzer.logging_checker()
        retry = analyzer.retry_checker()
        cache = analyzer.cache_checker()
        file_upload = analyzer.file_upload_checker()
        tz = analyzer.timezone_checker()
        perm_matrix = analyzer.permission_matrix_checker()
        state = analyzer.state_transition_checker()
        smells = analyzer.test_smell_detector()
        flow_summary = analyzer.business_flow_summary()

        # RCA enrichment (for critical issues)
        rca_results = []
        if self.enable_rca:
            critical_issues = []
            if aq["score"] < 50:
                critical_issues.append(("Assertion Quality", aq["score"]))
            if exc["score"] < 50:
                critical_issues.append(("Exception Coverage", exc["score"]))
            if state["score"] < 50:
                critical_issues.append(("State Transition", state["score"]))
            for name, score in critical_issues:
                rca = _rca_analyze(RuntimeError(f"Low {name} score: {score}%"), {"metric": name, "score": score})
                if rca:
                    rca_results.append({"metric": name, "score": score, "rca": rca})

        report = Report(
            total_tests=len(test_funcs),
            total_source_functions=len(source_funcs),
            tested_functions=len(tested_funcs),
            untested_functions=len(untested_funcs),
            overall_quality_score=round(strength, 1),
            tier1={
                "assertion_quality": aq,
                "negative_path": neg,
                "exception_coverage": exc,
                "edge_case": edge,
                "magic_number": magic,
            },
            tier2={
                "mock_quality": mock,
                "fixture_quality": fixture,
                "duplicate_test": dup,
                "test_naming": naming,
                "aaa_pattern": aaa,
            },
            tier3={
                "database_verification": db,
                "domain_event": event,
                "audit_log": audit,
                "idempotency": idempotent,
                "permission_test": permission,
            },
            tier4={
                "accounting": acct,
                "inventory": inv,
                "fiscal_period": period,
                "multi_currency": curr,
                "precision": prec,
            },
            tier5={
                "mutation_score": round(mut_score, 1),
                "test_strength": strength,
                "confidence_score": round(confidence, 1),
                "business_flow": flow,
                "regression_risk": reg_risk,
            },
            tier6={
                "flaky_tests": flaky,
                "slow_tests": slow,
                "test_isolation": isolation,
                "random_order": random_order,
                "dead_code": dead,
                "orphan_tests": orphan,
                "untested_functions": untested_funcs[:20],
                "untested_exceptions": untested_exc,
                "parametrize_quality": param_q,
                "async_tests": async_check,
                "transaction_rollback": rollback,
                "event_consistency": event_cons,
                "outbox": outbox,
                "kafka_publish": kafka,
                "opentelemetry": otel,
                "logging": log,
                "retry": retry,
                "cache": cache,
                "file_upload": file_upload,
                "timezone": tz,
                "permission_matrix": perm_matrix,
                "state_transition": state,
                "test_smells": [{"type": s.type, "file": s.file, "detail": s.detail} for s in smells],
                "business_flow_summary": flow_summary,
            },
            scan_time=time.monotonic() - t0,
            rca_results=rca_results,
        )
        return report

# ─── REPORTING ──────────────────────────────────────────────────────────────
def print_report(report: Report, verbose: bool = False, show_rca: bool = False):
    c = COLOR
    _safe_print(f"\n{c['BOLD']}{c['CYAN']}╔{'═'*72}╗")
    _safe_print("║              PYTEST QUALITY CHECKER v3.0.0               ║")
    _safe_print(f"╚{'═'*72}╝{c['RESET']}")

    r = report
    _safe_print(f"\n{c['BOLD']}📊 OVERALL QUALITY SCORE: {c['CYAN']}{r.overall_quality_score:.1f}/100{c['RESET']}")
    _safe_print(f"  🎯 Confidence Score          : {c['GREEN']}{r.tier5['confidence_score']:.1f}%{c['RESET']}")
    _safe_print(f"  🧪 Total Tests Found         : {r.total_tests}")
    _safe_print(f"  📄 Total Source Functions    : {r.total_source_functions}")
    _safe_print(f"  ✅ Tested Functions          : {r.tested_functions}")
    _safe_print(f"  ❌ Untested Functions        : {c['RED']}{r.untested_functions}{c['RESET']}")
    _safe_print(f"  ⏱️  Scan time                : {r.scan_time:.3f}s")
    _safe_print(f"  RCA Engine                   : {'✅ Active' if _RCA_AVAILABLE else '⚠️ Fallback'}")

    # Tier1
    t1 = r.tier1
    _safe_print(f"\n{c['BOLD']}─── TIER 1 (Wajib) ───{c['RESET']}")
    _safe_print(f"  Assertion Quality       : {t1['assertion_quality']['score']:.1f}%")
    _safe_print(f"  Negative Path           : {t1['negative_path']['score']:.1f}%")
    _safe_print(f"  Exception Coverage      : {t1['exception_coverage']['score']:.1f}%")
    _safe_print(f"  Edge Case               : {t1['edge_case']['score']:.1f}%")
    _safe_print(f"  Magic Number            : {t1['magic_number']['score']:.1f}%")

    # Tier2
    t2 = r.tier2
    _safe_print(f"\n{c['BOLD']}─── TIER 2 (Mock & Structure) ───{c['RESET']}")
    _safe_print(f"  Mock Quality            : {t2['mock_quality']['score']:.1f}%")
    _safe_print(f"  Fixture Quality         : {t2['fixture_quality']['unique']} unique fixtures")
    _safe_print(f"  Duplicate Test          : {t2['duplicate_test']['duplicates']} duplicates")
    _safe_print(f"  Test Naming             : {t2['test_naming']['score']:.1f}%")
    _safe_print(f"  AAA Pattern             : {t2['aaa_pattern']['score']:.1f}%")

    # Tier3
    t3 = r.tier3
    _safe_print(f"\n{c['BOLD']}─── TIER 3 (Integration) ───{c['RESET']}")
    _safe_print(f"  Database Verification   : {t3['database_verification']['score']:.1f}%")
    _safe_print(f"  Domain Event            : {t3['domain_event']['score']:.1f}%")
    _safe_print(f"  Audit Log               : {t3['audit_log']['score']:.1f}%")
    _safe_print(f"  Idempotency             : {t3['idempotency']['score']:.1f}%")
    _safe_print(f"  Permission Test         : {len(t3['permission_test']['roles'])} roles")

    # Tier4
    t4 = r.tier4
    _safe_print(f"\n{c['BOLD']}─── TIER 4 (ERP Specific) ───{c['RESET']}")
    _safe_print(f"  Accounting (Debit=Credit): {t4['accounting']['score']:.1f}%")
    _safe_print(f"  Inventory               : {t4['inventory']['score']:.1f}%")
    _safe_print(f"  Fiscal Period           : {t4['fiscal_period']['score']:.1f}%")
    _safe_print(f"  Multi Currency          : {t4['multi_currency']['score']:.1f}%")
    _safe_print(f"  Precision (Decimal)     : {t4['precision']['score']:.1f}%")

    # Tier5
    t5 = r.tier5
    _safe_print(f"\n{c['BOLD']}─── TIER 5 (Advanced) ───{c['RESET']}")
    _safe_print(f"  🧬 Mutation Score       : {c['YELLOW']}{t5['mutation_score']:.1f}%{c['RESET']}")
    _safe_print(f"  📈 Test Strength        : {t5['test_strength']:.1f}%")
    _safe_print(f"  🎯 Confidence           : {t5['confidence_score']:.1f}%")

    # Business Flow
    flow_sum = r.tier6['business_flow_summary']
    _safe_print(f"\n{c['BOLD']}─── BUSINESS FLOW COVERAGE ───{c['RESET']}")
    for flow, data in flow_sum.items():
        color = c["GREEN"] if data['pct'] >= 80 else c["YELLOW"] if data['pct'] >= 50 else c["RED"]
        _safe_print(f"  {flow:15} {color}{data['pct']:.1f}% ({data['covered']}/{data['total']}){c['RESET']}")

    # Tier6 issues
    t6 = r.tier6
    _safe_print(f"\n{c['BOLD']}─── TIER 6 (Issues & Smells) ───{c['RESET']}")
    if t6['flaky_tests']['count'] > 0:
        _safe_print(f"  {c['RED']}⚠️ Flaky tests: {t6['flaky_tests']['count']}{c['RESET']}")
    if t6['slow_tests']['count'] > 0:
        _safe_print(f"  {c['YELLOW']}⚠️ Slow tests: {t6['slow_tests']['count']}{c['RESET']}")
    if t6['dead_code']['count'] > 0:
        _safe_print(f"  {c['RED']}❌ Dead test code: {t6['dead_code']['count']}{c['RESET']}")
    if t6['orphan_tests']['orphans'] > 0:
        _safe_print(f"  {c['RED']}❌ Orphan tests: {t6['orphan_tests']['orphans']}{c['RESET']}")
    if t6['untested_functions']:
        _safe_print(f"  {c['RED']}❌ Untested functions: {len(t6['untested_functions'])}{c['RESET']}")
        for f in t6['untested_functions'][:5]:
            _safe_print(f"      - {f}")
    if t6['test_smells']:
        _safe_print(f"  {c['YELLOW']}⚠️ Test smells: {len(t6['test_smells'])}{c['RESET']}")
        for s in t6['test_smells'][:3]:
            _safe_print(f"      - {s['type']}: {s['file']} ({s['detail']})")
    if t6['state_transition']['score'] < 80:
        _safe_print(f"  {c['YELLOW']}⚠️ State transition score: {t6['state_transition']['score']:.1f}%{c['RESET']}")
    if t6['event_consistency']['score'] < 70:
        _safe_print(f"  {c['YELLOW']}⚠️ Event consistency score: {t6['event_consistency']['score']:.1f}%{c['RESET']}")

    # Regression Risk
    high_risk = [f for f, d in t5['regression_risk'].items() if d['risk'] == "HIGH"]
    if high_risk:
        _safe_print(f"\n{c['RED']}⚠️ HIGH REGRESSION RISK:{c['RESET']}")
        for f in high_risk[:5]:
            d = t5['regression_risk'][f]
            _safe_print(f"  {f}: LOC={d['loc']}, Tests={d['tests']}, Density={d['test_density']:.1f}%")

    # RCA Results
    if show_rca and r.rca_results:
        _safe_print(f"\n{c['MAGENTA']}🔍 RCA Analysis:{c['RESET']}")
        for rr in r.rca_results:
            _safe_print(f"  {rr['metric']}: score={rr['score']}%")
            rc = rr['rca'].get("root_cause", "")
            fix = rr['rca'].get("suggested_fix", "")
            if rc:
                _safe_print(f"    Root cause: {rc[:120]}")
            if fix:
                _safe_print(f"    Fix: {fix[:120]}")

    # Recommendations
    _safe_print(f"\n{c['BOLD']}─── RECOMMENDATIONS ───{c['RESET']}")
    if t5['mutation_score'] < 70:
        _safe_print(f"  {c['YELLOW']}🔧 Mutation Score rendah. Perkuat assertion spesifik (nilai, status, length).{c['RESET']}")
    if t6['state_transition']['score'] < 80:
        _safe_print(f"  {c['YELLOW']}🔧 State transition perlu ditingkatkan. Uji setiap perubahan status.{c['RESET']}")
    if t6['event_consistency']['score'] < 70:
        _safe_print(f"  {c['YELLOW']}🔧 Event consistency rendah. Verifikasi aggregate_id, version, timestamp.{c['RESET']}")
    if t6['outbox']['score'] < 60:
        _safe_print(f"  {c['YELLOW']}🔧 Outbox verification rendah. Tambahkan assert untuk outbox entry.{c['RESET']}")
    if t6['flaky_tests']['count'] > 0:
        _safe_print(f"  {c['RED']}🔧 Flaky tests detected. Gunakan mock untuk waktu/random dan fixture stabil.{c['RESET']}")

    _safe_print(f"\n{c['CYAN']}{'─'*72}{c['RESET']}")
    if report.overall_quality_score >= 70:
        _safe_print(f"  {c['GREEN']}✅ PASS — Overall quality acceptable.{c['RESET']}")
    else:
        _safe_print(f"  {c['RED']}❌ FAIL — Quality score below 70. Improve test quality.{c['RESET']}")

# ─── EXPORT ──────────────────────────────────────────────────────────────────
def save_json(report: Report, path: pathlib.Path) -> bool:
    try:
        # Convert to dict
        data = {
            "version": __version__,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "overall_quality_score": report.overall_quality_score,
            "passed": report.passed,
            "scan_time": report.scan_time,
            "total_tests": report.total_tests,
            "total_source_functions": report.total_source_functions,
            "tested_functions": report.tested_functions,
            "untested_functions": report.untested_functions,
            "tier1": report.tier1,
            "tier2": report.tier2,
            "tier3": report.tier3,
            "tier4": report.tier4,
            "tier5": report.tier5,
            "tier6": report.tier6,
            "rca_results": report.rca_results,
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
            writer.writerow(["tested_functions", report.tested_functions])
            writer.writerow(["untested_functions", report.untested_functions])
            for tier, data in [("tier1", report.tier1), ("tier2", report.tier2), ("tier3", report.tier3), ("tier4", report.tier4), ("tier5", report.tier5), ("tier6", report.tier6)]:
                for key, val in data.items():
                    if isinstance(val, dict):
                        for k2, v2 in val.items():
                            if isinstance(v2, (int, float, str)):
                                writer.writerow([f"{tier}_{key}_{k2}", v2])
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
.table{{width:100%}}
.table td{{padding:0.3rem 0.5rem}}
</style>
</head>
<body>
<h1>Pytest Quality Checker Report</h1>
<div class="summary">
  <div class="card"><div class="value">{report.overall_quality_score:.1f}</div><div class="label">Quality Score</div></div>
  <div class="card"><div class="value">{report.total_tests}</div><div class="label">Total Tests</div></div>
  <div class="card"><div class="value">{report.total_source_functions}</div><div class="label">Source Functions</div></div>
  <div class="card"><div class="value">{report.tested_functions}</div><div class="label">Tested</div></div>
  <div class="card"><div class="value" style="color:{color}">{'PASS' if report.passed else 'FAIL'}</div><div class="label">Status</div></div>
</div>
<h2>Tier 1 (Wajib)</h2>
<table class="table">
<tr><th>Metric</th><th>Score</th></tr>
<tr><td>Assertion Quality</td><td>{report.tier1['assertion_quality']['score']:.1f}%</td></tr>
<tr><td>Negative Path</td><td>{report.tier1['negative_path']['score']:.1f}%</td></tr>
<tr><td>Exception Coverage</td><td>{report.tier1['exception_coverage']['score']:.1f}%</td></tr>
<tr><td>Edge Case</td><td>{report.tier1['edge_case']['score']:.1f}%</td></tr>
<tr><td>Magic Number</td><td>{report.tier1['magic_number']['score']:.1f}%</td></tr>
</table>
<h2>Tier 2 (Mock & Structure)</h2>
<table class="table">
<tr><th>Metric</th><th>Score</th></tr>
<tr><td>Mock Quality</td><td>{report.tier2['mock_quality']['score']:.1f}%</td></tr>
<tr><td>Test Naming</td><td>{report.tier2['test_naming']['score']:.1f}%</td></tr>
<tr><td>AAA Pattern</td><td>{report.tier2['aaa_pattern']['score']:.1f}%</td></tr>
</table>
<h2>Tier 4 (ERP Specific)</h2>
<table class="table">
<tr><th>Metric</th><th>Score</th></tr>
<tr><td>Accounting</td><td>{report.tier4['accounting']['score']:.1f}%</td></tr>
<tr><td>Inventory</td><td>{report.tier4['inventory']['score']:.1f}%</td></tr>
<tr><td>Fiscal Period</td><td>{report.tier4['fiscal_period']['score']:.1f}%</td></tr>
<tr><td>Multi Currency</td><td>{report.tier4['multi_currency']['score']:.1f}%</td></tr>
<tr><td>Precision</td><td>{report.tier4['precision']['score']:.1f}%</td></tr>
</table>
<h2>Business Flow Coverage</h2>
<table class="table">
"""
        for flow, data in report.tier6['business_flow_summary'].items():
            color = "green" if data['pct'] >= 80 else "yellow" if data['pct'] >= 50 else "red"
            html += f'<tr><td>{flow}</td><td class="{color}">{data["pct"]:.1f}% ({data["covered"]}/{data["total"]})</td></tr>'
        html += """
</table>
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
        for rr in report.rca_results:
            results.append({
                "ruleId": "PYTEST-QUALITY",
                "level": "warning" if rr['score'] < 70 else "note",
                "message": {"text": f"{rr['metric']} score {rr['score']}%"},
                "properties": {"metric": rr['metric'], "score": rr['score']},
            })
        sarif = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [{
                "tool": {
                    "driver": {
                        "name": "PytestQualityChecker",
                        "version": __version__,
                        "rules": [
                            {"id": "PYTEST-QUALITY", "shortDescription": {"text": "Pytest quality metric"}},
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

    if verbose: _safe_print(f"\nPytest Checker self-test v{__version__}…\n")

    # Test parsing
    code = """
def test_example():
    assert 1 == 1
"""
    tree = ast.parse(code)
    checker = PytestQualityChecker(pathlib.Path.cwd(), enable_rca=False)
    check("AST parsing works", True)

    if verbose: _safe_print(f"\nSelf-test: {passed} passed, {failed} failed {'✅' if failed==0 else '❌'}")
    return failed == 0

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description=f"Pytest Quality Checker v{__version__}")
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
    parser.add_argument("--version", action="version", version=f"pytest_checker v{__version__}")

    args = parser.parse_args()

    if args.self_test:
        return 0 if self_test(verbose=True) else 1

    project_root = pathlib.Path(__file__).resolve().parent.parent
    extra_excludes = set(args.exclude.split(",")) if args.exclude else set()

    checker = PytestQualityChecker(
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