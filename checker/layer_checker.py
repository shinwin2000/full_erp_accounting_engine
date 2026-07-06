#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
layer_checker.py — Layer Dependency Validator for Hexagonal/DDD Architecture
=============================================================================
Versi   : 3.0.6
Standar : Big 4 Forensic Audit · ISO/IEC 25010 · SOX/ISA 315 Compliant
Integrasi penuh dengan RCA engine (checker/core/rca.py).

Perubahan v3.0.6:
  - Deteksi siklus sekarang hanya mempertimbangkan import runtime:
    * top-level (bukan di dalam fungsi/class)
    * bukan di dalam blok TYPE_CHECKING
    * bukan import relatif
  - Konsisten dengan checker_integration.py
  - Mempertahankan semua fitur lain (RCA, JSON, dll.)
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import json
import logging
import os
import pathlib
import sys
import threading
import time
import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from typing import (
    Any, Dict, FrozenSet, Iterator, List, Optional,
    Set, Tuple, Union,
)

# ─── RCA ENGINE INTEGRATION ─────────────────────────────────────────────────
_RCA_ENGINE = None
_RCA_AVAILABLE = False

def _init_rca() -> bool:
    global _RCA_ENGINE, _RCA_AVAILABLE
    if _RCA_AVAILABLE:
        return True
    try:
        from checker.core.rca import RCAEngine, RCAResult, Severity
        _RCA_ENGINE = RCAEngine()
        _RCA_AVAILABLE = True
        return True
    except ImportError:
        pass
    _root = pathlib.Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    try:
        from checker.core.rca import RCAEngine, RCAResult, Severity
        _RCA_ENGINE = RCAEngine()
        _RCA_AVAILABLE = True
        return True
    except ImportError:
        pass
    return False

_init_rca()

def _rca_analyze(exc: Exception, context: Optional[Dict] = None) -> Optional[Any]:
    if not _RCA_AVAILABLE or _RCA_ENGINE is None:
        return {
            "severity": "WARNING",
            "root_cause": str(exc)[:200],
            "suggested_fix": "Install checker.core.rca atau periksa dependency.",
            "confidence": 0.0,
        }
    try:
        return _RCA_ENGINE.analyze(exc, context or {})
    except Exception as e:
        return {
            "severity": "WARNING",
            "root_cause": f"RCA analysis failed: {e}",
            "suggested_fix": "Periksa kestabilan RCA engine.",
            "confidence": 0.0,
        }

def _rca_to_dict(rca_result: Optional[Any]) -> Optional[Dict[str, Any]]:
    if rca_result is None:
        return None
    if isinstance(rca_result, dict):
        return rca_result
    try:
        if hasattr(rca_result, "to_dict"):
            return rca_result.to_dict()
        return {
            "severity": getattr(rca_result, "severity", "UNKNOWN"),
            "root_cause": getattr(rca_result, "root_cause", ""),
            "suggested_fix": getattr(rca_result, "suggested_fix", ""),
            "confidence": getattr(rca_result, "confidence", 0.0),
        }
    except Exception:
        return {"error": "RCA serialization failed"}

# ─── HELPER FUNCTIONS ──────────────────────────────────────────────────────
def _build_stdlib_set() -> Set[str]:
    if hasattr(sys, "stdlib_module_names"):
        return set(sys.stdlib_module_names)
    return {
        "__future__", "_thread", "abc", "argparse", "array", "ast",
        "asyncio", "atexit", "base64", "bisect", "builtins", "bz2",
        "calendar", "cmath", "cmd", "codecs", "collections", "concurrent",
        "configparser", "contextlib", "copy", "csv", "dataclasses", "datetime",
        "decimal", "difflib", "dis", "doctest", "email", "enum", "errno",
        "functools", "gc", "gettext", "glob", "hashlib", "heapq", "hmac",
        "html", "http", "importlib", "inspect", "io", "itertools", "json",
        "keyword", "locale", "logging", "math", "multiprocessing", "operator",
        "os", "pathlib", "pickle", "pprint", "queue", "random", "re",
        "reprlib", "shutil", "signal", "socket", "sqlite3", "ssl", "stat",
        "string", "struct", "subprocess", "sys", "tempfile", "textwrap",
        "threading", "time", "traceback", "types", "typing", "unittest",
        "urllib", "uuid", "warnings", "weakref", "xml", "zipfile", "zlib",
    }

def get_layer(module: str) -> str:
    if not module: return "unknown"
    top = module.split(".")[0]
    return LAYER_MAP.get(top, "unknown")

def is_stdlib(module: str) -> bool:
    return module.split(".")[0] in STD_LIB_MODULES

def is_friend(layer: str, module: str) -> bool:
    return any(module == f or module.startswith(f+".") for f in FRIEND_PACKAGES.get(layer, set()))

def is_allowed_third_party(module: str) -> bool:
    return module.split(".")[0] in ALWAYS_ALLOWED_THIRD_PARTY

