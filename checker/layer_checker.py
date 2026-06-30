#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
layer_checker.py — Layer Dependency Validator for Hexagonal/DDD Architecture
=============================================================================
Versi   : 2.0.0
Standar : Big 4 Forensic Audit · ISO/IEC 25010 · SOX/ISA 315 Compliant
Penulis : Senior Engineering Team

Fitur:
  - Dependency matrix (allow-list) untuk DDD/Hexagonal architecture
  - Integrasi penuh dengan rca.py v3.0.0 untuk RCA diagnosis per-violation
  - Iterative DFS cycle detection (tidak rekursif — aman untuk graph besar)
  - Parallel file scanning via ThreadPoolExecutor
  - Configurable project root via --root CLI argument
  - Self-test embedded
  - SOX-compliant JSON export dengan RCA context

Perbaikan dari v1.0:
  FIX-LC-01  NameError `c` di save_json() → ganti dengan COLOR
  FIX-LC-02  RecursionError di find_cycles() → iterative DFS dengan stack
  FIX-LC-03  PROJECT_ROOT hardcoded → configurable via --root + validasi
  FIX-LC-04  MemoryError/PermissionError/OSError tidak ditangkap → ditambah
  FIX-LC-05  Duplikat cycle di find_cycles() → normalisasi + set dedup
  FIX-LC-06  get_layer_from_module() variable `top` tidak dipakai → pakai top
  FIX-LC-07  resolve_relative_import() base_parts kosong → guard ditambah
  FIX-LC-08  Exclusion list hardcoded → pakai Path(__file__).name
  FIX-LC-09  ALLOWED_PAIRS duplikat → dibersihkan
  FIX-LC-10  STD_LIB_MODULES tidak lengkap Python < 3.10 → fallback list lengkap
  FIX-LC-11  dateutil (third-party) di FRIEND_PACKAGES stdlib → dipindah
  FIX-LC-12  Single-threaded scan → ThreadPoolExecutor parallel
  FIX-LC-14  print_report() tidak bisa di-test → return ReportLines
  FIX-LC-15  save_json() tanpa IOError handling → try/except ditambah
  FIX-LC-16  Tidak ada integrasi rca.py → RCAViolationAnalyzer + ViolationRule
  FIX-LC-17  ast.walk() tidak membedakan top-level vs nested import → ditandai
  FIX-LC-19  verbose parameter tidak digunakan → diimplementasikan
  FIX-LC-20  rca.py tidak di-exclude → _SELF_EXCLUDE set dinamis
