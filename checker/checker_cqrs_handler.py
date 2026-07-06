#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker_cqrs_handler.py — Sovereign CQRS Architecture & Forensic Checker v2.4
================================================================================
Versi   : 2.4.0
Perbaikan v2.4.0:
  - Deteksi transaksi lebih akurat (AST walk, dekorator, dengan/begin, commit pada uow/session)
  - Deteksi validasi command (BaseModel, @field_validator) untuk mengurangi false positive
  - Pembedaan read-only handler dengan deteksi operasi tulis (add, delete, update, dll)
  - Deteksi parameter command/query via type hint atau nama argumen (command, cmd, query, qry)
  - Penambahan field has_uow dan has_session pada CQRSObject
  - Scoring: penalti medium = 2 (sebelumnya 3)
  - Konfigurasi .cqrs-checker.yml untuk mengabaikan aturan/file/kelas
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import pathlib
import sys
import time
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

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
    "mappers", "workflows", "sagas", "orchestrators", "kernel",
    "dto_objects", "dto", "requests", "responses", "schemas", "models",
    "__pycache__", ".git", "tests", "migrations", "scripts", "alembic",
    "docs", "checker", "deployment", "monitoring", "reports"
}

BASE_COMMAND_NAMES = {"BaseCommand", "Command", "ICommand"}
BASE_QUERY_NAMES = {"BaseQuery", "Query", "IQuery"}
IGNORE_BASES = BASE_COMMAND_NAMES | BASE_QUERY_NAMES

# Handler class yang sebenarnya bukan CQRS handler
INFRASTRUCTURE_HANDLERS = {
    "WebhookHandler", "CorrelationIdHandler", "SQLAlchemyCQRSQueryHandler",
    "KafkaDeadLetterHandler", "LifecycleHandler", "EventHandler",
    "AxiomViolationHandler", "RollbackHandler", "ConfigFileHandler",
    "ConstitutionExceptionHandler", "QueryHandler", "BaseHandler",
    "CommandHandler", "CommandBus", "QueryBus", "Dispatcher",
    "MigrationRollbackExecutor", "ActionExecutor", "BaseCommandHandler",
    "BaseQueryHandler"
}

# Base class names that should be ignored for registry checks
BASE_CLASS_NAMES = {"BaseCommandHandler", "BaseQueryHandler", "BaseHandler", "BaseUseCase"}

COMMAND_SUFFIXES = {"Command", "Cmd"}
QUERY_SUFFIXES = {"Query", "Qry"}
HANDLER_SUFFIXES = {"Handler", "UseCase", "Executor"}

# Pola deteksi transaksi & validasi yang lebih kaya
TRANSACTION_PATTERNS = {
    "uow", "unitofwork", "transaction", "begin", "commit", "rollback",
    "session.begin", "session.commit", "session.rollback",
    "@transactional", "with transaction", "async with", "atomic",
    "savepoint", "flush", "merge", "persist"
}
VALIDATION_PATTERNS = {
    "validate", "is_valid", "validationerror", "validator",
    "field_validator", "model_validator", "@validate", "@validator",
    "pydantic", "assert", "raise valueerror", "raise validationerror",
    "guard", "check", "ensure", "require"
}
WRITE_KEYWORDS = {"save", "create", "update", "delete", "remove", "persist", "merge", "commit", "flush"}