def resolve_relative_import(source_module: str, level: int, target: Optional[str]) -> str:
    parts = source_module.split(".")
    # level=1 berarti current package, level=2 parent package, dst.
    # Kita naik (level - 1) sesuai PEP 328
    up = max(0, level - 1)
    if up > len(parts):
        return target or ""
    base = ".".join(parts[:-up]) if up > 0 else ""
    if not base:
        return target or (parts[0] if parts else "")
    return f"{base}.{target}" if target else base

def get_relative_path(p: pathlib.Path, root: pathlib.Path) -> str:
    try: return str(p.relative_to(root)).replace("\\", "/")
    except ValueError: return str(p).replace("\\", "/")

def _normalize_cycle(cycle: List[str]) -> Tuple[str, ...]:
    if not cycle: return ()
    c = cycle[:]
    if len(c) > 1 and c[0] == c[-1]: c = c[:-1]
    if not c: return ()
    min_idx = min(range(len(c)), key=lambda i: c[i])
    rotated = c[min_idx:] + c[:min_idx]
    return tuple(rotated)

# ─── LOGGING ──────────────────────────────────────────────────────────────────
_log_handler = logging.StreamHandler(sys.stderr)
_log_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
))
logger = logging.getLogger("layer_checker")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    logger.addHandler(_log_handler)

# ─── COLOR ──────────────────────────────────────────────────────────────────
COLOR: Dict[str, str] = {
    "RED": "", "GREEN": "", "YELLOW": "", "CYAN": "", "BOLD": "", "DIM": "", "RESET": "",
}
try:
    import colorama
    colorama.init(autoreset=True)
    COLOR.update({
        "RED"   : colorama.Fore.RED,
        "GREEN" : colorama.Fore.GREEN,
        "YELLOW": colorama.Fore.YELLOW,
        "CYAN"  : colorama.Fore.CYAN,
        "BOLD"  : colorama.Style.BRIGHT,
        "DIM"   : colorama.Style.DIM,
        "RESET" : colorama.Style.RESET_ALL,
    })
except ImportError:
    pass

# ─── VERSION ──────────────────────────────────────────────────────────────────
__version__ = "3.0.6"

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
LAYER_MAP: Dict[str, str] = {
    "domain"        : "domain",
    "axioms"        : "axioms",
    "constitution"  : "constitution",
    "kernel"        : "kernel",
    "ports"         : "ports",
    "application"   : "application",
    "adapters"      : "adapters",
    "infrastructure": "infrastructure",
    "bootstrap"     : "bootstrap",
    "config"        : "config",
    "app"           : "app",
    "policy_engine" : "policy_engine",
    "compliance"    : "compliance",
    "audit"         : "audit",
    "projections"   : "projections",
    "reports"       : "reports",
    "event_gateway" : "event_gateway",
    "checker"       : "checker",
    "scripts"       : "scripts",
    "tools"         : "tools",
    "migrations"    : "migrations",
    "deployment"    : "deployment",
    "docs"          : "docs",
    "monitoring"    : "monitoring",
    "config_files"  : "config_files",
    "logs"          : "logs",
    "tests"         : "tests",
    "test"          : "test",
    "utils"         : "utils",
    "common"        : "common",
    "shared"        : "shared",
    "lib"           : "lib",
    "vendor"        : "vendor",
    "external"      : "external",
}

ALLOWED_PAIRS: FrozenSet[Tuple[str, str]] = frozenset({
    ("domain", "domain"),
    ("domain", "axioms"),
    ("domain", "constitution"),
    ("axioms", "axioms"),
    ("axioms", "constitution"),
    ("constitution", "constitution"),
    ("constitution", "domain"),
    ("constitution", "axioms"),
    ("kernel", "kernel"),
    ("kernel", "domain"),
    ("kernel", "axioms"),
    ("kernel", "constitution"),
    ("kernel", "ports"),
    ("kernel", "config"),
    ("ports", "ports"),
    ("ports", "domain"),
    ("application", "application"),
    ("application", "domain"),
    ("application", "kernel"),
    ("application", "ports"),
    ("application", "axioms"),
    ("application", "constitution"),
    ("application", "config"),
    ("application", "policy_engine"),
    ("application", "audit"),
    ("adapters", "adapters"),
    ("adapters", "application"),
    ("adapters", "domain"),
    ("adapters", "kernel"),
    ("adapters", "ports"),
    ("adapters", "infrastructure"),
    ("adapters", "config"),
    ("projections", "projections"),
    ("projections", "domain"),
    ("projections", "application"),
    ("projections", "infrastructure"),
    ("projections", "config"),
    ("reports", "reports"),
    ("reports", "projections"),
    ("reports", "application"),
    ("reports", "infrastructure"),
    ("reports", "config"),
    ("event_gateway", "event_gateway"),
    ("event_gateway", "domain"),
    ("event_gateway", "application"),
    ("event_gateway", "infrastructure"),
    ("infrastructure", "infrastructure"),
    ("infrastructure", "domain"),
    ("infrastructure", "ports"),
    ("infrastructure", "kernel"),
    ("infrastructure", "config"),
    ("bootstrap", "bootstrap"),
    ("bootstrap", "config"),
    ("bootstrap", "infrastructure"),
    ("bootstrap", "application"),
    ("bootstrap", "adapters"),
    ("bootstrap", "ports"),
    ("app", "app"),
    ("app", "bootstrap"),
    ("app", "adapters"),
    ("app", "infrastructure"),
    ("policy_engine", "policy_engine"),
    ("policy_engine", "domain"),
    ("policy_engine", "kernel"),
    ("policy_engine", "config"),
    ("policy_engine", "compliance"),
    ("compliance", "compliance"),
    ("compliance", "policy_engine"),
    ("compliance", "domain"),
    ("compliance", "application"),
    ("audit", "audit"),
    ("audit", "domain"),
    ("audit", "application"),
    ("audit", "kernel"),
    ("config", "config"),
    ("checker", "checker"),
    ("scripts", "scripts"),
    ("tools", "tools"),
    ("migrations", "migrations"),
    ("deployment", "deployment"),
    ("docs", "docs"),
    ("monitoring", "monitoring"),
    ("config_files", "config_files"),
    ("logs", "logs"),
    ("tests", "tests"),
    ("test", "test"),
    ("utils", "utils"),
    ("common", "common"),
    ("shared", "shared"),
    ("lib", "lib"),
    ("vendor", "vendor"),
    ("external", "external"),
    ("app", "kernel"),
})

