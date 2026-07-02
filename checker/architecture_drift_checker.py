#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║    SOVEREIGN ERP — ARCHITECTURE DRIFT & BOUNDARY VALIDATOR   v5.1.1       ║
║    Big‑4 Audit Grade  •  Full RCA Integration  •  Zero False Positives    ║
║    Context‑Aware AST Visitor  •  Complete Coverage Reporting             ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  PERBAIKAN v5.1.1:                                                         ║
║  ✅ Membaca file dengan utf-8-sig terlebih dahulu (dukungan BOM)          ║
║  ✅ Fallback encoding: utf-8, latin-1, cp1252                             ║
║  ✅ Menampilkan detail file gagal scan dengan --show-skipped             ║
║  ✅ RCA Engine terintegrasi penuh (multiple fallback import paths)        ║
║  ✅ Mode --deep-rca untuk analisis root cause berbasis engine             ║
║  ✅ Coverage 100% setelah file diperbaiki                                 ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import pathlib
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Any, List, Dict, Set, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# VERSI & METADATA
# ─────────────────────────────────────────────────────────────────────────────
TOOL_VERSION = "5.1.1"
TOOL_NAME    = "SovereignArchitectureDriftValidator"

# ─────────────────────────────────────────────────────────────────────────────
# KONFIGURASI TERMINAL
# ─────────────────────────────────────────────────────────────────────────────
COLOR = {
    "RED":     "\033[91m",
    "GREEN":   "\033[92m",
    "YELLOW":  "\033[93m",
    "BLUE":    "\033[94m",
    "MAGENTA": "\033[95m",
    "CYAN":    "\033[96m",
    "WHITE":   "\033[97m",
    "BOLD":    "\033[1m",
    "DIM":     "\033[2m",
    "RESET":   "\033[0m",
}
if not sys.stdout.isatty():
    COLOR = dict.fromkeys(COLOR, "")

def c(key: str, text: str) -> str:
    return f"{COLOR[key]}{text}{COLOR['RESET']}"

# ─────────────────────────────────────────────────────────────────────────────
# RCA ENGINE – INTEGRASI ROBUST
# ─────────────────────────────────────────────────────────────────────────────
RCA_ENGINE: Any = None
RCA_AVAILABLE: bool = False
RCA_ANALYZE = None
RCA_SEVERITY = None

def _init_rca_engine() -> bool:
    """Inisialisasi RCA engine dengan multiple fallback paths."""
    global RCA_ENGINE, RCA_AVAILABLE, RCA_ANALYZE, RCA_SEVERITY

    # 1. Coba import langsung
    try:
        from checker.core.rca import get_engine, analyze_exception, Severity
        RCA_ENGINE = get_engine()
        RCA_ANALYZE = analyze_exception
        RCA_SEVERITY = Severity
        RCA_AVAILABLE = True
        return True
    except ImportError:
        pass

    # 2. Tambahkan root proyek ke sys.path
    root = pathlib.Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from checker.core.rca import get_engine, analyze_exception, Severity
        RCA_ENGINE = get_engine()
        RCA_ANALYZE = analyze_exception
        RCA_SEVERITY = Severity
        RCA_AVAILABLE = True
        return True
    except ImportError:
        pass

    # 3. Coba dari subfolder core
    core_path = root / "checker" / "core"
    if core_path.exists() and str(core_path) not in sys.path:
        sys.path.insert(0, str(core_path))
    try:
        from rca import get_engine, analyze_exception, Severity
        RCA_ENGINE = get_engine()
        RCA_ANALYZE = analyze_exception
        RCA_SEVERITY = Severity
        RCA_AVAILABLE = True
        return True
    except ImportError:
        pass

    # 4. Fallback terakhir: dari core.rca
    try:
        from core.rca import get_engine, analyze_exception, Severity
        RCA_ENGINE = get_engine()
        RCA_ANALYZE = analyze_exception
        RCA_SEVERITY = Severity
        RCA_AVAILABLE = True
        return True
    except ImportError:
        pass

    return False

_init_rca_engine()

# ─────────────────────────────────────────────────────────────────────────────
# STDLIB / THIRD‑PARTY
# ─────────────────────────────────────────────────────────────────────────────
STDLIB_TOP_LEVEL: frozenset[str] = frozenset({
    "abc", "ast", "asyncio", "base64", "builtins", "collections", "concurrent",
    "contextlib", "copy", "csv", "dataclasses", "datetime", "decimal",
    "enum", "functools", "gc", "hashlib", "http", "importlib", "inspect",
    "io", "itertools", "json", "logging", "math", "multiprocessing", "operator",
    "os", "pathlib", "pickle", "platform", "pprint", "queue", "random", "re",
    "secrets", "shutil", "signal", "socket", "ssl", "stat", "string", "struct",
    "subprocess", "sys", "tempfile", "textwrap", "threading", "time", "traceback",
    "typing", "typing_extensions", "unittest", "urllib", "uuid", "warnings",
    "weakref", "xml", "zipfile", "zlib",
    "alembic", "anyio", "click", "cryptography", "fastapi", "grpc",
    "httpx", "jose", "kafka", "kombu", "minio", "opentelemetry", "passlib",
    "pydantic", "pydantic_settings", "pymongo", "pytest", "redis",
    "requests", "sqlalchemy", "starlette", "uvicorn", "celery", "boto3",
    "botocore", "aiokafka", "aiofiles", "aiopg", "asyncpg", "psycopg2",
    "yaml", "toml", "dotenv", "prometheus_client", "structlog", "loguru",
    "babel", "pytz", "arrow", "pendulum", "PIL", "numpy", "pandas",
    "reportlab", "openpyxl", "jinja2", "lxml", "bs4", "httptools",
    "pkg_resources", "setuptools", "packaging", "attrs", "cattrs",
    "marshmallow", "cerberus", "voluptuous", "aiohttp", "tenacity",
    "backoff", "retry", "cachetools", "diskcache", "apscheduler",
    "dramatiq", "rq", "arq", "faust", "confluent_kafka",
    "__future__",
})

def is_stdlib_or_thirdparty(module_name: str) -> bool:
    top = module_name.split(".")[0] if module_name else ""
    return top in STDLIB_TOP_LEVEL

# ─────────────────────────────────────────────────────────────────────────────
# LAYER MAP
# ─────────────────────────────────────────────────────────────────────────────
LAYER_MAP: dict[str, str] = {
    "domain":               "domain",
    "application":          "application",
    "infrastructure":       "infrastructure",
    "adapters":             "adapters",
    "ports":                "ports",
    "kernel":               "kernel",
    "bootstrap":            "bootstrap",
    "config":               "config",
    "app":                  "app",
    "constitution":         "constitution",
    "axioms":               "axioms",
    "policy_engine":        "policy_engine",
    "compliance":           "compliance",
    "audit":                "audit",
    "projections":          "projections",
    "reports":              "reports",
    "event_gateway":        "event_gateway",
    "transformers":         "transformers",
    "security_hardening":   "security_hardening",
    "monitoring":           "monitoring",
    "disaster_recovery":    "disaster_recovery",
    "deployment":           "deployment",
    "architecture":         "architecture",
    "checker":              "checker",
    "tests":                "tests",
}

SKIP_LAYERS: frozenset[str] = frozenset({
    "tests", "deployment", "checker", "unknown",
})

OPERATIONAL_LAYERS: frozenset[str] = frozenset({
    "monitoring", "disaster_recovery", "security_hardening", "architecture",
})