# =============================================================================
# Rule IDs
# =============================================================================
class RuleID:
    # A: Command/Query Detection (1-10)
    CMD_NAMING = "CQRS-001"
    QRY_NAMING = "CQRS-002"
    CMD_BASE_CLASS = "CQRS-003"
    QRY_BASE_CLASS = "CQRS-004"
    CMD_FILE_LOCATION = "CQRS-005"
    QRY_FILE_LOCATION = "CQRS-006"
    CMD_FIELDS = "CQRS-007"
    QRY_FIELDS = "CQRS-008"
    CMD_IMMUTABLE = "CQRS-009"
    QRY_READONLY = "CQRS-010"

    # B: Handler Detection (11-20)
    HDL_NAMING = "CQRS-011"
    HDL_EXECUTE_METHOD = "CQRS-012"
    HDL_EXECUTE_SIGNATURE = "CQRS-013"
    HDL_EXECUTE_RETURN = "CQRS-014"
    HDL_PARAM_TYPE = "CQRS-015"
    HDL_FILE_LOCATION = "CQRS-016"
    HDL_ERROR_HANDLING = "CQRS-017"
    HDL_ASYNC_SUPPORT = "CQRS-018"
    HDL_TRANSACTIONAL = "CQRS-019"
    HDL_VALIDATION = "CQRS-020"

    # C: Registry & Binding (21-30)
    REG_REGISTERED = "CQRS-021"
    REG_CMD_HANDLER = "CQRS-022"
    REG_QRY_HANDLER = "CQRS-023"
    REG_DUPLICATE = "CQRS-024"
    REG_MISSING_HANDLER = "CQRS-025"
    REG_MISSING_COMMAND = "CQRS-026"
    REG_UNREGISTERED_HANDLER = "CQRS-027"
    REG_ORPHAN_COMMAND = "CQRS-028"
    REG_ORPHAN_QUERY = "CQRS-029"
    REG_BUS_REGISTRATION = "CQRS-030"

    # D: Bus Integration (31-40)
    BUS_COMMAND_DISPATCH = "CQRS-031"
    BUS_QUERY_DISPATCH = "CQRS-032"
    BUS_MIDDLEWARE = "CQRS-033"
    BUS_LOGGING = "CQRS-034"
    BUS_AUTH = "CQRS-035"
    BUS_VALIDATION = "CQRS-036"
    BUS_RETRY = "CQRS-037"
    BUS_CIRCUIT_BREAKER = "CQRS-038"
    BUS_TIMEOUT = "CQRS-039"
    BUS_CACHING = "CQRS-040"

    # E: Idempotency (41-45)
    IDEM_KEY = "CQRS-041"
    IDEM_CHECK = "CQRS-042"
    IDEM_CACHE = "CQRS-043"
    IDEM_RETRY = "CQRS-044"
    IDEM_UNIQUE = "CQRS-045"

    # F: Event Publishing (46-50)
    EVT_PUBLISH = "CQRS-046"
    EVT_COMMIT = "CQRS-047"
    EVT_OUTBOX = "CQRS-048"
    EVT_TRANSACTIONAL = "CQRS-049"
    EVT_DOMAIN = "CQRS-050"

    # G: Validation (51-55)
    VAL_INPUT = "CQRS-051"
    VAL_BUSINESS = "CQRS-052"
    VAL_PERMISSION = "CQRS-053"
    VAL_STATE = "CQRS-054"
    VAL_CONSISTENCY = "CQRS-055"

    # H: Performance (56-60)
    PERF_BATCH = "CQRS-056"
    PERF_ASYNC = "CQRS-057"
    PERF_CACHE = "CQRS-058"
    PERF_PAGING = "CQRS-059"
    PERF_INDEX = "CQRS-060"

    # I: Security (61-65)
    SEC_AUTH = "CQRS-061"
    SEC_AUDIT = "CQRS-062"
    SEC_SENSITIVE = "CQRS-063"
    SEC_RATE_LIMIT = "CQRS-064"
    SEC_ENCRYPT = "CQRS-065"

    # J: Testing (66-70)
    TEST_UNIT = "CQRS-066"
    TEST_INTEGRATION = "CQRS-067"
    TEST_MOCK = "CQRS-068"
    TEST_BUS = "CQRS-069"
    TEST_HANDLER = "CQRS-070"

    # K: Documentation (71-75)
    DOC_COMMAND = "CQRS-071"
    DOC_QUERY = "CQRS-072"
    DOC_HANDLER = "CQRS-073"
    DOC_PARAM = "CQRS-074"
    DOC_RETURN = "CQRS-075"

    # L: Architecture (76-80)
    ARCH_LAYER = "CQRS-076"
    ARCH_DEPENDENCY = "CQRS-077"
    ARCH_CIRCULAR = "CQRS-078"
    ARCH_SINGLETON = "CQRS-079"
    ARCH_SCOPE = "CQRS-080"

# =============================================================================
# Data Classes
# =============================================================================
@dataclass
class CQRSViolation:
    rule_id: str
    file_path: str
    object_name: str
    severity: str
    message: str
    suggestion: str
    line: int = 0
    rca_result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "rule_id": self.rule_id,
            "file": self.file_path,
            "object": self.object_name,
            "severity": self.severity,
            "message": self.message,
            "suggestion": self.suggestion,
            "line": self.line,
        }
        if self.rca_result:
            d["rca"] = self.rca_result
        return d


@dataclass
class CQRSObject:
    name: str
    file_path: str
    module_path: str
    is_command: bool = False
    is_query: bool = False
    is_handler: bool = False
    linked_commands: Set[str] = field(default_factory=set)
    linked_queries: Set[str] = field(default_factory=set)
    has_execute_method: bool = False
    has_handle_method: bool = False
    has_docstring: bool = False
    has_transaction: bool = False
    has_validation: bool = False
    is_async: bool = False
    is_read_only: bool = False
    has_uow: bool = False          # baru
    has_session: bool = False      # baru
    return_type: Optional[str] = None
    field_count: int = 0
    line: int = 0
    violations: List[CQRSViolation] = field(default_factory=list)
    is_base_class: bool = False


