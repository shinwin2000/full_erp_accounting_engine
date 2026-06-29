#!/usr/bin/env python3
"""
Sovereign ERP System — PYTEST QUALITY CHECKER (FULL SPECTRUM)
================================================================
Menganalisis kualitas test suite secara mendalam dengan 50+ fitur.

Fitur Lengkap:
Tier 1 (Wajib):
1. Assertion Quality (spesifik vs generik)
2. Happy Path + Negative Path coverage
3. Exception Coverage (pytest.raises)
4. Edge Case Detector (0, None, "", Decimal("0"), Negative, Max Length, Unicode, Duplicate ID)
5. Magic Number Detector (angka keras tanpa konstanta)

Tier 2:
6. Mock Quality (terlalu banyak mock)
7. Fixture Quality (penggunaan fixture)
8. Duplicate Test (tes dengan isi mirip)
9. Test Naming Checker (pola penamaan)
10. AAA Pattern (Arrange-Act-Assert)

Tier 3:
11. Database Verification (commit, rollback, session)
12. Domain Event Verification (event publish & assert)
13. Audit Log Verification
14. Idempotency Verification
15. Permission Test

Tier 4:
16. Accounting Checker (Debit == Credit)
17. Inventory Checker (stock non-negative)
18. Fiscal Period Checker (period close/reopen)
19. Multi Currency Checker (USD, IDR, EUR)
20. Precision Checker (Decimal, quantize, rounding)

Tier 5:
21. Mutation Testing Score (statis)
22. Test Strength Score (agregat)
23. Confidence Score
24. Business Coverage (Sales, Purchase, Inventory, Accounting, Tax, Payroll, FixedAsset, IntangibleAsset)
25. Regression Risk (LOC vs Test ratio)

Tier 6 (Tambahan 26-50):
26. Flaky Test Detector (sleep, random, datetime.now tanpa mock, timeout)
27. Slow Test Detector (sleep, large loops, heavy setup)
28. Test Isolation (dependency antar test - statis)
29. Random Order Checker (deteksi state mutation)
30. Dead Code Test Detector (test tanpa assert / hanya assert True)
31. Orphan Test Checker (test menguji class/fungsi yang hilang)
32. Untested Function Checker (sudah)
33. Untested Exception Checker (raise tanpa test)
34. Branch Coverage Analyzer (sudah)
35. Parametrize Quality (rekomendasi parametrize untuk duplikasi)
36. Async Test Checker (async/await correctness)
37. Transaction Rollback Checker (rollback on exception)
38. Event Consistency Checker (aggregate_id, version, timestamp)
39. Outbox Checker (outbox entry verification)
40. Kafka Publish Checker (topic, key, payload)
41. OpenTelemetry Checker (trace, span)
42. Logging Checker (error logging)
43. Retry Checker (retry logic test)
44. Cache Checker (hit/miss/invalidation)
45. File Upload Checker (upload, delete, checksum)
46. Timezone Checker (UTC, Asia/Jakarta, DST)
47. Permission Matrix Checker (role-based)
48. State Transition Checker (status lifecycle)
49. Test Smell Detector (panjang, sleep, try/except, duplicate setup)
50. ERP Business Flow Coverage (sudah)
"""

from __future__ import annotations

import ast
import json
import logging
import re
import sys
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# ========================================================================
# Konfigurasi
# ========================================================================
ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_DIRS = {
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "venv", "env", "virtualenv", "node_modules", "checker", "migrations",
    "logs", "reports", "deployment", "docs", "scripts", "alembic", ".benchmarks"
}

COLOR = {
    "RED": "\033[91m",
    "GREEN": "\033[92m",
    "YELLOW": "\033[93m",
    "BLUE": "\033[94m",
    "CYAN": "\033[96m",
    "BOLD": "\033[1m",
    "RESET": "\033[0m"
}
if not sys.stdout.isatty():
    COLOR = dict.fromkeys(COLOR, "")

# ========================================================================
# 1. MODELS
# ========================================================================

@dataclass
class TestFunction:
    name: str
    file: Path
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
    file: Path
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

# ========================================================================
# 2. PARSER (Enhanced)
# ========================================================================

