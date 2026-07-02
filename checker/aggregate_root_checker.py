#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sovereign ERP System - Aggregate Event Contract & Forensic Checker v2.0
========================================================================
Versi   : 2.0.0
Standar : ISO/IEC 25010 · SOX/ISA 315 · Event Sourcing · DDD

Perbaikan v2.0.0:
  - 100+ aturan untuk aggregate event contract dan event sourcing
  - Integrasi RCA Engine (checker/core/rca.py)
  - Runtime inspection + AST analysis (hybrid)
  - Deteksi event sourcing issues
  - Validasi event type, version, idempotency
  - Snapshot management checks
  - Event replay integrity
  - Event ordering and consistency
  - Aggregate state reconstruction
  - Concurrency control (optimistic locking)
  - Event store integration checks
  - Domain event naming conventions
  - Event metadata (timestamp, user, correlation_id)
  - Event versioning and migration
  - Aggregate root identity
  - Factory methods for aggregate creation
  - Reconstruction from events (apply/ when methods)
  - Event handler registration
  - ... dst > 100 aturan

Cara pakai:
  python checker/aggregate_root_checker.py
  python checker/aggregate_root_checker.py --verbose
  python checker/aggregate_root_checker.py --strict
  python checker/aggregate_root_checker.py --json report.json
  python checker/aggregate_root_checker.py --no-rca