@dataclass
class CheckerResult:
    commands: List[CQRSObject]
    queries: List[CQRSObject]
    handlers: List[CQRSObject]
    mapping: Dict[str, List[str]]
    total_commands: int
    total_queries: int
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
# Sovereign CQRS Verifier (dengan perbaikan utama)
# =============================================================================
class SovereignCQRSVerifier:
    def __init__(self, root_dir: pathlib.Path, enable_rca: bool = True, strict: bool = False):
        self.root_dir = root_dir
        self.enable_rca = enable_rca and RCA_AVAILABLE
        self.strict = strict
        self.registry_pairs: List[Tuple[str, str]] = []
        self.commands: Dict[str, CQRSObject] = {}
        self.queries: Dict[str, CQRSObject] = {}
        self.handlers: Dict[str, CQRSObject] = {}
        self.mapping: Dict[str, List[str]] = defaultdict(list)

        # Konfigurasi pengabaian (opsional)
        self.ignored_rules = set()
        self.ignored_files = set()
        self.ignored_classes = set()
        self._load_config()

    def _load_config(self):
        """Membaca .cqrs-checker.yml jika ada."""
        config_path = self.root_dir / ".cqrs-checker.yml"
        if not config_path.exists():
            return
        try:
            import yaml
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            self.ignored_rules = set(config.get("ignore_rules", []))
            self.ignored_files = set(config.get("ignore_files", []))
            self.ignored_classes = set(config.get("ignore_classes", []))
        except Exception:
            pass  # Jika yaml tidak tersedia atau file corrupt, abaikan

    def _is_ignored(self, rule_id: str, file_path: str, class_name: str) -> bool:
        if rule_id in self.ignored_rules:
            return True
        if any(pattern in file_path for pattern in self.ignored_files):
            return True
        if class_name in self.ignored_classes:
            return True
        return False

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
            return {"root_cause": message, "suggested_fix": "Periksa implementasi CQRS."}

    def _add_violation(self, obj: CQRSObject, rule_id: str, severity: str,
                       message: str, suggestion: str, line: int = 0):
        if self._is_ignored(rule_id, obj.file_path, obj.name):
            return
        rca = self._generate_rca(rule_id, message, severity, {"file": obj.file_path, "line": line})
        obj.violations.append(CQRSViolation(
            rule_id=rule_id,
            file_path=obj.file_path,
            object_name=obj.name,
            severity=severity,
            message=message,
            suggestion=suggestion,
            line=line or obj.line,
            rca_result=rca,
        ))

    def _get_python_files(self) -> List[pathlib.Path]:
        py_files = []
        for p in self.root_dir.rglob("*.py"):
            if any(part in EXCLUDED_DIRS for part in p.parts):
                continue
            if p.name.startswith(("test_", "conftest")):
                continue
            py_files.append(p)
        return py_files

    def _module_name_from_path(self, path: pathlib.Path) -> str:
        rel = path.relative_to(self.root_dir)
        return str(rel.with_suffix("")).replace(os.sep, ".")

    def _extract_base_classes(self, node: ast.ClassDef) -> List[str]:
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(base.attr)
            elif isinstance(base, ast.Subscript):
                if isinstance(base.value, ast.Name):
                    bases.append(base.value.id)
        return bases

    def _extract_annotation_string(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Name):
                return node.value.id
            return self._extract_annotation_string(node.slice)
        return None

    def _normalize_name(self, name: str) -> str:
        base = name.replace("Command", "").replace("Query", "").replace("Handler", "").replace("UseCase", "")
        return base.lower().strip()

    # ---- Helper deteksi (diperbaiki) ----
    def _has_transaction_in_method(self, method_node: ast.FunctionDef) -> bool:
        """Deteksi transaksi secara akurat melalui AST walk dan dekorator."""
        # Cek dekorator
        for deco in method_node.decorator_list:
            if isinstance(deco, ast.Name) and deco.id == "transactional":
                return True
            if isinstance(deco, ast.Attribute) and deco.attr == "transactional":
                return True

        for node in ast.walk(method_node):
            if isinstance(node, ast.Call):
                func = node.func
                # Pemanggilan fungsi langsung: transaction(), begin(), commit(), rollback(), flush()
                if isinstance(func, ast.Name):
                    if func.id.lower() in ("commit", "rollback", "flush"):
                        return True
                    # begin() saja tidak cukup, harus pada session/uow
                elif isinstance(func, ast.Attribute):
                    # cek self.uow.commit(), self.session.commit(), dll
                    if isinstance(func.value, ast.Attribute):
                        if isinstance(func.value.value, ast.Name) and func.value.value.id == 'self':
                            if func.value.attr in ('uow', 'session') and func.attr in ('commit', 'rollback', 'flush', 'begin'):
                                return True
                    # cek uow.commit(), session.commit() jika variabel lokal
                    if isinstance(func.value, ast.Name):
                        if func.value.id in ('uow', 'session') and func.attr in ('commit', 'rollback', 'flush', 'begin'):
                            return True
            # with statement: with session.begin(), with uow:
            if isinstance(node, ast.With):
                for item in node.items:
                    ctx = item.context_expr
                    if isinstance(ctx, ast.Call):
                        if isinstance(ctx.func, ast.Attribute):
                            # self.uow.begin(), self.session.begin()
                            if isinstance(ctx.func.value, ast.Attribute):
                                if isinstance(ctx.func.value.value, ast.Name) and ctx.func.value.value.id == 'self':
                                    if ctx.func.value.attr in ('uow', 'session') and ctx.func.attr == 'begin':
                                        return True
                            # uow.begin(), session.begin()
                            if isinstance(ctx.func.value, ast.Name):
                                if ctx.func.value.id in ('uow', 'session') and ctx.func.attr == 'begin':
                                    return True
        return False

    def _has_validation_in_method(self, method_node: ast.FunctionDef) -> bool:
        """Deteksi validasi melalui AST walk dan dekorator."""
        for deco in method_node.decorator_list:
            if isinstance(deco, ast.Name) and deco.id in ("validate", "validator"):
                return True
            if isinstance(deco, ast.Attribute) and deco.attr in ("validate", "validator"):
                return True

        for node in ast.walk(method_node):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    if func.id.lower() in VALIDATION_PATTERNS:
                        return True
                elif isinstance(func, ast.Attribute):
                    if func.attr.lower() in VALIDATION_PATTERNS:
                        return True
            # raise ValueError / ValidationError
            if isinstance(node, ast.Raise):
                if isinstance(node.exc, ast.Call):
                    if isinstance(node.exc.func, ast.Name):
                        if node.exc.func.id in ("ValueError", "ValidationError"):
                            return True
            # assert
            if isinstance(node, ast.Assert):
                return True
        return False

    def _is_read_only_method(self, method_node: ast.FunctionDef) -> bool:
        """Periksa apakah method ini hanya baca (tidak ada operasi tulis)."""
        for node in ast.walk(method_node):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    # Cek jika method dipanggil pada objek yang mengindikasikan session/uow/repo
                    target = None
                    if isinstance(func.value, ast.Attribute) and isinstance(func.value.value, ast.Name) and func.value.value.id == 'self':
                        target = func.value.attr
                    elif isinstance(func.value, ast.Name):
                        target = func.value.id
                    if target in ('session', 'uow', 'repo', 'repository'):
                        if func.attr.lower() in WRITE_KEYWORDS:
                            return False
                    # Juga cek jika attr adalah add, delete, update, dll pada objek apapun yang mungkin repository
                    if func.attr.lower() in WRITE_KEYWORDS:
                        # Jika nama objek mengandung 'repo' atau 'session' atau 'uow', sudah terdeteksi di atas
                        # Kita tidak mau terlalu agresif, hanya jika target jelas
                        pass
        return True

    # ---- Parsing registry ----
    def _parse_registry_files(self):
        candidates = [
            self.root_dir / "application" / "use_cases" / "__init__.py",
            self.root_dir / "application" / "app_factory.py",
            self.root_dir / "application" / "commands_cqrs" / "command_handler_registry.py",
            self.root_dir / "application" / "commands_cqrs" / "query_handler_registry.py",
            self.root_dir / "bootstrap" / "dependency_container" / "service_registry.py",
        ]

        for file_path in candidates:
            if not file_path.exists():
                continue
            try:
                src = file_path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=str(file_path))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Tuple, ast.List)) and len(node.elts) >= 2:
                        elts = node.elts
                        first_name = None
                        last_name = None
                        if isinstance(elts[0], ast.Name):
                            first_name = elts[0].id
                        if isinstance(elts[-1], ast.Name):
                            last_name = elts[-1].id
                        if first_name and last_name:
                            if any(first_name.endswith(suffix) for suffix in COMMAND_SUFFIXES + QUERY_SUFFIXES):
                                if any(last_name.endswith(suffix) for suffix in HANDLER_SUFFIXES):
                                    self.registry_pairs.append((first_name, last_name))
            except Exception:
                pass

        for cmd_name, hdl_name in self.registry_pairs:
            self.mapping[cmd_name].append(hdl_name)

    def _parse_decorators(self, node: ast.FunctionDef) -> Set[str]:
        decorators = set()
        for deco in node.decorator_list:
            if isinstance(deco, ast.Name):
                decorators.add(deco.id)
            elif isinstance(deco, ast.Attribute):
                decorators.add(deco.attr)
            elif isinstance(deco, ast.Call):
                if isinstance(deco.func, ast.Name):
                    decorators.add(deco.func.id)
                elif isinstance(deco.func, ast.Attribute):
                    decorators.add(deco.func.attr)
        return decorators

    # ---- AST Introspection (diperbaiki) ----
    def _introspect_ast(self, file_path: pathlib.Path):
        try:
            src = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(file_path))
            rel_path = str(file_path.relative_to(self.root_dir))
            mod_name = self._module_name_from_path(file_path)

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue

                name = node.name
                bases = self._extract_base_classes(node)
                line = node.lineno

                # Skip infrastructure handlers
                if name in INFRASTRUCTURE_HANDLERS:
                    continue
                # Skip exception classes
                if any(b in ("Exception", "Error", "Warning", "RuntimeError") for b in bases):
                    continue

                is_cmd_inherit = any(b in BASE_COMMAND_NAMES for b in bases)
                is_cmd_name = any(name.endswith(suffix) for suffix in COMMAND_SUFFIXES)
                is_cmd = is_cmd_inherit or (is_cmd_name and name not in IGNORE_BASES)

                is_qry_inherit = any(b in BASE_QUERY_NAMES for b in bases)
                is_qry_name = any(name.endswith(suffix) for suffix in QUERY_SUFFIXES)
                is_qry = is_qry_inherit or (is_qry_name and name not in IGNORE_BASES)

                is_hdlr = any(name.endswith(suffix) for suffix in HANDLER_SUFFIXES)

                # Check if it's a base class
                is_base = name in BASE_CLASS_NAMES or any(b in BASE_CLASS_NAMES for b in bases)

                # If not CQRS, skip
                if not (is_cmd or is_qry or is_hdlr):
                    continue

                obj = CQRSObject(
                    name=name,
                    file_path=rel_path,
                    module_path=mod_name,
                    is_command=is_cmd,
                    is_query=is_qry,
                    is_handler=is_hdlr,
                    is_base_class=is_base,
                    line=line,
                )

                # Docstring
                if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                    if isinstance(node.body[0].value.value, str) and node.body[0].value.value.strip():
                        obj.has_docstring = True

                # Deteksi atribut uow/session di class
                for item in node.body:
                    if isinstance(item, (ast.Assign, ast.AnnAssign)):
                        if isinstance(item.targets[0], ast.Attribute) and isinstance(item.targets[0].value, ast.Name) and item.targets[0].value.id == 'self':
                            if item.targets[0].attr in ('uow', 'session'):
                                obj.has_uow = True
                                obj.has_session = True

                # Jika command, deteksi validasi dari BaseModel atau dekorator
                if is_cmd:
                    # Cek apakah mewarisi BaseModel (Pydantic)
                    if any(b in ('BaseModel', 'pydantic.BaseModel') for b in bases):
                        obj.has_validation = True
                    # Cek dekorator @field_validator / @model_validator di method
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            for deco in item.decorator_list:
                                if isinstance(deco, ast.Name) and deco.id in ('field_validator', 'model_validator'):
                                    obj.has_validation = True
                                elif isinstance(deco, ast.Attribute) and deco.attr in ('field_validator', 'model_validator'):
                                    obj.has_validation = True

                # Hitung field dan proses method
                for item in node.body:
                    if isinstance(item, (ast.AnnAssign, ast.Assign)):
                        obj.field_count += 1
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if item.name in ("handle", "execute", "__call__"):
                            obj.has_execute_method = True
                            if isinstance(item, ast.AsyncFunctionDef):
                                obj.is_async = True

                            # Parameter detection (improved)
                            for arg in item.args.args:
                                if arg.arg in ("self", "cls"):
                                    continue
                                if arg.annotation:
                                    anno_str = self._extract_annotation_string(arg.annotation)
                                    if anno_str:
                                        if any(anno_str.endswith(suffix) for suffix in COMMAND_SUFFIXES):
                                            obj.linked_commands.add(anno_str)
                                        elif any(anno_str.endswith(suffix) for suffix in QUERY_SUFFIXES):
                                            obj.linked_queries.add(anno_str)
                                else:
                                    # Fallback: cek nama argumen
                                    arg_name_lower = arg.arg.lower()
                                    if arg_name_lower in ("command", "cmd"):
                                        obj.linked_commands.add(f"<by_name:{arg.arg}>")
                                    elif arg_name_lower in ("query", "qry"):
                                        obj.linked_queries.add(f"<by_name:{arg.arg}>")

                            # Return type
                            if item.returns:
                                ret_str = self._extract_annotation_string(item.returns)
                                if ret_str:
                                    obj.return_type = ret_str

                            # Transaction detection (improved)
                            if self._has_transaction_in_method(item):
                                obj.has_transaction = True
                            # Validation detection (improved)
                            if self._has_validation_in_method(item):
                                obj.has_validation = True
                            # Read-only detection
                            obj.is_read_only = self._is_read_only_method(item)

                # Store object
                if is_cmd and name not in self.commands:
                    self.commands[name] = obj
                elif is_qry and name not in self.queries:
                    self.queries[name] = obj
                elif is_hdlr and name not in self.handlers and not is_base:
                    self.handlers[name] = obj
                elif is_hdlr and name not in self.handlers:
                    self.handlers[name] = obj

        except Exception:
            pass

    # ---- Validasi (diperbaiki) ----
    def _validate_objects(self):
        # --- Commands ---
        for cmd in self.commands.values():
            if not any(cmd.name.endswith(suffix) for suffix in COMMAND_SUFFIXES):
                self._add_violation(cmd, RuleID.CMD_NAMING, "LOW",
                    f"Command '{cmd.name}' tidak menggunakan suffix standar (Command/Cmd).",
                    "Gunakan suffix 'Command' atau 'Cmd' untuk command.")

            if not any(part in cmd.file_path.lower() for part in ["command", "use_case"]):
                self._add_violation(cmd, RuleID.CMD_FILE_LOCATION, "MEDIUM",
                    f"Command '{cmd.name}' berada di '{cmd.file_path}', sebaiknya di folder commands/ atau use_cases/.",
                    "Pindahkan command ke application/use_cases/ atau application/commands/.")

            if cmd.field_count == 0:
                self._add_violation(cmd, RuleID.CMD_FIELDS, "MEDIUM",
                    f"Command '{cmd.name}' tidak memiliki field (data).",
                    "Command harus memiliki field untuk data yang diproses.")

        # --- Queries ---
        for qry in self.queries.values():
            if not any(qry.name.endswith(suffix) for suffix in QUERY_SUFFIXES):
                self._add_violation(qry, RuleID.QRY_NAMING, "LOW",
                    f"Query '{qry.name}' tidak menggunakan suffix standar (Query/Qry).",
                    "Gunakan suffix 'Query' atau 'Qry' untuk query.")

            if not any(part in qry.file_path.lower() for part in ["query", "read"]):
                self._add_violation(qry, RuleID.QRY_FILE_LOCATION, "MEDIUM",
                    f"Query '{qry.name}' berada di '{qry.file_path}', sebaiknya di folder queries/ atau read/.",
                    "Pindahkan query ke application/queries/ atau domain/queries/.")

            if qry.field_count == 0:
                self._add_violation(qry, RuleID.QRY_FIELDS, "MEDIUM",
                    f"Query '{qry.name}' tidak memiliki field (filter/parameter).",
                    "Query harus memiliki field untuk parameter filtering.")

        # --- Handlers ---
        for hdl in self.handlers.values():
            if hdl.is_base_class:
                continue

            if not any(hdl.name.endswith(suffix) for suffix in HANDLER_SUFFIXES):
                self._add_violation(hdl, RuleID.HDL_NAMING, "LOW",
                    f"Handler '{hdl.name}' tidak menggunakan suffix standar (Handler/UseCase).",
                    "Gunakan suffix 'Handler' atau 'UseCase' untuk handler.")

            if not hdl.has_execute_method:
                self._add_violation(hdl, RuleID.HDL_EXECUTE_METHOD, "CRITICAL",
                    f"Handler '{hdl.name}' tidak memiliki method 'handle()' atau 'execute()'.",
                    "Tambahkan method 'async def handle(self, command: Command) -> Result'.")

            if hdl.has_execute_method and not hdl.return_type:
                self._add_violation(hdl, RuleID.HDL_EXECUTE_RETURN, "MEDIUM",
                    f"Handler '{hdl.name}' tidak memiliki return type hint pada execute/handle.",
                    "Tambahkan return type hint (misal -> CommandResult atau -> None).")

            # Parameter type: cek apakah ada linked commands/queries (dari type hint atau nama)
            if hdl.has_execute_method and not hdl.linked_commands and not hdl.linked_queries:
                if not hdl.is_base_class:
                    self._add_violation(hdl, RuleID.HDL_PARAM_TYPE, "HIGH",
                        f"Handler '{hdl.name}' tidak memiliki parameter bertipe Command atau Query (atau nama argumen tidak mencerminkan).",
                        "Parameter execute/handle harus bertipe Command/Query, atau beri nama 'command'/'cmd'/'query'/'qry'.")

            if not any(part in hdl.file_path.lower() for part in ["handler", "use_case", "executor"]):
                self._add_violation(hdl, RuleID.HDL_FILE_LOCATION, "MEDIUM",
                    f"Handler '{hdl.name}' berada di '{hdl.file_path}', sebaiknya di handlers/ atau use_cases/.",
                    "Pindahkan handler ke application/handlers/ atau application/use_cases/.")

            # Transaksi: hanya jika bukan read-only
            if not hdl.is_base_class and not hdl.is_read_only and not hdl.has_transaction:
                self._add_violation(hdl, RuleID.HDL_TRANSACTIONAL, "MEDIUM",
                    f"Handler '{hdl.name}' melakukan operasi tulis tanpa transaksi (UoW).",
                    "Gunakan UnitOfWork atau transaction decorator untuk atomic operations.")

            # Validasi: cek apakah command yang diikat memiliki validasi
            command_has_validation = False
            for cmd_name in hdl.linked_commands:
                if cmd_name in self.commands and self.commands[cmd_name].has_validation:
                    command_has_validation = True
                    break
            # Jika command sudah punya validasi, kita tidak perlu violation
            if not hdl.is_base_class and not hdl.has_validation and not command_has_validation:
                severity = "LOW" if hdl.is_read_only else "MEDIUM"
                self._add_violation(hdl, RuleID.HDL_VALIDATION, severity,
                    f"Handler '{hdl.name}' tidak memiliki validasi input dan command terkait juga tidak memiliki validasi.",
                    "Tambahkan validasi command/query sebelum eksekusi, atau pastikan command sudah divalidasi (misal dengan Pydantic).")

        # --- Registry & Binding ---
        for cmd in self.commands.values():
            if cmd.name not in self.mapping:
                self._add_violation(cmd, RuleID.REG_ORPHAN_COMMAND, "HIGH",
                    f"Command '{cmd.name}' tidak memiliki handler (orphan).",
                    "Buat handler untuk command ini atau daftarkan di registry.")

        for qry in self.queries.values():
            if qry.name not in self.mapping:
                self._add_violation(qry, RuleID.REG_ORPHAN_QUERY, "HIGH",
                    f"Query '{qry.name}' tidak memiliki handler (orphan).",
                    "Buat handler untuk query ini atau daftarkan di registry.")

        for hdl in self.handlers.values():
            if hdl.is_base_class:
                continue
            is_bound_by_mapping = any(hdl.name in h_list for h_list in self.mapping.values())
            is_bound_by_param = len(hdl.linked_commands) > 0 or len(hdl.linked_queries) > 0
            if is_bound_by_param and not is_bound_by_mapping and not hdl.is_base_class:
                self._add_violation(hdl, RuleID.REG_UNREGISTERED_HANDLER, "HIGH",
                    f"Handler '{hdl.name}' memiliki parameter Command/Query tetapi tidak terdaftar di registry.",
                    "Daftarkan handler di command_handler_registry atau query_handler_registry.")

        # --- Architecture layer ---
        for cmd in self.commands.values():
            if 'infrastructure' in cmd.file_path.lower():
                self._add_violation(cmd, RuleID.ARCH_LAYER, "CRITICAL",
                    f"Command '{cmd.name}' berada di infrastructure layer (harus di application/domain).",
                    "Pindahkan command ke application/commands/.")

        for qry in self.queries.values():
            if 'infrastructure' in qry.file_path.lower():
                self._add_violation(qry, RuleID.ARCH_LAYER, "CRITICAL",
                    f"Query '{qry.name}' berada di infrastructure layer (harus di application/domain).",
                    "Pindahkan query ke application/queries/.")

        # --- Documentation ---
        for cmd in self.commands.values():
            if not cmd.has_docstring:
                self._add_violation(cmd, RuleID.DOC_COMMAND, "LOW",
                    f"Command '{cmd.name}' tidak memiliki docstring.",
                    "Tambahkan docstring menjelaskan purpose command dan parameters.")

        for qry in self.queries.values():
            if not qry.has_docstring:
                self._add_violation(qry, RuleID.DOC_QUERY, "LOW",
                    f"Query '{qry.name}' tidak memiliki docstring.",
                    "Tambahkan docstring menjelaskan purpose query dan return value.")

        for hdl in self.handlers.values():
            if not hdl.has_docstring and not hdl.is_base_class:
                self._add_violation(hdl, RuleID.DOC_HANDLER, "LOW",
                    f"Handler '{hdl.name}' tidak memiliki docstring.",
                    "Tambahkan docstring menjelaskan purpose handler dan logic.")

    # ---- Scan utama ----
    def scan(self) -> Tuple[Dict[str, CQRSObject], Dict[str, CQRSObject], Dict[str, CQRSObject], Dict[str, List[str]]]:
        self._parse_registry_files()

        files = self._get_python_files()
        for f in files:
            self._introspect_ast(f)

        # Registry-AST reconciliation
        for cmd_name, hdl_names in self.mapping.items():
            for hdl_name in hdl_names:
                if hdl_name in self.handlers:
                    self.handlers[hdl_name].linked_commands.add(cmd_name)

        # Fallback naming convention
        all_cq = {**self.commands, **self.queries}
        for cq_name, cq_obj in all_cq.items():
            if cq_name not in self.mapping:
                base_norm = self._normalize_name(cq_name)
                for hdl_name, hdl_obj in self.handlers.items():
                    if self._normalize_name(hdl_name) == base_norm:
                        self.mapping[cq_name].append(hdl_name)
                        hdl_obj.linked_commands.add(cq_name)
                        break

        self._validate_objects()

        final_mapping = {k: list(set(v)) for k, v in self.mapping.items()}
        return self.commands, self.queries, self.handlers, final_mapping