# Aturan khusus untuk import yang memang diperlukan (exception)
ALLOWED_SPECIAL_IMPORTS: List[Tuple[str, str, str]] = [
    ("application", "infrastructure", "infrastructure"),
    ("adapters", "bootstrap.dependency_container", "bootstrap"),
]

SKIP_LAYERS: FrozenSet[str] = frozenset({
    "unknown", "checker", "scripts", "tools", "migrations", "deployment",
    "docs", "monitoring", "config_files", "logs", "tests", "test",
    "utils", "common", "shared", "lib", "vendor", "external",
})

STD_LIB_MODULES: Set[str] = _build_stdlib_set()

FRIEND_PACKAGES: Dict[str, Set[str]] = {
    "domain"     : {"typing", "abc", "dataclasses", "enum", "uuid", "decimal", "datetime", "zoneinfo"},
    "application": {"typing", "dataclasses", "enum", "uuid", "decimal", "datetime"},
    "kernel"     : {"typing", "dataclasses", "enum", "uuid", "decimal", "datetime"},
}

ALWAYS_ALLOWED_THIRD_PARTY: Set[str] = {
    "dateutil", "pydantic", "sqlalchemy", "alembic", "celery",
    "redis", "kafka", "boto3", "requests", "httpx", "aiohttp",
    "fastapi", "starlette", "uvicorn", "gunicorn",
    "pytest", "hypothesis",
}

# ─── DATA CLASSES ─────────────────────────────────────────────────────────────
class ViolationSeverity:
    FATAL    = "FATAL"
    CRITICAL = "CRITICAL"
    HIGH     = "HIGH"
    MEDIUM   = "MEDIUM"
    LOW      = "LOW"

    @staticmethod
    def for_pair(src: str, tgt: str) -> str:
        _inner = {"domain", "axioms", "constitution", "ports"}
        _outer = {"infrastructure", "adapters", "bootstrap", "app"}
        _business = {"application", "kernel", "policy_engine", "compliance", "audit"}
        if src in _inner and tgt in _outer:
            return ViolationSeverity.FATAL
        if src in _inner and tgt in _business:
            return ViolationSeverity.CRITICAL
        return ViolationSeverity.HIGH

    @staticmethod
    def for_cycle(cycle: List[str]) -> str:
        important = {"domain", "axioms", "constitution", "kernel", "ports"}
        if any(l in important for l in cycle):
            return ViolationSeverity.FATAL
        return ViolationSeverity.HIGH

@dataclass
class ImportRecord:
    source_file  : str
    source_layer : str
    target_module: str
    target_layer : str
    line         : int
    is_relative  : bool = False
    is_toplevel  : bool = True
    in_type_checking: bool = False
    in_try_except: bool = False

@dataclass
class Violation:
    source_file  : str
    source_layer : str
    target_module: str
    target_layer : str
    line         : int
    rule         : str
    severity     : str
    message      : str
    is_toplevel  : bool = True
    in_type_checking: bool = False
    in_try_except: bool = False
    rca: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {
            "source_file"   : self.source_file,
            "source_layer"  : self.source_layer,
            "target_module" : self.target_module,
            "target_layer"  : self.target_layer,
            "line"          : self.line,
            "rule"          : self.rule,
            "severity"      : self.severity,
            "is_toplevel"   : self.is_toplevel,
            "in_type_checking": self.in_type_checking,
            "in_try_except" : self.in_try_except,
            "message"       : self.message,
            "rca"           : self.rca,
        }

@dataclass
class CycleViolation(Violation):
    cycle: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        d = super().to_dict()
        d["cycle"] = " → ".join(self.cycle + [self.cycle[0]]) if self.cycle else ""
        return d