class ASTParser:
    """Enhanced AST parser for source & test files."""

    def __init__(self, root: Path):
        self.root = root
        self.source_functions: Dict[str, SourceFunction] = {}
        self.test_functions: Dict[str, TestFunction] = {}
        self.source_files: List[Path] = []
        self.test_files: List[Path] = []

    def scan_files(self):
        for py_file in self.root.rglob("*.py"):
            if any(part in EXCLUDED_DIRS for part in py_file.parts):
                continue
            if py_file.name.startswith("test_") or py_file.name.endswith("_test.py"):
                self.test_files.append(py_file)
            elif "tests" in py_file.parts:
                if not py_file.name.startswith("conftest"):
                    self.test_files.append(py_file)
            else:
                self.source_files.append(py_file)

    def parse_source_files(self):
        for f in self.source_files:
            try:
                src = f.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=str(f))
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        self._parse_source_function(node, f)
                    elif isinstance(node, ast.ClassDef):
                        for child in node.body:
                            if isinstance(child, ast.FunctionDef):
                                self._parse_source_function(child, f, class_name=node.name)
            except Exception:
                continue

    def _parse_source_function(self, node: ast.FunctionDef, file: Path, class_name: str = ""):
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
                    name = child.func.attr.lower()
                    if "debit" in name and "credit" in name:
                        has_accounting = True
                    if "stock" in name or "inventory" in name:
                        has_inventory = True
                    if "period" in name or "fiscal" in name:
                        has_period = True
                    if "currency" in name or "idr" in name or "usd" in name:
                        has_currency = True
                    if "decimal" in name or "quantize" in name:
                        has_decimal = True
                    if "retry" in name:
                        has_retry = True
                    if "cache" in name or "redis" in name:
                        has_cache = True
                    if "file" in name or "upload" in name or "minio" in name:
                        has_file = True
                    if "otel" in name or "trace" in name or "span" in name:
                        has_otel = True
                    if "log" in name or "logger" in name:
                        has_logging = True
                    if "commit" in name or "rollback" in name:
                        has_transaction = True
                    if "outbox" in name:
                        has_outbox = True
                    if "kafka" in name or "publish" in name:
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
                src = f.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=str(f))
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                        self._parse_test_function(node, f)
                    elif isinstance(node, ast.ClassDef):
                        for child in node.body:
                            if isinstance(child, ast.FunctionDef) and child.name.startswith("test_"):
                                self._parse_test_function(child, f)
            except Exception:
                continue

    def _parse_test_function(self, node: ast.FunctionDef, file: Path):
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

        # Decorators
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

        # Params
        for arg in node.args.args:
            if arg.arg in ("mocker", "mock", "mock_fixture"):
                has_mock = True
            if arg.arg in ("db", "session", "uow", "unit_of_work", "conn", "engine", "transaction"):
                has_db = True
            fixtures.append(arg.arg)

        # Walk body
        for child in ast.walk(node):
            if isinstance(child, ast.Assert):
                if isinstance(child.test, ast.Compare):
                    if isinstance(child.test.left, ast.Name):
                        name = child.test.left.id.lower()
                        if "event" in name:
                            has_event_assert = True
                        if "audit" in name:
                            has_audit_assert = True
                    # Detect specific assertions
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
                    # Detect role testing
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
                # Service calls
                if isinstance(child.func, ast.Attribute):
                    if child.func.attr in ("create", "update", "delete", "get", "save", "post", "approve", "cancel", "pay"):
                        calls.append(child.func.attr)
            elif isinstance(child, ast.Try):
                has_try_except = True
            elif isinstance(child, ast.ExceptHandler):
                pass

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

# ========================================================================
# 3. ALL ANALYZERS (50+ features)
# ========================================================================