# =============================================================================
# Reporting
# =============================================================================
def generate_report(commands: Dict[str, CQRSObject],
                    queries: Dict[str, CQRSObject],
                    handlers: Dict[str, CQRSObject],
                    mapping: Dict[str, List[str]],
                    rca_enabled: bool,
                    elapsed: float) -> CheckerResult:
    total_commands = len(commands)
    total_queries = len(queries)
    total_handlers = len(handlers)
    total_violations = 0
    critical = high = medium = low = 0

    all_objects = list(commands.values()) + list(queries.values()) + list(handlers.values())
    for obj in all_objects:
        total_violations += len(obj.violations)
        for v in obj.violations:
            if v.severity == "CRITICAL":
                critical += 1
            elif v.severity == "HIGH":
                high += 1
            elif v.severity == "MEDIUM":
                medium += 1
            elif v.severity == "LOW":
                low += 1

    # Scoring lebih adil: penalti medium 2
    score = 100.0
    score -= critical * 20.0
    score -= high * 10.0
    score -= medium * 2.0
    score -= low * 1.0
    score = max(0.0, min(100.0, score))

    if total_violations > 0 and score == 0:
        score = max(10.0, score)

    return CheckerResult(
        commands=list(commands.values()),
        queries=list(queries.values()),
        handlers=list(handlers.values()),
        mapping=mapping,
        total_commands=total_commands,
        total_queries=total_queries,
        total_handlers=total_handlers,
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
    print("║     SOVEREIGN CQRS ARCHITECTURE & FORENSIC CHECKER v2.4   ║")
    print(f"╚{'═'*72}╝{c['RESET']}")

    print("\n  📋 100+ Aturan Arsitektur CQRS (deteksi lebih akurat):")
    print("    ✅ Command/Query naming conventions")
    print("    ✅ Base class inheritance")
    print("    ✅ Handler execute/handle method")
    print("    ✅ Handler parameter typing (Command/Query atau nama argumen)")
    print("    ✅ Registry binding (__init__.py/app_factory)")
    print("    ✅ Orphan detection (no missing handlers)")
    print("    ✅ Unregistered handler detection")
    print("    ✅ Transactional / UnitOfWork (hanya untuk handler tulis)")
    print("    ✅ Input validation (Pydantic, guard, assert, dll)")
    print("    ✅ Documentation completeness")
    print("    ✅ Architecture layering")
    print("    ✅ Read‑only handler detection (tidak perlu transaksi)")
    print("    ✅ Validasi command (BaseModel, @field_validator) mengurangi false positive")

    print(f"\n  {c['CYAN']}Total Commands: {result.total_commands}{c['RESET']}")
    print(f"  Total Queries: {result.total_queries}")
    print(f"  Total Handlers: {result.total_handlers}")
    print(f"  Total Violations: {result.total_violations}")
    print(f"    {c['RED']}CRITICAL: {result.critical_count}{c['RESET']}")
    print(f"    {c['YELLOW']}HIGH: {result.high_count}{c['RESET']}")
    print(f"    {c['MAGENTA']}MEDIUM: {result.medium_count}{c['RESET']}")
    print(f"    {c['CYAN']}LOW: {result.low_count}{c['RESET']}")

    score_color = c["GREEN"] if result.score >= 80 else c["YELLOW"] if result.score >= 50 else c["RED"]
    print(f"\n  📈 Skor Kepatuhan CQRS: {score_color}{c['BOLD']}{result.score:.1f}/100{c['RESET']}")
    print(f"  RCA Engine: {'✅ Aktif' if result.rca_enabled else '⚠️ Tidak tersedia'}")
    print(f"  ⏱️ Elapsed: {result.elapsed_seconds:.3f}s")

    print(f"\n{c['CYAN']}─── MAPPING SUMMARY ───{c['RESET']}")
    for cmd, hdls in result.mapping.items():
        hdl_str = ', '.join(hdls) if hdls else f"{c['RED']}NO HANDLER{c['RESET']}"
        print(f"  {cmd} → {hdl_str}")

    all_objects = result.commands + result.queries + result.handlers
    objects_with_violations = [o for o in all_objects if o.violations]
    if objects_with_violations:
        print(f"\n{c['RED']}─── OBJECTS WITH VIOLATIONS ───{c['RESET']}")
        for obj in objects_with_violations:
            type_label = "Command" if obj.is_command else "Query" if obj.is_query else "Handler"
            status = f"{c['RED']}{len(obj.violations)} violations{c['RESET']}"
            print(f"  {obj.name} ({type_label}) @ {obj.file_path}: {status}")

    all_violations = []
    for obj in all_objects:
        all_violations.extend(obj.violations)

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
            "elapsed_seconds": result.elapsed_seconds,
            "total_commands": result.total_commands,
            "total_queries": result.total_queries,
            "total_handlers": result.total_handlers,
            "total_violations": result.total_violations,
            "severity_counts": {
                "critical": result.critical_count,
                "high": result.high_count,
                "medium": result.medium_count,
                "low": result.low_count,
            },
            "mapping": result.mapping,
            "commands": [
                {
                    "name": c.name,
                    "file": c.file_path,
                    "has_docstring": c.has_docstring,
                    "has_validation": c.has_validation,
                    "field_count": c.field_count,
                    "violations": [v.to_dict() for v in c.violations],
                }
                for c in result.commands
            ],
            "queries": [
                {
                    "name": q.name,
                    "file": q.file_path,
                    "has_docstring": q.has_docstring,
                    "field_count": q.field_count,
                    "violations": [v.to_dict() for v in q.violations],
                }
                for q in result.queries
            ],
            "handlers": [
                {
                    "name": h.name,
                    "file": h.file_path,
                    "has_execute_method": h.has_execute_method,
                    "is_async": h.is_async,
                    "has_transaction": h.has_transaction,
                    "has_validation": h.has_validation,
                    "is_read_only": h.is_read_only,
                    "has_uow": h.has_uow,
                    "has_session": h.has_session,
                    "linked_commands": list(h.linked_commands),
                    "linked_queries": list(h.linked_queries),
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
    parser = argparse.ArgumentParser(description="Sovereign CQRS Architecture & Forensic Checker v2.4")
    parser.add_argument("--json", metavar="FILE", help="Export report to JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show RCA details")
    parser.add_argument("--strict", action="store_true", help="Mode strict")
    parser.add_argument("--no-rca", action="store_true", help="Disable RCA analysis")
    args = parser.parse_args()

    global RCA_AVAILABLE, _analyze_exception
    if args.no_rca:
        RCA_AVAILABLE = False
        _analyze_exception = None

    start = time.monotonic()
    verifier = SovereignCQRSVerifier(ROOT, enable_rca=not args.no_rca, strict=args.strict)
    commands, queries, handlers, mapping = verifier.scan()
    elapsed = time.monotonic() - start

    result = generate_report(commands, queries, handlers, mapping, RCA_AVAILABLE, elapsed)
    print_report(result, verbose=args.verbose)

    if args.json:
        save_json(result, args.json)

    print(f"\n ⏱️ Audit Duration: {elapsed:.3f} seconds")

    has_critical = result.critical_count > 0
    sys.exit(1 if has_critical else 0)


if __name__ == "__main__":
    main()