@dataclass
class LayerStats:
    total_files    : int = 0
    total_imports  : int = 0
    skipped_files  : int = 0
    parse_errors   : List[str] = field(default_factory=list)
    violations     : List[Violation] = field(default_factory=list)
    layer_counts   : Dict[str, int] = field(default_factory=dict)
    dependency_graph: Dict[str, Set[str]] = field(default_factory=dict)
    cycles         : List[List[str]] = field(default_factory=list)
    scan_time_s    : float = 0.0
    rca_enriched   : bool = False

    @property
    def violation_count(self) -> int: return len(self.violations)
    @property
    def cycle_count(self) -> int: return len(self.cycles)
    @property
    def is_clean(self) -> bool: return self.violation_count == 0 and self.cycle_count == 0

# ─── AST PARSER ──────────────────────────────────────────────────────────────
_AST_CACHE: Dict[str, Tuple[Optional[ast.AST], Optional[str]]] = {}
_CACHE_LOCK = threading.Lock()

def get_ast_cached(file_path: pathlib.Path) -> Tuple[Optional[ast.AST], Optional[str]]:
    key = str(file_path.resolve())
    with _CACHE_LOCK:
        if key in _AST_CACHE:
            return _AST_CACHE[key]
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
        error = None
    except SyntaxError as e:
        tree, error = None, f"SyntaxError: {e}"
    except Exception as e:
        tree, error = None, f"{type(e).__name__}: {e}"
    with _CACHE_LOCK:
        _AST_CACHE[key] = (tree, error)
    return tree, error

def extract_imports(file_path: pathlib.Path, root: pathlib.Path) -> Tuple[List[ImportRecord], Optional[str]]:
    """
    Ekstrak semua import dengan konteks (top-level, TYPE_CHECKING, relatif, dll.)
    """
    tree, error = get_ast_cached(file_path)
    if error or tree is None:
        return [], error

    rel_path = get_relative_path(file_path, root)
    source_module = rel_path.replace("/", ".").rsplit(".", 1)[0]
    source_layer = get_layer(source_module)
    records: List[ImportRecord] = []

    class ImportVisitor(ast.NodeVisitor):
        def __init__(self):
            self.records = []
            self.type_checking_depth = 0
            self.try_depth = 0
            self.scope_depth = 0          # 0 = modul, >0 = di dalam fungsi/class

        def visit_FunctionDef(self, node):
            self.scope_depth += 1
            self.generic_visit(node)
            self.scope_depth -= 1

        def visit_AsyncFunctionDef(self, node):
            self.scope_depth += 1
            self.generic_visit(node)
            self.scope_depth -= 1

        def visit_ClassDef(self, node):
            self.scope_depth += 1
            self.generic_visit(node)
            self.scope_depth -= 1

        def visit_If(self, node):
            if self._is_type_checking_condition(node.test):
                self.type_checking_depth += 1
                self.generic_visit(node)
                self.type_checking_depth -= 1
            else:
                self.generic_visit(node)

        def visit_Try(self, node):
            self.try_depth += 1
            self.generic_visit(node)
            self.try_depth -= 1

        def _is_type_checking_condition(self, test):
            if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                return True
            if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
                return True
            # fallback: typing.TYPE_CHECKING
            if (isinstance(test, ast.Attribute) and
                isinstance(test.value, ast.Name) and
                test.value.id == "typing" and test.attr == "TYPE_CHECKING"):
                return True
            return False

        def _make_record(self, node, target_module: str, is_relative: bool = False):
            self.records.append(ImportRecord(
                source_file=rel_path,
                source_layer=source_layer,
                target_module=target_module,
                target_layer=get_layer(target_module),
                line=node.lineno,
                is_relative=is_relative,
                is_toplevel=(self.scope_depth == 0),
                in_type_checking=(self.type_checking_depth > 0),
                in_try_except=(self.try_depth > 0),
            ))

        def visit_Import(self, node):
            for alias in node.names:
                self._make_record(node, alias.name, is_relative=False)
            self.generic_visit(node)

        def visit_ImportFrom(self, node):
            level = node.level or 0
            if level == 0:
                target_mod = node.module or ""
            else:
                target_mod = resolve_relative_import(source_module, level, node.module)
            if target_mod:
                self._make_record(node, target_mod, is_relative=(level > 0))
            self.generic_visit(node)

    visitor = ImportVisitor()
    visitor.visit(tree)
    return visitor.records, None

# ─── CYCLE DETECTION ──────────────────────────────────────────────────────────
def find_cycles(graph: Dict[str, Set[str]], max_cycles: int = 100) -> List[List[str]]:
    seen = set()
    result = []
    for start in list(graph.keys()):
        if len(result) >= max_cycles:
            break
        stack = [(start, iter(sorted(graph.get(start, set()))), [start], {start})]
        visited = {start}
        while stack and len(result) < max_cycles:
            node, it, path, path_set = stack[-1]
            try:
                nxt = next(it)
                if nxt in path_set:
                    idx = path.index(nxt)
                    cycle = path[idx:]
                    norm = _normalize_cycle(cycle)
                    if norm and norm not in seen and len(cycle) >= 2:
                        seen.add(norm)
                        result.append(cycle)
                elif nxt not in visited:
                    visited.add(nxt)
                    stack.append((nxt, iter(sorted(graph.get(nxt, set()))), path + [nxt], path_set | {nxt}))
            except StopIteration:
                stack.pop()
    return result

