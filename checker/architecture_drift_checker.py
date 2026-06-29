#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════════╗
║    SOVEREIGN ERP ACCOUNTING ENGINE — ARCHITECTURE DRIFT & BOUNDARY VALIDATOR   ║
║    Version: 4.1.0  |  Audit-Grade  |  Big4-Ready  |  Smart Scoring + RCA      ║
╚══════════════════════════════════════════════════════════════════════════════════╝

PERBAIKAN VERSI 4.1.0:
  • Duplicate module → severity INFO, penalti 0 (false positive pada domain/projection)
  • Intra-layer cycle → penalti 0 (kecuali --strict) — wajar di ORM (SQLAlchemy)
  • RCA diperkaya: fix_time, risk, category untuk tiap pelanggaran
  • Skor sekarang mencerminkan ancaman arsitektur nyata, bukan false positive.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# VERSI & METADATA
# ─────────────────────────────────────────────────────────────────────────────
TOOL_VERSION = "4.1.0"
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
# STDLIB / BUILTIN — FILTER
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
    # Third-party
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
    "celery", "dramatiq", "rq", "arq", "faust", "confluent_kafka",
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

# ─────────────────────────────────────────────────────────────────────────────
# HIERARCHY LAYER — untuk menentukan CRITICAL vs ERROR
# ─────────────────────────────────────────────────────────────────────────────
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
    # Operational
    "monitoring":           99,
    "disaster_recovery":    99,
    "security_hardening":   99,
    "architecture":         99,
    "checker":              99,
    "tests":                99,
    "unknown":              99,
}