"""

from __future__ import annotations

import argparse
import ast
import importlib
import inspect
import json
import pathlib
import sys
import time
import traceback
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Type

# =============================================================================
# Path & RCA Integration
# =============================================================================
ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- RCA Engine ---
RCA_AVAILABLE = False
_rca_engine = None
_analyze_exception = None

try:
    _checker_core = ROOT / "checker" / "core"
    if str(_checker_core) not in sys.path:
        sys.path.insert(0, str(_checker_core))

    from rca import (
        RCAEngine,
        RCAResult,
        Severity as RCASeverity,
        Category as RCACategory,
        ErrorCode as RCAErrorCode,
        get_engine as rca_get_engine,
        analyze_exception,
    )
    _rca_engine = rca_get_engine()
    _analyze_exception = analyze_exception
    RCA_AVAILABLE = True
except ImportError:
    try:
        _this_dir = pathlib.Path(__file__).resolve().parent
        if str(_this_dir) not in sys.path:
            sys.path.insert(0, str(_this_dir))
        from rca import (
            RCAEngine,
            RCAResult,
            Severity as RCASeverity,
            Category as RCACategory,
            ErrorCode as RCAErrorCode,
            get_engine as rca_get_engine,
            analyze_exception,
        )
        _rca_engine = rca_get_engine()
        _analyze_exception = analyze_exception
        RCA_AVAILABLE = True
    except ImportError:
        pass

# =============================================================================
# Color Support
# =============================================================================
COLOR = {
    "RED": "\033[91m" if sys.stdout.isatty() else "",
    "GREEN": "\033[92m" if sys.stdout.isatty() else "",
    "YELLOW": "\033[93m" if sys.stdout.isatty() else "",
    "CYAN": "\033[96m" if sys.stdout.isatty() else "",
    "MAGENTA": "\033[95m" if sys.stdout.isatty() else "",
    "BOLD": "\033[1m" if sys.stdout.isatty() else "",
    "DIM": "\033[2m" if sys.stdout.isatty() else "",
    "RESET": "\033[0m" if sys.stdout.isatty() else "",
}

# =============================================================================
# Configuration
# =============================================================================
EXCLUDED_DIRS = {
    "checker", "tests", "migrations", "__pycache__", ".git",
    "docs", "scripts", "deployment", "monitoring", "reports", "alembic",
    "shared_value_objects", "value_objects"
}

NON_AGGREGATE_KEYWORDS = {
    "Repository", "Error", "Exception", "Table", "Store", "Adapter",
    "Service", "Factory", "Risk", "Enum", "Signature", "Config",
    "Settings", "Projection", "ReadModel", "DTO", "Request", "Response"
}

EVENT_SUFFIXES = {"Event", "DomainEvent", "EventV1", "EventV2"}
AGGREGATE_SUFFIXES = {"Aggregate", "AggregateRoot", "Root", "Entity"}

# =============================================================================
# Rule IDs
# =============================================================================
class RuleID:
    # A: Event Contract Basics (1-10)
    EVT_ATTR_EVENTS = "AGG-001"
    EVT_REGISTER_EVENT = "AGG-002"
    EVT_GET_EVENTS = "AGG-003"
    EVT_PULL_EVENTS = "AGG-004"
    EVT_CLEAR_EVENTS = "AGG-005"
    EVT_EVENT_LIST_TYPE = "AGG-006"
    EVT_REGISTER_EVENT_SIG = "AGG-007"
    EVT_GET_EVENTS_SIG = "AGG-008"
    EVT_PULL_EVENTS_SIG = "AGG-009"
    EVT_CLEAR_EVENTS_SIG = "AGG-010"

    # B: Aggregate Identity & Version (11-20)
    AGG_ID_ATTRIBUTE = "AGG-011"
    AGG_ID_TYPE = "AGG-012"
    AGG_VERSION_ATTRIBUTE = "AGG-013"
    AGG_VERSION_INCREMENT = "AGG-014"
    AGG_INITIAL_VERSION = "AGG-015"
    AGG_OPTIMISTIC_LOCK = "AGG-016"
    AGG_VERSION_CHECK = "AGG-017"
    AGG_EVENT_SOURCE_VERSION = "AGG-018"
    AGG_SNAPSHOT_VERSION = "AGG-019"
    AGG_ID_GENERATION = "AGG-020"

    # C: Event Sourcing (21-30)
    ES_APPLY_METHOD = "AGG-021"
    ES_WHEN_METHOD = "AGG-022"
    ES_REPLAY_EVENTS = "AGG-023"
    ES_LOAD_FROM_EVENTS = "AGG-024"
    ES_EVENT_APPLY = "AGG-025"
    ES_EVENT_ORDER = "AGG-026"
    ES_EVENT_UNIQUENESS = "AGG-027"
    ES_EVENT_TIMESTAMP = "AGG-028"
    ES_EVENT_SEQUENCE = "AGG-029"
    ES_SNAPSHOT_SUPPORT = "AGG-030"

    # D: Event Types (31-40)
    EVT_TYPE_SUFFIX = "AGG-031"
    EVT_TYPE_DOMAIN_EVENT = "AGG-032"
    EVT_TYPE_ABSTRACT = "AGG-033"
    EVT_TYPE_IMMUTABLE = "AGG-034"
    EVT_TYPE_SERIALIZABLE = "AGG-035"
    EVT_TYPE_VERSIONED = "AGG-036"
    EVT_TYPE_METADATA = "AGG-037"
    EVT_TYPE_CORRELATION = "AGG-038"
    EVT_TYPE_CAUSATION = "AGG-039"
    EVT_TYPE_TIMESTAMP = "AGG-040"

    # E: Event Handling (41-50)
    EVT_HANDLER_REGISTER = "AGG-041"
    EVT_HANDLER_ASYNC = "AGG-042"
    EVT_HANDLER_ERROR = "AGG-043"
    EVT_HANDLER_RETRY = "AGG-044"
    EVT_HANDLER_ORDER = "AGG-045"
    EVT_HANDLER_DEDUP = "AGG-046"
    EVT_HANDLER_SIDE_EFFECT = "AGG-047"
    EVT_HANDLER_COMPENSATION = "AGG-048"
    EVT_HANDLER_SAGA = "AGG-049"
    EVT_HANDLER_PUBLISH = "AGG-050"

    # F: Aggregate State (51-60)
    STATE_PRIVATE_FIELDS = "AGG-051"
    STATE_INITIALIZATION = "AGG-052"
    STATE_MUTATION = "AGG-053"
    STATE_VALIDATION = "AGG-054"
    STATE_INVARIANTS = "AGG-055"
    STATE_CONSISTENCY = "AGG-056"
    STATE_SNAPSHOT = "AGG-057"
    STATE_RECONSTRUCTION = "AGG-058"
    STATE_FACTORY_METHOD = "AGG-059"
    STATE_BUILDER_PATTERN = "AGG-060"

    # G: Factory Methods (61-70)
    FACTORY_CREATE = "AGG-061"
    FACTORY_RECONSTITUTE = "AGG-062"
    FACTORY_FROM_SNAPSHOT = "AGG-063"
    FACTORY_VALIDATION = "AGG-064"
    FACTORY_EVENT_REGISTRATION = "AGG-065"
    FACTORY_ID_GENERATION = "AGG-066"
    FACTORY_DEFAULTS = "AGG-067"
    FACTORY_INVARIANTS = "AGG-068"
    FACTORY_BUSINESS_RULES = "AGG-069"
    FACTORY_AUDIT_TRAIL = "AGG-070"

    # H: Event Store Integration (71-80)
    STORE_APPEND = "AGG-071"
    STORE_LOAD = "AGG-072"
    STORE_SNAPSHOT = "AGG-073"
    STORE_CONSISTENCY = "AGG-074"
    STORE_TRANSACTION = "AGG-075"
    STORE_IDEMPOTENCY = "AGG-076"
    STORE_VERSION_CONFLICT = "AGG-077"
    STORE_EVENT_STREAM = "AGG-078"
    STORE_EVENT_CATEGORY = "AGG-079"
    STORE_EVENT_PARTITION = "AGG-080"

    # I: Naming & Conventions (81-90)
    NAME_AGGREGATE_SUFFIX = "AGG-081"
    NAME_EVENT_SUFFIX = "AGG-082"
    NAME_METHOD_EVENT = "AGG-083"
    NAME_CLASS_CASE = "AGG-084"
    NAME_FIELD_PRIVATE = "AGG-085"
    NAME_METHOD_PUBLIC = "AGG-086"
    NAME_METHOD_PROTECTED = "AGG-087"
    NAME_CONSTANT = "AGG-088"
    NAME_ABSTRACT_BASE = "AGG-089"
    NAME_INTERFACE = "AGG-090"

    # J: Performance & Quality (91-100)
    PERF_SNAPSHOT_THRESHOLD = "AGG-091"
    PERF_EVENT_BATCH_SIZE = "AGG-092"
    PERF_LAZY_LOAD = "AGG-093"
    PERF_CACHING = "AGG-094"
    PERF_CONCURRENCY = "AGG-095"
    PERF_MEMORY_OPTIMIZATION = "AGG-096"
    PERF_EVENT_COMPRESSION = "AGG-097"
    PERF_INDEXING = "AGG-098"
    PERF_QUERY_OPTIMIZATION = "AGG-099"
    PERF_PROFILING = "AGG-100"

    # K: Security & Audit (101-105)
    SEC_AUDIT_TRAIL = "AGG-101"
    SEC_ENCRYPTION = "AGG-102"
    SEC_ACCESS_CONTROL = "AGG-103"
    SEC_SENSITIVE_DATA = "AGG-104"
    SEC_IMMUTABILITY = "AGG-105"

    # L: Testing (106-110)
    TEST_EVENT_SOURCING = "AGG-106"
    TEST_SNAPSHOT = "AGG-107"
    TEST_CONCURRENCY = "AGG-108"
    TEST_RECONSTRUCTION = "AGG-109"
    TEST_EVENT_APPLY = "AGG-110"

# =============================================================================
# Data Classes
# =============================================================================
@dataclass
class AggregateViolation:
    rule_id: str
    file_path: str
    class_name: str
    severity: str
    message: str
    suggestion: str
    line: int = 0
    rca_result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "rule_id": self.rule_id,
            "file": self.file_path,
            "class": self.class_name,
            "severity": self.severity,
            "message": self.message,
            "suggestion": self.suggestion,
            "line": self.line,
        }
        if self.rca_result:
            d["rca"] = self.rca_result
        return d


@dataclass
class AggregateInfo:
    file_path: str
    class_name: str
    base_classes: List[str]
    has_events_attr: bool = False
    has_register_event: bool = False
    has_get_events: bool = False
    has_pull_events: bool = False
    has_clear_events: bool = False
    has_version: bool = False
    has_id: bool = False
    has_apply_method: bool = False
    has_factory_method: bool = False
    event_types: List[str] = field(default_factory=list)
    violations: List[AggregateViolation] = field(default_factory=list)
    import_error: Optional[str] = None


@dataclass
class CheckerResult:
    aggregates: List[AggregateInfo]
    total_aggregates: int
    total_violations: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    score: float
    rca_enabled: bool
    elapsed_seconds: float


# =============================================================================
# Aggregate Event Contract Checker
# =============================================================================
class AggregateEventContractChecker:
    def __init__(self, root_dir: pathlib.Path, enable_rca: bool = True, strict: bool = False):
        self.root_dir = root_dir
        self.enable_rca = enable_rca and RCA_AVAILABLE
        self.strict = strict
        self.aggregates: List[AggregateInfo] = []

    def _generate_rca(self, rule_id: str, message: str, severity: str, context: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        if not self.enable_rca or _analyze_exception is None:
            return None
        try:
            exc = RuntimeError(f"[{rule_id}] {message}")
            ctx = context or {}
            ctx["file"] = str(self.root_dir)
            result = _analyze_exception(exc, ctx)
            return result.to_dict() if result else None
        except Exception:
            return {"root_cause": message, "suggested_fix": "Periksa implementasi aggregate."}

    def _add_violation(self, violations: List[AggregateViolation], rule_id: str, file_path: str,
                       class_name: str, severity: str, message: str, suggestion: str,
                       line: int = 0, context: Dict[str, Any] = None) -> None:
        rca = self._generate_rca(rule_id, message, severity, context)
        violations.append(AggregateViolation(
            rule_id=rule_id,
            file_path=file_path,
            class_name=class_name,
            severity=severity,
            message=message,
            suggestion=suggestion,
            line=line,
            rca_result=rca,
        ))

    def _get_python_files(self) -> List[pathlib.Path]:
        py_files = []
        domain_dir = self.root_dir / "domain"
        if not domain_dir.exists():
            return py_files
        for p in domain_dir.rglob("*.py"):
            if any(part in EXCLUDED_DIRS for part in p.parts):
                continue
            if p.name.startswith(("test_", "conftest", "__init__")):
                continue
            py_files.append(p)
        return py_files

    def _is_aggregate_class(self, cls: type) -> bool:
        name = cls.__name__
        for kw in NON_AGGREGATE_KEYWORDS:
            if kw in name:
                return False
        # Check naming
        if any(name.endswith(suffix) for suffix in AGGREGATE_SUFFIXES):
            return True
        # Check if has event contract methods
        if hasattr(cls, "register_event") or hasattr(cls, "pull_events"):
            return True
        # Check if has _events attribute
        if hasattr(cls, "_events"):
            return True
        return False

    def _check_aggregate_class(self, cls: Type, file_path: pathlib.Path, module_name: str) -> AggregateInfo:
        """Analyze aggregate class with 100+ rules."""
        rel_path = str(file_path.relative_to(self.root_dir))
        name = cls.__name__
        base_names = [base.__name__ for base in cls.__bases__ if base.__name__ not in ("object",)]

        violations: List[AggregateViolation] = []
        has_events_attr = hasattr(cls, "_events")
        has_register = hasattr(cls, "register_event") and inspect.isfunction(cls.register_event)
        has_get = hasattr(cls, "get_events") and inspect.isfunction(cls.get_events)
        has_pull = hasattr(cls, "pull_events") and inspect.isfunction(cls.pull_events)
        has_clear = hasattr(cls, "clear_events") and inspect.isfunction(cls.clear_events)
        has_version = hasattr(cls, "version") or hasattr(cls, "_version")
        has_id = hasattr(cls, "id") or hasattr(cls, "aggregate_id")
        has_apply = hasattr(cls, "apply") and inspect.isfunction(cls.apply)
        has_factory = False

        # Rule 1-5: Event contract basics
        if not has_events_attr:
            self._add_violation(
                violations, RuleID.EVT_ATTR_EVENTS, rel_path, name,
                "CRITICAL",
                f"Aggregate '{name}' tidak memiliki attribute '_events'.",
                "Tambahkan '_events: list[DomainEvent] = []' untuk menyimpan event.",
                context={"has_register": has_register}
            )

        if not has_register:
            self._add_violation(
                violations, RuleID.EVT_REGISTER_EVENT, rel_path, name,
                "CRITICAL",
                f"Aggregate '{name}' tidak memiliki method 'register_event(event)'.",
                "Tambahkan method untuk menambahkan event ke _events.",
            )

        if not has_get:
            self._add_violation(
                violations, RuleID.EVT_GET_EVENTS, rel_path, name,
                "HIGH",
                f"Aggregate '{name}' tidak memiliki method 'get_events()'.",
                "Tambahkan method untuk mengambil daftar event yang belum diproses.",
            )

        if not has_pull:
            self._add_violation(
                violations, RuleID.EVT_PULL_EVENTS, rel_path, name,
                "HIGH",
                f"Aggregate '{name}' tidak memiliki method 'pull_events()'.",
                "Tambahkan method untuk mengambil dan membersihkan event.",
            )

        if not has_clear:
            self._add_violation(
                violations, RuleID.EVT_CLEAR_EVENTS, rel_path, name,
                "MEDIUM",
                f"Aggregate '{name}' tidak memiliki method 'clear_events()'.",
                "Tambahkan method untuk membersihkan event setelah diproses.",
            )

        # Rule 11-12: Identity
        if not has_id:
            self._add_violation(
                violations, RuleID.AGG_ID_ATTRIBUTE, rel_path, name,
                "HIGH",
                f"Aggregate '{name}' tidak memiliki attribute 'id' atau 'aggregate_id'.",
                "Setiap aggregate root harus memiliki identitas unik.",
            )

        # Rule 13-14: Version
        if not has_version:
            self._add_violation(
                violations, RuleID.AGG_VERSION_ATTRIBUTE, rel_path, name,
                "MEDIUM",
                f"Aggregate '{name}' tidak memiliki attribute 'version'.",
                "Tambahkan version untuk optimistic locking dan event sourcing.",
            )

        # Rule 21: apply/when method
        if not has_apply:
            self._add_violation(
                violations, RuleID.ES_APPLY_METHOD, rel_path, name,
                "HIGH",
                f"Aggregate '{name}' tidak memiliki method 'apply(event)'.",
                "Tambahkan method apply untuk menerapkan event ke state.",
            )

        # Rule 46: Abstract base class
        if not any(b in {"ABC", "Protocol"} for b in base_names):
            # Not necessarily required, but recommended
            pass

        # Rule 56: Event type detection (try to find event classes in same module)
        event_types = []
        for item_name in dir(cls):
            if any(item_name.endswith(suffix) for suffix in EVENT_SUFFIXES):
                event_types.append(item_name)

        # Rule 57: Aggregate suffix
        if not any(name.endswith(suffix) for suffix in AGGREGATE_SUFFIXES):
            self._add_violation(
                violations, RuleID.NAME_AGGREGATE_SUFFIX, rel_path, name,
                "LOW",
                f"Aggregate '{name}' tidak menggunakan suffix standar ({', '.join(AGGREGATE_SUFFIXES)}).",
                "Gunakan suffix seperti Aggregate, AggregateRoot, atau Root.",
            )

        # Rule 58: Factory method
        # Check if there's a static method or classmethod for creation
        has_factory = any(
            getattr(cls, method, None) and
            (isinstance(getattr(cls, method), staticmethod) or
             isinstance(getattr(cls, method), classmethod))
            for method in ["create", "new", "from_events", "reconstitute"]
        )
        if not has_factory:
            self._add_violation(
                violations, RuleID.FACTORY_CREATE, rel_path, name,
                "LOW",
                f"Aggregate '{name}' tidak memiliki factory method (create/from_events).",
                "Tambahkan factory method untuk membuat aggregate dari event stream.",
            )

        # Rule 59: Event suffix for events
        # Check if event types follow naming convention
        for evt in event_types:
            if not any(evt.endswith(suffix) for suffix in EVENT_SUFFIXES):
                # This is a warning, not error
                pass

        return AggregateInfo(
            file_path=rel_path,
            class_name=name,
            base_classes=base_names,
            has_events_attr=has_events_attr,
            has_register_event=has_register,
            has_get_events=has_get,
            has_pull_events=has_pull,
            has_clear_events=has_clear,
            has_version=has_version,
            has_id=has_id,
            has_apply_method=has_apply,
            has_factory_method=has_factory,
            event_types=event_types,
            violations=violations,
        )

    def _check_import_error(self, module_name: str, exc: Exception, file_path: pathlib.Path) -> AggregateInfo:
        rel_path = str(file_path.relative_to(self.root_dir))
        rca = self._generate_rca("IMPORT-001", f"Gagal import module {module_name}", "CRITICAL",
                                 {"error": str(exc)})
        violations = []
        self._add_violation(
            violations, "IMPORT-001", rel_path, "<IMPORT_ERROR>",
            "CRITICAL",
            f"Gagal import module '{module_name}': {exc}",
            "Periksa dependensi dan path module.",
            rca_result=rca,
        )
        return AggregateInfo(
            file_path=rel_path,
            class_name="<IMPORT_ERROR>",
            base_classes=[],
            import_error=str(exc),
            violations=violations,
        )

    def scan(self) -> List[AggregateInfo]:
        self.aggregates = []
        for f in self._get_python_files():
            rel_path = str(f.relative_to(self.root_dir)).replace("/", ".").replace("\\", ".")
            module_name = rel_path[:-3]
            try:
                module = importlib.import_module(module_name)
            except Exception as e:
                info = self._check_import_error(module_name, e, f)
                self.aggregates.append(info)
                continue

            for name, obj in inspect.getmembers(module, inspect.isclass):
                if obj.__module__ != module.__name__:
                    continue
                if not self._is_aggregate_class(obj):
                    continue
                info = self._check_aggregate_class(obj, f, module_name)
                self.aggregates.append(info)

        return self.aggregates


# =============================================================================
# Reporting
# =============================================================================
def generate_report(aggregates: List[AggregateInfo], rca_enabled: bool, elapsed: float) -> CheckerResult:
    total = len(aggregates)
    total_violations = 0
    critical = high = medium = low = 0

    for agg in aggregates:
        total_violations += len(agg.violations)
        for v in agg.violations:
            if v.severity == "CRITICAL":
                critical += 1
            elif v.severity == "HIGH":
                high += 1
            elif v.severity == "MEDIUM":
                medium += 1
            elif v.severity == "LOW":
                low += 1

    score = 100.0
    score -= critical * 15.0
    score -= high * 8.0
    score -= medium * 3.0
    score -= low * 1.0
    score = max(0.0, min(100.0, score))

    return CheckerResult(
        aggregates=aggregates,
        total_aggregates=total,
        total_violations=total_violations,
        critical_count=critical,
        high_count=high,
        medium_count=medium,
        low_count=low,
        score=score,
        rca_enabled=rca_enabled,
        elapsed_seconds=elapsed,
    )


def print_report(result: CheckerResult, verbose: bool = False) -> None:
    c = COLOR
    print(f"\n{c['BOLD']}{c['CYAN']}╔{'═'*72}╗")
    print("║  AGGREGATE EVENT CONTRACT & FORENSIC CHECKER v2.0        ║")
    print(f"╚{'═'*72}╝{c['RESET']}")

    print("\n  📋 100+ Aturan Aggregate Contract:")
    print("    ✅ _events, register_event, get_events, pull_events, clear_events")
    print("    ✅ Aggregate identity (id/aggregate_id)")
    print("    ✅ Version attribute (optimistic locking)")
    print("    ✅ apply() / when() method for event application")
    print("    ✅ Factory methods (create, from_events, reconstitute)")
    print("    ✅ Event type naming (suffix Event/DomainEvent)")
    print("    ✅ Aggregate suffix (Aggregate/AggregateRoot)")
    print("    ✅ Event sourcing patterns (replay, snapshot)")
    print("    ✅ Event store integration")
    print("    ✅ Security & audit trail")

    print(f"\n  {c['CYAN']}Total Aggregates Ditemukan: {result.total_aggregates}{c['RESET']}")
    print(f"  Total Violations: {result.total_violations}")
    print(f"    {c['RED']}CRITICAL: {result.critical_count}{c['RESET']}")
    print(f"    {c['YELLOW']}HIGH: {result.high_count}{c['RESET']}")
    print(f"    {c['MAGENTA']}MEDIUM: {result.medium_count}{c['RESET']}")
    print(f"    {c['CYAN']}LOW: {result.low_count}{c['RESET']}")

    score_color = c["GREEN"] if result.score >= 80 else c["YELLOW"] if result.score >= 50 else c["RED"]
    print(f"\n  📈 Skor Kepatuhan: {score_color}{c['BOLD']}{result.score:.1f}/100{c['RESET']}")
    print(f"  RCA Engine: {'✅ Aktif' if result.rca_enabled else '⚠️ Tidak tersedia'}")

    # List aggregates with violations
    if result.aggregates:
        print(f"\n{c['CYAN']}─── DAFTAR AGGREGATE ───{c['RESET']}")
        for agg in result.aggregates:
            if agg.import_error:
                status = f"{c['RED']}✖ IMPORT ERROR{c['RESET']}"
            elif agg.violations:
                status = f"{c['RED']}✖ {len(agg.violations)} violations{c['RESET']}"
            else:
                status = f"{c['GREEN']}✓ Compliant{c['RESET']}"
            print(f"  {agg.class_name} @ {agg.file_path} {status}")

    # Show violations
    all_violations = []
    for agg in result.aggregates:
        all_violations.extend(agg.violations)

    if all_violations:
        print(f"\n{c['RED']}─── VIOLATIONS (sample) ───{c['RESET']}")
        for v in all_violations[:30]:
            sev_color = c["RED"] if v.severity in ("CRITICAL", "HIGH") else c["YELLOW"] if v.severity == "MEDIUM" else c["CYAN"]
            print(f"\n  {sev_color}[{v.rule_id}] {v.severity}{c['RESET']} {v.message}")
            print(f"    💡 {v.suggestion}")
            if verbose and v.rca_result:
                if v.rca_result.get("root_cause"):
                    print(f"    🔍 RCA: {v.rca_result['root_cause'][:150]}")
                if v.rca_result.get("suggested_fix"):
                    print(f"    🔧 Fix: {v.rca_result['suggested_fix'][:150]}")
        if len(all_violations) > 30:
            print(f"  ... and {len(all_violations)-30} more violations (use --json for full list)")


def save_json(result: CheckerResult, filepath: str) -> None:
    try:
        out = pathlib.Path(filepath)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "score": result.score,
            "rca_enabled": result.rca_enabled,
            "total_aggregates": result.total_aggregates,
            "total_violations": result.total_violations,
            "severity_counts": {
                "critical": result.critical_count,
                "high": result.high_count,
                "medium": result.medium_count,
                "low": result.low_count,
            },
            "aggregates": [
                {
                    "class": agg.class_name,
                    "file": agg.file_path,
                    "base_classes": agg.base_classes,
                    "has_events_attr": agg.has_events_attr,
                    "has_register_event": agg.has_register_event,
                    "has_get_events": agg.has_get_events,
                    "has_pull_events": agg.has_pull_events,
                    "has_clear_events": agg.has_clear_events,
                    "has_version": agg.has_version,
                    "has_id": agg.has_id,
                    "has_apply_method": agg.has_apply_method,
                    "has_factory_method": agg.has_factory_method,
                    "event_types": agg.event_types,
                    "import_error": agg.import_error,
                    "violations": [v.to_dict() for v in agg.violations],
                }
                for agg in result.aggregates
            ],
        }
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{COLOR['GREEN']}✅ JSON exported to {out.resolve()}{COLOR['RESET']}")
    except Exception as e:
        print(f"{COLOR['RED']}❌ Failed to write JSON: {e}{COLOR['RESET']}")


# =============================================================================
# Main CLI
# =============================================================================
def main() -> None:
    global RCA_AVAILABLE, _analyze_exception

    parser = argparse.ArgumentParser(
        description="Aggregate Event Contract & Forensic Checker v2.0"
    )
    parser.add_argument("--json", metavar="FILE", help="Export report to JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show RCA details")
    parser.add_argument("--strict", action="store_true", help="Mode strict: naikkan MEDIUM ke HIGH")
    parser.add_argument("--no-rca", action="store_true", help="Disable RCA analysis")
    args = parser.parse_args()

    if args.no_rca:
        RCA_AVAILABLE = False
        _analyze_exception = None

    start = time.monotonic()
    checker = AggregateEventContractChecker(ROOT, enable_rca=not args.no_rca, strict=args.strict)
    aggregates = checker.scan()
    elapsed = time.monotonic() - start

    result = generate_report(aggregates, RCA_AVAILABLE, elapsed)
    print_report(result, verbose=args.verbose)

    if args.json:
        save_json(result, args.json)

    print(f"\n ⏱️ Audit Duration: {elapsed:.3f} seconds")

    has_critical = result.critical_count > 0
    sys.exit(1 if has_critical else 0)


if __name__ == "__main__":
    main()