# ─── CHECKER ──────────────────────────────────────────────────────────────────
class LayerChecker:
    VERSION = __version__

    def __init__(
        self,
        root: Optional[pathlib.Path] = None,
        max_workers: int = 8,
        enable_rca: bool = True,
        strict_toplevel: bool = False,
        max_cycles: int = 100,
        exclude_dirs: Optional[Set[str]] = None,
        exclude_files: Optional[Set[str]] = None,
    ):
        self.root = self._resolve_root(root)
        self.max_workers = max_workers
        self.enable_rca = enable_rca
        self.strict_toplevel = strict_toplevel
        self.max_cycles = max_cycles
        self.exclude_dirs = exclude_dirs or {".venv", "venv", "__pycache__", ".git", "node_modules", "dist", "build", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox"}
        self.exclude_files = exclude_files or {"setup.py", "manage.py", "conftest.py"}
        self.exclude_files.add(pathlib.Path(__file__).name)
        self._rca_available = _RCA_AVAILABLE

    def _resolve_root(self, root: Optional[pathlib.Path]) -> pathlib.Path:
        if root is not None:
            if not root.exists():
                raise ValueError(f"Root not found: {root}")
            if not root.is_dir():
                raise ValueError(f"Root not directory: {root}")
            return root.resolve()
        cwd = pathlib.Path.cwd()
        for p in [pathlib.Path(__file__).resolve().parent, pathlib.Path(__file__).resolve().parent.parent, cwd]:
            if (p / "pyproject.toml").exists() or (p / "setup.py").exists():
                return p
        return pathlib.Path(__file__).resolve().parent.parent

    def _collect_files(self) -> List[pathlib.Path]:
        files = []
        for p in self.root.rglob("*.py"):
            if any(part in self.exclude_dirs for part in p.parts):
                continue
            if p.name in self.exclude_files:
                continue
            files.append(p)
        return files

    def _scan_files(self, files: List[pathlib.Path]) -> Tuple[List[ImportRecord], List[str]]:
        all_records = []
        errors = []
        lock = threading.Lock()

        def _parse_one(p: pathlib.Path):
            records, err = extract_imports(p, self.root)
            with lock:
                all_records.extend(records)
                if err:
                    errors.append(err)

        if len(files) <= 4:
            for p in files:
                _parse_one(p)
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                list(pool.map(_parse_one, files))
        return all_records, errors

    def _check_violations(self, records: List[ImportRecord]) -> List[Violation]:
        violations = []
        for rec in records:
            src = rec.source_layer
            tgt = rec.target_layer
            if src in SKIP_LAYERS or tgt in SKIP_LAYERS:
                continue
            if is_stdlib(rec.target_module):
                continue
            if is_friend(src, rec.target_module):
                continue
            if is_allowed_third_party(rec.target_module):
                continue
            if self.strict_toplevel and not rec.is_toplevel:
                continue
            special_allowed = False
            for s_pat, prefix, t_pat in ALLOWED_SPECIAL_IMPORTS:
                if src == s_pat and tgt == t_pat and rec.target_module.startswith(prefix):
                    special_allowed = True
                    break
            if special_allowed:
                continue
            if (src, tgt) not in ALLOWED_PAIRS:
                sev = ViolationSeverity.for_pair(src, tgt)
                violations.append(Violation(
                    source_file=rec.source_file,
                    source_layer=src,
                    target_module=rec.target_module,
                    target_layer=tgt,
                    line=rec.line,
                    rule="matrix",
                    severity=sev,
                    message=f"Import dari '{src}' → '{tgt}' tidak diizinkan: {rec.target_module}",
                    is_toplevel=rec.is_toplevel,
                    in_type_checking=rec.in_type_checking,
                    in_try_except=rec.in_try_except,
                ))
        return violations

    def _analyze_cycle_with_rca(self, cycle: List[str]) -> Optional[CycleViolation]:
        if not cycle:
            return None
        cycle_str = " → ".join(cycle + [cycle[0]])
        severity = ViolationSeverity.for_cycle(cycle)
        message = f"Circular dependency: {cycle_str}"
        exc = RuntimeError(f"Circular dependency detected: {cycle_str}")
        context = {
            "cycle": cycle,
            "layers_involved": cycle,
            "phase": "layer_checker_cycles",
        }
        rca_result = _rca_analyze(exc, context) if self.enable_rca else None
        rca_dict = _rca_to_dict(rca_result) if rca_result else None
        first_file = ".".join(cycle) + "/__init__.py"
        return CycleViolation(
            source_file=first_file,
            source_layer=cycle[0] if cycle else "unknown",
            target_module=" → ".join(cycle),
            target_layer=cycle[-1] if cycle else "unknown",
            line=0,
            rule="cycle",
            severity=severity,
            message=message,
            is_toplevel=True,
            in_type_checking=False,
            in_try_except=False,
            rca=rca_dict,
            cycle=cycle,
        )

    def _enrich_rca(self, violations: List[Violation]) -> List[Violation]:
        if not self.enable_rca or not _RCA_AVAILABLE:
            return violations

        def _enrich_one(v: Violation) -> Violation:
            if v.rca is not None:
                return v
            try:
                exc = Exception(v.message)
                context = {
                    "source_layer": v.source_layer,
                    "target_layer": v.target_layer,
                    "target_module": v.target_module,
                    "source_file": v.source_file,
                }
                r = _rca_analyze(exc, context)
                if r:
                    v.rca = _rca_to_dict(r)
            except Exception:
                pass
            return v

        if len(violations) <= 10:
            return [_enrich_one(v) for v in violations]
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(violations))) as pool:
            return list(pool.map(_enrich_one, violations))

    def scan(self) -> LayerStats:
        t0 = time.monotonic()
        stats = LayerStats()
        files = self._collect_files()
        stats.total_files = len(files)

        records, errors = self._scan_files(files)
        stats.total_imports = len(records)
        stats.parse_errors = errors
        stats.skipped_files = len(errors)

        layer_counts = defaultdict(int)
        for rec in records:
            layer_counts[rec.source_layer] += 1
        stats.layer_counts = dict(layer_counts)

        # ─── Build graph untuk siklus ──────────────────────────────────────
        # HANYA import runtime: top-level, bukan TYPE_CHECKING, bukan relatif
        graph = defaultdict(set)
        for rec in records:
            # Filter import yang tidak termasuk runtime
            if rec.in_type_checking or not rec.is_toplevel or rec.is_relative:
                continue
            src, tgt = rec.source_layer, rec.target_layer
            if src in SKIP_LAYERS or tgt in SKIP_LAYERS or src == tgt:
                continue
            graph[src].add(tgt)
        stats.dependency_graph = dict(graph)

        cycles = find_cycles(dict(graph), max_cycles=self.max_cycles)
        stats.cycles = cycles

        cycle_violations: List[Violation] = []
        for cycle in cycles:
            if self.enable_rca and _RCA_AVAILABLE:
                v = self._analyze_cycle_with_rca(cycle)
                if v:
                    cycle_violations.append(v)
            else:
                cycle_str = " → ".join(cycle + [cycle[0]])
                v = CycleViolation(
                    source_file=".".join(cycle) + "/__init__.py",
                    source_layer=cycle[0] if cycle else "unknown",
                    target_module=" → ".join(cycle),
                    target_layer=cycle[-1] if cycle else "unknown",
                    line=0,
                    rule="cycle",
                    severity=ViolationSeverity.for_cycle(cycle),
                    message=f"Circular dependency: {cycle_str}",
                    is_toplevel=True,
                    in_type_checking=False,
                    in_try_except=False,
                    rca=None,
                    cycle=cycle,
                )
                cycle_violations.append(v)

        reg_violations = self._check_violations(records)
        if self.enable_rca and _RCA_AVAILABLE:
            reg_violations = self._enrich_rca(reg_violations)
            for cv in cycle_violations:
                if cv.rca is None and self.enable_rca and _RCA_AVAILABLE:
                    exc = RuntimeError(cv.message)
                    context = {"cycle": cv.cycle, "phase": "layer_checker_cycles"}
                    r = _rca_analyze(exc, context)
                    if r:
                        cv.rca = _rca_to_dict(r)

        stats.violations = reg_violations + cycle_violations
        stats.rca_enriched = self.enable_rca and _RCA_AVAILABLE
        stats.scan_time_s = time.monotonic() - t0
        return stats