# ─────────────────────────────────────────────────────────────────────────────
# ALLOWED DEPENDENCY PAIRS (MATRIX)
# ─────────────────────────────────────────────────────────────────────────────
ALLOWED_PAIRS: frozenset[tuple[str, str]] = frozenset({

    # ── AXIOMS ───────────────────────────────────────────────────────────────
    ("axioms",           "axioms"),
    ("axioms",           "constitution"),  # Supreme law reference

    # ── CONSTITUTION ────────────────────────────────────────────────────────
    ("constitution",     "constitution"),
    ("constitution",     "axioms"),

    # ── DOMAIN ──────────────────────────────────────────────────────────────
    ("domain",           "domain"),
    ("domain",           "axioms"),
    ("domain",           "constitution"),

    # ── PORTS ────────────────────────────────────────────────────────────────
    ("ports",            "ports"),
    ("ports",            "domain"),
    ("ports",            "axioms"),
    ("ports",            "constitution"),

    # ── KERNEL ───────────────────────────────────────────────────────────────
    ("kernel",           "kernel"),
    ("kernel",           "domain"),
    ("kernel",           "axioms"),
    ("kernel",           "constitution"),
    ("kernel",           "ports"),
    ("kernel",           "config"),

    # ── CONFIG ──────────────────────────────────────────────────────────────
    ("config",           "config"),
    ("config",           "axioms"),

    # ── POLICY ENGINE ────────────────────────────────────────────────────────
    ("policy_engine",    "policy_engine"),
    ("policy_engine",    "domain"),
    ("policy_engine",    "axioms"),
    ("policy_engine",    "constitution"),
    ("policy_engine",    "kernel"),
    ("policy_engine",    "config"),
    ("policy_engine",    "ports"),
    ("policy_engine",    "compliance"),

    # ── AUDIT ───────────────────────────────────────────────────────────────
    ("audit",            "audit"),
    ("audit",            "domain"),
    ("audit",            "axioms"),
    ("audit",            "kernel"),
    ("audit",            "ports"),
    ("audit",            "config"),
    ("audit",            "infrastructure"),
    ("audit",            "application"),

    # ── COMPLIANCE ──────────────────────────────────────────────────────────
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

    # ── APPLICATION ────────────────────────────────────────────────────────
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

    # ── INFRASTRUCTURE ──────────────────────────────────────────────────────
    ("infrastructure",   "infrastructure"),
    ("infrastructure",   "domain"),
    ("infrastructure",   "axioms"),
    ("infrastructure",   "ports"),
    ("infrastructure",   "kernel"),
    ("infrastructure",   "config"),

    # ── EVENT GATEWAY ───────────────────────────────────────────────────────
    ("event_gateway",    "event_gateway"),
    ("event_gateway",    "domain"),
    ("event_gateway",    "application"),
    ("event_gateway",    "infrastructure"),
    ("event_gateway",    "kernel"),
    ("event_gateway",    "config"),
    ("event_gateway",    "ports"),

    # ── ADAPTERS ────────────────────────────────────────────────────────────
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

    # ── TRANSFORMERS ────────────────────────────────────────────────────────
    ("transformers",     "transformers"),
    ("transformers",     "domain"),
    ("transformers",     "application"),
    ("transformers",     "ports"),
    ("transformers",     "infrastructure"),
    ("transformers",     "config"),
    ("transformers",     "kernel"),

    # ── PROJECTIONS ────────────────────────────────────────────────────────
    ("projections",      "projections"),
    ("projections",      "domain"),
    ("projections",      "application"),
    ("projections",      "infrastructure"),
    ("projections",      "kernel"),
    ("projections",      "ports"),
    ("projections",      "config"),

    # ── REPORTS ────────────────────────────────────────────────────────────
    ("reports",          "reports"),
    ("reports",          "projections"),
    ("reports",          "application"),
    ("reports",          "domain"),
    ("reports",          "infrastructure"),
    ("reports",          "ports"),
    ("reports",          "config"),

    # ── BOOTSTRAP ──────────────────────────────────────────────────────────
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

    # ── APP ────────────────────────────────────────────────────────────────
    ("app",              "app"),
    ("app",              "bootstrap"),
    ("app",              "adapters"),
    ("app",              "infrastructure"),
    ("app",              "config"),
    ("app",              "domain"),
    ("app",              "kernel"),

    # ── OPERATIONAL LAYERS ────────────────────────────────────────────────
    ("monitoring",           "monitoring"),
    ("monitoring",           "domain"),
    ("monitoring",           "application"),
    ("monitoring",           "infrastructure"),
    ("monitoring",           "kernel"),
    ("monitoring",           "config"),
    ("monitoring",           "ports"),
    ("monitoring",           "adapters"),
    ("monitoring",           "bootstrap"),
    ("monitoring",           "app"),

    ("security_hardening",   "security_hardening"),
    ("security_hardening",   "domain"),
    ("security_hardening",   "application"),
    ("security_hardening",   "infrastructure"),
    ("security_hardening",   "kernel"),
    ("security_hardening",   "config"),
    ("security_hardening",   "ports"),
    ("security_hardening",   "adapters"),
    ("security_hardening",   "audit"),
    ("security_hardening",   "compliance"),

    ("disaster_recovery",    "disaster_recovery"),
    ("disaster_recovery",    "domain"),
    ("disaster_recovery",    "infrastructure"),
    ("disaster_recovery",    "kernel"),
    ("disaster_recovery",    "config"),
    ("disaster_recovery",    "adapters"),
    ("disaster_recovery",    "bootstrap"),

    ("architecture",         "architecture"),
    ("architecture",         "domain"),
    ("architecture",         "application"),
    ("architecture",         "infrastructure"),
    ("architecture",         "kernel"),
    ("architecture",         "ports"),
    ("architecture",         "adapters"),
    ("architecture",         "config"),
    ("architecture",         "axioms"),
    ("architecture",         "constitution"),
    ("architecture",         "policy_engine"),
    ("architecture",         "compliance"),
    ("architecture",         "audit"),
    ("architecture",         "projections"),
    ("architecture",         "reports"),
    ("architecture",         "event_gateway"),
    ("architecture",         "transformers"),
    ("architecture",         "bootstrap"),
    ("architecture",         "app"),
    ("architecture",         "security_hardening"),
    ("architecture",         "monitoring"),
    ("architecture",         "disaster_recovery"),
    ("architecture",         "checker"),
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
    severity:    str = "INFO"  # sekarang INFO

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
# RCA DIAGNOSTICS — DIPERKAYA
# ─────────────────────────────────────────────────────────────────────────────
def generate_violation_rca(
    source_layer: str,
    target_layer: str,
    source_module: str,
    target_module: str,
    import_type: str,
    severity: str,
) -> dict:
    """
    Kembalikan RCA terstruktur dengan metadata tambahan.
    """
    sr = LAYER_RANK.get(source_layer, 99)
    tr = LAYER_RANK.get(target_layer, 99)
    direction = "downward" if sr > tr else "upward" if sr < tr else "same-rank"

    evidence = [
        f"Source layer: {source_layer} (rank {sr})",
        f"Target layer: {target_layer} (rank {tr})",
        f"Import type: {import_type}",
        f"Module: {source_module} → {target_module}",
        f"Dependency direction: {direction}",
    ]

    impact = []
    root_cause = ""
    suggested_fix = ""
    confidence = 0.8
    fix_time = "Unknown"
    risk = "Medium"
    category = "Architecture"

    # ── Special cases ────────────────────────────────────────────────────────
    if source_layer == "transformers" and target_layer == "bootstrap":
        root_cause = (
            "Transformer modules are responsible for data transformation and should not "
            "know about the Dependency Injection container (IoC). Direct import of "
            "bootstrap.dependency_container violates Separation of Concerns."
        )
        impact = [
            "Transformers become hard to unit test (need to mock the container).",
            "Reusability is reduced because the transformer carries container dependencies.",
            "Changes in the container may break transformers unexpectedly.",
        ]
        suggested_fix = (
            "Inject required dependencies (e.g., services, repositories) as constructor "
            "parameters or via a port interface. The composition root (bootstrap) should "
            "wire the dependencies, not the transformer itself."
        )
        confidence = 0.95
        fix_time = "2 hours"
        risk = "Critical"
        category = "Clean Architecture / DI"

    elif source_layer == "transformers" and target_layer == "event_gateway":
        root_cause = (
            "Transformer should not publish events directly. Event publishing is a "
            "responsibility of the application or domain layer."
        )
        impact = [
            "Event publishing becomes scattered and harder to audit.",
            "Transformer now has side effects, violating Single Responsibility Principle.",
        ]
        suggested_fix = (
            "Have the transformer return a command or DTO that the application layer "
            "then uses to publish events via the event gateway."
        )
        confidence = 0.92
        fix_time = "1.5 hours"
        risk = "High"
        category = "CQRS / Event Sourcing"

    elif source_layer == "axioms" and target_layer == "constitution":
        root_cause = "Axioms naturally refer to the supreme law (constitution) for validation."
        impact = ["No negative impact; this is a legitimate dependency."]
        suggested_fix = "Keep as is; already allowed."
        confidence = 1.0
        fix_time = "0 minutes"
        risk = "Low"
        category = "Architecture (Intentional)"

    else:
        # Generic analysis
        if sr < tr:
            root_cause = (
                f"Layer '{source_layer}' (rank {sr}) is more foundational than "
                f"'{target_layer}' (rank {tr}). Foundational layers must not depend "
                "on higher layers; this inverts the dependency direction."
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
            risk = "High"
            category = "Dependency Inversion"
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
            risk = "Medium"
            category = "Layer Isolation"

    return {
        "severity": severity,
        "category": category,
        "root_cause": root_cause,
        "evidence": evidence,
        "impact": impact,
        "suggested_fix": suggested_fix,
        "confidence": confidence,
        "fix_time_estimate": fix_time,
        "risk": risk,
    }

# ─────────────────────────────────────────────────────────────────────────────
# HELPER
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

    def identify_layer(self, module_name: str) -> str:
        if not module_name:
            return "unknown"
        module_name = module_name.replace("/", ".").replace("\\", ".")
        top = module_name.split(".")[0]
        if not top:
            return "unknown"
        if top in STDLIB_TOP_LEVEL:
            return "__external__"
        return LAYER_MAP.get(top, "unknown")

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

    def parse_module(
        self,
        file_path: pathlib.Path,
    ) -> tuple[Optional[ModuleReport], list[ImportEdge]]:
        try:
            source_code = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None, []

        try:
            tree = ast.parse(source_code, filename=str(file_path))
        except SyntaxError:
            return None, []

        try:
            relative_path = file_path.relative_to(self.root_dir)
        except ValueError:
            return None, []

        source_module = str(relative_path.with_suffix("")).replace(os.sep, ".")
        source_layer  = self.identify_layer(source_module)

        report = ModuleReport(
            module_path=source_module,
            file_path=str(relative_path),
            layer=source_layer,
        )

        edges: list[ImportEdge] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target_mod = alias.name
                    report.import_count += 1
                    self._process_import_target(
                        source_module, source_layer, target_mod,
                        node.lineno, "import", report, edges,
                        relative_path
                    )

            elif isinstance(node, ast.ImportFrom):
                level = node.level or 0
                is_wildcard = any(alias.name == "*" for alias in node.names)

                if level > 0:
                    target_mod = self.resolve_relative_import(
                        source_module, level, node.module
                    )
                else:
                    target_mod = node.module

                if target_mod:
                    report.import_count += 1
                    import_type = "wildcard" if is_wildcard else "from_import"
                    self._process_import_target(
                        source_module, source_layer, target_mod,
                        node.lineno, import_type, report, edges,
                        relative_path
                    )

                    if is_wildcard and not is_stdlib_or_thirdparty(target_mod):
                        target_layer = self.identify_layer(target_mod)
                        if target_layer not in ("__external__", "unknown", source_layer):
                            report.wildcards.append(WildcardViolation(
                                module_path=source_module,
                                file_path=str(relative_path),
                                line=node.lineno,
                                message=(
                                    f"WILDCARD IMPORT: 'from {target_mod} import *' "
                                    f"dari layer '{source_layer}' ke layer '{target_layer}'"
                                )
                            ))

        return report, edges

    def _process_import_target(
        self,
        source_module:  str,
        source_layer:   str,
        target_mod:     str,
        line_no:        int,
        import_type:    str,
        report:         ModuleReport,
        edges:          list[ImportEdge],
        relative_path:  pathlib.Path,
    ) -> None:
        if not target_mod:
            return

        target_layer = self.identify_layer(target_mod)

        if target_layer == "__external__":
            return

        edge = ImportEdge(
            source_module=source_module,
            source_layer=source_layer,
            target_module=target_mod,
            target_layer=target_layer,
            line=line_no,
            file_path=str(relative_path),
            import_type=import_type,
        )
        edges.append(edge)

        if source_layer in SKIP_LAYERS:
            return
        if target_layer in ("unknown", "__external__"):
            return
        if source_module == target_mod:
            return
        if source_layer == target_layer:
            return

        if (source_layer, target_layer) not in ALLOWED_PAIRS:
            src_rank = LAYER_RANK.get(source_layer, 99)
            tgt_rank = LAYER_RANK.get(target_layer, 99)

            if src_rank < tgt_rank:
                severity = "CRITICAL"
            else:
                severity = "ERROR"

            drift_msg = (
                f"LAYER DRIFT: '{source_layer}' (rank {src_rank}) "
                f"→ '{target_layer}' (rank {tgt_rank}) "
                f"[{import_type}] Modul: {target_mod}"
            )
            report.violations.append(ViolationInfo(
                line=line_no,
                import_type=import_type,
                target_module=target_mod,
                target_layer=target_layer,
                message=drift_msg,
                severity=severity,
                source_layer=source_layer,
                source_module=source_module,
            ))

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

    def tarjan_scc_iterative(
        self, graph: dict[str, set[str]]
    ) -> list[list[str]]:
        index_counter = [0]
        indices:  dict[str, int]  = {}
        lowlinks: dict[str, int]  = {}
        on_stack: set[str]        = set()
        stack:    list[str]       = []
        sccs:     list[list[str]] = []

        all_nodes = list(graph.keys())
        for node in list(graph.keys()):
            for neighbor in graph[node]:
                if neighbor not in graph:
                    all_nodes.append(neighbor)
        all_nodes = list(dict.fromkeys(all_nodes))

        def _strongconnect(start: str) -> None:
            iter_stack: list[tuple[str, list[str], int]] = []

            if start in indices:
                return

            indices[start]  = index_counter[0]
            lowlinks[start] = index_counter[0]
            index_counter[0] += 1
            stack.append(start)
            on_stack.add(start)

            neighbors = list(graph.get(start, set()))
            iter_stack.append((start, neighbors, 0))

            while iter_stack:
                v, nbrs, ni = iter_stack[-1]

                if ni < len(nbrs):
                    iter_stack[-1] = (v, nbrs, ni + 1)
                    w = nbrs[ni]

                    if w not in indices:
                        indices[w]  = index_counter[0]
                        lowlinks[w] = index_counter[0]
                        index_counter[0] += 1
                        stack.append(w)
                        on_stack.add(w)
                        w_neighbors = list(graph.get(w, set()))
                        iter_stack.append((w, w_neighbors, 0))
                    elif w in on_stack:
                        lowlinks[v] = min(lowlinks[v], indices[w])
                else:
                    iter_stack.pop()

                    if iter_stack:
                        parent, _, _ = iter_stack[-1]
                        lowlinks[parent] = min(lowlinks[parent], lowlinks[v])

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
                _strongconnect(node)

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
                name_to_paths[f.stem].append(str(rel))
            except ValueError:
                pass

        duplicates: list[DuplicateModuleInfo] = []
        for name, paths in name_to_paths.items():
            if len(paths) > 1:
                layers = {
                    self.identify_layer(str(pathlib.Path(p).with_suffix("")).replace(os.sep, "."))
                    for p in paths
                }
                if len(layers) > 1:
                    duplicates.append(DuplicateModuleInfo(
                        module_name=name,
                        occurrences=sorted(paths),
                        message=(
                            f"DUPLICATE MODULE '{name}' di {len(paths)} lokasi "
                            f"berbeda ({', '.join(sorted(layers))}) — "
                            f"risiko import shadowing (INFO)"
                        ),
                        severity="INFO"
                    ))

        return sorted(duplicates, key=lambda d: d.module_name)

# ─────────────────────────────────────────────────────────────────────────────
# SCORING ENGINE — DIPERBAIKI
# ─────────────────────────────────────────────────────────────────────────────
def compute_score(
    report: MasterReport,
    strict_mode: bool,
) -> tuple[int, dict[str, int], str]:
    """
    Skor integritas arsitektur — penalti hanya untuk ancaman nyata.
    Duplikat & intra-layer cycle TIDAK dipenalti.
    """
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
    # Intra-layer cycle: hanya dipenalti jika strict mode
    intra_penalty    = len(report.intra_layer_cycles) * 1 if strict_mode else 0
    wildcard_penalty = report.total_wildcard_violations * 1
    init_penalty     = len(report.missing_init_files) * 1
    # Duplicate module: 0 penalti (sekarang hanya INFO)
    dup_penalty      = 0

    breakdown["critical_drift"]    = -critical_penalty
    breakdown["error_drift"]       = -error_penalty
    breakdown["inter_layer_cycle"] = -inter_penalty
    breakdown["intra_layer_cycle"] = -intra_penalty  # 0 jika strict mode off
    breakdown["wildcard_import"]   = -wildcard_penalty
    breakdown["missing_init"]      = -init_penalty
    breakdown["duplicate_module"]  = 0  # tidak ada penalti

    score -= (critical_penalty + error_penalty + inter_penalty +
              intra_penalty + wildcard_penalty + init_penalty + dup_penalty)
    score = max(0, score)

    if score == 100:
        verdict = "SEMPURNA — Nol pelanggaran terdeteksi. Siap audit Big4."
    elif score >= 90:
        verdict = "SANGAT BAIK — Pelanggaran minor. Segera perbaiki."
    elif score >= 75:
        verdict = "BAIK — Beberapa pelanggaran signifikan. Perlu perbaikan segera."
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
        description=(
            f"{TOOL_NAME} v{TOOL_VERSION} — "
            "Validator Arsitektur Tingkat Auditor untuk ERP Accounting Engine"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh penggunaan:
  python architecture_drift_checker.py --verbose --rca
  python architecture_drift_checker.py --json laporan.json
  python architecture_drift_checker.py --strict --verbose
        """
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE")
    parser.add_argument("--sarif", metavar="FILE")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--hide-intra-cycles", action="store_true")
    parser.add_argument("--show-clean", action="store_true")
    parser.add_argument("--show-wildcards", action="store_true")
    parser.add_argument("--rca", action="store_true")
    parser.add_argument(
        "--exclude",
        default=".venv,venv,__pycache__,node_modules,dist,build,migrations,deployment,docs",
    )
    parser.add_argument("--layer-report", action="store_true")
    args = parser.parse_args()

    start_time = time.monotonic()
    root_dir   = pathlib.Path.cwd()
    verifier   = SovereignArchitectureVerifier(root_dir, strict_mode=args.strict)
    git_commit = get_git_commit(root_dir)
    scan_ts    = datetime.now(timezone.utc).isoformat()

    print(c("BOLD", c("CYAN",
        "╔══════════════════════════════════════════════════════════════════════════╗\n"
        "║   SOVEREIGN ERP — ARCHITECTURE DRIFT & BOUNDARY VALIDATOR  v4.1.0      ║\n"
        "║   Audit-Grade · Big4-Ready · Smart Scoring + RCA                       ║\n"
        "╚══════════════════════════════════════════════════════════════════════════╝"
    )))
    print(c("DIM", f"  Direktori : {root_dir}"))
    print(c("DIM", f"  Git Commit : {git_commit}"))
    print(c("DIM", f"  Timestamp  : {scan_ts}"))
    print(c("DIM", f"  Python     : {sys.version.split()[0]}"))
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

    for file_path in py_files:
        report, edges = verifier.parse_module(file_path)

        if report is None:
            skipped_count += 1
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

    master.total_files_skipped = skipped_count

    graph      = verifier.build_import_graph(all_edges)
    raw_cycles = verifier.tarjan_scc_iterative(graph)
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
    print(f"  File Dilewati (error)     : {master.total_files_skipped}")
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

    # ── DETAIL PELANGGARAN ────────────────────────────────────────────────────
    if master.total_drift_violations > 0 and (args.verbose or True):
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
                if args.rca or args.verbose:
                    rca = generate_violation_rca(
                        source_layer=v.source_layer or rep.layer,
                        target_layer=v.target_layer,
                        source_module=mod_name,
                        target_module=v.target_module,
                        import_type=v.import_type,
                        severity=v.severity,
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
                    confidence_pct = int(rca['confidence'] * 100)
                    print(f"          {c('DIM', f'Confidence: {confidence_pct}%')}")

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
        for idx, chain in enumerate(inter_cycles, 1):
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
    else:
        print(c("GREEN", "  ✅ Tidak ada siklus antar layer terdeteksi."))
    print("─" * 76)

    if intra_cycles and not args.hide_intra_cycles:
        print()
        print(f"  🔗 Siklus Intra-Layer [INFO] — {len(intra_cycles)} ditemukan")
        for idx, chain in enumerate(intra_cycles[:20], 1):
            layer = verifier.identify_layer(chain[0])
            preview = chain[:4]
            suffix  = f" (+{len(chain)-4})" if len(chain) > 4 else ""
            print(f"     {idx:3d}. [{layer}] {' ➔ '.join(preview)}{suffix}")
        if len(intra_cycles) > 20:
            print(f"         ... dan {len(intra_cycles)-20} siklus intra-layer lainnya")
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

    # ── DUPLICATE MODULES (INFO) ─────────────────────────────────────────────
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
    if args.verbose and args.show_clean:
        print()
        print("─" * 76)
        print(c("BOLD", c("GREEN", "  MODUL BERSIH (TANPA PELANGGARAN)")))
        print("─" * 76)
        for mod_name in sorted(master.modules.keys()):
            rep = master.modules[mod_name]
            if not rep.violations:
                print(f"  ✅ {mod_name} [{rep.layer}]")

    # ── FOOTER ────────────────────────────────────────────────────────────────
    print()
    print("─" * 76)
    print(f"  ⏱️  Waktu Eksekusi  : {elapsed:.3f} detik")
    print(f"  📁 Total Edge Import: {len(all_edges)} (dedup: {len(graph)} node)")
    print(f"  🔍 Coverage         : {master.total_files_scanned} dari {len(py_files)} file")
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
            },
            "summary": {
                "score": master.score,
                "verdict": master.verdict,
                "score_breakdown": master.score_breakdown,
                "total_files_found": master.total_files_found,
                "total_files_scanned": master.total_files_scanned,
                "total_files_skipped": master.total_files_skipped,
                "total_files_excluded": master.total_files_excluded,
                "clean_modules": master.clean_modules_count,
                "violated_modules": master.violated_modules_count,
                "total_drift_violations": master.total_drift_violations,
                "total_wildcard_violations": master.total_wildcard_violations,
                "inter_layer_cycles": len(master.inter_layer_cycles),
                "intra_layer_cycles": len(master.intra_layer_cycles),
                "missing_init_files": len(master.missing_init_files),
                "duplicate_modules": len(master.duplicate_modules),
            },
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
                            "rca": generate_violation_rca(
                                source_layer=v.source_layer or rep.layer,
                                target_layer=v.target_layer,
                                source_module=mod,
                                target_module=v.target_module,
                                import_type=v.import_type,
                                severity=v.severity,
                            ),
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

        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        print(c("GREEN", f"  ✅ Laporan JSON diekspor ke: {args.json}"))

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

        with open(args.sarif, "w", encoding="utf-8") as fh:
            json.dump(sarif_payload, fh, indent=2, ensure_ascii=False)
        print(c("GREEN", f"  ✅ SARIF report diekspor ke: {args.sarif}"))

    # ── EXIT CODE ─────────────────────────────────────────────────────────────
    has_drift_errors  = master.total_drift_violations > 0 or len(inter_cycles) > 0
    has_strict_errors = args.strict and len(intra_cycles) > 0

    if has_drift_errors:
        sys.exit(1)
    elif has_strict_errors:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()