LAYER_RANK: dict[str, int] = {
    "axioms":               0,
    "constitution":         1,
    "domain":               2,
    "ports":                3,
    "kernel":               4,
    "config":               4,
    "policy_engine":        5,
    "audit":                5,
    "compliance":           6,
    "application":          7,
    "infrastructure":       8,
    "event_gateway":        8,
    "adapters":             9,
    "transformers":         9,
    "projections":          10,
    "reports":              10,
    "bootstrap":            11,
    "app":                  12,
    "monitoring":           99,
    "disaster_recovery":    99,
    "security_hardening":   99,
    "architecture":         99,
    "checker":              99,
    "tests":                99,
    "unknown":              99,
}

ALLOWED_PAIRS: frozenset[tuple[str, str]] = frozenset({
    ("axioms",           "axioms"),
    ("axioms",           "constitution"),
    ("constitution",     "constitution"),
    ("constitution",     "axioms"),
    ("domain",           "domain"),
    ("domain",           "axioms"),
    ("domain",           "constitution"),
    ("ports",            "ports"),
    ("ports",            "domain"),
    ("ports",            "axioms"),
    ("ports",            "constitution"),
    ("kernel",           "kernel"),
    ("kernel",           "domain"),
    ("kernel",           "axioms"),
    ("kernel",           "constitution"),
    ("kernel",           "ports"),
    ("kernel",           "config"),
    ("config",           "config"),
    ("config",           "axioms"),
    ("policy_engine",    "policy_engine"),
    ("policy_engine",    "domain"),
    ("policy_engine",    "axioms"),
    ("policy_engine",    "constitution"),
    ("policy_engine",    "kernel"),
    ("policy_engine",    "config"),
    ("policy_engine",    "ports"),
    ("policy_engine",    "compliance"),
    ("audit",            "audit"),
    ("audit",            "domain"),
    ("audit",            "axioms"),
    ("audit",            "kernel"),
    ("audit",            "ports"),
    ("audit",            "config"),
    ("audit",            "infrastructure"),
    ("audit",            "application"),
    ("compliance",       "compliance"),
    ("compliance",       "domain"),
    ("compliance",       "axioms"),
    ("compliance",       "constitution"),
    ("compliance",       "policy_engine"),
    ("compliance",       "application"),
    ("compliance",       "kernel"),
    ("compliance",       "infrastructure"),
    ("compliance",       "config"),
    ("compliance",       "ports"),
    ("application",      "application"),
    ("application",      "domain"),
    ("application",      "axioms"),
    ("application",      "constitution"),
    ("application",      "kernel"),
    ("application",      "ports"),
    ("application",      "config"),
    ("application",      "policy_engine"),
    ("application",      "audit"),
    ("application",      "compliance"),
    ("infrastructure",   "infrastructure"),
    ("infrastructure",   "domain"),
    ("infrastructure",   "axioms"),
    ("infrastructure",   "ports"),
    ("infrastructure",   "kernel"),
    ("infrastructure",   "config"),
    ("event_gateway",    "event_gateway"),
    ("event_gateway",    "domain"),
    ("event_gateway",    "application"),
    ("event_gateway",    "infrastructure"),
    ("event_gateway",    "kernel"),
    ("event_gateway",    "config"),
    ("event_gateway",    "ports"),
    ("adapters",         "adapters"),
    ("adapters",         "application"),
    ("adapters",         "domain"),
    ("adapters",         "axioms"),
    ("adapters",         "constitution"),
    ("adapters",         "kernel"),
    ("adapters",         "ports"),
    ("adapters",         "infrastructure"),
    ("adapters",         "config"),
    ("adapters",         "audit"),
    ("adapters",         "policy_engine"),
    ("transformers",     "transformers"),
    ("transformers",     "domain"),
    ("transformers",     "application"),
    ("transformers",     "ports"),
    ("transformers",     "infrastructure"),
    ("transformers",     "config"),
    ("transformers",     "kernel"),
    ("projections",      "projections"),
    ("projections",      "domain"),
    ("projections",      "application"),
    ("projections",      "infrastructure"),
    ("projections",      "kernel"),
    ("projections",      "ports"),
    ("projections",      "config"),
    ("reports",          "reports"),
    ("reports",          "projections"),
    ("reports",          "application"),
    ("reports",          "domain"),
    ("reports",          "infrastructure"),
    ("reports",          "ports"),
    ("reports",          "config"),
    ("bootstrap",        "bootstrap"),
    ("bootstrap",        "config"),
    ("bootstrap",        "domain"),
    ("bootstrap",        "axioms"),
    ("bootstrap",        "constitution"),
    ("bootstrap",        "kernel"),
    ("bootstrap",        "ports"),
    ("bootstrap",        "infrastructure"),
    ("bootstrap",        "application"),
    ("bootstrap",        "adapters"),
    ("bootstrap",        "policy_engine"),
    ("bootstrap",        "audit"),
    ("bootstrap",        "compliance"),
    ("bootstrap",        "event_gateway"),
    ("bootstrap",        "transformers"),
    ("bootstrap",        "projections"),
    ("bootstrap",        "reports"),
    ("app",              "app"),
    ("app",              "bootstrap"),
    ("app",              "adapters"),
    ("app",              "infrastructure"),
    ("app",              "config"),
    ("app",              "domain"),
    ("app",              "kernel"),
    ("monitoring",       "monitoring"),
    ("monitoring",       "domain"),
    ("monitoring",       "application"),
    ("monitoring",       "infrastructure"),
    ("monitoring",       "kernel"),
    ("monitoring",       "config"),
    ("monitoring",       "ports"),
    ("monitoring",       "adapters"),
    ("monitoring",       "bootstrap"),
    ("monitoring",       "app"),
    ("security_hardening", "security_hardening"),
    ("security_hardening", "domain"),
    ("security_hardening", "application"),
    ("security_hardening", "infrastructure"),
    ("security_hardening", "kernel"),
    ("security_hardening", "config"),
    ("security_hardening", "ports"),
    ("security_hardening", "adapters"),
    ("security_hardening", "audit"),
    ("security_hardening", "compliance"),
    ("disaster_recovery", "disaster_recovery"),
    ("disaster_recovery", "domain"),
    ("disaster_recovery", "infrastructure"),
    ("disaster_recovery", "kernel"),
    ("disaster_recovery", "config"),
    ("disaster_recovery", "adapters"),
    ("disaster_recovery", "bootstrap"),
    ("architecture",     "architecture"),
    ("architecture",     "domain"),
    ("architecture",     "application"),
    ("architecture",     "infrastructure"),
    ("architecture",     "kernel"),
    ("architecture",     "ports"),
    ("architecture",     "adapters"),
    ("architecture",     "config"),
    ("architecture",     "axioms"),
    ("architecture",     "constitution"),
    ("architecture",     "policy_engine"),
    ("architecture",     "compliance"),
    ("architecture",     "audit"),
    ("architecture",     "projections"),
    ("architecture",     "reports"),
    ("architecture",     "event_gateway"),
    ("architecture",     "transformers"),
    ("architecture",     "bootstrap"),
    ("architecture",     "app"),
    ("architecture",     "security_hardening"),
    ("architecture",     "monitoring"),
    ("architecture",     "disaster_recovery"),
    ("architecture",     "checker"),
})

# ─────────────────────────────────────────────────────────────────────────────
# DATA MODELS
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ImportEdge:
    source_module: str
    source_layer:  str
    target_module: str
    target_layer:  str
    line:          int
    file_path:     str
    import_type:   str

@dataclass
class ViolationInfo:
    line:          int
    import_type:   str
    target_module: str
    target_layer:  str
    message:       str
    severity:      str
    source_layer:  str = ""
    source_module: str = ""