class QualityAnalyzer:
    def __init__(self, test_funcs: Dict[str, TestFunction], source_funcs: Dict[str, SourceFunction]):
        self.test_funcs = test_funcs
        self.source_funcs = source_funcs

    # ---- Tier 1 ----

    def assertion_quality(self) -> Dict:
        total_tests = len(self.test_funcs)
        if total_tests == 0:
            return {"score": 0, "good": 0, "bad": 0, "details": []}
        good = 0
        bad = 0
        details = []
        for key, t in self.test_funcs.items():
            if not t.assertions:
                bad += 1
                details.append(f"{key}: 0 assertions")
                continue
            # Count specific assertions
            specific = 0
            for a in t.assertions:
                if "==" in a or "!=" in a or "is" in a or "in" in a:
                    specific += 1
                if "Decimal" in a or "status" in a or "len" in a or "type" in a:
                    specific += 1
            # If average specific >= 1 per assert
            if specific >= len(t.assertions):
                good += 1
            else:
                bad += 1
                details.append(f"{key}: low specificity")
        score = (good / total_tests) * 100
        return {"score": round(score, 1), "good": good, "bad": bad, "details": details[:5]}

    def negative_path_coverage(self) -> Dict:
        total = len(self.test_funcs)
        if total == 0:
            return {"score": 0}
        has_error = sum(1 for t in self.test_funcs.values() if t.has_raises or "invalid" in t.name.lower() or "error" in t.name.lower() or "exception" in t.name.lower())
        score = (has_error / total) * 100
        return {"score": round(score, 1), "has_error": has_error, "total": total}

    def exception_coverage(self) -> Dict:
        # Count tests with raises
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
            # Cari angka keras (bukan 0, 1, -1 yang umum)
            numbers = re.findall(r'\b\d{2,}\b', t.source)
            if numbers:
                # Cek apakah ada konstanta di dekatnya
                for num in numbers:
                    # Cari apakah ada assignment ke variabel konstanta
                    if f"={num}" not in t.source:
                        magic_count += 1
        return {"magic_numbers": magic_count, "score": max(0, 100 - magic_count * 5)}

    # ---- Tier 2 ----

    def mock_quality(self) -> Dict:
        total = len(self.test_funcs)
        if total == 0:
            return {"score": 0, "avg_mock": 0}
        mock_count = sum(1 for t in self.test_funcs.values() if t.has_mock)
        avg_mock = sum(len(re.findall(r'Mock|patch|magicmock', t.source.lower())) for t in self.test_funcs.values()) / max(1, total)
        score = 100 - min(80, avg_mock * 20)  # penalti jika avg > 2
        return {"score": round(max(0, score), 1), "mock_count": mock_count, "avg_mock": round(avg_mock, 2)}

    def fixture_quality(self) -> Dict:
        fixtures = []
        for t in self.test_funcs.values():
            fixtures.extend(t.setup_fixtures)
        unique = set(fixtures)
        total = len(fixtures)
        # Deteksi fixture besar (by name)
        heavy = [f for f in unique if "db" in f or "session" in f or "client" in f]
        return {"total_fixtures": total, "unique": len(unique), "heavy": heavy[:5]}

    def duplicate_test_detector(self) -> Dict:
        # Group tests by content similarity (simple: first 3 lines + function name pattern)
        seen = {}
        duplicates = []
        for k, t in self.test_funcs.items():
            signature = t.name.split("_")[0]  # test_xxx
            if signature in seen:
                # Check if similar length and assertions count
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
        # Deteksi Arrange Act Assert dalam test
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

    # ---- Tier 3 ----

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
        total_roles = len(roles)
        return {"unique_roles": total_roles, "roles": list(roles)[:5]}

    # ---- Tier 4 ----

    def accounting_checker(self) -> Dict:
        # Cari source functions with accounting checks
        total_src = len(self.source_funcs)
        has_acct = sum(1 for f in self.source_funcs.values() if f.has_accounting_check)
        # Cek test yang memverifikasi debit==credit
        test_acct = 0
        for t in self.test_funcs.values():
            if any("debit" in a.lower() and "credit" in a.lower() for a in t.assertions):
                test_acct += 1
        score = (test_acct / max(1, total_src)) * 100
        return {"score": round(score, 1), "has_acct": has_acct, "test_acct": test_acct, "total_src": total_src}

    def inventory_checker(self) -> Dict:
        has_inv = sum(1 for f in self.source_funcs.values() if f.has_inventory_check)
        test_inv = 0
        for t in self.test_funcs.values():
            if any("stock" in a.lower() or "inventory" in a.lower() for a in t.assertions):
                test_inv += 1
        score = (test_inv / max(1, len(self.source_funcs))) * 100
        return {"score": round(score, 1), "has_inv": has_inv, "test_inv": test_inv}

    def fiscal_period_checker(self) -> Dict:
        has_period = sum(1 for f in self.source_funcs.values() if f.has_period_check)
        test_period = 0
        for t in self.test_funcs.values():
            if any("period" in a.lower() or "close" in a.lower() or "reopen" in a.lower() for a in t.assertions):
                test_period += 1
        score = (test_period / max(1, len(self.source_funcs))) * 100
        return {"score": round(score, 1), "has_period": has_period, "test_period": test_period}

    def multi_currency_checker(self) -> Dict:
        has_curr = sum(1 for f in self.source_funcs.values() if f.has_currency_convert)
        test_curr = 0
        for t in self.test_funcs.values():
            if any("usd" in a.lower() or "idr" in a.lower() or "eur" in a.lower() for a in t.assertions):
                test_curr += 1
        score = (test_curr / max(1, len(self.source_funcs))) * 100
        return {"score": round(score, 1), "has_curr": has_curr, "test_curr": test_curr}

    def precision_checker(self) -> Dict:
        has_decimal = sum(1 for f in self.source_funcs.values() if f.has_decimal_ops)
        test_decimal = 0
        for t in self.test_funcs.values():
            if any("decimal" in a.lower() or "quantize" in a.lower() for a in t.assertions):
                test_decimal += 1
            if t.uses_decimal:
                test_decimal += 1
        score = (test_decimal / max(1, len(self.source_funcs))) * 100
        return {"score": round(score, 1), "has_decimal": has_decimal, "test_decimal": test_decimal}

    # ---- Tier 5 ----

    def mutation_score(self) -> Tuple[float, float, float]:
        # Simulasi mutasi statis berdasarkan assertions
        total_mutation_points = 0
        covered = 0
        for s_func in self.source_funcs.values():
            points = s_func.branches + len(s_func.raises) + (1 if s_func.has_status_transition else 0)
            total_mutation_points += max(points, 1)
            # Cek jika fungsi di-test
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
        # Combine multiple metrics
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
        # Mutation
        mut, _, _ = self.mutation_score()
        scores.append(mut)
        return round(sum(scores) / len(scores), 1)

    def confidence_score(self, strength_score: float) -> float:
        # Confidence = strength_score adjusted by coverage and test density
        base = 50 + (strength_score / 2)
        # adjust by test count relative to source functions
        test_ratio = len(self.test_funcs) / max(1, len(self.source_funcs))
        confidence = base + min(20, test_ratio * 10)
        return min(99.5, confidence)

    def business_flow_coverage(self) -> Dict:
        # ERP-specific flows
        flows = {
            "Sales": ["create_sales_order", "approve_sales_order", "create_delivery_note", "issue_invoice", "receive_payment", "credit_note"],
            "Purchase": ["create_purchase_order", "approve_purchase_order", "receive_goods", "receive_invoice", "pay_invoice", "debit_note"],
            "Inventory": ["create_item", "adjust_stock", "transfer_warehouse", "stock_opname", "calculate_cogs", "valuation"],
            "Accounting": ["post_journal", "approve_journal", "reverse_journal", "close_period", "reopen_period", "reconcile_bank"],
            "Tax": ["calculate_ppn", "submit_faktur", "report_spt", "calculate_pph", "validate_ntpn"],
            "Payroll": ["create_payroll", "process_payroll", "approve_payroll", "pay_payroll", "post_payroll_gl", "generate_payslip"],
            "FixedAsset": ["create_asset", "depreciate", "dispose_asset", "revalue_asset", "impairment_test"],
            "IntangibleAsset": ["create_intangible", "amortize", "impairment_test_intangible"]
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
        # LOC vs Test ratio per file
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

    # ---- Tier 6 (26-50) ----

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
        # Detect global state mutation (staticmethod, classmethod, global vars)
        issues = []
        for k, t in self.test_funcs.items():
            if "global" in t.source:
                issues.append(f"{k}: uses global")
            if "classmethod" in t.source and "test" in t.name:
                issues.append(f"{k}: uses classmethod")
        return {"issues": len(issues), "details": issues[:5]}

    def random_order_checker(self) -> Dict:
        # Statis: cari dependency antar test berdasarkan shared state
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
        # Cek apakah test menguji class/function yang tidak ada di source
        orphans = []
        source_names = set(f.name for f in self.source_funcs.values())
        for k, t in self.test_funcs.items():
            # Ambil target dari nama test (test_xxx_yyy)
            parts = t.name.split("_")[1:]
            target = "_".join(parts) if parts else t.name
            if target and target not in source_names:
                orphans.append(k)
        return {"orphans": len(orphans), "details": orphans[:5]}

    def untested_exception_checker(self) -> Dict:
        # Exceptions raised in source but not tested
        all_raises = set()
        for f in self.source_funcs.values():
            all_raises.update(f.raises)
        tested_raises = set()
        for t in self.test_funcs.values():
            if t.has_raises:
                # Coba ambil exception name dari raises
                for a in t.assertions:
                    if "raises" in a:
                        # ekstrak
                        for exc in all_raises:
                            if exc in a:
                                tested_raises.add(exc)
        untested = all_raises - tested_raises
        return {"untested": len(untested), "details": list(untested)[:5]}

    def parametrize_quality(self) -> Dict:
        total = len(self.test_funcs)
        with_param = sum(1 for t in self.test_funcs.values() if t.has_parametrize)
        # Cari duplikasi (tests with same name prefix)
        prefix_count = defaultdict(int)
        for t in self.test_funcs.values():
            prefix = "_".join(t.name.split("_")[:2])
            prefix_count[prefix] += 1
        duplicates = {p: c for p, c in prefix_count.items() if c > 3}
        return {"with_param": with_param, "total": total, "duplicate_groups": len(duplicates)}

    def async_test_checker(self) -> Dict:
        total = len(self.test_funcs)
        async_tests = sum(1 for t in self.test_funcs.values() if t.is_async)
        # Cek apakah ada decorator @pytest.mark.asyncio
        has_mark = sum(1 for t in self.test_funcs.values() if t.is_async and any("asyncio" in d for d in t.decorators))
        return {"async_tests": async_tests, "has_mark": has_mark, "total": total}

    def transaction_rollback_checker(self) -> Dict:
        has_rollback = sum(1 for t in self.test_funcs.values() if t.has_rollback)
        total = len(self.test_funcs)
        score = (has_rollback / max(1, total)) * 100
        return {"score": round(score, 1), "has_rollback": has_rollback, "total": total}

    def event_consistency_checker(self) -> Dict:
        # Cek assert untuk aggregate_id, version, occurred_at
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
                # Cek apakah ada assert untuk topic, key, payload
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
                # Cek apakah ada assert untuk retry success/fail
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
        score = (tested_trans / max(1, total_trans)) * 100
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

# ========================================================================
# 4. MAIN ENGINE
# ========================================================================

class PytestQualityChecker:
    def __init__(self, root: Path):
        self.root = root
        self.parser = ASTParser(root)
        self.parser.scan_files()
        self.parser.parse_source_files()
        self.parser.parse_test_files()
        self.results = {}

    def run(self):
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
        mut_score, mut_covered, mut_total = analyzer.mutation_score()
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

        self.results = {
            "total_tests": len(test_funcs),
            "total_source_functions": len(source_funcs),
            "tested_functions": len(tested_funcs),
            "untested_functions": len(untested_funcs),
            "tier1": {
                "assertion_quality": aq,
                "negative_path": neg,
                "exception_coverage": exc,
                "edge_case": edge,
                "magic_number": magic,
            },
            "tier2": {
                "mock_quality": mock,
                "fixture_quality": fixture,
                "duplicate_test": dup,
                "test_naming": naming,
                "aaa_pattern": aaa,
            },
            "tier3": {
                "database_verification": db,
                "domain_event": event,
                "audit_log": audit,
                "idempotency": idempotent,
                "permission_test": permission,
            },
            "tier4": {
                "accounting": acct,
                "inventory": inv,
                "fiscal_period": period,
                "multi_currency": curr,
                "precision": prec,
            },
            "tier5": {
                "mutation_score": round(mut_score, 1),
                "test_strength": strength,
                "confidence_score": round(confidence, 1),
                "business_flow": flow,
                "regression_risk": reg_risk,
            },
            "tier6": {
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
            "overall_quality_score": round(strength, 1),
        }
        return self.results

# ========================================================================
# 5. REPORTER
# ========================================================================

def print_report(results: Dict[str, Any]):
    r = results
    print(f"\n{COLOR['BOLD']}{COLOR['CYAN']}╔════════════════════════════════════════════════════════════════════╗")
    print("║              PYTEST QUALITY CHECKER v5.0 (ERP FULL)           ║")
    print(f"╚════════════════════════════════════════════════════════════════════╝{COLOR['RESET']}")

    print(f"\n{COLOR['BOLD']}📊 OVERALL QUALITY SCORE: {COLOR['CYAN']}{r['overall_quality_score']}/100{COLOR['RESET']}")
    print(f"  🎯 Confidence Score          : {COLOR['GREEN']}{r['tier5']['confidence_score']:.1f}%{COLOR['RESET']}")
    print(f"  🧪 Total Tests Found         : {r['total_tests']}")
    print(f"  📄 Total Source Functions    : {r['total_source_functions']}")
    print(f"  ✅ Tested Functions          : {r['tested_functions']}")
    print(f"  ❌ Untested Functions        : {COLOR['RED']}{r['untested_functions']}{COLOR['RESET']}")

    # Tier1
    t1 = r['tier1']
    print(f"\n{COLOR['BOLD']}─── TIER 1 (Wajib) ───{COLOR['RESET']}")
    print(f"  Assertion Quality       : {t1['assertion_quality']['score']:.1f}%")
    print(f"  Negative Path           : {t1['negative_path']['score']:.1f}%")
    print(f"  Exception Coverage      : {t1['exception_coverage']['score']:.1f}%")
    print(f"  Edge Case               : {t1['edge_case']['score']:.1f}%")
    print(f"  Magic Number            : {t1['magic_number']['score']:.1f}%")

    # Tier2
    t2 = r['tier2']
    print(f"\n{COLOR['BOLD']}─── TIER 2 (Mock & Structure) ───{COLOR['RESET']}")
    print(f"  Mock Quality            : {t2['mock_quality']['score']:.1f}%")
    print(f"  Fixture Quality         : {t2['fixture_quality']['unique']} unique fixtures")
    print(f"  Duplicate Test          : {t2['duplicate_test']['duplicates']} duplicates")
    print(f"  Test Naming             : {t2['test_naming']['score']:.1f}%")
    print(f"  AAA Pattern             : {t2['aaa_pattern']['score']:.1f}%")

    # Tier3
    t3 = r['tier3']
    print(f"\n{COLOR['BOLD']}─── TIER 3 (Integration) ───{COLOR['RESET']}")
    print(f"  Database Verification   : {t3['database_verification']['score']:.1f}%")
    print(f"  Domain Event            : {t3['domain_event']['score']:.1f}%")
    print(f"  Audit Log               : {t3['audit_log']['score']:.1f}%")
    print(f"  Idempotency             : {t3['idempotency']['score']:.1f}%")
    print(f"  Permission Test         : {len(t3['permission_test']['roles'])} roles")

    # Tier4
    t4 = r['tier4']
    print(f"\n{COLOR['BOLD']}─── TIER 4 (ERP Specific) ───{COLOR['RESET']}")
    print(f"  Accounting (Debit=Credit): {t4['accounting']['score']:.1f}%")
    print(f"  Inventory               : {t4['inventory']['score']:.1f}%")
    print(f"  Fiscal Period           : {t4['fiscal_period']['score']:.1f}%")
    print(f"  Multi Currency          : {t4['multi_currency']['score']:.1f}%")
    print(f"  Precision (Decimal)     : {t4['precision']['score']:.1f}%")

    # Tier5
    t5 = r['tier5']
    print(f"\n{COLOR['BOLD']}─── TIER 5 (Advanced) ───{COLOR['RESET']}")
    print(f"  🧬 Mutation Score       : {COLOR['YELLOW']}{t5['mutation_score']:.1f}%{COLOR['RESET']}")
    print(f"  📈 Test Strength        : {t5['test_strength']:.1f}%")
    print(f"  🎯 Confidence           : {t5['confidence_score']:.1f}%")

    # Business Flow
    flow_sum = r['tier6']['business_flow_summary']
    print(f"\n{COLOR['BOLD']}─── BUSINESS FLOW COVERAGE ───{COLOR['RESET']}")
    for flow, data in flow_sum.items():
        color = COLOR["GREEN"] if data['pct'] >= 80 else COLOR["YELLOW"] if data['pct'] >= 50 else COLOR["RED"]
        print(f"  {flow:15} {color}{data['pct']:.1f}% ({data['covered']}/{data['total']}){COLOR['RESET']}")

    # Tier6 issues
    t6 = r['tier6']
    print(f"\n{COLOR['BOLD']}─── TIER 6 (Issues & Smells) ───{COLOR['RESET']}")
    if t6['flaky_tests']['count'] > 0:
        print(f"  {COLOR['RED']}⚠️ Flaky tests: {t6['flaky_tests']['count']}{COLOR['RESET']}")
    if t6['slow_tests']['count'] > 0:
        print(f"  {COLOR['YELLOW']}⚠️ Slow tests: {t6['slow_tests']['count']}{COLOR['RESET']}")
    if t6['dead_code']['count'] > 0:
        print(f"  {COLOR['RED']}❌ Dead test code: {t6['dead_code']['count']}{COLOR['RESET']}")
    if t6['orphan_tests']['orphans'] > 0:
        print(f"  {COLOR['RED']}❌ Orphan tests: {t6['orphan_tests']['orphans']}{COLOR['RESET']}")
    if t6['untested_functions']:
        print(f"  {COLOR['RED']}❌ Untested functions: {len(t6['untested_functions'])}{COLOR['RESET']}")
        for f in t6['untested_functions'][:5]:
            print(f"      - {f}")
    if t6['test_smells']:
        print(f"  {COLOR['YELLOW']}⚠️ Test smells: {len(t6['test_smells'])}{COLOR['RESET']}")
        for s in t6['test_smells'][:3]:
            print(f"      - {s['type']}: {s['file']} ({s['detail']})")
    if t6['state_transition']['score'] < 80:
        print(f"  {COLOR['YELLOW']}⚠️ State transition score: {t6['state_transition']['score']:.1f}%{COLOR['RESET']}")
    if t6['event_consistency']['score'] < 70:
        print(f"  {COLOR['YELLOW']}⚠️ Event consistency score: {t6['event_consistency']['score']:.1f}%{COLOR['RESET']}")

    # Regression Risk
    high_risk = [f for f, d in t5['regression_risk'].items() if d['risk'] == "HIGH"]
    if high_risk:
        print(f"\n{COLOR['RED']}⚠️ HIGH REGRESSION RISK:{COLOR['RESET']}")
        for f in high_risk[:5]:
            d = t5['regression_risk'][f]
            print(f"  {f}: LOC={d['loc']}, Tests={d['tests']}, Density={d['test_density']:.1f}%")

    # Recommendations
    print(f"\n{COLOR['BOLD']}─── RECOMMENDATIONS ───{COLOR['RESET']}")
    if t5['mutation_score'] < 70:
        print(f"  {COLOR['YELLOW']}🔧 Mutation Score rendah. Perkuat assertion spesifik (nilai, status, length).{COLOR['RESET']}")
    if t6['state_transition']['score'] < 80:
        print(f"  {COLOR['YELLOW']}🔧 State transition perlu ditingkatkan. Uji setiap perubahan status.{COLOR['RESET']}")
    if t6['event_consistency']['score'] < 70:
        print(f"  {COLOR['YELLOW']}🔧 Event consistency rendah. Verifikasi aggregate_id, version, timestamp.{COLOR['RESET']}")
    if t6['outbox']['score'] < 60:
        print(f"  {COLOR['YELLOW']}🔧 Outbox verification rendah. Tambahkan assert untuk outbox entry.{COLOR['RESET']}")
    if t6['flaky_tests']['count'] > 0:
        print(f"  {COLOR['RED']}🔧 Flaky tests detected. Gunakan mock untuk waktu/random dan fixture stabil.{COLOR['RESET']}")

    print("")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Pytest Quality Checker Full")
    parser.add_argument("--json", metavar="FILE", help="Ekspor laporan ke JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan detail")
    args = parser.parse_args()

    checker = PytestQualityChecker(ROOT)
    results = checker.run()

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"{COLOR['GREEN']}✅ Laporan diekspor ke {args.json}{COLOR['RESET']}")

    print_report(results)

    sys.exit(0)

if __name__ == "__main__":
    main()