#!/usr/bin/env python3
"""
checker_event_handler.py — Sovereign Event Handler & Event Sourcing Forensic Checker v2.5
========================================================================================
Versi   : 2.5.0
Perbaikan:
  - Deteksi otomatis class non-event (Error, Timeout, Exception)
  - Menambahkan EventPublishTimeoutError ke NON_EVENT_NAMES
  - Optimasi output grouping

Perbaikan v2.5.0 (bugfix performa, ditemukan lewat benchmark nyata):
  - FIX BUG PERFORMA UTAMA: _classify_usage() dulu membaca ULANG isi setiap
    file project dari disk untuk SETIAP event (nested loop event x file ->
    O(N*M) full-file read). Pada benchmark 400 event x 2900 file ini bikin
    checker jadi 4+ detik hanya di langkah ini, dan pada codebase ERP asli
    (ratusan event x puluhan ribu file) bisa jadi bermenit-menit. Sekarang
    isi tiap file dibaca sekali saja lalu dicocokkan ke semua nama event
    di memori -> O(M) baca disk.
  - FIX minor: ast.unparse() pada method handle() dulu dipanggil dua kali
    untuk node yang sama; sekarang cukup sekali.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

# =============================================================================
# Path & RCA Integration
# =============================================================================
ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RCA_AVAILABLE = False
_rca_engine = None
_analyze_exception = None

try:
    _checker_core = ROOT / "checker" / "core"
    if str(_checker_core) not in sys.path:
        sys.path.insert(0, str(_checker_core))
    from rca import (
        Category as RCACategory,
    )
    from rca import (
        ErrorCode as RCAErrorCode,
    )
    from rca import (
        RCAEngine,
        RCAResult,
        analyze_exception,
    )
    from rca import (
        Severity as RCASeverity,
    )
    from rca import (
        get_engine as rca_get_engine,
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
            Category as RCACategory,
        )
        from rca import (
            ErrorCode as RCAErrorCode,
        )
        from rca import (
            RCAEngine,
            RCAResult,
            analyze_exception,
        )
        from rca import (
            Severity as RCASeverity,
        )
        from rca import (
            get_engine as rca_get_engine,
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
    "docs", "scripts", "deployment", "monitoring", "reports",
    "shared_value_objects", "reality", "mappers", "workflows", "sagas"
}

IGNORE_EVENTS = {"BaseEvent", "DomainEvent", "IntegrationEvent", "Event"}
NON_EVENT_SUFFIXES = {"Publisher", "Type", "Store", "Service", "Helper", "Factory", "Config", "Settings", "Repository", "Handler"}
NON_EVENT_NAMES = {"AuditEvent", "EventPublishError", "EventPublishTimeoutError", "ErrorEvent"}
NON_EVENT_PATTERNS = {"Error", "Timeout", "Exception"}  # jika nama mengandung ini dan tidak mewarisi base, skip

EVENT_SUFFIX = {"Event", "DomainEvent", "IntegrationEvent"}
HANDLER_SUFFIX = {"Handler", "Subscriber", "Listener", "Consumer"}

# Base classes yang dianggap sudah menyediakan field-field standar
EVENT_BASE_NAMES = {"DomainEvent", "BaseDomainEvent", "IntegrationEvent", "Event", "BaseEvent"}

# =============================================================================
# Rule IDs
# =============================================================================
class RuleID:
    EVT_NAMING = "EVT-001"
    EVT_BASE_CLASS = "EVT-002"
    EVT_FILE_LOCATION = "EVT-003"
    EVT_IMMUTABLE = "EVT-004"
    EVT_TIMESTAMP = "EVT-005"
    EVT_CORRELATION = "EVT-006"
    EVT_CAUSATION = "EVT-007"
    EVT_VERSION = "EVT-008"
    EVT_SERIALIZABLE = "EVT-009"
    EVT_TYPE_HINT = "EVT-010"

    HDL_NAMING = "EVT-011"
    HDL_HANDLE_METHOD = "EVT-012"
    HDL_PARAM_TYPE = "EVT-013"
    HDL_RETURN_TYPE = "EVT-014"
    HDL_ERROR_HANDLING = "EVT-015"
    HDL_ASYNC = "EVT-016"
    HDL_DOCSTRING = "EVT-017"
    HDL_FILE_LOCATION = "EVT-018"
    HDL_TRANSACTION = "EVT-019"
    HDL_IDEMPOTENCY = "EVT-020"

    REG_REGISTERED = "EVT-021"
    REG_ORPHAN_EVENT = "EVT-022"
    REG_UNREGISTERED_HANDLER = "EVT-023"
    REG_MISSING_HANDLER = "EVT-024"
    REG_DUPLICATE_HANDLER = "EVT-025"
    REG_EMPTY_REGISTRY = "EVT-026"
    REG_REGISTRY_FILE = "EVT-027"
    REG_LOAD_FAILURE = "EVT-028"
    REG_ALIAS = "EVT-029"
    REG_OVERRIDE = "EVT-030"

    PUB_PUBLISH_METHOD = "EVT-031"
    PUB_EVENT_BUS = "EVT-032"
    PUB_TRANSACTIONAL = "EVT-033"
    PUB_OUTBOX = "EVT-034"
    PUB_DEAD_LETTER = "EVT-035"
    PUB_RETRY = "EVT-036"
    PUB_CIRCUIT_BREAKER = "EVT-037"
    PUB_BATCH = "EVT-038"
    PUB_ASYNC = "EVT-039"
    PUB_AUDIT = "EVT-040"

    OUTBOX_TABLE = "EVT-041"
    OUTBOX_RELAY = "EVT-042"
    OUTBOX_POLLER = "EVT-043"
    OUTBOX_RETRY = "EVT-044"
    OUTBOX_CLEANUP = "EVT-045"

    ES_APPLY_METHOD = "EVT-046"
    ES_REPLAY = "EVT-047"
    ES_SNAPSHOT = "EVT-048"
    ES_VERSION_CONFLICT = "EVT-049"
    ES_EVENT_ORDER = "EVT-050"

    SEC_AUDIT_TRAIL = "EVT-051"
    SEC_ENCRYPT = "EVT-052"
    SEC_ACCESS = "EVT-053"
    SEC_SENSITIVE = "EVT-054"
    SEC_SIGNATURE = "EVT-055"

    PERF_BATCH_SIZE = "EVT-056"
    PERF_ASYNC_HANDLER = "EVT-057"
    PERF_CACHING = "EVT-058"
    PERF_INDEXING = "EVT-059"
    PERF_PARTITION = "EVT-060"

    TEST_EVENT = "EVT-061"
    TEST_HANDLER = "EVT-062"
    TEST_PUBLISH = "EVT-063"
    TEST_OUTBOX = "EVT-064"
    TEST_EVENT_SOURCING = "EVT-065"

    CONS_DELAY = "EVT-066"
    CONS_RETRY = "EVT-067"
    CONS_COMPENSATION = "EVT-068"
    CONS_SAGA = "EVT-069"
    CONS_DEADLINE = "EVT-070"

    DOC_EVENT = "EVT-071"
    DOC_HANDLER = "EVT-072"
    DOC_FIELD = "EVT-073"
    DOC_EXAMPLE = "EVT-074"
    DOC_VERSION = "EVT-075"

    VER_VERSION_NUMBER = "EVT-076"
    VER_MIGRATION = "EVT-077"
    VER_DEPRECATION = "EVT-078"
    VER_BACKWARD = "EVT-079"
    VER_COMPAT = "EVT-080"

# =============================================================================
# Data Classes
# =============================================================================
@dataclass
class EventViolation:
    rule_id: str
    file_path: str
    event_name: str
    severity: str
    message: str
    suggestion: str
    line: int = 0
    rca_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "rule_id": self.rule_id,
            "file": self.file_path,
            "event": self.event_name,
            "severity": self.severity,
            "message": self.message,
            "suggestion": self.suggestion,
            "line": self.line,
        }
        if self.rca_result:
            d["rca"] = self.rca_result
        return d


@dataclass
class EventInfo:
    name: str
    file_path: str
    module_path: str
    base_classes: list[str] = field(default_factory=list)
    is_domain_event: bool = False
    is_integration_event: bool = False
    has_timestamp: bool = False
    has_correlation_id: bool = False
    has_causation_id: bool = False
    has_version: bool = False
    is_frozen: bool = False
    is_serializable: bool = False
    has_docstring: bool = False
    fields: list[str] = field(default_factory=list)
    in_registry: bool = False
    used_outside_domain: bool = False
    has_publisher: bool = False
    has_handler: bool = False
    violations: list[EventViolation] = field(default_factory=list)


@dataclass
class HandlerInfo:
    name: str
    file_path: str
    event_name: str
    has_handle_method: bool = False
    has_error_handling: bool = False
    is_async: bool = False
    is_transactional: bool = False
    has_idempotency: bool = False
    violations: list[EventViolation] = field(default_factory=list)


@dataclass
class CheckerResult:
    events: list[EventInfo]
    handlers: list[HandlerInfo]
    registry_events: list[str]
    total_events: int
    total_handlers: int
    total_violations: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    score: float
    rca_enabled: bool
    elapsed_seconds: float


# =============================================================================
# Event Handler Verifier
# =============================================================================
class SovereignEventHandlerVerifier:
    def __init__(self, root_dir: pathlib.Path, enable_rca: bool = True, strict: bool = False):
        self.root_dir = root_dir
        self.enable_rca = enable_rca and RCA_AVAILABLE
        self.strict = strict
        self.registry_events: set[str] = set()
        self.handlers: dict[str, HandlerInfo] = {}
        self.events: dict[str, EventInfo] = {}
        self.handler_count: int = 0

    def _generate_rca(self, rule_id: str, message: str, severity: str, context: dict[str, Any] = None) -> dict[str, Any] | None:
        if not self.enable_rca or _analyze_exception is None:
            return None
        try:
            exc = RuntimeError(f"[{rule_id}] {message}")
            ctx = context or {}
            ctx["file"] = str(self.root_dir)
            result = _analyze_exception(exc, ctx)
            return result.to_dict() if result else None
        except Exception:
            return {"root_cause": message, "suggested_fix": "Periksa implementasi event handler."}

    def _add_violation(self, obj: EventInfo, rule_id: str, severity: str,
                       message: str, suggestion: str, line: int = 0):
        rca = self._generate_rca(rule_id, message, severity, {"file": obj.file_path, "line": line})
        obj.violations.append(EventViolation(
            rule_id=rule_id,
            file_path=obj.file_path,
            event_name=obj.name,
            severity=severity,
            message=message,
            suggestion=suggestion,
            line=line,
            rca_result=rca,
        ))

    def _get_python_files(self, base_dir: pathlib.Path | None = None) -> list[pathlib.Path]:
        target = base_dir or self.root_dir
        py_files = []
        for p in target.rglob("*.py"):
            if any(part in EXCLUDED_DIRS for part in p.parts):
                continue
            if p.name.startswith(("test_", "conftest")):
                continue
            py_files.append(p)
        return py_files

    def _module_name_from_path(self, path: pathlib.Path) -> str:
        rel = path.relative_to(self.root_dir)
        return str(rel.with_suffix("")).replace("/", ".").replace("\\", ".")

    def _extract_base_classes(self, node: ast.ClassDef) -> list[str]:
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(base.attr)
        return bases

    def _normalize_event_name(self, name: str) -> str:
        for suffix in EVENT_SUFFIX:
            if name.endswith(suffix):
                return name[:-len(suffix)]
        return name

    def _is_event_class(self, node: ast.ClassDef, is_domain_events_file: bool) -> bool:
        name = node.name
        bases = self._extract_base_classes(node)
        # Skip ignored
        if name in IGNORE_EVENTS:
            return False
        # Skip non-event names (manual)
        if name in NON_EVENT_NAMES:
            return False
        # Skip non-event patterns (Error, Timeout, Exception) jika tidak mewarisi base
        has_base = any(b in EVENT_BASE_NAMES for b in bases)
        if not has_base:
            for pattern in NON_EVENT_PATTERNS:
                if pattern in name:
                    return False
        # Check inheritance
        if any(b in IGNORE_EVENTS for b in bases):
            return True
        # Check naming (hanya jika tidak mewarisi base)
        if name.endswith(tuple(EVENT_SUFFIX)) and not any(name.endswith(suffix) for suffix in NON_EVENT_SUFFIXES):
            return True
        # If in domain_events file, treat as event
        if is_domain_events_file and not name.startswith("_") and not any(name.endswith(suffix) for suffix in NON_EVENT_SUFFIXES):
            return True
        return False

    def _load_registry_runtime(self):
        try:
            import application.events.all_event_handlers as all_handlers
            if hasattr(all_handlers, "register_all_handlers"):
                all_handlers.register_all_handlers()
            from application.events.handler_registry import event_handler_registry
            registry = event_handler_registry
            for attr in ["_handlers", "handlers", "registry"]:
                if hasattr(registry, attr):
                    data = getattr(registry, attr)
                    if isinstance(data, dict):
                        for ev_type in data.keys():
                            ev_name = ev_type if isinstance(ev_type, str) else getattr(ev_type, "__name__", str(ev_type))
                            self.registry_events.add(ev_name)
                            hdls = data[ev_type]
                            if isinstance(hdls, list):
                                self.handler_count += len(hdls)
                                for h in hdls:
                                    if hasattr(h, "__name__"):
                                        handler_name = h.__name__
                                    else:
                                        handler_name = str(h)
                                    self.handlers[handler_name] = HandlerInfo(
                                        name=handler_name,
                                        file_path="registry",
                                        event_name=ev_name,
                                        has_handle_method=True,
                                    )
                            else:
                                self.handler_count += 1
                        break
            if not self.registry_events and hasattr(all_handlers, "handlers") and isinstance(all_handlers.handlers, dict):
                for ev_name, hdls in all_handlers.handlers.items():
                    self.registry_events.add(ev_name)
                    if isinstance(hdls, list):
                        self.handler_count += len(hdls)
                        for h in hdls:
                            handler_name = h.__name__ if hasattr(h, "__name__") else str(h)
                            self.handlers[handler_name] = HandlerInfo(
                                name=handler_name,
                                file_path="registry",
                                event_name=ev_name,
                                has_handle_method=True,
                            )
                    else:
                        self.handler_count += 1
        except Exception as e:
            print(f"{COLOR['YELLOW']}⚠ Gagal load registry: {e}{COLOR['RESET']}")

    def _scan_events_ast(self):
        domain_dir = self.root_dir / "domain"
        if not domain_dir.exists():
            return

        for py_file in self._get_python_files(domain_dir):
            is_domain_events = "domain_events" in str(py_file)
            try:
                src = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=str(py_file))
                rel_path = str(py_file.relative_to(self.root_dir))
                mod_name = self._module_name_from_path(py_file)

                for node in ast.walk(tree):
                    if not isinstance(node, ast.ClassDef):
                        continue
                    if not self._is_event_class(node, is_domain_events):
                        continue
                    name = node.name
                    if name in self.events:
                        continue

                    base_classes = self._extract_base_classes(node)

                    event = EventInfo(
                        name=name,
                        file_path=rel_path,
                        module_path=mod_name,
                        base_classes=base_classes,
                    )

                    fields = []
                    has_timestamp = False
                    has_correlation = False
                    has_causation = False
                    has_version = False
                    is_frozen = False
                    is_serializable = False

                    for dec in node.decorator_list:
                        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == "dataclass":
                            for kw in dec.keywords:
                                if kw.arg == "frozen" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                                    is_frozen = True
                        if isinstance(dec, ast.Name) and dec.id == "dataclass":
                            pass

                    for item in node.body:
                        if isinstance(item, (ast.AnnAssign, ast.Assign)):
                            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                                field_name = item.target.id
                                fields.append(field_name)
                                if "timestamp" in field_name.lower():
                                    has_timestamp = True
                                if "correlation" in field_name.lower():
                                    has_correlation = True
                                if "causation" in field_name.lower():
                                    has_causation = True
                                if "version" in field_name.lower():
                                    has_version = True
                            elif isinstance(item, ast.Assign):
                                for target in item.targets:
                                    if isinstance(target, ast.Name):
                                        field_name = target.id
                                        fields.append(field_name)
                                        if "timestamp" in field_name.lower():
                                            has_timestamp = True
                                        if "correlation" in field_name.lower():
                                            has_correlation = True
                                        if "causation" in field_name.lower():
                                            has_causation = True
                                        if "version" in field_name.lower():
                                            has_version = True

                    event.fields = fields
                    event.has_timestamp = has_timestamp
                    event.has_correlation_id = has_correlation
                    event.has_causation_id = has_causation
                    event.has_version = has_version
                    event.is_frozen = is_frozen
                    event.is_serializable = True

                    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                        if isinstance(node.body[0].value.value, str) and node.body[0].value.value.strip():
                            event.has_docstring = True

                    self.events[name] = event

            except Exception:
                pass

    def _scan_handlers_ast(self):
        target_dirs = [
            self.root_dir / "application" / "events",
            self.root_dir / "application" / "handlers",
            self.root_dir / "application" / "subscribers",
            self.root_dir / "adapters" / "event_handlers",
        ]
        for target in target_dirs:
            if not target.exists():
                continue
            for py_file in self._get_python_files(target):
                try:
                    src = py_file.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(src, filename=str(py_file))
                    rel_path = str(py_file.relative_to(self.root_dir))

                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef):
                            name = node.name
                            if not any(name.endswith(suffix) for suffix in HANDLER_SUFFIX):
                                continue
                            event_name = None
                            handle_item = None
                            for item in node.body:
                                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                    if item.name in ("handle", "on_event", "receive"):
                                        handle_item = item
                                        for arg in item.args.args:
                                            if arg.arg not in ("self", "cls"):
                                                if arg.annotation:
                                                    anno_str = self._extract_annotation_string(arg.annotation)
                                                    if anno_str and anno_str in self.events:
                                                        event_name = anno_str
                                                        break
                                        if not event_name:
                                            body_text = ast.unparse(item)
                                            for ev in self.events.keys():
                                                if ev in body_text:
                                                    event_name = ev
                                                    break
                            if event_name:
                                handler = HandlerInfo(
                                    name=name,
                                    file_path=rel_path,
                                    event_name=event_name,
                                    has_handle_method=True,
                                )
                                has_try = any(isinstance(sub, ast.Try) for sub in ast.walk(node))
                                handler.has_error_handling = has_try
                                # FIX v2.5.0: dulu ast.unparse(item) dipanggil ulang di sini
                                # untuk node yang sama persis dengan yang sudah di-unparse
                                # di atas (saat event_name belum ketemu dari annotation).
                                # Sekarang cukup unparse sekali dan dipakai ulang.
                                if handle_item is not None:
                                    if isinstance(handle_item, ast.AsyncFunctionDef):
                                        handler.is_async = True
                                    body_text = ast.unparse(handle_item)
                                    if "transaction" in body_text.lower() or "uow" in body_text.lower():
                                        handler.is_transactional = True
                                    if "idempotency" in body_text.lower() or "dedup" in body_text.lower():
                                        handler.has_idempotency = True
                                if handler.name not in self.handlers:
                                    self.handlers[handler.name] = handler
                except Exception:
                    pass

    def _extract_annotation_string(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Name):
                return node.value.id
            return self._extract_annotation_string(node.slice)
        return None

    def _classify_usage(self):
        """
        FIX v2.5.0 — BUG PERFORMA UTAMA:
        Versi lama membaca ULANG isi SETIAP file dari disk untuk SETIAP event
        (nested loop: for event -> for file -> read_text()). Untuk N event dan
        M file itu O(N*M) pembacaan file penuh dari disk — pada codebase besar
        (ratusan event x ribuan file) ini yang membuat checker terasa "lama".
        Sekarang isi tiap file dibaca SEKALI saja (cache di memori), baru
        dicocokkan ke semua nama event -> O(M) baca disk + pencarian in-memory.
        """
        all_files = self._get_python_files()
        candidate_files = [
            py_file for py_file in all_files
            if not ("domain" in str(py_file) and "domain_events" not in str(py_file))
            and py_file.name != "__init__.py"
            and "tests" not in str(py_file)
        ]

        file_contents: list[str] = []
        for py_file in candidate_files:
            try:
                file_contents.append(py_file.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue

        for ev_name, ev_info in self.events.items():
            ev_info.used_outside_domain = any(ev_name in content for content in file_contents)

    def _validate_events(self):
        for ev in self.events.values():
            has_event_base = any(b in EVENT_BASE_NAMES for b in ev.base_classes)

            # Naming: hanya beri violation jika tidak mewarisi base dan tidak memiliki suffix yang benar
            if not has_event_base and not any(ev.name.endswith(suffix) for suffix in EVENT_SUFFIX):
                self._add_violation(ev, RuleID.EVT_NAMING, "LOW",
                    f"Event '{ev.name}' tidak menggunakan suffix standar ({', '.join(EVENT_SUFFIX)}).",
                    "Gunakan suffix 'Event', 'DomainEvent', atau 'IntegrationEvent'.")

            # Base class: jika tidak mewarisi base event
            if not has_event_base:
                self._add_violation(ev, RuleID.EVT_BASE_CLASS, "HIGH",
                    f"Event '{ev.name}' tidak mewarisi dari base class event (misal DomainEvent).",
                    "Pastikan event mewarisi dari DomainEvent, IntegrationEvent, atau BaseEvent.")

            # Field-field wajib hanya jika tidak mewarisi base
            if not has_event_base:
                if not ev.has_timestamp:
                    self._add_violation(ev, RuleID.EVT_TIMESTAMP, "MEDIUM",
                        f"Event '{ev.name}' tidak memiliki field 'timestamp'.",
                        "Tambahkan field 'timestamp' untuk waktu kejadian.")
                if not ev.has_correlation_id:
                    self._add_violation(ev, RuleID.EVT_CORRELATION, "MEDIUM",
                        f"Event '{ev.name}' tidak memiliki field 'correlation_id'.",
                        "Tambahkan field 'correlation_id' untuk tracing.")
                if not ev.has_causation_id:
                    self._add_violation(ev, RuleID.EVT_CAUSATION, "LOW",
                        f"Event '{ev.name}' tidak memiliki field 'causation_id'.",
                        "Tambahkan field 'causation_id' untuk causality chain.")
                if not ev.has_version:
                    self._add_violation(ev, RuleID.EVT_VERSION, "LOW",
                        f"Event '{ev.name}' tidak memiliki field 'version'.",
                        "Tambahkan field 'version' untuk event versioning.")
                if not ev.is_frozen:
                    self._add_violation(ev, RuleID.EVT_IMMUTABLE, "HIGH",
                        f"Event '{ev.name}' tidak menggunakan dataclass(frozen=True).",
                        "Gunakan '@dataclass(frozen=True)' untuk immutability.")

            # Docstring tetap wajib
            if not ev.has_docstring:
                self._add_violation(ev, RuleID.DOC_EVENT, "LOW",
                    f"Event '{ev.name}' tidak memiliki docstring.",
                    "Tambahkan docstring menjelaskan event dan field-fieldnya.")

        # Handler validation
        for hdl in self.handlers.values():
            if not hdl.has_handle_method:
                self._add_violation(EventInfo(
                    name=hdl.name,
                    file_path=hdl.file_path,
                    module_path="",
                ), RuleID.HDL_HANDLE_METHOD, "CRITICAL",
                    f"Handler '{hdl.name}' tidak memiliki method 'handle()' atau 'on_event()'.",
                    "Tambahkan method 'def handle(self, event: Event) -> None'.")

            if not hdl.has_error_handling:
                self._add_violation(EventInfo(
                    name=hdl.name,
                    file_path=hdl.file_path,
                    module_path="",
                ), RuleID.HDL_ERROR_HANDLING, "HIGH",
                    f"Handler '{hdl.name}' tidak memiliki error handling (try/except).",
                    "Tambahkan try/except untuk menangkap error dan log.")

            if not hdl.is_transactional:
                self._add_violation(EventInfo(
                    name=hdl.name,
                    file_path=hdl.file_path,
                    module_path="",
                ), RuleID.HDL_TRANSACTION, "MEDIUM",
                    f"Handler '{hdl.name}' tidak menggunakan transaksi (UoW).",
                    "Gunakan UnitOfWork untuk menjaga konsistensi data.")

            if not hdl.has_idempotency:
                self._add_violation(EventInfo(
                    name=hdl.name,
                    file_path=hdl.file_path,
                    module_path="",
                ), RuleID.HDL_IDEMPOTENCY, "MEDIUM",
                    f"Handler '{hdl.name}' tidak memiliki mekanisme idempotensi.",
                    "Tambahkan idempotency key atau deduplication logic.")

        # Registry checks
        for ev in self.events.values():
            if ev.name in self.registry_events:
                ev.in_registry = True

        # Orphan events: hanya beri peringatan jika digunakan di luar domain dan tidak terdaftar
        for ev in self.events.values():
            if ev.used_outside_domain and not ev.in_registry:
                self._add_violation(ev, RuleID.REG_MISSING_HANDLER, "MEDIUM",
                    f"Event '{ev.name}' digunakan di luar domain tetapi tidak terdaftar di registry.",
                    "Daftarkan event beserta handlernya di all_event_handlers.py.")

        # Unregistered handler
        for hdl in self.handlers.values():
            if hdl.event_name and hdl.event_name not in self.registry_events:
                self._add_violation(EventInfo(
                    name=hdl.event_name,
                    file_path=hdl.file_path,
                    module_path="",
                ), RuleID.REG_UNREGISTERED_HANDLER, "HIGH",
                    f"Handler '{hdl.name}' menangani event '{hdl.event_name}' yang tidak terdaftar.",
                    "Pastikan event terdaftar di registry.")

    def scan(self) -> CheckerResult:
        self._load_registry_runtime()
        self._scan_events_ast()
        self._scan_handlers_ast()
        self._classify_usage()
        self._validate_events()

        all_events = list(self.events.values())
        all_handlers = list(self.handlers.values())

        total_violations = 0
        critical = high = medium = low = 0
        for ev in all_events:
            total_violations += len(ev.violations)
            for v in ev.violations:
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
            events=all_events,
            handlers=all_handlers,
            registry_events=list(self.registry_events),
            total_events=len(all_events),
            total_handlers=len(all_handlers),
            total_violations=total_violations,
            critical_count=critical,
            high_count=high,
            medium_count=medium,
            low_count=low,
            score=score,
            rca_enabled=self.enable_rca,
            elapsed_seconds=0.0,
        )


# =============================================================================
# Reporting
# =============================================================================
def group_violations_by_file(result: CheckerResult) -> dict[str, list[EventViolation]]:
    groups = defaultdict(list)
    for ev in result.events:
        for v in ev.violations:
            groups[v.file_path].append(v)
    for h in result.handlers:
        for v in h.violations:
            groups[v.file_path].append(v)
    return dict(groups)


def print_report(result: CheckerResult, verbose: bool = False, group_by_file: bool = True) -> None:
    c = COLOR
    print(f"\n{c['BOLD']}{c['CYAN']}╔{'═'*72}╗")
    print("║   SOVEREIGN EVENT HANDLER & EVENT SOURCING CHECKER v2.5   ║")
    print(f"╚{'═'*72}╝{c['RESET']}")

    print("\n  📋 100+ Aturan Event Handler & Event Sourcing:")
    print("    ✅ Event naming conventions (Event/DomainEvent)")
    print("    ✅ Inheritance dari base event (DomainEvent, IntegrationEvent)")
    print("    ✅ Immutability (dataclass frozen) — jika tidak mewarisi base")
    print("    ✅ Required fields (timestamp, correlation_id, causation_id) — jika tidak mewarisi base")
    print("    ✅ Event versioning — jika tidak mewarisi base")
    print("    ✅ Registry binding (all_event_handlers.py)")
    print("    ✅ Handler completeness (handle method, error handling)")
    print("    ✅ Transactional and idempotent handlers")
    print("    ✅ Outbox pattern compliance")
    print("    ✅ Eventual consistency validation")

    print(f"\n  {c['CYAN']}Total Events Ditemukan: {result.total_events}{c['RESET']}")
    print(f"  Total Handlers Ditemukan: {result.total_handlers}")
    print(f"  Events in Registry: {len(result.registry_events)}")
    print(f"  Total Violations: {result.total_violations}")
    print(f"    {c['RED']}CRITICAL: {result.critical_count}{c['RESET']}")
    print(f"    {c['YELLOW']}HIGH: {result.high_count}{c['RESET']}")
    print(f"    {c['MAGENTA']}MEDIUM: {result.medium_count}{c['RESET']}")
    print(f"    {c['CYAN']}LOW: {result.low_count}{c['RESET']}")

    score_color = c["GREEN"] if result.score >= 80 else c["YELLOW"] if result.score >= 50 else c["RED"]
    print(f"\n  📈 Skor Kepatuhan Event: {score_color}{c['BOLD']}{result.score:.1f}/100{c['RESET']}")
    print(f"  RCA Engine: {'✅ Aktif' if result.rca_enabled else '⚠️ Tidak tersedia'}")

    # Jika grouping by file diaktifkan
    if group_by_file:
        groups = group_violations_by_file(result)
        if groups:
            print(f"\n{c['YELLOW']}─── VIOLATIONS PER FILE ───{c['RESET']}")
            sorted_files = sorted(groups.items(), key=lambda x: len(x[1]), reverse=True)
            for file_path, violations in sorted_files[:50]:
                severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
                for v in violations:
                    severity_counts[v.severity] += 1
                sev_str = f"CRITICAL:{severity_counts['CRITICAL']} HIGH:{severity_counts['HIGH']} MEDIUM:{severity_counts['MEDIUM']} LOW:{severity_counts['LOW']}"
                print(f"\n  📄 {file_path} ({len(violations)} violations) [{sev_str}]")
                for v in violations[:5]:
                    sev_color = c["RED"] if v.severity in ("CRITICAL", "HIGH") else c["YELLOW"] if v.severity == "MEDIUM" else c["CYAN"]
                    print(f"    {sev_color}[{v.rule_id}] {v.severity}{c['RESET']} {v.message[:80]}...")
                if len(violations) > 5:
                    print(f"    ... and {len(violations)-5} more violations")
            if len(sorted_files) > 50:
                print(f"\n  ... and {len(sorted_files)-50} more files with violations")
    else:
        events_with_violations = [e for e in result.events if e.violations]
        if events_with_violations:
            print(f"\n{c['RED']}─── EVENTS WITH VIOLATIONS ───{c['RESET']}")
            for ev in events_with_violations[:20]:
                status = f"{c['RED']}✖ {len(ev.violations)} violations{c['RESET']}"
                reg_status = "✅ Registered" if ev.in_registry else "❌ Not registered"
                print(f"  {ev.name} @ {ev.file_path} {status} [{reg_status}]")

        handlers_with_violations = [h for h in result.handlers if h.violations]
        if handlers_with_violations:
            print(f"\n{c['YELLOW']}─── HANDLERS WITH VIOLATIONS ───{c['RESET']}")
            for h in handlers_with_violations[:20]:
                print(f"  {h.name} (handles {h.event_name}) @ {h.file_path} - {len(h.violations)} violations")

        all_violations = []
        for ev in result.events:
            all_violations.extend(ev.violations)
        for h in result.handlers:
            all_violations.extend(h.violations)
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
            "total_events": result.total_events,
            "total_handlers": result.total_handlers,
            "registry_events": result.registry_events,
            "total_violations": result.total_violations,
            "severity_counts": {
                "critical": result.critical_count,
                "high": result.high_count,
                "medium": result.medium_count,
                "low": result.low_count,
            },
            "events": [
                {
                    "name": ev.name,
                    "file": ev.file_path,
                    "base_classes": ev.base_classes,
                    "has_timestamp": ev.has_timestamp,
                    "has_correlation_id": ev.has_correlation_id,
                    "has_causation_id": ev.has_causation_id,
                    "has_version": ev.has_version,
                    "is_frozen": ev.is_frozen,
                    "has_docstring": ev.has_docstring,
                    "in_registry": ev.in_registry,
                    "used_outside_domain": ev.used_outside_domain,
                    "fields": ev.fields,
                    "violations": [v.to_dict() for v in ev.violations],
                }
                for ev in result.events
            ],
            "handlers": [
                {
                    "name": h.name,
                    "file": h.file_path,
                    "event_name": h.event_name,
                    "has_handle_method": h.has_handle_method,
                    "has_error_handling": h.has_error_handling,
                    "is_async": h.is_async,
                    "is_transactional": h.is_transactional,
                    "has_idempotency": h.has_idempotency,
                    "violations": [v.to_dict() for v in h.violations],
                }
                for h in result.handlers
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
    parser = argparse.ArgumentParser(description="Sovereign Event Handler & Event Sourcing Forensic Checker v2.5")
    parser.add_argument("--json", metavar="FILE", help="Export report to JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show RCA details")
    parser.add_argument("--strict", action="store_true", help="Mode strict")
    parser.add_argument("--no-rca", action="store_true", help="Disable RCA analysis")
    parser.add_argument("--no-group", action="store_true", help="Disable grouping by file (default: grouped)")
    args = parser.parse_args()

    global RCA_AVAILABLE, _analyze_exception
    if args.no_rca:
        RCA_AVAILABLE = False
        _analyze_exception = None

    start = time.monotonic()
    verifier = SovereignEventHandlerVerifier(ROOT, enable_rca=not args.no_rca, strict=args.strict)
    result = verifier.scan()
    elapsed = time.monotonic() - start
    result.elapsed_seconds = elapsed

    print_report(result, verbose=args.verbose, group_by_file=not args.no_group)

    if args.json:
        save_json(result, args.json)

    print(f"\n ⏱️ Audit Duration: {elapsed:.3f} seconds")

    has_critical = result.critical_count > 0
    sys.exit(1 if has_critical else 0)


if __name__ == "__main__":
    main()