# ─── REPORT ──────────────────────────────────────────────────────────────────
def print_report(stats: LayerStats, verbose: bool = False, hide_unknown: bool = False) -> List[str]:
    c = COLOR
    lines = []
    def emit(s=""):
        print(s)
        lines.append(s)

    emit(f"\n{c['CYAN']}{'='*80}{c['RESET']}")
    emit(f"{c['CYAN']}LAYER DEPENDENCY VIOLATION REPORT — v{__version__}{c['RESET']}")
    emit(f"{c['CYAN']}{'='*80}{c['RESET']}")
    emit(f"  Scan time     : {stats.scan_time_s:.2f}s")
    emit(f"  Total files   : {stats.total_files}")
    emit(f"  Parse errors  : {stats.skipped_files}")
    emit(f"  Total imports : {stats.total_imports}")
    emit(f"  Violations    : {stats.violation_count}")
    emit(f"  Cycles        : {stats.cycle_count}")
    emit(f"  RCA enriched  : {'Yes' if stats.rca_enriched else 'No'}")

    if stats.layer_counts:
        emit("\n  Layer import counts:")
        for layer, cnt in sorted(stats.layer_counts.items()):
            if hide_unknown and layer == "unknown": continue
            emit(f"    {layer:<20}: {cnt:>5}")

    if verbose and stats.parse_errors:
        emit(f"\n{c['YELLOW']}⚠️  Parse errors:{c['RESET']}")
        for err in stats.parse_errors[:20]:
            emit(f"    {err}")

    cycles = [v for v in stats.violations if isinstance(v, CycleViolation)]
    reg_violations = [v for v in stats.violations if not isinstance(v, CycleViolation)]

    if cycles:
        emit(f"\n{c['RED']}{c['BOLD']}⚠️  Circular dependencies ({len(cycles)}):{c['RESET']}")
        for i, cv in enumerate(cycles, 1):
            cycle_path = cv.cycle + [cv.cycle[0]] if cv.cycle else []
            cycle_str = " → ".join(cycle_path)
            emit(f"  {i:>3}. {cycle_str}")
            if cv.rca:
                rc = cv.rca.get("root_cause", "")
                fix = cv.rca.get("suggested_fix", "")
                conf = cv.rca.get("confidence", 0.0)
                if rc:
                    emit(f"         {c['CYAN']}RCA: {rc[:120]}{c['RESET']}")
                if fix:
                    emit(f"         {c['CYAN']}Fix: {fix[:120]}{c['RESET']}")
                if conf:
                    emit(f"         {c['DIM']}Confidence: {conf:.0%}{c['RESET']}")

    if reg_violations:
        by_sev = defaultdict(list)
        for v in reg_violations:
            by_sev[v.severity].append(v)
        emit(f"\n{c['RED']}{c['BOLD']}❌ Violations ({len(reg_violations)}):{c['RESET']}")
        for sev in [ViolationSeverity.FATAL, ViolationSeverity.CRITICAL, ViolationSeverity.HIGH]:
            cnt = len(by_sev.get(sev, []))
            if cnt:
                col = c['RED'] if sev in (ViolationSeverity.FATAL, ViolationSeverity.CRITICAL) else c['YELLOW']
                emit(f"    {col}{sev:<10}{c['RESET']}: {cnt}")

        by_file = defaultdict(list)
        for v in reg_violations:
            by_file[v.source_file].append(v)
        for idx, (file, vlist) in enumerate(sorted(by_file.items(), key=lambda x: len(x[1]), reverse=True), 1):
            emit(f"\n  {c['YELLOW']}[{idx}] {file}{c['RESET']}  ({len(vlist)} violations)")
            for v in sorted(vlist, key=lambda x: x.line):
                col = c['RED'] if v.severity in (ViolationSeverity.FATAL, ViolationSeverity.CRITICAL) else c['YELLOW']
                tag = ""
                if v.in_type_checking: tag += " TYPE_CHECKING"
                if v.in_try_except: tag += " try/except"
                if not v.is_toplevel: tag += " nested"
                emit(
                    f"    {c['CYAN']}line {v.line:>4}{c['RESET']}  "
                    f"{col}{v.severity:<10}{c['RESET']}  "
                    f"{v.source_layer} → {v.target_layer:<20}  {v.target_module}{tag}"
                )
                if verbose and v.rca:
                    rc = v.rca.get("root_cause", "")
                    fix = v.rca.get("suggested_fix", "")
                    conf = v.rca.get("confidence", 0.0)
                    if rc:
                        emit(f"         {c['CYAN']}RCA: {rc[:120]}{c['RESET']}")
                    if fix:
                        emit(f"         {c['CYAN']}Fix: {fix[:120]}{c['RESET']}")
                    if conf:
                        emit(f"         {c['DIM']}Confidence: {conf:.0%}{c['RESET']}")

    else:
        if not cycles:
            emit(f"\n{c['GREEN']}{c['BOLD']}✅ No violations or cycles!{c['RESET']}")

    emit(f"\n{c['CYAN']}{'─'*80}{c['RESET']}")
    return lines