@dataclass
class WildcardViolation:
    module_path: str
    file_path:   str
    line:        int
    message:     str

@dataclass
class MissingInitInfo:
    package_path: str
    message:      str

@dataclass
class DuplicateModuleInfo:
    module_name: str
    occurrences: list[str]
    message:     str
    severity:    str = "INFO"

@dataclass
class SkippedFileInfo:
    file_path: pathlib.Path
    error:     str
    error_type: str  # SyntaxError, UnicodeDecodeError, OSError, dll.

@dataclass
class ModuleReport:
    module_path:  str
    file_path:    str
    layer:        str
    violations:   list[ViolationInfo]        = field(default_factory=list)
    wildcards:    list[WildcardViolation]    = field(default_factory=list)
    import_count: int                         = 0

@dataclass
class LayerStats:
    layer:             str
    total_modules:     int = 0
    violated_modules:  int = 0
    total_violations:  int = 0
    wildcard_imports:  int = 0

@dataclass
class MasterReport:
    scan_timestamp:       str = ""
    scan_duration_sec:    float = 0.0
    tool_version:         str = TOOL_VERSION
    root_dir:             str = ""
    python_version:       str = ""
    git_commit:           str = ""

    total_files_found:    int = 0
    total_files_scanned:  int = 0
    total_files_skipped:  int = 0
    total_files_excluded: int = 0

    skipped_files:        list[SkippedFileInfo] = field(default_factory=list)

    total_drift_violations:   int = 0
    total_wildcard_violations: int = 0
    violated_modules_count:   int = 0
    clean_modules_count:      int = 0

    inter_layer_cycles: list[list[str]] = field(default_factory=list)
    intra_layer_cycles: list[list[str]] = field(default_factory=list)

    missing_init_files:    list[MissingInitInfo]    = field(default_factory=list)
    duplicate_modules:     list[DuplicateModuleInfo] = field(default_factory=list)

    modules:      dict[str, ModuleReport]  = field(default_factory=dict)
    layer_stats:  dict[str, LayerStats]    = field(default_factory=dict)

    score:             int = 100
    score_breakdown:   dict[str, int] = field(default_factory=dict)
    verdict:           str = ""

# ─────────────────────────────────────────────────────────────────────────────
# RCA HELPER
# ─────────────────────────────────────────────────────────────────────────────
def analyze_violation_with_rca(
    source_layer: str,
    target_layer: str,
    source_module: str,
    target_module: str,
    import_type: str,
    severity: str,
    use_deep_rca: bool = False,
) -> dict:
    global RCA_AVAILABLE, RCA_ANALYZE, RCA_SEVERITY

    if use_deep_rca and RCA_AVAILABLE and RCA_ANALYZE:
        try:
            msg = (
                f"Architecture drift violation: {source_layer} (rank {LAYER_RANK.get(source_layer, 99)}) "
                f"→ {target_layer} (rank {LAYER_RANK.get(target_layer, 99)}) "
                f"via {import_type} from {source_module} to {target_module}"
            )
            exc = ValueError(msg)
            ctx = {
                "source_layer": source_layer,
                "target_layer": target_layer,
                "source_module": source_module,
                "target_module": target_module,
                "import_type": import_type,
                "severity": severity,
            }
            r = RCA_ANALYZE(exc, ctx)
            if r:
                return {
                    "severity": severity,
                    "category": "Architecture",
                    "root_cause": r.root_cause,
                    "evidence": r.evidence[:5] if r.evidence else [msg],
                    "impact": r.impact[:3] if r.impact else ["Architecture boundary violation detected."],
                    "suggested_fix": r.suggested_fix,
                    "confidence": r.confidence,
                    "fix_time_estimate": "Unknown",
                    "risk": "Critical" if severity == "CRITICAL" else "High" if severity == "ERROR" else "Medium",
                }
        except Exception:
            pass

    # ── FALLBACK MANUAL ──────────────────────────────────────────────────────
    sr = LAYER_RANK.get(source_layer, 99)
    tr = LAYER_RANK.get(target_layer, 99)

    if sr < tr:
        root_cause = (
            f"Layer '{source_layer}' (rank {sr}) is more foundational than "
            f"'{target_layer}' (rank {tr}). Foundational layers must not depend on higher layers."
        )
        impact = [
            "The foundational layer becomes coupled to higher-level details.",
            "Changes in higher layers can break foundational invariants.",
        ]
        suggested_fix = (
            "Move the dependency to an interface/port defined in a lower layer, "
            "and inject the implementation from the composition root."
        )
        fix_time = "1 hour"
        risk = "Critical" if severity == "CRITICAL" else "High"
    elif source_layer == "transformers" and target_layer == "bootstrap":
        root_cause = (
            "Transformer modules are responsible for data transformation and should not "
            "know about the Dependency Injection container (IoC)."
        )
        impact = [
            "Transformers become hard to unit test (need to mock the container).",
            "Reusability is reduced because the transformer carries container dependencies.",
        ]
        suggested_fix = (
            "Inject required dependencies as constructor parameters or via a port interface."
        )
        fix_time = "2 hours"
        risk = "Critical"
    else:
        root_cause = (
            f"Layer '{source_layer}' depends on '{target_layer}' which is "
            "not allowed by the architecture definition."
        )
        impact = [
            "Code becomes harder to maintain and evolve.",
            "Layer boundaries are blurred, reducing the benefits of hexagonal architecture.",
        ]
        suggested_fix = (
            f"Consider whether the dependency is truly needed. If so, add "
            f"({source_layer}, {target_layer}) to ALLOWED_PAIRS after architectural review."
        )
        fix_time = "30 minutes"
        risk = "Medium" if severity != "CRITICAL" else "High"

    return {
        "severity": severity,
        "category": "Architecture",
        "root_cause": root_cause,
        "evidence": [
            f"Source: {source_layer} ({source_module})",
            f"Target: {target_layer} ({target_module})",
            f"Import type: {import_type}",
        ],
        "impact": impact[:3],
        "suggested_fix": suggested_fix,
        "confidence": 0.85,
        "fix_time_estimate": fix_time,
        "risk": risk,
    }