"""

from __future__ import annotations

# ── Standard library ──────────────────────────────────────────────────────────
import argparse
import ast
import concurrent.futures
import json
import logging
import os
import pathlib
import sys
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import (
    Any, Dict, FrozenSet, Iterator, List, Optional,
    Set, Tuple, Union,
)

# ── Public API ────────────────────────────────────────────────────────────────
__all__ = [
    "LayerChecker", "LayerStats", "Violation", "ImportRecord",
    "ViolationSeverity", "LAYER_MAP", "ALLOWED_PAIRS", "SKIP_LAYERS",
    "scan_project", "main",
]

# ── Logging ───────────────────────────────────────────────────────────────────
_logger = logging.getLogger(__name__)
if not _logger.handlers:
    _logger.addHandler(logging.NullHandler())

# ── Version ───────────────────────────────────────────────────────────────────
__version__ = "2.0.0"

# ── Color (soft dependency) ───────────────────────────────────────────────────
COLOR: Dict[str, str] = {
    "RED": "", "GREEN": "", "YELLOW": "", "CYAN": "", "BOLD": "", "RESET": "",
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
        "RESET" : colorama.Style.RESET_ALL,
    })
except ImportError:
    pass  # Berjalan tanpa warna — aman di CI/CD

# ── RCA integration (soft dependency) ─────────────────────────────────────────
# FIX-LC-16: Integrasi rca.py sebagai soft dependency
try:
    # Import dari file rca.py yang sudah di-fix (v3.0.0)
    # Cari di direktori yang sama dengan script ini
    _rca_path = pathlib.Path(__file__).resolve().parent / "rca.py"
    if _rca_path.exists():
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location("rca", _rca_path)
        if _spec and _spec.loader:
            _rca_mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_rca_mod)  # type: ignore[union-attr]
            RCAEngine     = _rca_mod.RCAEngine
            RCAResult     = _rca_mod.RCAResult
            Severity      = _rca_mod.Severity
            Category      = _rca_mod.Category
            ErrorCode     = _rca_mod.ErrorCode
            RCARule       = _rca_mod.RCARule
            HAS_RCA       = True
        else:
            HAS_RCA = False
    else:
        # Coba import langsung (jika rca sudah di sys.path)
        from rca import (  # type: ignore[import]
            RCAEngine, RCAResult, Severity, Category, ErrorCode, RCARule,
        )
        HAS_RCA = True
except (ImportError, Exception):
    HAS_RCA = False
    # Stub classes untuk type hints saat rca tidak tersedia
    RCAEngine   = None  # type: ignore[assignment,misc]
    RCAResult   = None  # type: ignore[assignment,misc]
    Severity    = None  # type: ignore[assignment,misc]
    Category    = None  # type: ignore[assignment,misc]
    ErrorCode   = None  # type: ignore[assignment,misc]
    RCARule     = None  # type: ignore[assignment,misc]

# ─────────────────────────────────────────────────────────────────────────────
# ── Constants & Configuration ─────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

# Mapping folder/package → layer name
LAYER_MAP: Dict[str, str] = {
    # Core DDD layers
    "domain"        : "domain",
    "axioms"        : "axioms",
    "constitution"  : "constitution",
    "kernel"        : "kernel",
    "ports"         : "ports",
    "application"   : "application",
    "adapters"      : "adapters",
    "infrastructure": "infrastructure",
    "bootstrap"     : "bootstrap",
    # Specialized ERP layers
    "config"        : "config",
    "app"           : "app",
    "policy_engine" : "policy_engine",
    "compliance"    : "compliance",
    "audit"         : "audit",
    "projections"   : "projections",
    "reports"       : "reports",
    "event_gateway" : "event_gateway",
    # Support & tooling (always skipped in violation check)
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

# Dependency Allow-list (matrix).
# FIX-LC-09: Duplikat dihapus, representasi bersih.
ALLOWED_PAIRS: FrozenSet[Tuple[str, str]] = frozenset({
    # ── Domain ────────────────────────────────────────────────────────────────
    ("domain", "domain"),
    ("domain", "axioms"),
    ("domain", "constitution"),
    # ── Axioms ────────────────────────────────────────────────────────────────
    ("axioms", "axioms"),
    ("axioms", "constitution"),
    # ── Constitution ──────────────────────────────────────────────────────────
    ("constitution", "constitution"),
    ("constitution", "domain"),
    ("constitution", "axioms"),
    # ── Kernel ────────────────────────────────────────────────────────────────
    ("kernel", "kernel"),
    ("kernel", "domain"),
    ("kernel", "axioms"),
    ("kernel", "constitution"),
    ("kernel", "ports"),
    ("kernel", "config"),
    # ── Ports ─────────────────────────────────────────────────────────────────
    ("ports", "ports"),
    ("ports", "domain"),
    # ── Application ───────────────────────────────────────────────────────────
    ("application", "application"),
    ("application", "domain"),
    ("application", "kernel"),
    ("application", "ports"),
    ("application", "axioms"),
    ("application", "constitution"),
    ("application", "config"),
    ("application", "policy_engine"),
    ("application", "audit"),
    # ── Adapters ──────────────────────────────────────────────────────────────
    ("adapters", "adapters"),
    ("adapters", "application"),
    ("adapters", "domain"),
    ("adapters", "kernel"),
    ("adapters", "ports"),
    ("adapters", "infrastructure"),
    ("adapters", "config"),
    # ── Projections ───────────────────────────────────────────────────────────
    ("projections", "projections"),
    ("projections", "domain"),
    ("projections", "application"),
    ("projections", "infrastructure"),
    ("projections", "config"),
    # ── Reports ───────────────────────────────────────────────────────────────
    ("reports", "reports"),
    ("reports", "projections"),
    ("reports", "application"),
    ("reports", "infrastructure"),
    ("reports", "config"),
    # ── Event Gateway ─────────────────────────────────────────────────────────
    ("event_gateway", "event_gateway"),
    ("event_gateway", "domain"),
    ("event_gateway", "application"),
    ("event_gateway", "infrastructure"),
    # ── Infrastructure ────────────────────────────────────────────────────────
    ("infrastructure", "infrastructure"),
    ("infrastructure", "domain"),
    ("infrastructure", "ports"),
    ("infrastructure", "kernel"),
    ("infrastructure", "config"),
    # ── Bootstrap ─────────────────────────────────────────────────────────────
    ("bootstrap", "bootstrap"),
    ("bootstrap", "config"),
    ("bootstrap", "infrastructure"),
    ("bootstrap", "application"),
    ("bootstrap", "adapters"),
    # ── App ───────────────────────────────────────────────────────────────────
    ("app", "app"),
    ("app", "bootstrap"),
    ("app", "adapters"),
    ("app", "infrastructure"),
    # ── Policy Engine ─────────────────────────────────────────────────────────
    ("policy_engine", "policy_engine"),
    ("policy_engine", "domain"),
    ("policy_engine", "kernel"),
    ("policy_engine", "config"),
    ("policy_engine", "compliance"),
    # ── Compliance ────────────────────────────────────────────────────────────
    ("compliance", "compliance"),
    ("compliance", "policy_engine"),
    ("compliance", "domain"),
    ("compliance", "application"),
    # ── Audit ─────────────────────────────────────────────────────────────────
    ("audit", "audit"),
    ("audit", "domain"),
    ("audit", "application"),
    ("audit", "kernel"),
    # ── Support layers (same-layer only) ──────────────────────────────────────
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
})

# Layers yang tidak diperiksa (skip violation check)
SKIP_LAYERS: FrozenSet[str] = frozenset({
    "unknown", "checker", "scripts", "tools", "migrations", "deployment",
    "docs", "monitoring", "config_files", "logs", "tests", "test",
    "utils", "common", "shared", "lib", "vendor", "external",
})

# ── Standard library module names ─────────────────────────────────────────────
# FIX-LC-10: Fallback lengkap untuk Python < 3.10
def _build_stdlib_set() -> Set[str]:
    """Bangun set stdlib module names yang komprehensif."""
    if hasattr(sys, "stdlib_module_names"):
        return set(sys.stdlib_module_names)  # Python 3.10+

    # Fallback manual — daftar komprehensif Python 3.8/3.9
    return {
        "__future__", "_thread", "abc", "aifc", "argparse", "array", "ast",
        "asynchat", "asyncio", "asyncore", "atexit", "audioop", "base64",
        "bdb", "binascii", "binhex", "bisect", "builtins", "bz2", "calendar",
        "cgi", "cgitb", "chunk", "cmath", "cmd", "code", "codecs", "codeop",
        "colorsys", "compileall", "concurrent", "configparser", "contextlib",
        "contextvars", "copy", "copyreg", "cProfile", "csv", "ctypes", "curses",
        "dataclasses", "datetime", "dbm", "decimal", "difflib", "dis",
        "distutils", "doctest", "email", "encodings", "enum", "errno",
        "faulthandler", "fcntl", "filecmp", "fileinput", "fnmatch",
        "fractions", "ftplib", "functools", "gc", "getopt", "getpass",
        "gettext", "glob", "grp", "gzip", "hashlib", "heapq", "hmac",
        "html", "http", "idlelib", "imaplib", "imghdr", "imp",
        "importlib", "inspect", "io", "ipaddress", "itertools", "json",
        "keyword", "lib2to3", "linecache", "locale", "logging", "lzma",
        "mailbox", "marshal", "math", "mimetypes", "mmap", "modulefinder",
        "multiprocessing", "netrc", "nis", "nntplib", "numbers", "operator",
        "optparse", "os", "ossaudiodev", "parser", "pathlib", "pdb",
        "pickle", "pickletools", "pipes", "pkgutil", "platform", "plistlib",
        "poplib", "posix", "posixpath", "pprint", "profile", "pstats",
        "pty", "pwd", "py_compile", "pyclbr", "pydoc", "queue", "quopri",
        "random", "re", "readline", "reprlib", "resource", "rlcompleter",
        "runpy", "sched", "secrets", "select", "selectors", "shelve",
        "shlex", "shutil", "signal", "site", "smtpd", "smtplib", "sndhdr",
        "socket", "socketserver", "spwd", "sqlite3", "sre_compile",
        "sre_constants", "sre_parse", "ssl", "stat", "statistics",
        "string", "stringprep", "struct", "subprocess", "sunau",
        "symtable", "sys", "sysconfig", "syslog", "tabnanny", "tarfile",
        "telnetlib", "tempfile", "termios", "test", "textwrap", "threading",
        "time", "timeit", "tkinter", "token", "tokenize", "tomllib",
        "trace", "traceback", "tracemalloc", "tty", "turtle", "turtledemo",
        "types", "typing", "unicodedata", "unittest", "urllib", "uu",
        "uuid", "venv", "warnings", "wave", "weakref", "webbrowser",
        "winreg", "winsound", "wsgiref", "xdrlib", "xml", "xmlrpc",
        "zipapp", "zipfile", "zipimport", "zlib", "zoneinfo",
        # Common typing extensions
        "typing_extensions", "_collections_abc", "_weakrefset",
    }

STD_LIB_MODULES: Set[str] = _build_stdlib_set()

# ── Friend packages per layer ─────────────────────────────────────────────────
# FIX-LC-11: dateutil (third-party) dipindah dari stdlib friends ke own dict
FRIEND_PACKAGES: Dict[str, Set[str]] = {
    "domain"     : {"typing", "abc", "dataclasses", "enum", "uuid",
                    "decimal", "datetime", "zoneinfo"},
    "application": {"typing", "dataclasses", "enum", "uuid", "decimal", "datetime"},
    "kernel"     : {"typing", "dataclasses", "enum", "uuid", "decimal", "datetime"},
}

# Third-party packages yang selalu diizinkan (bukan stdlib, bukan layer)
ALWAYS_ALLOWED_THIRD_PARTY: Set[str] = {
    "dateutil", "pydantic", "sqlalchemy", "alembic", "celery",
    "redis", "kafka", "boto3", "requests", "httpx", "aiohttp",
    "fastapi", "starlette", "uvicorn", "gunicorn",
    "pytest", "hypothesis",  # hanya di test layers
}

# ── Violation severity mapping ────────────────────────────────────────────────
class ViolationSeverity:
    """Tingkat keparahan violation dependency layer."""
    FATAL    = "FATAL"     # Dependency langsung dari inner ke outer layer (misal domain→infra)
    CRITICAL = "CRITICAL"  # Cycle antara non-support layers
    HIGH     = "HIGH"      # Dependency yang tidak ada di matrix
    MEDIUM   = "MEDIUM"    # Warning / deprecation
    LOW      = "LOW"       # Info / suggestion

    @staticmethod
    def for_pair(src: str, tgt: str) -> str:
        """Tentukan severity berdasarkan pasangan layer."""
        # Domain tidak boleh sama sekali bergantung pada outer layers
        _inner_layers    = {"domain", "axioms", "constitution", "ports"}
        _outer_layers    = {"infrastructure", "adapters", "bootstrap", "app"}
        _business_layers = {"application", "kernel", "policy_engine", "compliance", "audit"}

        if src in _inner_layers and tgt in _outer_layers:
            return ViolationSeverity.FATAL
        if src in _inner_layers and tgt in _business_layers:
            return ViolationSeverity.CRITICAL
        return ViolationSeverity.HIGH


# ─────────────────────────────────────────────────────────────────────────────
# ── Data Structures ───────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ImportRecord:
    """Satu record import dari sebuah file Python."""
    source_file  : str
    source_layer : str
    target_module: str
    target_layer : str
    line         : int
    is_relative  : bool  = False
    is_toplevel  : bool  = True    # FIX-LC-17: tandai apakah top-level import

    def __repr__(self) -> str:
        return (
            f"<Import {self.source_layer} → {self.target_layer} "
            f"({self.target_module}) at {self.source_file}:{self.line}>"
        )


@dataclass
class Violation:
    """Satu violation dependency layer, diperkaya dengan RCA diagnosis."""
    source_file  : str
    source_layer : str
    target_module: str
    target_layer : str
    line         : int
    rule         : str
    message      : str
    severity     : str        = ViolationSeverity.HIGH
    is_toplevel  : bool       = True
    # RCA integration — diisi oleh RCAViolationAnalyzer
    rca_root_cause  : str     = ""
    rca_suggested_fix: str    = ""
    rca_confidence  : float   = 0.0
    rca_error_code  : str     = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_file"     : self.source_file,
            "source_layer"    : self.source_layer,
            "target_module"   : self.target_module,
            "target_layer"    : self.target_layer,
            "line"            : self.line,
            "rule"            : self.rule,
            "severity"        : self.severity,
            "is_toplevel"     : self.is_toplevel,
            "message"         : self.message,
            "rca_root_cause"  : self.rca_root_cause,
            "rca_suggested_fix": self.rca_suggested_fix,
            "rca_confidence"  : self.rca_confidence,
            "rca_error_code"  : self.rca_error_code,
        }


@dataclass
class LayerStats:
    """Statistik hasil scan satu project."""
    total_files    : int                    = 0
    total_imports  : int                    = 0
    skipped_files  : int                    = 0
    parse_errors   : List[str]              = field(default_factory=list)
    violations     : List[Violation]        = field(default_factory=list)
    layer_counts   : Dict[str, int]         = field(default_factory=dict)
    dependency_graph: Dict[str, Set[str]]   = field(default_factory=dict)
    cycles         : List[List[str]]        = field(default_factory=list)
    scan_time_s    : float                  = 0.0
    rca_enriched   : bool                   = False

    @property
    def violation_count(self) -> int:
        return len(self.violations)

    @property
    def cycle_count(self) -> int:
        return len(self.cycles)

    @property
    def is_clean(self) -> bool:
        return self.violation_count == 0 and self.cycle_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# ── RCA Integration ───────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class _LayerViolationException(Exception):
    """
    Exception sintetis yang merepresentasikan satu violation layer.
    Digunakan sebagai input ke RCAEngine untuk mendapatkan diagnosis.
    """
    def __init__(self, violation: "Violation") -> None:
        self.violation = violation
        super().__init__(
            f"Layer violation [{violation.severity}]: "
            f"{violation.source_layer} → {violation.target_layer} "
            f"({violation.target_module}) in {violation.source_file}:{violation.line}"
        )


class RCAViolationAnalyzer:
    """
    Enriches Violation objects dengan RCA diagnosis dari rca.py.
    FIX-LC-16: Implementasi integrasi penuh.
    """

    def __init__(self) -> None:
        self._engine: Any = None
        self._available = HAS_RCA
        if self._available:
            try:
                self._engine = RCAEngine()  # type: ignore[misc]
                _logger.info("RCA engine initialized for layer violation analysis")
            except Exception as exc:
                _logger.warning("RCA engine init failed: %s", exc)
                self._available = False

    @property
    def available(self) -> bool:
        return self._available and self._engine is not None

    def enrich(self, violation: Violation) -> Violation:
        """Enrich satu Violation dengan RCA diagnosis. Return violation yang sudah di-enrich."""
        if not self.available:
            violation.rca_root_cause   = self._static_root_cause(violation)
            violation.rca_suggested_fix= self._static_fix(violation)
            violation.rca_confidence   = 0.7
            violation.rca_error_code   = "RCA_NA"
            return violation

        try:
            exc = _LayerViolationException(violation)
            result = self._engine.analyze(exc, {
                "source_layer" : violation.source_layer,
                "target_layer" : violation.target_layer,
                "target_module": violation.target_module,
                "source_file"  : violation.source_file,
                "violation_rule": violation.rule,
                "severity"     : violation.severity,
            })
            if result:
                violation.rca_root_cause    = result.root_cause  or self._static_root_cause(violation)
                violation.rca_suggested_fix = result.suggested_fix or self._static_fix(violation)
                violation.rca_confidence    = result.confidence
                violation.rca_error_code    = (
                    result.error_code.value
                    if hasattr(result.error_code, "value")
                    else str(result.error_code)
                )
        except Exception as exc_inner:
            _logger.debug("RCA enrich failed for %s: %s", violation.source_file, exc_inner)
            violation.rca_root_cause    = self._static_root_cause(violation)
            violation.rca_suggested_fix = self._static_fix(violation)
            violation.rca_confidence    = 0.6

        return violation

    def enrich_batch(
        self,
        violations: List[Violation],
        max_workers: int = 4,
    ) -> List[Violation]:
        """Enrich batch violations secara parallel."""
        if not violations:
            return violations

        # Untuk batch kecil, sequential lebih efisien (overhead thread > gain)
        if len(violations) <= 10 or not self.available:
            return [self.enrich(v) for v in violations]

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            enriched = list(pool.map(self.enrich, violations))
        return enriched

    # ── Static fallback diagnosis ─────────────────────────────────────────────
    # Digunakan ketika rca.py tidak tersedia atau gagal

    _ROOT_CAUSE_MATRIX: Dict[Tuple[str, str], str] = {
        # Domain violations
        ("domain", "infrastructure"): (
            "Domain layer mengimport langsung dari Infrastructure — "
            "melanggar Dependency Inversion Principle (DIP). "
            "Domain seharusnya tidak tahu detail implementasi storage/network."
        ),
        ("domain", "application"): (
            "Domain layer mengimport dari Application layer — "
            "ini menciptakan dependency cycle dan melanggar Clean Architecture. "
            "Domain harus murni, tanpa ketergantungan pada orchestration layer."
        ),
        ("domain", "adapters"): (
            "Domain mengimport Adapter — pelanggaran keras Hexagonal Architecture. "
            "Adapters adalah 'outer ring' yang seharusnya bergantung ke domain, bukan sebaliknya."
        ),
        ("ports", "infrastructure"): (
            "Ports (interface definitions) mengimport Infrastructure (implementasi). "
            "Ports seharusnya hanya mendefinisikan kontrak — bukan implementasi."
        ),
        ("application", "infrastructure"): (
            "Application layer mengimport Infrastructure langsung — bypassing ports. "
            "Gunakan Dependency Injection dan inject implementasi melalui ports."
        ),
    }

    def _static_root_cause(self, v: Violation) -> str:
        key = (v.source_layer, v.target_layer)
        if key in self._ROOT_CAUSE_MATRIX:
            return self._ROOT_CAUSE_MATRIX[key]
        return (
            f"Layer '{v.source_layer}' mengimport dari layer '{v.target_layer}' "
            f"yang tidak diizinkan oleh dependency matrix. "
            f"Module: {v.target_module}"
        )

    _FIX_MATRIX: Dict[Tuple[str, str], str] = {
        ("domain", "infrastructure"): (
            "1. Definisikan port/interface di layer 'ports' atau 'domain'. "
            "2. Pindahkan implementasi ke 'infrastructure'. "
            "3. Inject dependency melalui constructor (DI) atau abstract base class."
        ),
        ("domain", "application"): (
            "1. Identifikasi apa yang diimport dari application. "
            "2. Jika itu data type → pindahkan ke domain. "
            "3. Jika itu use case logic → refactor menjadi domain service."
        ),
        ("domain", "adapters"): (
            "1. Definisikan abstract interface di domain/ports. "
            "2. Adapter implements interface tersebut. "
            "3. Domain hanya bergantung pada abstraksi, bukan adapter konkret."
        ),
        ("application", "infrastructure"): (
            "1. Buat port interface di layer 'ports'. "
            "2. Infrastructure implements port tersebut. "
            "3. Application inject port interface (bukan implementasi konkret)."
        ),
    }

    def _static_fix(self, v: Violation) -> str:
        key = (v.source_layer, v.target_layer)
        if key in self._FIX_MATRIX:
            return self._FIX_MATRIX[key]
        return (
            f"Periksa dependency matrix ALLOWED_PAIRS dan pertimbangkan: "
            f"1. Apakah import ini perlu? Jika tidak, hapus. "
            f"2. Jika perlu, definisikan port/interface di layer yang tepat. "
            f"3. Tambahkan ke ALLOWED_PAIRS hanya jika secara arsitektur justified."
        )


# ─────────────────────────────────────────────────────────────────────────────
# ── Utility Functions ─────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def get_layer_from_module(module: str) -> str:
    """
    Map nama module ke layer name.
    FIX-LC-06: Gunakan `top` variable secara langsung (O(1) lookup).
    """
    if not module:
        return "unknown"
    top = module.split(".")[0]
    return LAYER_MAP.get(top, "unknown")


def get_relative_path(path: pathlib.Path, root: pathlib.Path) -> str:
    """
    Konversi absolute path ke relative dari root.
    FIX-LC-03: root sekarang sebagai parameter, bukan global.
    """
    try:
        rel = path.relative_to(root)
        return str(rel).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def resolve_relative_import(
    source_module: str,
    level        : int,
    target       : Optional[str],
) -> str:
    """
    Resolve relative import (`from . import x`) ke absolute module path.
    FIX-LC-07: Guard untuk base_parts kosong.
    """
    if not source_module:
        return target or ""
    parts = source_module.split(".")
    if level > len(parts):
        return target or ""
    base_parts = parts[:-level] if level > 0 else parts
    # FIX-LC-07: jika slicing menghasilkan list kosong, kembalikan top-level
    if not base_parts:
        return target or (parts[0] if parts else "")
    if target:
        return ".".join(base_parts + [target])
    return ".".join(base_parts)


def is_stdlib_module(module: str) -> bool:
    """Cek apakah module adalah bagian dari Python standard library."""
    base = module.split(".")[0]
    return base in STD_LIB_MODULES


def is_friend_package(layer: str, module: str) -> bool:
    """Cek apakah module adalah 'friend package' yang selalu diizinkan untuk layer ini."""
    friends = FRIEND_PACKAGES.get(layer, set())
    for friend in friends:
        if module == friend or module.startswith(friend + "."):
            return True
    return False


def is_always_allowed(module: str) -> bool:
    """Cek apakah module ada di daftar third-party yang selalu diizinkan."""
    base = module.split(".")[0]
    return base in ALWAYS_ALLOWED_THIRD_PARTY


# ─────────────────────────────────────────────────────────────────────────────
# ── AST Parser ────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def _is_toplevel_import(node: ast.AST, tree: ast.AST) -> bool:
    """
    Cek apakah node import ada di top-level module (bukan di dalam fungsi/class).
    FIX-LC-17: Membedakan top-level import vs nested import.
    """
    # ast.walk tidak menyimpan parent, kita perlu cara lain
    # Gunakan pendekatan: periksa apakah parent adalah ast.Module
    for child in ast.walk(tree):
        if isinstance(child, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef, ast.If, ast.Try, ast.With)):
            for direct_child in ast.iter_child_nodes(child):
                if direct_child is node:
                    return isinstance(child, ast.Module)
    return True  # Default: anggap top-level jika tidak bisa ditentukan


def extract_imports_from_file(
    file_path : pathlib.Path,
    root      : pathlib.Path,
) -> Tuple[List[ImportRecord], Optional[str]]:
    """
    Parse satu file Python dan ekstrak semua import records.
    FIX-LC-04: Tangkap MemoryError, PermissionError, OSError.
    FIX-LC-17: Tandai is_toplevel.

    Returns:
        (list of ImportRecord, error_message_or_None)
    """
    try:
        src  = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError as exc:
        return [], f"SyntaxError di {file_path}: {exc}"
    except UnicodeDecodeError as exc:
        return [], f"UnicodeDecodeError di {file_path}: {exc}"
    except MemoryError:           # FIX-LC-04
        return [], f"MemoryError: file terlalu besar: {file_path}"
    except PermissionError as exc:# FIX-LC-04
        return [], f"PermissionError di {file_path}: {exc}"
    except OSError as exc:        # FIX-LC-04
        return [], f"OSError di {file_path}: {exc}"
    except Exception as exc:      # FIX-LC-04: safety net
        return [], f"Unexpected error di {file_path}: {exc}"

    rel_path      = get_relative_path(file_path, root)
    source_module = rel_path.replace("/", ".").rsplit(".", 1)[0]
    source_layer  = get_layer_from_module(source_module)

    records: List[ImportRecord] = []

    # Precompute top-level nodes untuk is_toplevel check (O(n) sekali)
    toplevel_nodes: Set[int] = set()
    if isinstance(tree, ast.Module):
        for child in ast.iter_child_nodes(tree):
            toplevel_nodes.add(id(child))

    for node in ast.walk(tree):
        is_toplevel = id(node) in toplevel_nodes

        if isinstance(node, ast.Import):
            for alias in node.names:
                target = alias.name
                records.append(ImportRecord(
                    source_file  = rel_path,
                    source_layer = source_layer,
                    target_module= target,
                    target_layer = get_layer_from_module(target),
                    line         = node.lineno,
                    is_relative  = False,
                    is_toplevel  = is_toplevel,
                ))

        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:  # absolute import
                target_mod = node.module
                if target_mod:
                    records.append(ImportRecord(
                        source_file  = rel_path,
                        source_layer = source_layer,
                        target_module= target_mod,
                        target_layer = get_layer_from_module(target_mod),
                        line         = node.lineno,
                        is_relative  = False,
                        is_toplevel  = is_toplevel,
                    ))
            else:  # relative import
                if node.module:
                    target_mod = resolve_relative_import(source_module, node.level, node.module)
                else:
                    target_mod = resolve_relative_import(source_module, node.level, None)
                if target_mod:
                    records.append(ImportRecord(
                        source_file  = rel_path,
                        source_layer = source_layer,
                        target_module= target_mod,
                        target_layer = get_layer_from_module(target_mod),
                        line         = node.lineno,
                        is_relative  = True,
                        is_toplevel  = is_toplevel,
                    ))

    return records, None


# ─────────────────────────────────────────────────────────────────────────────
# ── Cycle Detection (Iterative DFS) ──────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_cycle(cycle: List[str]) -> Tuple[str, ...]:
    """
    Normalisasi representasi cycle ke canonical form.
    Rotate ke elemen terkecil secara leksikografis untuk deduplication.
    FIX-LC-05: Mencegah cycle duplikat dengan representasi berbeda.
    """
    if not cycle:
        return ()
    # Hilangkan duplikat endpoint jika ada (A→B→A → [A,B,A] → kita normalize [A,B])
    c = cycle[:]
    if len(c) > 1 and c[0] == c[-1]:
        c = c[:-1]
    if not c:
        return ()
    min_idx = c.index(min(c))
    rotated = c[min_idx:] + c[:min_idx]
    return tuple(rotated)


def find_cycles(graph: Dict[str, Set[str]], max_cycles: int = 100) -> List[List[str]]:
    """
    Temukan semua cycle dalam directed graph menggunakan iterative DFS.
    FIX-LC-02: Iterative (tidak rekursif) — aman untuk graph dengan 1000+ nodes.
    FIX-LC-05: Deduplikasi cycle via normalisasi.

    Args:
        graph    : {node: set of neighbors}
        max_cycles: batas jumlah cycle yang dikumpulkan (cegah output bloat)

    Returns:
        List of cycles, setiap cycle adalah list of node names.
    """
    seen_cycles : Set[Tuple[str, ...]] = set()
    result      : List[List[str]]      = []

    for start_node in list(graph.keys()):
        if len(result) >= max_cycles:
            break

        # Iterative DFS menggunakan explicit stack
        # Stack item: (node, iterator_of_neighbors, current_path, path_set)
        stack      : List[Tuple[str, Iterator[str], List[str], Set[str]]] = []
        visited    : Set[str] = set()

        stack.append((
            start_node,
            iter(sorted(graph.get(start_node, set()))),
            [start_node],
            {start_node},
        ))
        visited.add(start_node)

        while stack and len(result) < max_cycles:
            node, neighbors_iter, path, path_set = stack[-1]
            try:
                neighbor = next(neighbors_iter)
                if neighbor in path_set:
                    # Cycle ditemukan
                    idx   = path.index(neighbor)
                    cycle = path[idx:]
                    norm  = _normalize_cycle(cycle)
                    if norm and norm not in seen_cycles and len(cycle) >= 2:
                        seen_cycles.add(norm)
                        # Representasi dengan closing node
                        result.append(list(cycle) + [cycle[0]])
                elif neighbor not in visited:
                    visited.add(neighbor)
                    new_path     = path + [neighbor]
                    new_path_set = path_set | {neighbor}
                    stack.append((
                        neighbor,
                        iter(sorted(graph.get(neighbor, set()))),
                        new_path,
                        new_path_set,
                    ))
            except StopIteration:
                stack.pop()

    return result


# ─────────────────────────────────────────────────────────────────────────────
# ── File Scanner ──────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class LayerChecker:
    """
    Main class untuk scanning dan validasi layer dependency.
    Thread-safe, configurable, integrated dengan RCA.
    """

    VERSION = "2.0.0"

    # FIX-LC-08: Exclusion set dinamis menggunakan Path(__file__).name
    _BASE_EXCLUDES: FrozenSet[str] = frozenset({
        "setup.py", "manage.py", "conftest.py",
        "main_checker.py", "main_checker_2.py", "main_checker_3.py",
    })

    _EXCLUDE_DIRS: FrozenSet[str] = frozenset({
        ".venv", "venv", "__pycache__", ".git",
        "node_modules", "dist", "build", ".mypy_cache",
        ".pytest_cache", ".ruff_cache", ".tox",
    })

    def __init__(
        self,
        root              : Optional[pathlib.Path] = None,
        max_workers       : int  = 8,
        enable_rca        : bool = True,
        max_cycles        : int  = 100,
        strict_toplevel   : bool = False,
    ) -> None:
        """
        Args:
            root           : Project root directory. Auto-detect jika None.
            max_workers    : Thread count untuk parallel file parsing.
            enable_rca     : Enrich violations dengan RCA engine.
            max_cycles     : Batas cycle yang dikumpulkan.
            strict_toplevel: Jika True, hanya periksa top-level imports.
        """
        self.root           = self._resolve_root(root)
        self.max_workers    = max_workers
        self.max_cycles     = max_cycles
        self.strict_toplevel= strict_toplevel
        self._rca_analyzer  = RCAViolationAnalyzer() if enable_rca else None
        self._exclude_names = self._BASE_EXCLUDES | {pathlib.Path(__file__).name}
        _logger.info(
            "LayerChecker v%s initialized: root=%s, rca=%s",
            self.VERSION, self.root,
            "enabled" if (self._rca_analyzer and self._rca_analyzer.available) else "disabled",
        )

    def _resolve_root(self, root: Optional[pathlib.Path]) -> pathlib.Path:
        """
        Resolve project root dengan validasi.
        FIX-LC-03: Tidak lagi hardcoded 2 level ke atas.
        """
        if root is not None:
            resolved = root.resolve()
            if not resolved.exists():
                raise ValueError(f"Project root tidak ada: {resolved}")
            if not resolved.is_dir():
                raise ValueError(f"Project root bukan direktori: {resolved}")
            return resolved

        # Auto-detect: cari dari posisi script ke atas hingga ada pyproject.toml / setup.py
        candidates = [
            pathlib.Path(__file__).resolve().parent,
            pathlib.Path(__file__).resolve().parent.parent,
            pathlib.Path.cwd(),
        ]
        for candidate in candidates:
            if (candidate / "pyproject.toml").exists() or \
               (candidate / "setup.py").exists() or \
               (candidate / "setup.cfg").exists():
                _logger.info("Auto-detected project root: %s", candidate)
                return candidate

        # Fallback ke parent.parent (backward-compatible)
        fallback = pathlib.Path(__file__).resolve().parent.parent
        _logger.warning(
            "Tidak bisa auto-detect project root, menggunakan fallback: %s", fallback
        )
        return fallback

    def _collect_files(self) -> List[pathlib.Path]:
        """Kumpulkan semua .py files yang perlu di-scan."""
        py_files: List[pathlib.Path] = []
        for path in self.root.rglob("*.py"):
            # Skip direktori tertentu
            if any(part in self._EXCLUDE_DIRS for part in path.parts):
                continue
            # Skip file tertentu
            if path.name in self._exclude_names:
                continue
            py_files.append(path)
        return py_files

    def _scan_files(
        self,
        py_files: List[pathlib.Path],
    ) -> Tuple[List[ImportRecord], List[str]]:
        """
        Parse semua files secara parallel.
        FIX-LC-12: ThreadPoolExecutor untuk performa.
        """
        all_records : List[ImportRecord] = []
        parse_errors: List[str]          = []
        lock = threading.Lock()

        def parse_one(path: pathlib.Path) -> None:
            records, error = extract_imports_from_file(path, self.root)
            with lock:
                all_records.extend(records)
                if error:
                    parse_errors.append(error)

        if len(py_files) <= 4:
            # Sequential untuk project kecil (overhead thread > gain)
            for path in py_files:
                parse_one(path)
        else:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.max_workers
            ) as pool:
                list(pool.map(parse_one, py_files))

        return all_records, parse_errors

    def _check_violations(
        self,
        all_imports: List[ImportRecord],
    ) -> List[Violation]:
        """Periksa setiap import terhadap dependency matrix."""
        violations: List[Violation] = []

        for imp in all_imports:
            src = imp.source_layer
            tgt = imp.target_layer

            # Skip layers yang tidak diperiksa
            if src in SKIP_LAYERS or tgt in SKIP_LAYERS:
                continue

            # Skip stdlib
            if is_stdlib_module(imp.target_module):
                continue

            # Skip friend packages
            if is_friend_package(src, imp.target_module):
                continue

            # Skip always-allowed third-party
            if is_always_allowed(imp.target_module):
                continue

            # FIX-LC-19 / strict mode: skip non-toplevel jika strict mode aktif
            if self.strict_toplevel and not imp.is_toplevel:
                continue

            # Periksa terhadap matrix
            if (src, tgt) not in ALLOWED_PAIRS:
                sev = ViolationSeverity.for_pair(src, tgt)
                violations.append(Violation(
                    source_file  = imp.source_file,
                    source_layer = src,
                    target_module= imp.target_module,
                    target_layer = tgt,
                    line         = imp.line,
                    rule         = "matrix",
                    severity     = sev,
                    is_toplevel  = imp.is_toplevel,
                    message      = (
                        f"[{sev}] Import dari '{src}' → '{tgt}' "
                        f"tidak diizinkan oleh dependency matrix. "
                        f"Module: {imp.target_module}"
                    ),
                ))

        return violations

    def scan(self) -> LayerStats:
        """
        Jalankan scan lengkap: collect → parse → validate → cycles → rca.
        Entry point utama.
        """
        t_start = time.monotonic()
        stats   = LayerStats()

        # 1. Kumpulkan files
        py_files = self._collect_files()
        stats.total_files = len(py_files)
        _logger.info("Scanning %d files dari %s", len(py_files), self.root)

        # 2. Parse parallel
        all_imports, parse_errors = self._scan_files(py_files)
        stats.total_imports = len(all_imports)
        stats.parse_errors  = parse_errors
        stats.skipped_files = len(parse_errors)

        if parse_errors:
            _logger.warning("%d files gagal di-parse", len(parse_errors))

        # 3. Layer counts
        layer_counter: Dict[str, int] = defaultdict(int)
        for imp in all_imports:
            layer_counter[imp.source_layer] += 1
        stats.layer_counts = dict(layer_counter)

        # 4. Build dependency graph untuk cycle detection
        graph: Dict[str, Set[str]] = defaultdict(set)
        for imp in all_imports:
            src = imp.source_layer
            tgt = imp.target_layer
            if src in SKIP_LAYERS or tgt in SKIP_LAYERS or src == tgt:
                continue
            graph[src].add(tgt)
        stats.dependency_graph = dict(graph)

        # 5. FIX-LC-02: Iterative cycle detection
        stats.cycles = find_cycles(dict(graph), max_cycles=self.max_cycles)

        # 6. Check violations
        violations = self._check_violations(all_imports)

        # 7. RCA enrichment
        if self._rca_analyzer:
            try:
                violations = self._rca_analyzer.enrich_batch(violations)
                stats.rca_enriched = True
            except Exception as exc:
                _logger.warning("RCA batch enrichment failed: %s", exc)

        stats.violations  = violations
        stats.scan_time_s = time.monotonic() - t_start

        _logger.info(
            "Scan selesai: %d violations, %d cycles, %.2fs",
            stats.violation_count, stats.cycle_count, stats.scan_time_s,
        )
        return stats


# ─────────────────────────────────────────────────────────────────────────────
# ── Report & Output ───────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def print_report(
    stats       : LayerStats,
    verbose     : bool = False,         # FIX-LC-19: diimplementasikan
    hide_unknown: bool = False,
    show_rca    : bool = True,
) -> List[str]:
    """
    Print laporan ke stdout.
    FIX-LC-14: Return lines untuk testability.
    """
    c      = COLOR
    lines  : List[str] = []

    def emit(line: str = "") -> None:
        print(line)
        lines.append(line)

    # ── Header ────────────────────────────────────────────────────────────────
    emit(f"\n{c['CYAN']}{'='*80}{c['RESET']}")
    emit(f"{c['CYAN']}LAYER DEPENDENCY VIOLATION REPORT — Matrix-based v{__version__}{c['RESET']}")
    emit(f"{c['CYAN']}{'='*80}{c['RESET']}")
    emit(f"  Waktu scan     : {stats.scan_time_s:.2f}s")
    emit(f"  Total files    : {stats.total_files}")
    emit(f"  Files gagal    : {stats.skipped_files}")
    emit(f"  Total imports  : {stats.total_imports}")
    emit(f"  Total violations: {stats.violation_count}")
    emit(f"  Circular deps  : {stats.cycle_count}")
    emit(f"  RCA enriched   : {'Ya' if stats.rca_enriched else 'Tidak (rca.py tidak tersedia)'}")

    # ── Layer counts ──────────────────────────────────────────────────────────
    if stats.layer_counts:
        emit("\n  Layer import counts:")
        for layer, count in sorted(stats.layer_counts.items()):
            if hide_unknown and layer == "unknown":
                continue
            flag = " ⚠️" if layer == "unknown" else ""
            emit(f"    {layer:<20}: {count:>5}{flag}")

    # ── Parse errors (verbose) ────────────────────────────────────────────────
    if verbose and stats.parse_errors:
        emit(f"\n{c['YELLOW']}⚠️  Files yang gagal di-parse:{c['RESET']}")
        for err in stats.parse_errors[:20]:
            emit(f"    {err}")
        if len(stats.parse_errors) > 20:
            emit(f"    ... dan {len(stats.parse_errors) - 20} lainnya")

    # ── Cycles ────────────────────────────────────────────────────────────────
    if stats.cycles:
        emit(f"\n{c['RED']}{c['BOLD']}⚠️  Circular dependencies terdeteksi ({stats.cycle_count}):{c['RESET']}")
        for i, cycle in enumerate(stats.cycles, 1):
            emit(f"  {i:>3}. {' → '.join(cycle)}")

    # ── Violations ────────────────────────────────────────────────────────────
    if stats.violations:
        # Group by severity dulu
        by_severity: Dict[str, List[Violation]] = defaultdict(list)
        for v in stats.violations:
            by_severity[v.severity].append(v)

        # Group by file
        by_file: Dict[str, List[Violation]] = defaultdict(list)
        for v in stats.violations:
            by_file[v.source_file].append(v)

        emit(f"\n{c['RED']}{c['BOLD']}❌ Violations ({stats.violation_count} total, {len(by_file)} files):{c['RESET']}")

        # Summary by severity
        for sev in [ViolationSeverity.FATAL, ViolationSeverity.CRITICAL,
                    ViolationSeverity.HIGH, ViolationSeverity.MEDIUM, ViolationSeverity.LOW]:
            count = len(by_severity.get(sev, []))
            if count:
                sev_color = c['RED'] if sev in (ViolationSeverity.FATAL, ViolationSeverity.CRITICAL) else c['YELLOW']
                emit(f"    {sev_color}{sev:<10}{c['RESET']}: {count}")

        emit()

        # Detail per file (sort by violation count desc)
        sorted_files = sorted(by_file.items(), key=lambda x: len(x[1]), reverse=True)
        for idx, (file_path, file_violations) in enumerate(sorted_files, 1):
            emit(f"{c['YELLOW']}[{idx:>3}] {file_path}{c['RESET']}  ({len(file_violations)} violations)")
            for v in sorted(file_violations, key=lambda x: x.line):
                sev_color = c['RED'] if v.severity in (
                    ViolationSeverity.FATAL, ViolationSeverity.CRITICAL
                ) else c['YELLOW']
                toplevel_tag = "" if v.is_toplevel else " [nested]"
                emit(
                    f"    {c['CYAN']}line {v.line:>4}{c['RESET']}  "
                    f"{sev_color}{v.severity:<10}{c['RESET']}  "
                    f"{v.source_layer} → {v.target_layer:<20}  "
                    f"{v.target_module}{toplevel_tag}"
                )
                # FIX-LC-19: verbose mode menampilkan detail RCA
                if verbose and show_rca and v.rca_root_cause:
                    emit(f"         {c['CYAN']}Root cause  :{c['RESET']} {v.rca_root_cause[:120]}")
                    emit(f"         {c['CYAN']}Suggested fix:{c['RESET']} {v.rca_suggested_fix[:120]}")
                    if v.rca_confidence > 0:
                        emit(f"         {c['CYAN']}Confidence  :{c['RESET']} {v.rca_confidence:.0%}")
            emit()

        # Summary by rule type
        rule_counts: Dict[str, int] = defaultdict(int)
        for v in stats.violations:
            rule_counts[v.rule] += 1
        emit(f"\n{c['CYAN']}Summary by rule:{c['RESET']}")
        for rule, count in sorted(rule_counts.items(), key=lambda x: x[1], reverse=True):
            emit(f"  {rule:<20}: {count}")

    else:
        emit(f"\n{c['GREEN']}{c['BOLD']}✅ Tidak ada layer violations!{c['RESET']}")

    emit(f"\n{c['CYAN']}{'─'*80}{c['RESET']}")
    return lines


def save_json(
    stats       : LayerStats,
    filepath    : str,
    hide_unknown: bool = False,
) -> bool:
    """
    Simpan laporan ke JSON file.
    FIX-LC-01: Ganti c['CYAN'] → COLOR['CYAN'].
    FIX-LC-15: Tangkap IOError/PermissionError.

    Returns: True jika berhasil, False jika gagal.
    """
    violations_data = [v.to_dict() for v in stats.violations]
    layer_counts    = {
        k: v for k, v in stats.layer_counts.items()
        if not (hide_unknown and k == "unknown")
    }
    data: Dict[str, Any] = {
        "meta": {
            "version"    : __version__,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "scan_time_s": stats.scan_time_s,
            "rca_enriched": stats.rca_enriched,
        },
        "summary": {
            "total_files"      : stats.total_files,
            "total_imports"    : stats.total_imports,
            "skipped_files"    : stats.skipped_files,
            "violations_count" : stats.violation_count,
            "cycles_count"     : stats.cycle_count,
            "is_clean"         : stats.is_clean,
        },
        "layer_counts": layer_counts,
        "cycles"      : stats.cycles,
        "violations"  : violations_data,
        "parse_errors": stats.parse_errors,
    }

    try:
        # Pastikan direktori ada
        output_dir = pathlib.Path(filepath).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # FIX-LC-01: pakai COLOR bukan c
        print(f"\n{COLOR['GREEN']}✅ JSON report disimpan ke: {filepath}{COLOR['RESET']}")
        return True

    except PermissionError as exc:
        print(f"\n{COLOR['RED']}❌ Permission denied saat menyimpan {filepath}: {exc}{COLOR['RESET']}")
        return False
    except OSError as exc:
        print(f"\n{COLOR['RED']}❌ Gagal menyimpan {filepath}: {exc}{COLOR['RESET']}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# ── Self-test ─────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def self_test(verbose: bool = True) -> bool:
    """
    Test komprehensif semua komponen layer_checker.
    Return True jika semua test lulus.
    """
    passed = failed = 0

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal passed, failed
        if cond:
            if verbose:
                print(f"  ✅ {name}")
            passed += 1
        else:
            if verbose:
                print(f"  ❌ {name}" + (f": {detail}" if detail else ""))
            failed += 1

    if verbose:
        print(f"\nRunning LayerChecker self-test (v{__version__})…\n")

    # ── get_layer_from_module ─────────────────────────────────────────────────
    check("get_layer_from_module: domain.entities.user → domain",
          get_layer_from_module("domain.entities.user") == "domain")
    check("get_layer_from_module: infrastructure.db → infrastructure",
          get_layer_from_module("infrastructure.db") == "infrastructure")
    check("get_layer_from_module: unknown_pkg → unknown",
          get_layer_from_module("unknown_pkg") == "unknown")
    check("get_layer_from_module: empty string → unknown",
          get_layer_from_module("") == "unknown")
    # FIX-LC-06: top variable dipakai
    check("get_layer_from_module: application (exact match) → application",
          get_layer_from_module("application") == "application")

    # ── resolve_relative_import ───────────────────────────────────────────────
    check("resolve_relative_import: level=1 normal",
          resolve_relative_import("domain.entities.user", 1, "value_objects")
          == "domain.entities.value_objects")
    check("resolve_relative_import: level=2",
          resolve_relative_import("domain.entities.user", 2, "core")
          == "domain.core")
    # FIX-LC-07: base_parts kosong
    check("resolve_relative_import: level=1 from root package",
          resolve_relative_import("domain", 1, "ports") in ("ports", "domain"))
    check("resolve_relative_import: no target",
          resolve_relative_import("domain.entities", 1, None) == "domain")
    check("resolve_relative_import: empty source",
          resolve_relative_import("", 1, "something") == "something")

    # ── is_stdlib_module ──────────────────────────────────────────────────────
    check("is_stdlib_module: os → True", is_stdlib_module("os"))
    check("is_stdlib_module: sys → True", is_stdlib_module("sys"))
    check("is_stdlib_module: typing → True", is_stdlib_module("typing"))
    check("is_stdlib_module: pathlib → True", is_stdlib_module("pathlib"))
    check("is_stdlib_module: requests → False", not is_stdlib_module("requests"))
    check("is_stdlib_module: sqlalchemy → False", not is_stdlib_module("sqlalchemy"))

    # ── is_friend_package ─────────────────────────────────────────────────────
    check("is_friend_package: domain + typing → True",
          is_friend_package("domain", "typing"))
    check("is_friend_package: domain + sqlalchemy → False",
          not is_friend_package("domain", "sqlalchemy"))

    # ── find_cycles (iterative) ───────────────────────────────────────────────
    # Cycle sederhana A→B→A
    g1: Dict[str, Set[str]] = {"A": {"B"}, "B": {"A"}}
    cycles1 = find_cycles(g1)
    check("find_cycles: A→B→A terdeteksi", len(cycles1) >= 1,
          str(cycles1))

    # Tidak ada cycle
    g2: Dict[str, Set[str]] = {"A": {"B"}, "B": {"C"}}
    cycles2 = find_cycles(g2)
    check("find_cycles: tidak ada cycle untuk A→B→C",
          len(cycles2) == 0, str(cycles2))

    # Cycle kompleks A→B→C→A
    g3: Dict[str, Set[str]] = {"A": {"B"}, "B": {"C"}, "C": {"A"}}
    cycles3 = find_cycles(g3)
    check("find_cycles: A→B→C→A terdeteksi", len(cycles3) >= 1, str(cycles3))

    # Deduplikasi — FIX-LC-05
    # Graph A→B→A — hanya boleh 1 cycle
    cycles_dedup = find_cycles({"A": {"B"}, "B": {"A"}})
    check("find_cycles: deduplication (A→B→A hanya 1 cycle)",
          len(cycles_dedup) == 1, f"got {len(cycles_dedup)}: {cycles_dedup}")

    # Deep graph — tidak boleh RecursionError (FIX-LC-02)
    deep_graph: Dict[str, Set[str]] = {}
    for i in range(500):
        deep_graph[f"node_{i}"] = {f"node_{i+1}"}
    deep_graph["node_499"] = {"node_0"}  # satu cycle di akhir
    try:
        deep_cycles = find_cycles(deep_graph, max_cycles=5)
        check("find_cycles: deep graph (500 nodes) tanpa RecursionError",
              True, f"found {len(deep_cycles)} cycles")
    except RecursionError:
        check("find_cycles: deep graph (500 nodes) tanpa RecursionError",
              False, "RecursionError!")

    # ── ViolationSeverity.for_pair ────────────────────────────────────────────
    check("ViolationSeverity: domain→infrastructure = FATAL",
          ViolationSeverity.for_pair("domain", "infrastructure")
          == ViolationSeverity.FATAL)
    check("ViolationSeverity: domain→application = CRITICAL",
          ViolationSeverity.for_pair("domain", "application")
          == ViolationSeverity.CRITICAL)
    check("ViolationSeverity: adapters→domain = HIGH",
          ViolationSeverity.for_pair("adapters", "domain")
          == ViolationSeverity.HIGH)

    # ── ALLOWED_PAIRS immutability ────────────────────────────────────────────
    check("ALLOWED_PAIRS adalah frozenset (immutable)",
          isinstance(ALLOWED_PAIRS, frozenset))
    check("ALLOWED_PAIRS berisi (domain, domain)",
          ("domain", "domain") in ALLOWED_PAIRS)
    check("ALLOWED_PAIRS TIDAK berisi (domain, infrastructure)",
          ("domain", "infrastructure") not in ALLOWED_PAIRS)

    # ── _normalize_cycle ──────────────────────────────────────────────────────
    check("_normalize_cycle: [B,A] → ('A','B')",
          _normalize_cycle(["B", "A"]) == ("A", "B"))
    check("_normalize_cycle: [A,B,A] → ('A','B') (closing node stripped)",
          _normalize_cycle(["A", "B", "A"]) == ("A", "B"))
    check("_normalize_cycle: empty → ()",
          _normalize_cycle([]) == ())

    # ── save_json (FIX-LC-01) ─────────────────────────────────────────────────
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as tf:
        tmppath = tf.name
    try:
        dummy_stats = LayerStats(total_files=1, total_imports=5)
        dummy_stats.violations.append(Violation(
            source_file="domain/x.py", source_layer="domain",
            target_module="infrastructure.db", target_layer="infrastructure",
            line=10, rule="matrix",
            message="test violation", severity=ViolationSeverity.FATAL,
        ))
        result = save_json(dummy_stats, tmppath)
        check("save_json: berhasil tanpa NameError (FIX-LC-01)", result)
        with open(tmppath, encoding="utf-8") as jf:
            loaded = json.load(jf)
        check("save_json: JSON valid dan parseable", "violations" in loaded)
        check("save_json: meta.version ada", loaded.get("meta", {}).get("version") == __version__)
    finally:
        try:
            os.unlink(tmppath)
        except OSError:
            pass

    # ── RCA Integration ───────────────────────────────────────────────────────
    analyzer = RCAViolationAnalyzer()
    v_test   = Violation(
        source_file="domain/entities/user.py", source_layer="domain",
        target_module="infrastructure.db.session", target_layer="infrastructure",
        line=5, rule="matrix",
        message="domain → infrastructure not allowed", severity=ViolationSeverity.FATAL,
    )
    enriched = analyzer.enrich(v_test)
    check("RCA enrich: root_cause terisi",
          bool(enriched.rca_root_cause))
    check("RCA enrich: suggested_fix terisi",
          bool(enriched.rca_suggested_fix))

    # ── print_report return type ──────────────────────────────────────────────
    dummy = LayerStats(total_files=3, total_imports=10)
    report_lines = print_report(dummy, verbose=False)
    check("print_report: mengembalikan list of strings",
          isinstance(report_lines, list) and len(report_lines) > 0)

    # ── LayerChecker instantiation ────────────────────────────────────────────
    try:
        checker = LayerChecker(root=pathlib.Path.cwd(), enable_rca=False)
        check("LayerChecker.__init__: berhasil dengan cwd sebagai root", True)
    except Exception as exc:
        check("LayerChecker.__init__: berhasil dengan cwd sebagai root",
              False, str(exc))

    try:
        LayerChecker(root=pathlib.Path("/nonexistent_xyz_abc_123"), enable_rca=False)
        check("LayerChecker.__init__: ValueError untuk root tidak ada", False,
              "seharusnya raise ValueError")
    except ValueError:
        check("LayerChecker.__init__: ValueError untuk root tidak ada", True)

    if verbose:
        print(f"\nSelf-test: {passed} passed, {failed} failed "
              f"({'✅ ALL PASS' if failed == 0 else '❌ SOME FAILED'})")

    return failed == 0


# ─────────────────────────────────────────────────────────────────────────────
# ── Module-level convenience function ────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def scan_project(
    root        : Optional[pathlib.Path] = None,
    max_workers : int  = 8,
    enable_rca  : bool = True,
) -> LayerStats:
    """Convenience function: buat LayerChecker dan scan."""
    checker = LayerChecker(root=root, max_workers=max_workers, enable_rca=enable_rca)
    return checker.scan()


# ─────────────────────────────────────────────────────────────────────────────
# ── CLI ───────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    """
    CLI entry point.
    FIX-LC-03: --root argument untuk override PROJECT_ROOT.
    """
    parser = argparse.ArgumentParser(
        description=(
            f"Layer Dependency Checker v{__version__} (Matrix-based, RCA-integrated)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh:
  python layer_checker.py
  python layer_checker.py --root /path/to/project --verbose
  python layer_checker.py --json report.json --hide-unknown
  python layer_checker.py --self-test
        """,
    )
    parser.add_argument(
        "--root", metavar="DIR",
        help="Project root directory (auto-detect jika tidak diberikan)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Tampilkan detail: parse errors, RCA diagnosis per violation",
    )
    parser.add_argument(
        "--json", metavar="FILE",
        help="Simpan laporan JSON ke file",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="Hanya tampilkan ringkasan",
    )
    parser.add_argument(
        "--hide-unknown", action="store_true",
        help="Sembunyikan layer 'unknown' dari output",
    )
    parser.add_argument(
        "--no-rca", action="store_true",
        help="Nonaktifkan RCA enrichment",
    )
    parser.add_argument(
        "--workers", type=int, default=8, metavar="N",
        help="Jumlah thread untuk parallel scan (default: 8)",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Hanya periksa top-level imports (skip imports dalam fungsi/class)",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Jalankan self-test dan exit",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"layer_checker v{__version__}",
    )

    args = parser.parse_args(argv)

    # Self-test mode
    if args.self_test:
        ok = self_test(verbose=True)
        return 0 if ok else 1

    # Resolve root
    root: Optional[pathlib.Path] = None
    if args.root:
        root = pathlib.Path(args.root)

    try:
        checker = LayerChecker(
            root        = root,
            max_workers = args.workers,
            enable_rca  = not args.no_rca,
            strict_toplevel = args.strict,
        )
    except ValueError as exc:
        print(f"{COLOR['RED']}❌ Error: {exc}{COLOR['RESET']}", file=sys.stderr)
        return 2

    stats = checker.scan()

    if not args.quiet:
        print_report(
            stats,
            verbose     = args.verbose,
            hide_unknown= args.hide_unknown,
            show_rca    = not args.no_rca,
        )

    if args.quiet:
        # Minimal output untuk CI/CD
        status = "PASS" if stats.is_clean else "FAIL"
        print(
            f"{status}: {stats.violation_count} violations, "
            f"{stats.cycle_count} cycles, "
            f"{stats.total_files} files, "
            f"{stats.scan_time_s:.2f}s"
        )

    if args.json:
        save_json(stats, args.json, hide_unknown=args.hide_unknown)

    return 0 if stats.is_clean else 1


if __name__ == "__main__":
    sys.exit(main())