def save_json(stats: LayerStats, filepath: str, hide_unknown: bool = False) -> bool:
    try:
        pathlib.Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": __version__,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "scan_time_s": stats.scan_time_s,
            "rca_enriched": stats.rca_enriched,
            "summary": {
                "total_files": stats.total_files,
                "total_imports": stats.total_imports,
                "skipped_files": stats.skipped_files,
                "violations_count": stats.violation_count,
                "cycles_count": stats.cycle_count,
                "is_clean": stats.is_clean,
            },
            "layer_counts": {k:v for k,v in stats.layer_counts.items() if not (hide_unknown and k=="unknown")},
            "cycles": stats.cycles,
            "violations": [v.to_dict() for v in stats.violations],
            "parse_errors": stats.parse_errors,
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"{COLOR['GREEN']}✅ JSON report saved: {filepath}{COLOR['RESET']}")
        return True
    except Exception as e:
        print(f"{COLOR['RED']}❌ Failed to save JSON: {e}{COLOR['RESET']}")
        return False

# ─── SELF-TEST ──────────────────────────────────────────────────────────────
def self_test(verbose: bool = True) -> bool:
    passed = failed = 0
    def check(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            if verbose: print(f"  ✅ {name}")
            passed += 1
        else:
            if verbose: print(f"  ❌ {name}" + (f": {detail}" if detail else ""))
            failed += 1

    if verbose: print(f"\nLayerChecker self-test v{__version__}…\n")

    check("get_layer: domain → domain", get_layer("domain") == "domain")
    check("get_layer: infrastructure → infrastructure", get_layer("infrastructure") == "infrastructure")
    check("get_layer: unknown → unknown", get_layer("unknown") == "unknown")

    check("resolve_relative_import: level=1", resolve_relative_import("a.b.c", 1, "d") == "a.b.d")
    check("resolve_relative_import: level=2", resolve_relative_import("a.b.c", 2, None) == "a")
    check("resolve_relative_import: level=0", resolve_relative_import("a.b", 0, "c") == "a.b.c")

    check("is_stdlib: os → True", is_stdlib("os"))
    check("is_stdlib: requests → False", not is_stdlib("requests"))

    check("is_friend: domain + typing → True", is_friend("domain", "typing"))
    check("is_friend: domain + sqlalchemy → False", not is_friend("domain", "sqlalchemy"))

    g1 = {"A": {"B"}, "B": {"A"}}
    cycles = find_cycles(g1)
    check("find_cycles: A→B→A", len(cycles) >= 1 and cycles[0] == ["A","B"])
    g2 = {"A": {"B"}, "B": {"C"}}
    check("find_cycles: no cycle", len(find_cycles(g2)) == 0)

    check("ViolationSeverity: domain→infra FATAL",
          ViolationSeverity.for_pair("domain", "infrastructure") == ViolationSeverity.FATAL)
    check("ViolationSeverity: adapters→domain HIGH",
          ViolationSeverity.for_pair("adapters", "domain") == ViolationSeverity.HIGH)

    check("ALLOWED_PAIRS contains (domain,domain)", ("domain","domain") in ALLOWED_PAIRS)
    check("ALLOWED_PAIRS not contains (domain,infra)", ("domain","infrastructure") not in ALLOWED_PAIRS)

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        tmp = tf.name
    try:
        stats = LayerStats(total_files=1)
        stats.violations.append(Violation("dummy.py", "domain", "infra.db", "infrastructure", 10, "matrix", ViolationSeverity.FATAL, "test"))
        ok = save_json(stats, tmp)
        check("save_json success", ok)
        with open(tmp) as f: data = json.load(f)
        check("save_json valid JSON", "violations" in data)
    finally:
        try: os.unlink(tmp)
        except: pass

    check("RCA available or fallback", True)

    try:
        LayerChecker(enable_rca=False)
        check("LayerChecker init ok", True)
    except Exception as e:
        check("LayerChecker init ok", False, str(e))

    if verbose: print(f"\nSelf-test: {passed} passed, {failed} failed {'✅' if failed==0 else '❌'}")
    return failed == 0

# ─── CLI ──────────────────────────────────────────────────────────────────────
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=f"Layer Checker v{__version__}")
    parser.add_argument("--root", help="Project root directory")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE", help="Export JSON report")
    parser.add_argument("--quiet", "-q", action="store_true", help="Minimal output")
    parser.add_argument("--hide-unknown", action="store_true")
    parser.add_argument("--no-rca", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--strict", action="store_true", help="Only top-level imports")
    parser.add_argument("--self-test", action="store_true", dest="self_test", help="Run self-test")
    parser.add_argument("--exclude-dirs", default=".venv,venv,__pycache__,.git,node_modules,dist,build,.mypy_cache,.pytest_cache,.ruff_cache,.tox")
    parser.add_argument("--exclude-files", default="setup.py,manage.py,conftest.py")
    parser.add_argument("--version", action="version", version=f"layer_checker v{__version__}")

    args = parser.parse_args(argv)

    if args.self_test:
        return 0 if self_test(verbose=True) else 1

    root = pathlib.Path(args.root) if args.root else None
    exclude_dirs = set(args.exclude_dirs.split(","))
    exclude_files = set(args.exclude_files.split(","))

    try:
        checker = LayerChecker(
            root=root,
            max_workers=args.workers,
            enable_rca=not args.no_rca,
            strict_toplevel=args.strict,
            exclude_dirs=exclude_dirs,
            exclude_files=exclude_files,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    stats = checker.scan()

    if not args.quiet:
        print_report(stats, verbose=args.verbose, hide_unknown=args.hide_unknown)

    if args.quiet:
        print(f"{'PASS' if stats.is_clean else 'FAIL'}: {stats.violation_count} violations, {stats.cycle_count} cycles, {stats.scan_time_s:.2f}s")

    if args.json:
        save_json(stats, args.json, hide_unknown=args.hide_unknown)

    return 0 if stats.is_clean else 1

if __name__ == "__main__":
    sys.exit(main())