# ─────────────────────────────────────────────────────────────────────────────
# GIT HELPER
# ─────────────────────────────────────────────────────────────────────────────
def get_git_commit(root_dir: pathlib.Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=str(root_dir), timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else "N/A"
    except Exception:
        return "N/A"

# ─────────────────────────────────────────────────────────────────────────────
# CORE VERIFIER
# ─────────────────────────────────────────────────────────────────────────────
class SovereignArchitectureVerifier:
    def __init__(self, root_dir: pathlib.Path, strict_mode: bool = False):
        self.root_dir    = root_dir
        self.strict_mode = strict_mode
        self._layer_cache: dict[str, str] = {}

    def identify_layer(self, module_name: str) -> str:
        if not module_name:
            return "unknown"
        if module_name in self._layer_cache:
            return self._layer_cache[module_name]
        mod = module_name.replace("/", ".").replace("\\", ".")
        top = mod.split(".")[0]
        if top in STDLIB_TOP_LEVEL:
            result = "__external__"
        else:
            result = LAYER_MAP.get(top, "unknown")
        self._layer_cache[module_name] = result
        return result

    def resolve_relative_import(
        self,
        source_module: str,
        level: int,
        target_name: Optional[str],
    ) -> Optional[str]:
        if level <= 0:
            return target_name
        parts = source_module.split(".")
        if level >= len(parts):
            base = ""
        else:
            base = ".".join(parts[:-level])
        if target_name:
            return f"{base}.{target_name}" if base else target_name
        else:
            return base if base else None

    @staticmethod
    def _read_file_with_encodings(path: pathlib.Path) -> tuple[Optional[str], Optional[str]]:
        """Baca file dengan mencoba beberapa encoding. Return (content, error_msg)."""
        encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
        for enc in encodings:
            try:
                content = path.read_text(encoding=enc, errors='strict')
                return content, None
            except UnicodeDecodeError:
                continue
            except OSError as e:
                return None, f"OSError: {e}"
        return None, f"UnicodeDecodeError: cannot decode with any of {encodings}"

    def parse_module(
        self,
        file_path: pathlib.Path,
    ) -> tuple[Optional[ModuleReport], list[ImportEdge], Optional[str]]:
        """Return: (ModuleReport or None, list of edges, error message or None)"""
        # ── Baca file dengan multi-encoding ──────────────────────────────
        source_code, error = self._read_file_with_encodings(file_path)
        if error:
            return None, [], error

        # ── Parse AST ─────────────────────────────────────────────────────
        try:
            tree = ast.parse(source_code, filename=str(file_path))
        except SyntaxError as e:
            col = f", col {e.offset}" if e.offset else ""
            return None, [], f"SyntaxError at line {e.lineno}{col}: {e.msg}"
        except MemoryError:
            return None, [], "MemoryError: file too large"
        except Exception as e:
            return None, [], f"Unexpected parse error: {type(e).__name__}: {e}"

        try:
            relative_path = file_path.relative_to(self.root_dir)
        except ValueError:
            return None, [], f"Path outside root: {file_path}"

        source_module = str(relative_path.with_suffix("")).replace(os.sep, ".")
        source_layer  = self.identify_layer(source_module)

        report = ModuleReport(
            module_path=source_module,
            file_path=str(relative_path),
            layer=source_layer,
        )

        edges: list[ImportEdge] = []

        class ImportCollector(ast.NodeVisitor):
            def __init__(self, verifier, report, edges, source_module, source_layer, relative_path):
                self.verifier = verifier
                self.report = report
                self.edges = edges
                self.source_module = source_module
                self.source_layer = source_layer
                self.relative_path = relative_path
                self.in_type_checking = False
                self.in_function = False
                self.context_stack = []

            def visit_If(self, node):
                is_type_checking = False
                if isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
                    is_type_checking = True
                elif isinstance(node.test, ast.Attribute) and node.test.attr == "TYPE_CHECKING":
                    is_type_checking = True
                if is_type_checking:
                    self.in_type_checking = True
                    self.context_stack.append(("type_checking", node))
                self.generic_visit(node)
                if is_type_checking:
                    self.context_stack.pop()
                    self.in_type_checking = any(ctx[0] == "type_checking" for ctx in self.context_stack)

            def visit_FunctionDef(self, node):
                self.in_function = True
                self.context_stack.append(("function", node))
                self.generic_visit(node)
                self.context_stack.pop()
                self.in_function = any(ctx[0] == "function" for ctx in self.context_stack)

            def visit_AsyncFunctionDef(self, node):
                self.in_function = True
                self.context_stack.append(("function", node))
                self.generic_visit(node)
                self.context_stack.pop()
                self.in_function = any(ctx[0] == "function" for ctx in self.context_stack)

            def visit_Import(self, node):
                if self.in_type_checking or self.in_function:
                    return
                for alias in node.names:
                    target_mod = alias.name
                    self.report.import_count += 1
                    self._process_import(target_mod, node.lineno, "import")

            def visit_ImportFrom(self, node):
                if self.in_type_checking or self.in_function:
                    return
                level = node.level or 0
                is_wildcard = any(alias.name == "*" for alias in node.names)

                if level > 0:
                    target_mod = self.verifier.resolve_relative_import(
                        self.source_module, level, node.module
                    )
                else:
                    target_mod = node.module

                if target_mod:
                    self.report.import_count += 1
                    import_type = "wildcard" if is_wildcard else "from_import"
                    self._process_import(target_mod, node.lineno, import_type)

                    if is_wildcard and not is_stdlib_or_thirdparty(target_mod):
                        target_layer = self.verifier.identify_layer(target_mod)
                        if target_layer not in ("__external__", "unknown", self.source_layer):
                            self.report.wildcards.append(WildcardViolation(
                                module_path=self.source_module,
                                file_path=str(self.relative_path),
                                line=node.lineno,
                                message=(
                                    f"WILDCARD IMPORT: 'from {target_mod} import *' "
                                    f"dari layer '{self.source_layer}' ke layer '{target_layer}'"
                                )
                            ))
                else:
                    # Kasus: from . import x (node.module is None)
                    if level > 0 and node.module is None:
                        parts = self.source_module.split(".")
                        if level < len(parts):
                            base = ".".join(parts[:-level])
                            if base:
                                for alias in node.names:
                                    if alias.name != "*":
                                        full = f"{base}.{alias.name}"
                                        self.report.import_count += 1
                                        self._process_import(full, node.lineno, "from_import")

            def _process_import(self, target_mod, line_no, import_type):
                if not target_mod:
                    return

                target_layer = self.verifier.identify_layer(target_mod)

                if target_layer == "__external__":
                    return

                edge = ImportEdge(
                    source_module=self.source_module,
                    source_layer=self.source_layer,
                    target_module=target_mod,
                    target_layer=target_layer,
                    line=line_no,
                    file_path=str(self.relative_path),
                    import_type=import_type,
                )
                self.edges.append(edge)

                if self.source_layer in SKIP_LAYERS:
                    return
                if target_layer in ("unknown", "__external__"):
                    return
                if self.source_module == target_mod:
                    return
                if self.source_layer == target_layer:
                    return

                if (self.source_layer, target_layer) not in ALLOWED_PAIRS:
                    src_rank = LAYER_RANK.get(self.source_layer, 99)
                    tgt_rank = LAYER_RANK.get(target_layer, 99)

                    if src_rank < tgt_rank:
                        severity = "CRITICAL"
                    else:
                        severity = "ERROR"

                    drift_msg = (
                        f"LAYER DRIFT: '{self.source_layer}' (rank {src_rank}) "
                        f"→ '{target_layer}' (rank {tgt_rank}) "
                        f"[{import_type}] Modul: {target_mod}"
                    )
                    self.report.violations.append(ViolationInfo(
                        line=line_no,
                        import_type=import_type,
                        target_module=target_mod,
                        target_layer=target_layer,
                        message=drift_msg,
                        severity=severity,
                        source_layer=self.source_layer,
                        source_module=self.source_module,
                    ))

        collector = ImportCollector(
            verifier=self,
            report=report,
            edges=edges,
            source_module=source_module,
            source_layer=source_layer,
            relative_path=relative_path,
        )
        collector.visit(tree)

        return report, edges, None

    def build_import_graph(self, all_edges: list[ImportEdge]) -> dict[str, set[str]]:
        graph: dict[str, set[str]] = defaultdict(set)
        seen: set[tuple[str, str]] = set()

        for edge in all_edges:
            if edge.source_layer in SKIP_LAYERS:
                continue
            if edge.target_layer in ("unknown", "__external__"):
                continue
            if edge.source_module == edge.target_module:
                continue

            key = (edge.source_module, edge.target_module)
            if key in seen:
                continue
            seen.add(key)
            graph[edge.source_module].add(edge.target_module)

        return dict(graph)

    def tarjan_scc_recursive(self, graph: dict[str, set[str]]) -> list[list[str]]:
        sys.setrecursionlimit(10000)
        index_counter = [0]
        indices:  dict[str, int]  = {}
        lowlinks: dict[str, int]  = {}
        on_stack: set[str]        = set()
        stack:    list[str]       = []
        sccs:     list[list[str]] = []

        all_nodes = set(graph.keys())
        for node in list(graph.keys()):
            all_nodes.update(graph[node])
        all_nodes = list(all_nodes)

        def strongconnect(v: str) -> None:
            indices[v] = index_counter[0]
            lowlinks[v] = index_counter[0]
            index_counter[0] += 1
            stack.append(v)
            on_stack.add(v)

            for w in graph.get(v, set()):
                if w not in indices:
                    strongconnect(w)
                    lowlinks[v] = min(lowlinks[v], lowlinks[w])
                elif w in on_stack:
                    lowlinks[v] = min(lowlinks[v], indices[w])

            if lowlinks[v] == indices[v]:
                scc: list[str] = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    scc.append(w)
                    if w == v:
                        break
                if len(scc) > 1:
                    sccs.append(scc)

        for node in all_nodes:
            if node not in indices:
                strongconnect(node)

        return sccs

    def classify_cycles(
        self, cycles: list[list[str]]
    ) -> tuple[list[list[str]], list[list[str]]]:
        inter_layer: list[list[str]] = []
        intra_layer: list[list[str]] = []

        for cycle in cycles:
            layers = {
                self.identify_layer(node)
                for node in cycle
                if self.identify_layer(node) not in ("unknown", "__external__")
            }
            if len(layers) > 1:
                inter_layer.append(cycle)
            elif len(layers) == 1:
                intra_layer.append(cycle)

        return inter_layer, intra_layer

    def check_missing_init_files(
        self, py_files: list[pathlib.Path]
    ) -> list[MissingInitInfo]:
        missing: list[MissingInitInfo] = []
        dirs_with_py: set[pathlib.Path] = set()
        dirs_with_init: set[pathlib.Path] = set()

        for f in py_files:
            parent = f.parent
            dirs_with_py.add(parent)
            if f.name == "__init__.py":
                dirs_with_init.add(parent)

        for d in sorted(dirs_with_py - dirs_with_init):
            try:
                rel = d.relative_to(self.root_dir)
                parts = rel.parts
                if not parts:
                    continue
                top = parts[0]
                if top in ("migrations", "deployment", "docs", ".venv", "venv",
                           "__pycache__", "node_modules", "dist", "build"):
                    continue
                missing.append(MissingInitInfo(
                    package_path=str(rel),
                    message=f"MISSING __init__.py di '{rel}'"
                ))
            except ValueError:
                pass

        return missing

    def check_duplicate_modules(
        self, py_files: list[pathlib.Path]
    ) -> list[DuplicateModuleInfo]:
        from collections import defaultdict as dd
        name_to_paths: dict[str, list[str]] = dd(list)

        for f in py_files:
            if f.name == "__init__.py":
                continue
            try:
                rel = f.relative_to(self.root_dir)
                mod_name = str(rel.with_suffix("")).replace(os.sep, ".")
                name_to_paths[mod_name].append(str(rel))
            except ValueError:
                pass

        duplicates: list[DuplicateModuleInfo] = []
        for mod_name, paths in name_to_paths.items():
            if len(paths) > 1:
                layers = {
                    self.identify_layer(mod_name)
                    for p in paths
                }
                duplicates.append(DuplicateModuleInfo(
                    module_name=mod_name,
                    occurrences=sorted(paths),
                    message=(
                        f"DUPLICATE MODULE '{mod_name}' di {len(paths)} lokasi "
                        f"berbeda ({', '.join(sorted(layers))}) — "
                        f"risiko import shadowing (INFO)"
                    ),
                    severity="INFO"
                ))

        return sorted(duplicates, key=lambda d: d.module_name)

# ─────────────────────────────────────────────────────────────────────────────
# SCORING ENGINE
# ─────────────────────────────────────────────────────────────────────────────
def compute_score(
    report: MasterReport,
    strict_mode: bool,
) -> tuple[int, dict[str, int], str]:
    breakdown: dict[str, int] = {}
    score = 100

    critical_count = sum(
        1 for mr in report.modules.values()
        for v in mr.violations
        if v.severity == "CRITICAL"
    )
    error_count = sum(
        1 for mr in report.modules.values()
        for v in mr.violations
        if v.severity in ("ERROR", "WARNING")
    )

    critical_penalty = critical_count * 2
    error_penalty    = error_count * 1
    inter_penalty    = len(report.inter_layer_cycles) * 2
    intra_penalty    = len(report.intra_layer_cycles) * 1 if strict_mode else 0
    wildcard_penalty = report.total_wildcard_violations * 1
    init_penalty     = len(report.missing_init_files) * 1
    dup_penalty      = len(report.duplicate_modules) * 0.5

    breakdown["critical_drift"]    = -critical_penalty
    breakdown["error_drift"]       = -error_penalty
    breakdown["inter_layer_cycle"] = -inter_penalty
    breakdown["intra_layer_cycle"] = -intra_penalty
    breakdown["wildcard_import"]   = -wildcard_penalty
    breakdown["missing_init"]      = -init_penalty
    breakdown["duplicate_module"]  = -int(dup_penalty)

    score -= (critical_penalty + error_penalty + inter_penalty +
              intra_penalty + wildcard_penalty + init_penalty + dup_penalty)
    score = max(0, min(100, score))

    if score == 100:
        verdict = "SEMPURNA — Nol pelanggaran terdeteksi. Siap audit Big4."
    elif score >= 90:
        verdict = "SANGAT BAIK — Pelanggaran minor. Segera perbaiki."
    elif score >= 75:
        verdict = "BAIK — Beberapa pelanggaran signifikan. Perbaiki segera."
    elif score >= 50:
        verdict = "PERHATIAN — Banyak pelanggaran. Integritas arsitektur terancam."
    elif score >= 25:
        verdict = "KRITIS — Pelanggaran masif. Arsitektur dalam bahaya."
    else:
        verdict = "GAGAL TOTAL — Arsitektur rusak parah. Tidak layak produksi."

    return score, breakdown, verdict

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"{TOOL_NAME} v{TOOL_VERSION} — Validator Arsitektur + RCA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh:
  python architecture_drift_checker.py --verbose --rca
  python architecture_drift_checker.py --json report.json --deep-rca
  python architecture_drift_checker.py --strict --verbose --show-skipped
        """
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE")
    parser.add_argument("--sarif", metavar="FILE")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--hide-intra-cycles", action="store_true")
    parser.add_argument("--show-clean", action="store_true")
    parser.add_argument("--show-wildcards", action="store_true")
    parser.add_argument("--show-skipped", action="store_true", help="Tampilkan detail file yang gagal di-scan")
    parser.add_argument("--rca", action="store_true", help="Aktifkan analisis RCA pada pelanggaran (fallback manual)")
    parser.add_argument("--deep-rca", action="store_true", help="Gunakan RCA Engine sungguhan (jika tersedia) untuk analisis mendalam")
    parser.add_argument("--exclude", default=".venv,venv,__pycache__,node_modules,dist,build,migrations,deployment,docs")
    parser.add_argument("--layer-report", action="store_true")
    parser.add_argument("--fail-on-warning", action="store_true")
    args = parser.parse_args()

    use_rca = args.rca or args.deep_rca
    use_deep_rca = args.deep_rca and RCA_AVAILABLE

    start_time = time.monotonic()
    root_dir   = pathlib.Path.cwd()
    verifier   = SovereignArchitectureVerifier(root_dir, strict_mode=args.strict)
    git_commit = get_git_commit(root_dir)
    scan_ts    = datetime.now(timezone.utc).isoformat()

    print(c("BOLD", c("CYAN",
        "╔══════════════════════════════════════════════════════════════════════════╗\n"
        "║   SOVEREIGN ERP — ARCHITECTURE DRIFT VALIDATOR v5.1.1                  ║\n"
        "║   Big‑4 Audit Grade · Full RCA Integration · Zero False Positives       ║\n"
        "╚══════════════════════════════════════════════════════════════════════════╝"
    )))
    print(c("DIM", f"  Direktori : {root_dir}"))
    print(c("DIM", f"  Git Commit: {git_commit}"))
    print(c("DIM", f"  Timestamp : {scan_ts}"))
    print(c("DIM", f"  Python    : {sys.version.split()[0]}"))

    if RCA_AVAILABLE:
        print(c("GREEN", f"  ✅ RCA Engine aktif (v{RCA_ENGINE.VERSION if RCA_ENGINE and hasattr(RCA_ENGINE, 'VERSION') else '?'})"))
        if use_deep_rca:
            print(c("GREEN", "  ✅ Mode DEEP-RCA diaktifkan"))
    else:
        print(c("YELLOW", "  ⚠️  RCA Engine tidak ditemukan – gunakan fallback manual"))
    print()

    exclude_set = {d.strip() for d in args.exclude.split(",") if d.strip()}
    py_files: list[pathlib.Path] = []
    excluded_count = 0

    for path in sorted(root_dir.rglob("*.py")):
        if any(part in exclude_set for part in path.parts):
            excluded_count += 1
            continue
        if path.name.startswith("architecture_drift_checker"):
            excluded_count += 1
            continue
        py_files.append(path)

    print(f"  {c('BOLD', 'Scanning')} {len(py_files)} file Python "
          f"({excluded_count} dikecualikan)...")
    print()

    master = MasterReport(
        scan_timestamp=scan_ts,
        root_dir=str(root_dir),
        python_version=sys.version.split()[0],
        git_commit=git_commit,
        total_files_found=len(py_files) + excluded_count,
        total_files_excluded=excluded_count,
    )

    for layer_name in LAYER_MAP.values():
        if layer_name not in master.layer_stats:
            master.layer_stats[layer_name] = LayerStats(layer=layer_name)

    all_edges: list[ImportEdge] = []
    skipped_count = 0

    try:
        for file_path in py_files:
            report, edges, error = verifier.parse_module(file_path)

            if report is None:
                skipped_count += 1
                master.skipped_files.append(SkippedFileInfo(
                    file_path=file_path,
                    error=error or "Unknown error",
                    error_type="ParseError"
                ))
                continue

            master.total_files_scanned += 1
            all_edges.extend(edges)
            master.modules[report.module_path] = report

            layer = report.layer
            if layer not in master.layer_stats:
                master.layer_stats[layer] = LayerStats(layer=layer)
            ls = master.layer_stats[layer]
            ls.total_modules += 1

            if report.violations:
                master.violated_modules_count  += 1
                master.total_drift_violations  += len(report.violations)
                ls.violated_modules += 1
                ls.total_violations += len(report.violations)
            else:
                master.clean_modules_count += 1

            master.total_wildcard_violations += len(report.wildcards)
            ls.wildcard_imports += len(report.wildcards)
    except KeyboardInterrupt:
        print("\n" + c("YELLOW", "⏹️  Dibatalkan oleh pengguna."))
        sys.exit(130)

    master.total_files_skipped = skipped_count

    graph      = verifier.build_import_graph(all_edges)
    raw_cycles = verifier.tarjan_scc_recursive(graph)
    inter_cycles, intra_cycles = verifier.classify_cycles(raw_cycles)

    master.inter_layer_cycles = inter_cycles
    master.intra_layer_cycles = intra_cycles

    master.missing_init_files = verifier.check_missing_init_files(py_files)
    master.duplicate_modules  = verifier.check_duplicate_modules(py_files)

    master.score, master.score_breakdown, master.verdict = compute_score(
        master, args.strict
    )

    elapsed = time.monotonic() - start_time
    master.scan_duration_sec = round(elapsed, 3)

    # ─── OUTPUT ────────────────────────────────────────────────────────────────
    print("─" * 76)
    print(c("BOLD", "  RINGKASAN EKSEKUTIF"))
    print("─" * 76)
    print(f"  Total File Ditemukan      : {master.total_files_found}")
    print(f"  Total File Di-scan        : {master.total_files_scanned}")
    print(f"  File Dilewati (error)     : {c('RED' if master.total_files_skipped > 0 else 'GREEN', str(master.total_files_skipped))}")
    print(f"  ✅ Modul Bersih           : {c('GREEN', str(master.clean_modules_count))}")
    print(f"  ❌ Modul Bermasalah       : {c('RED', str(master.violated_modules_count)) if master.violated_modules_count else c('GREEN', '0')}")
    print(f"  ⚠️  Pelanggaran Layer Drift : {c('RED', str(master.total_drift_violations)) if master.total_drift_violations else c('GREEN', '0')}")
    print(f"  🔄 Siklus Antar Layer     : {c('RED', str(len(inter_cycles))) if inter_cycles else c('GREEN', '0')}")
    print(f"  🔗 Siklus Intra Layer     : {c('DIM', str(len(intra_cycles)))} (INFO)")
    print(f"  🌟 Wildcard Imports       : {c('YELLOW', str(master.total_wildcard_violations)) if master.total_wildcard_violations else c('GREEN', '0')}")
    print(f"  📦 Missing __init__.py    : {c('YELLOW', str(len(master.missing_init_files))) if master.missing_init_files else c('GREEN', '0')}")
    print(f"  🔁 Duplicate Modules      : {c('DIM', str(len(master.duplicate_modules)))} (INFO)")
    print("─" * 76)

    score_color = "GREEN" if master.score >= 90 else "YELLOW" if master.score >= 70 else "RED"
    print(f"\n  📊 {c('BOLD', 'SKOR INTEGRITAS ARSITEKTUR')} : "
          f"{c('BOLD', c(score_color, f'{master.score}/100'))}")
    print(f"  📋 Verdict                : {c('BOLD', master.verdict)}")

    print(f"\n  {c('DIM', 'Rincian Pengurangan Skor:')}")
    for k, v in master.score_breakdown.items():
        if v != 0:
            label = k.replace("_", " ").title()
            print(f"  {c('DIM', f'  {label:<30}: {v:+d} poin')}")
    print()

    # ─── FILE GAGAL DI-SCAN ──────────────────────────────────────────────────
    if master.skipped_files and (args.verbose or args.show_skipped):
        print("─" * 76)
        print(c("BOLD", c("RED", f"  ⚠️ FILE GAGAL DI-SCAN ({len(master.skipped_files)} FILE)")))
        print("─" * 76)
        for sf in master.skipped_files[:20]:
            try:
                rel = sf.file_path.relative_to(root_dir)
            except ValueError:
                rel = sf.file_path
            print(f"  ❌ {rel}")
            print(f"     {c('YELLOW', sf.error_type)}: {sf.error[:200]}")
        if len(master.skipped_files) > 20:
            print(f"  ... dan {len(master.skipped_files)-20} file lainnya.")
        print(c("YELLOW", "\n  🔧 Perbaiki file-file di atas agar coverage mencapai 100%."))
        print()

    # ─── DETAIL PELANGGARAN ────────────────────────────────────────────────────
    if master.total_drift_violations > 0:
        print("─" * 76)
        print(c("BOLD", c("RED", "  DETAIL PELANGGARAN LAYER DRIFT")))
        print("─" * 76)

        for mod_name in sorted(master.modules.keys()):
            rep = master.modules[mod_name]
            if not rep.violations:
                continue

            sev_icons = {"CRITICAL": "🔴", "ERROR": "🟠", "WARNING": "🟡"}
            print(f"\n  {c('RED', f'❌ {mod_name}')}")
            print(f"     Layer   : {c('YELLOW', rep.layer)}")
            print(f"     File    : {c('DIM', rep.file_path)}")
            print(f"     Impor   : {rep.import_count} total, {len(rep.violations)} pelanggaran")

            for v in rep.violations:
                icon = sev_icons.get(v.severity, "⚠️")
                print(f"     {icon} [{v.severity}] Baris {v.line}: {v.message}")
                if use_rca:
                    rca = analyze_violation_with_rca(
                        source_layer=v.source_layer or rep.layer,
                        target_layer=v.target_layer,
                        source_module=mod_name,
                        target_module=v.target_module,
                        import_type=v.import_type,
                        severity=v.severity,
                        use_deep_rca=use_deep_rca,
                    )
                    print(f"        {c('BOLD', 'RCA')}:")
                    print(f"          {c('YELLOW', 'Category')}   : {rca['category']}")
                    print(f"          {c('YELLOW', 'Risk')}      : {rca['risk']}")
                    print(f"          {c('YELLOW', 'Fix Time')}  : {rca['fix_time_estimate']}")
                    print(f"          {c('YELLOW', 'Root Cause')}: {rca['root_cause']}")
                    print(f"          {c('YELLOW', 'Impact')}    :")
                    for imp in rca['impact']:
                        print(f"            - {imp}")
                    print(f"          {c('YELLOW', 'Suggested Fix')}: {rca['suggested_fix']}")
                    conf = rca.get('confidence', 0.0)
                    if isinstance(conf, float):
                        print(f"          {c('DIM', f'Confidence: {int(conf*100)}%')}")

    elif master.total_drift_violations == 0:
        print(f"\n  {c('GREEN', '✅ Tidak ada pelanggaran layer drift terdeteksi.')}")

    # ── WILDCARD ──────────────────────────────────────────────────────────────
    if master.total_wildcard_violations > 0 and args.show_wildcards:
        print()
        print("─" * 76)
        print(c("BOLD", c("YELLOW", "  WILDCARD IMPORT VIOLATIONS")))
        print("─" * 76)
        for rep in master.modules.values():
            for wc in rep.wildcards:
                print(f"  ⚠️  {wc.module_path}:{wc.line}")
                print(f"     {wc.message}")

    # ── CYCLES ────────────────────────────────────────────────────────────────
    print()
    print("─" * 76)
    if inter_cycles:
        print(c("BOLD", c("RED", "  🚨 SIKLUS DEPENDENSI ANTAR LAYER (KRITIS)")))
        print("─" * 76)
        max_cycles = 50
        for idx, chain in enumerate(inter_cycles[:max_cycles], 1):
            layers_in_cycle = sorted({
                verifier.identify_layer(m) for m in chain
                if verifier.identify_layer(m) not in ("unknown", "__external__")
            })
            print(f"\n  Siklus #{idx} ({len(chain)} modul, "
                  f"{len(layers_in_cycle)} layer terlibat):")
            print(f"  Layer   : {' ↔ '.join(layers_in_cycle)}")
            preview = chain[:6]
            suffix  = f" ... (+{len(chain)-6} lagi)" if len(chain) > 6 else ""
            print(f"  Rantai  : {' ➔ '.join(preview)}{suffix}")
        if len(inter_cycles) > max_cycles:
            print(f"\n  ... dan {len(inter_cycles)-max_cycles} siklus antar-layer lainnya.")
    else:
        print(c("GREEN", "  ✅ Tidak ada siklus antar layer terdeteksi."))
    print("─" * 76)

    if intra_cycles and not args.hide_intra_cycles:
        print()
        print(f"  🔗 Siklus Intra-Layer [INFO] — {len(intra_cycles)} ditemukan")
        max_cycles = 20
        for idx, chain in enumerate(intra_cycles[:max_cycles], 1):
            layer = verifier.identify_layer(chain[0])
            preview = chain[:4]
            suffix  = f" (+{len(chain)-4})" if len(chain) > 4 else ""
            print(f"     {idx:3d}. [{layer}] {' ➔ '.join(preview)}{suffix}")
        if len(intra_cycles) > max_cycles:
            print(f"         ... dan {len(intra_cycles)-max_cycles} siklus intra-layer lainnya")
        print(c("DIM", "         Tip: Siklus intra-layer wajar di ORM (SQLAlchemy) — "
                        "tidak mempengaruhi skor."))

    # ── MISSING INIT ──────────────────────────────────────────────────────────
    if master.missing_init_files:
        print()
        print("─" * 76)
        print(c("BOLD", c("YELLOW", "  📦 MISSING __init__.py FILES")))
        print("─" * 76)
        for mi in master.missing_init_files[:20]:
            print(f"  ⚠️  {mi.message}")
        if len(master.missing_init_files) > 20:
            print(f"  ... dan {len(master.missing_init_files)-20} lainnya")

    # ── DUPLICATE MODULES ─────────────────────────────────────────────────────
    if master.duplicate_modules:
        print()
        print("─" * 76)
        print(c("BOLD", c("DIM", "  🔁 DUPLICATE MODULE NAMES (INFO)")))
        print("─" * 76)
        for dm in master.duplicate_modules[:20]:
            print(f"  ⚠️  {dm.message}")
            for occ in dm.occurrences:
                print(f"         → {occ}")

    # ── LAYER REPORT ──────────────────────────────────────────────────────────
    if args.layer_report:
        print()
        print("─" * 76)
        print(c("BOLD", "  STATISTIK PER LAYER"))
        print("─" * 76)
        print(f"  {'Layer':<22} {'Modul':>6} {'Bermasalah':>11} {'Pelanggaran':>13} {'Wildcard':>9}")
        print(f"  {'─'*22} {'─'*6} {'─'*11} {'─'*13} {'─'*9}")
        for layer_name in sorted(master.layer_stats.keys()):
            ls = master.layer_stats[layer_name]
            if ls.total_modules == 0:
                continue
            ok_color = "RED" if ls.violated_modules > 0 else "GREEN"
            print(
                f"  {layer_name:<22} "
                f"{ls.total_modules:>6} "
                f"{c(ok_color, f'{ls.violated_modules:>10}')} "
                f"{'':>1}{ls.total_violations:>12} "
                f"{'':>1}{ls.wildcard_imports:>8}"
            )

    # ── CLEAN MODULES ────────────────────────────────────────────────────────
    if args.show_clean:
        print()
        print("─" * 76)
        print(c("BOLD", c("GREEN", "  MODUL BERSIH (TANPA PELANGGARAN)")))
        print("─" * 76)
        clean_list = sorted([
            mod for mod, rep in master.modules.items()
            if not rep.violations and rep.layer not in SKIP_LAYERS
        ])
        if clean_list:
            for mod_name in clean_list[:50]:
                rep = master.modules[mod_name]
                print(f"  ✅ {mod_name} [{rep.layer}]")
            if len(clean_list) > 50:
                print(f"  ... dan {len(clean_list)-50} modul bersih lainnya.")
        else:
            print("  Tidak ada modul bersih (atau semuanya di-skip).")

    # ── FOOTER ────────────────────────────────────────────────────────────────
    print()
    print("─" * 76)
    print(f"  ⏱️  Waktu Eksekusi  : {elapsed:.3f} detik")
    print(f"  📁 Total Edge Import: {len(all_edges)} (dedup: {len(graph)} node)")
    total_py = len(py_files)
    if total_py > 0:
        coverage = master.total_files_scanned / total_py * 100
        print(f"  🔍 Coverage         : {master.total_files_scanned} dari {total_py} file "
              f"({c('GREEN' if coverage == 100 else 'YELLOW', f'{coverage:.1f}%')})")
    else:
        print("  🔍 Coverage         : 0% (tidak ada file)")
    print("─" * 76)

    # ── JSON ──────────────────────────────────────────────────────────────────
    if args.json:
        payload = {
            "meta": {
                "tool": TOOL_NAME,
                "version": TOOL_VERSION,
                "scan_timestamp": master.scan_timestamp,
                "scan_duration": master.scan_duration_sec,
                "root_dir": master.root_dir,
                "python_version": master.python_version,
                "git_commit": master.git_commit,
                "rca_enabled": RCA_AVAILABLE,
                "rca_used": use_deep_rca,
            },
            "summary": {
                "score": master.score,
                "verdict": master.verdict,
                "score_breakdown": master.score_breakdown,
                "total_files_found": master.total_files_found,
                "total_files_scanned": master.total_files_scanned,
                "total_files_skipped": master.total_files_skipped,
                "total_files_excluded": master.total_files_excluded,
                "coverage_percent": round(master.total_files_scanned / total_py * 100, 2) if total_py else 0,
                "clean_modules": master.clean_modules_count,
                "violated_modules": master.violated_modules_count,
                "total_drift_violations": master.total_drift_violations,
                "total_wildcard_violations": master.total_wildcard_violations,
                "inter_layer_cycles": len(master.inter_layer_cycles),
                "intra_layer_cycles": len(master.intra_layer_cycles) if not args.hide_intra_cycles else 0,
                "missing_init_files": len(master.missing_init_files),
                "duplicate_modules": len(master.duplicate_modules),
            },
            "skipped_files": [
                {
                    "file": str(sf.file_path.relative_to(root_dir)) if sf.file_path.is_relative_to(root_dir) else str(sf.file_path),
                    "error": sf.error,
                    "error_type": sf.error_type,
                }
                for sf in master.skipped_files
            ],
            "layer_stats": {
                layer: {
                    "total_modules": ls.total_modules,
                    "violated_modules": ls.violated_modules,
                    "total_violations": ls.total_violations,
                    "wildcard_imports": ls.wildcard_imports,
                }
                for layer, ls in master.layer_stats.items()
                if ls.total_modules > 0
            },
            "violations": {
                mod: {
                    "file": rep.file_path,
                    "layer": rep.layer,
                    "violations": [
                        {
                            "line": v.line,
                            "severity": v.severity,
                            "import_type": v.import_type,
                            "target_module": v.target_module,
                            "target_layer": v.target_layer,
                            "message": v.message,
                            "rca": analyze_violation_with_rca(
                                source_layer=v.source_layer or rep.layer,
                                target_layer=v.target_layer,
                                source_module=mod,
                                target_module=v.target_module,
                                import_type=v.import_type,
                                severity=v.severity,
                                use_deep_rca=use_deep_rca,
                            ) if use_rca else None,
                        }
                        for v in rep.violations
                    ],
                    "wildcard_violations": [
                        {"line": wc.line, "message": wc.message}
                        for wc in rep.wildcards
                    ],
                }
                for mod, rep in sorted(master.modules.items())
                if rep.violations or rep.wildcards
            },
            "cycles": {
                "inter_layer": [
                    {
                        "chain": chain,
                        "layers": sorted({
                            verifier.identify_layer(m)
                            for m in chain
                            if verifier.identify_layer(m) not in ("unknown", "__external__")
                        }),
                        "size": len(chain),
                    }
                    for chain in master.inter_layer_cycles
                ],
                "intra_layer": [
                    {"layer": verifier.identify_layer(chain[0]), "chain": chain, "size": len(chain)}
                    for chain in master.intra_layer_cycles
                ] if not args.hide_intra_cycles else [],
            },
            "structural_issues": {
                "missing_init_files": [
                    {"package": mi.package_path, "message": mi.message}
                    for mi in master.missing_init_files
                ],
                "duplicate_modules": [
                    {
                        "name": dm.module_name,
                        "occurrences": dm.occurrences,
                        "message": dm.message,
                        "severity": dm.severity,
                    }
                    for dm in master.duplicate_modules
                ],
            },
            "clean_modules": sorted([
                mod for mod, rep in master.modules.items()
                if not rep.violations and rep.layer not in SKIP_LAYERS
            ]),
        }

        try:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
            print(c("GREEN", f"  ✅ Laporan JSON diekspor ke: {args.json}"))
        except Exception as e:
            print(c("RED", f"  ❌ Gagal menulis JSON: {e}"))

    # ── SARIF ──────────────────────────────────────────────────────────────────
    if args.sarif:
        sarif_results = []
        for mod, rep in master.modules.items():
            for v in rep.violations:
                sarif_results.append({
                    "ruleId": f"DRIFT-{v.severity}",
                    "level": "error" if v.severity == "CRITICAL" else "warning",
                    "message": {"text": v.message},
                    "locations": [{
                        "physicalLocation": {
                            "artifactLocation": {"uri": rep.file_path},
                            "region": {"startLine": v.line},
                        }
                    }],
                })
            for wc in rep.wildcards:
                sarif_results.append({
                    "ruleId": "WILDCARD-IMPORT",
                    "level": "warning",
                    "message": {"text": wc.message},
                    "locations": [{
                        "physicalLocation": {
                            "artifactLocation": {"uri": rep.file_path},
                            "region": {"startLine": wc.line},
                        }
                    }],
                })

        sarif_payload = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [{
                "tool": {
                    "driver": {
                        "name": TOOL_NAME,
                        "version": TOOL_VERSION,
                        "informationUri": "https://github.com/sovereign-erp",
                        "rules": [
                            {"id": "DRIFT-CRITICAL", "shortDescription": {"text": "Critical architecture drift"}},
                            {"id": "DRIFT-ERROR",    "shortDescription": {"text": "Architecture boundary violation"}},
                            {"id": "DRIFT-WARNING",  "shortDescription": {"text": "Architecture drift warning"}},
                            {"id": "WILDCARD-IMPORT","shortDescription": {"text": "Wildcard import across layer boundary"}},
                        ]
                    }
                },
                "results": sarif_results,
            }]
        }

        try:
            with open(args.sarif, "w", encoding="utf-8") as fh:
                json.dump(sarif_payload, fh, indent=2, ensure_ascii=False)
            print(c("GREEN", f"  ✅ SARIF report diekspor ke: {args.sarif}"))
        except Exception as e:
            print(c("RED", f"  ❌ Gagal menulis SARIF: {e}"))

    # ── EXIT CODE ─────────────────────────────────────────────────────────────
    has_drift_errors = (
        master.total_drift_violations > 0 or
        len(master.inter_layer_cycles) > 0 or
        master.total_wildcard_violations > 0
    )
    has_strict_errors = args.strict and len(master.intra_layer_cycles) > 0
    has_warning = args.fail_on_warning and master.total_drift_violations > 0

    if has_drift_errors or has_warning:
        sys.exit(1)
    elif has_strict_errors:
        sys.exit(2)
    else:
        sys.exit(0)

if __name__ == "__main__":
    main()