#!/usr/bin/env python3
"""
rca.py — Root Cause Analysis Engine for ERP Accounting System
================================================================
Versi   : 5.0.0 (final, unified, Big‑4 ready)
Standar : ISO/IEC 25010 · SOX/ISA 315 · PCAOB AS 2405 · IFRS/PSAK
Penulis : Senior Forensic Audit Team
Lisensi : Internal Use Only

Fitur :
- 30+ rules (generik + project‑specific) tanpa duplikasi
- Thread‑safe, time‑bounded analysis, LRU caches
- Integrasi dengan networkx (opsional), jedi, libcst
- Self‑test & benchmark terintegrasi
"""

from __future__ import annotations

import ast
import concurrent.futures
import copy
import difflib
import functools
import json
import logging
import os
import re
import sys
import threading
import time
import traceback
from abc import ABC, abstractmethod
from collections import Counter, OrderedDict, deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import (
    Any,
)

# ── Soft dependencies ─────────────────────────────────────────────────────────
try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False
    nx = None

try:
    import jedi
    HAS_JEDI = True
except ImportError:
    HAS_JEDI = False

try:
    import libcst as cst
    HAS_LIBCST = True
except ImportError:
    HAS_LIBCST = False

try:
    from sqlalchemy.exc import SQLAlchemyError as _SQLAlchemyError
    HAS_SQLALCHEMY = True
except ImportError:
    _SQLAlchemyError = None
    HAS_SQLALCHEMY = False

# ── Public API ────────────────────────────────────────────────────────────────
__all__ = [
    "Category",
    "ErrorCode",
    "EvidenceItem",
    "RCAEngine",
    "RCAResult",
    "RCARule",
    "Severity",
    "analyze",
    "analyze_exception",
    "get_engine",
    "reset_engine",
]

# ── Logging ───────────────────────────────────────────────────────────────────
_logger = logging.getLogger(__name__)
if not _logger.handlers:
    _logger.addHandler(logging.NullHandler())

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_CONTEXT_LINES    = 5
MAX_OBJECT_SIZE      = 100_000
MAX_EVIDENCE_ITEMS   = 30
MAX_EVIDENCE_LENGTH  = 500
MAX_IMPACT_ITEMS     = 10
MAX_TRACEBACK_FRAMES = 50
MAX_CHILDREN         = 10
CACHE_SIZE           = 512
DEFAULT_CONFIDENCE   = 0.5
TIMEOUT_SECONDS      = 3.0
REPR_TIMEOUT_SECONDS = 0.5
FILE_READ_LIMIT      = 10 * 1024 * 1024  # 10 MB

_SENSITIVE_KEYS: frozenset[str] = frozenset({
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "credential", "credentials", "auth", "authorization", "private_key",
    "access_key", "secret_key", "db_password", "database_password",
    "encryption_key", "signing_key", "jwt", "bearer",
    "client_secret", "bearer_token", "refresh_token", "otp", "pin",
})

# ── ErrorCode ─────────────────────────────────────────────────────────────────
class ErrorCode(str, Enum):
    IMPORT_MODULE_NOT_FOUND  = "RCA001"
    IMPORT_CIRCULAR          = "RCA002"
    IMPORT_SUBMODULE_MISSING = "RCA003"
    ATTR_MISSING             = "RCA010"
    ATTR_NONE_ACCESS         = "RCA011"
    TYPE_ARG_COUNT           = "RCA020"
    TYPE_OPERAND             = "RCA021"
    TYPE_MISSING_REQUIRED    = "RCA022"
    TYPE_UNEXPECTED_KEYWORD  = "RCA023"
    TYPE_NOT_CALLABLE        = "RCA024"
    TYPE_NOT_ITERABLE        = "RCA025"
    REPOSITORY_MISMATCH      = "RCA030"
    EVENT_PUBLISH_FAIL       = "RCA031"
    CONTAINER_RESOLVE_FAIL   = "RCA032"
    AGGREGATE_ERROR          = "RCA033"
    UOW_ERROR                = "RCA034"
    TRANSACTION_INTEGRITY    = "RCA035"
    COMMAND_HANDLER_MISSING  = "RCA040"
    QUERY_HANDLER_MISSING    = "RCA041"
    DB_CONNECTION_FAIL       = "RCA050"
    REDIS_FAIL               = "RCA051"
    KAFKA_FAIL               = "RCA052"
    NAME_NOT_DEFINED         = "RCA060"
    KEY_NOT_FOUND            = "RCA061"
    INDEX_OUT_OF_RANGE       = "RCA062"
    VALUE_INVALID            = "RCA063"
    PERMISSION_DENIED        = "RCA064"
    FILE_NOT_FOUND           = "RCA065"
    RECURSION_LIMIT          = "RCA066"
    MEMORY_ERROR             = "RCA067"
    ERP_VALIDATION           = "RCA070"
    ERP_PERIOD_CLOSED        = "RCA071"
    ERP_ACCOUNT_INVALID      = "RCA072"
    ERP_BALANCE_MISMATCH     = "RCA073"
    UNKNOWN                  = "RCA999"

# ── Severity ──────────────────────────────────────────────────────────────────

@functools.total_ordering
class Severity(Enum):
    FATAL    = ("FATAL",    7)
    CRITICAL = ("CRITICAL", 6)
    HIGH     = ("HIGH",     5)
    MEDIUM   = ("MEDIUM",   4)
    LOW      = ("LOW",      3)
    INFO     = ("INFO",     2)
    HINT     = ("HINT",     1)

    def __new__(cls, label: str, order: int):
        obj = object.__new__(cls)
        obj._value_ = label
        obj._order  = order
        return obj

    def __lt__(self, other: Severity) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self._order < other._order

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self._order == other._order

    def __hash__(self) -> int:
        return hash(self._order)

    @property
    def order(self) -> int:
        return self._order

# ── Tambahkan ini ──
_SEVERITY_ORDER = {s: s.order for s in Severity}


# ── Category ──────────────────────────────────────────────────────────────────
class Category(Enum):
    IMPORT         = "Import"
    SYNTAX         = "Syntax"
    ATTRIBUTE      = "Attribute"
    TYPE           = "Type"
    DDD            = "DDD"
    CQRS           = "CQRS"
    DI             = "DI"
    DATABASE       = "Database"
    INFRASTRUCTURE = "Infrastructure"
    PERFORMANCE    = "Performance"
    SECURITY       = "Security"
    UNKNOWN        = "Unknown"

# ── EvidenceItem ──────────────────────────────────────────────────────────────
@dataclass
class EvidenceItem:
    text        : str
    source_rule : str       = "unknown"
    evidence_type: str      = "general"
    redacted    : bool      = False

    def to_str(self) -> str:
        prefix = "[REDACTED] " if self.redacted else ""
        return f"{prefix}{self.text}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "text"        : self.text,
            "source_rule" : self.source_rule,
            "type"        : self.evidence_type,
            "redacted"    : self.redacted,
        }

# ── RCAResult ─────────────────────────────────────────────────────────────────
@dataclass
class RCAResult:
    severity     : Severity
    category     : Category           = field(default=Category.UNKNOWN)
    error_code   : ErrorCode          = field(default=ErrorCode.UNKNOWN)
    root_cause   : str                = field(default="")
    evidence     : list[str]          = field(default_factory=list)
    impact       : list[str]          = field(default_factory=list)
    suggested_fix: str                = field(default="")
    raw_error    : str                = field(default="")
    confidence   : float              = field(default=0.0)
    parent       : RCAResult | None = field(default=None)
    children     : list[RCAResult]  = field(default_factory=list)
    metadata     : dict[str, Any]     = field(default_factory=dict)
    typed_evidence: list[EvidenceItem] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

    def to_dict(self, _visited: set[int] | None = None, _depth: int = 0) -> dict[str, Any]:
        if _visited is None:
            _visited = set()
        obj_id = id(self)
        if obj_id in _visited or _depth > 10:
            return {"_recursive": True}
        _visited.add(obj_id)

        def safe_str(v: Any) -> str:
            if isinstance(v, (str, int, float, bool)):
                return str(v)
            if isinstance(v, Enum):
                return v.value
            return repr(v)

        def clean_list(lst: Any, max_items: int) -> list[str]:
            return [
                safe_str(e)[:MAX_EVIDENCE_LENGTH]
                for e in (lst or [])[:max_items]
            ]

        parent_dict = None
        if self.parent is not None and self.parent is not self:
            parent_dict = self.parent.to_dict(_visited, _depth + 1)
            if parent_dict.get("_recursive"):
                parent_dict = None

        children_out = []
        for child in self.children[:MAX_CHILDREN]:
            if id(child) not in _visited and child is not self:
                d = child.to_dict(_visited, _depth + 1)
                if not d.get("_recursive"):
                    children_out.append(d)

        return {
            "severity"      : self.severity.value,
            "category"      : self.category.value,
            "error_code"    : self.error_code.value,
            "root_cause"    : safe_str(self.root_cause),
            "evidence"      : clean_list(self.evidence, MAX_EVIDENCE_ITEMS),
            "typed_evidence": [e.to_dict() for e in self.typed_evidence[:MAX_EVIDENCE_ITEMS]],
            "impact"        : clean_list(self.impact, MAX_IMPACT_ITEMS),
            "suggested_fix" : safe_str(self.suggested_fix),
            "raw_error"     : safe_str(self.raw_error),
            "confidence"    : round(self.confidence, 4),
            "parent"        : parent_dict,
            "children"      : children_out,
            "metadata"      : {k: safe_str(v) for k, v in (self.metadata or {}).items()},
        }

    def to_json(self, indent: int = 2) -> str:
        try:
            return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as exc:
            return json.dumps({"error": f"Serialization failed: {exc}"})

    def summary(self) -> str:
        return (
            f"[{self.error_code.value}] {self.severity.value} "
            f"({self.category.value}) conf={self.confidence:.2f}: "
            f"{self.root_cause[:100]}"
        )

# ── Thread‑safe LRU Cache ────────────────────────────────────────────────────
class _ThreadSafeLRUCache:
    def __init__(self, maxsize: int = CACHE_SIZE) -> None:
        self.maxsize = maxsize
        self._cache: OrderedDict[Any, Any] = OrderedDict()
        self._lock  = threading.RLock()
        self._hits  = 0
        self._misses= 0

    def get(self, key: Any) -> Any | None:
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            self._cache.move_to_end(key)
            self._hits += 1
            return self._cache[key]

    def set(self, key: Any, value: Any) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            else:
                if len(self._cache) >= self.maxsize:
                    self._cache.popitem(last=False)
            self._cache[key] = value

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._hits = self._misses = 0

    def invalidate(self, path: str) -> None:
        with self._lock:
            keys_to_delete = [
                k for k in self._cache
                if isinstance(k, tuple) and k and k[0] == path
            ]
            for k in keys_to_delete:
                del self._cache[k]

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "size"  : len(self._cache),
                "hits"  : self._hits,
                "misses": self._misses,
            }

# ── Caches ────────────────────────────────────────────────────────────────────
_file_cache    = _ThreadSafeLRUCache(CACHE_SIZE)
_ast_cache     = _ThreadSafeLRUCache(CACHE_SIZE)
_context_cache = _ThreadSafeLRUCache(CACHE_SIZE)

# ── reprlib wrapper ──────────────────────────────────────────────────────────
_reprlib_lock = threading.Lock()
_reprlib_fn: Any | None = None

def _get_reprlib() -> Any:
    global _reprlib_fn
    if _reprlib_fn is None:
        with _reprlib_lock:
            if _reprlib_fn is None:
                import reprlib
                r = reprlib.Repr()
                r.maxstring = 150
                r.maxother  = 150
                _reprlib_fn = r.repr
    return _reprlib_fn

def safe_repr(obj: Any, max_len: int = 150) -> str:
    def _do_repr() -> str:
        return _get_reprlib()(obj)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_do_repr)
            try:
                s = future.result(timeout=REPR_TIMEOUT_SECONDS)
            except concurrent.futures.TimeoutError:
                return "<repr_timeout>"
        if len(s) > max_len:
            return s[:max_len] + "…"
        return s
    except Exception:
        return "<unrepresentable>"

def _is_sensitive_key(key: str) -> bool:
    key_lower = key.lower()
    return any(sk in key_lower for sk in _SENSITIVE_KEYS)

# ── File utilities ────────────────────────────────────────────────────────────
def _get_file_info(path: str) -> tuple[float, int] | None:
    try:
        stat = os.stat(path)
        return stat.st_mtime, stat.st_size
    except OSError:
        return None

def _get_file_content(filename: str) -> str | None:
    info = _get_file_info(filename)
    if info is None:
        return None
    mtime, size = info
    if size > FILE_READ_LIMIT:
        _logger.warning("File too large (>%d bytes): %s", FILE_READ_LIMIT, filename)
        return None
    key    = (filename, mtime, size)
    cached = _file_cache.get(key)
    if cached is not None:
        return cached
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252", "iso-8859-1"):
        try:
            with open(filename, encoding=enc, errors="replace") as f:
                content = f.read()
            _file_cache.set(key, content)
            return content
        except (UnicodeDecodeError, LookupError, OSError):
            continue
    return None

def get_ast(filename: str) -> ast.AST | None:
    info = _get_file_info(filename)
    if info is None:
        return None
    mtime, size = info
    if size > FILE_READ_LIMIT:
        return None
    key    = (filename, mtime, size)
    cached = _ast_cache.get(key)
    if cached is not None:
        return cached
    content = _get_file_content(filename)
    if content is None:
        return None
    try:
        tree = ast.parse(content, filename=filename)
        _ast_cache.set(key, tree)
        return tree
    except (SyntaxError, MemoryError, RecursionError):
        return None

def get_code_context(
    filename: str,
    lineno: int,
    context_lines: int = MAX_CONTEXT_LINES,
) -> list[str]:
    if lineno <= 0:
        return []
    info = _get_file_info(filename)
    if info is None:
        return []
    mtime, size = info
    if size > FILE_READ_LIMIT:
        return []
    key    = (filename, mtime, size, lineno, context_lines)
    cached = _context_cache.get(key)
    if cached is not None:
        return cached
    content = _get_file_content(filename)
    if content is None:
        return []
    lines  = content.splitlines()
    start  = max(0, lineno - context_lines - 1)
    end    = min(len(lines), lineno + context_lines)
    result = [f"{i + 1}: {lines[i].rstrip()[:200]}" for i in range(start, end)]
    _context_cache.set(key, result)
    return result

def _get_error_line(
    code: list[str],
    frame_lineno: int,
    context_lines: int = MAX_CONTEXT_LINES,
) -> str | None:
    if not code or frame_lineno <= 0:
        return None
    start      = max(0, frame_lineno - context_lines - 1)
    target_idx = frame_lineno - 1 - start
    target_idx = max(0, min(target_idx, len(code) - 1))
    return code[target_idx]

def get_frame_locals(frame: Any, max_items: int = 10) -> dict[str, str]:
    if not hasattr(frame, "f_locals"):
        return {}
    filtered: dict[str, str] = {}
    for k, v in list(frame.f_locals.items())[:max_items]:
        if k.startswith("__") and k.endswith("__"):
            continue
        if _is_sensitive_key(k):
            filtered[k] = "[REDACTED — sensitive key]"
        else:
            filtered[k] = safe_repr(v)
    return filtered

def get_traceback_frames(exc: BaseException) -> list[traceback.FrameSummary]:
    tb = exc.__traceback__
    if tb is None:
        return []
    frames = list(traceback.extract_tb(tb))
    return frames[-MAX_TRACEBACK_FRAMES:]

def flatten_exception(
    exc: BaseException,
    _seen: set[int] | None = None,
) -> list[BaseException]:
    if _seen is None:
        _seen = set()
    result: list[BaseException] = []
    if id(exc) in _seen:
        return result
    _seen.add(id(exc))
    if hasattr(exc, "exceptions") and isinstance(exc.exceptions, (list, tuple)):
        for e in exc.exceptions:
            result.extend(flatten_exception(e, _seen))
    else:
        result.append(exc)
    return result

def get_all_causes(exc: BaseException) -> list[BaseException]:
    result: list[BaseException] = []
    seen  : set[int]            = set()
    queue : deque               = deque([exc])

    while queue:
        e   = queue.popleft()
        eid = id(e)
        if eid in seen:
            continue
        seen.add(eid)
        result.append(e)

        # __cause__
        if e.__cause__ is not None:
            queue.append(e.__cause__)

        # __context__ (unless suppressed)
        suppress = getattr(e, "__suppress_context__", False)
        if (e.__context__ is not None
                and e.__context__ is not e.__cause__
                and not suppress):
            queue.append(e.__context__)

        # ExceptionGroup / BaseExceptionGroup
        if hasattr(e, "exceptions"):
            for sub in flatten_exception(e):
                if id(sub) not in seen:
                    queue.append(sub)

    return result

# ═══════════════════════════════════════════════════════════════════════════════
#  RULES — semua aturan (generik + project) dalam satu tempat
# ═══════════════════════════════════════════════════════════════════════════════

class RCARule(ABC):
    def __init__(
        self,
        priority : int             = 0,
        enabled  : bool            = True,
        name     : str | None   = None,
        category : Category        = Category.UNKNOWN,
        version  : str             = "1.0",
        author   : str             = "system",
    ) -> None:
        self.priority    = priority
        self.enabled     = enabled
        self.name        = name or self.__class__.__name__
        self.category    = category
        self.version     = version
        self.author      = author
        self._stats_lock = threading.RLock()
        self._stats: dict[str, Any] = {
            "matches": 0, "hits": 0, "misses": 0, "errors": 0, "time_ms": 0.0,
        }

    @abstractmethod
    def match(
        self,
        exc     : BaseException,
        frames  : list[traceback.FrameSummary],
        context : dict[str, Any],
    ) -> bool:
        pass

    @abstractmethod
    def analyze(
        self,
        exc     : BaseException,
        frames  : list[traceback.FrameSummary],
        context : dict[str, Any],
    ) -> RCAResult | None:
        pass

    def stats(self) -> dict[str, Any]:
        with self._stats_lock:
            s = dict(self._stats)
        s["name"]     = self.name
        s["priority"] = self.priority
        s["enabled"]  = self.enabled
        return s

    def _make_evidence(self, text: str, evidence_type: str = "general") -> EvidenceItem:
        return EvidenceItem(text=text, source_rule=self.name, evidence_type=evidence_type)

    def __repr__(self) -> str:
        return f"<{self.name} priority={self.priority} enabled={self.enabled}>"

# ─── ImportErrorRule ─────────────────────────────────────────────────────────
class ImportErrorRule(RCARule):
    def __init__(self) -> None:
        super().__init__(priority=100, category=Category.IMPORT, name="ImportErrorRule")

    def match(self, exc, frames, context) -> bool:
        return isinstance(exc, (ImportError, ModuleNotFoundError))

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg        = str(exc)
        evidence   : list[str] = []
        impact     : list[str] = []
        severity   = Severity.HIGH
        confidence = DEFAULT_CONFIDENCE
        error_code = ErrorCode.IMPORT_MODULE_NOT_FOUND
        root_cause = suggested_fix = ""

        module_name = getattr(exc, "name", None)
        if not module_name:
            m = re.search(r"^No module named '([^']+)'", msg)
            if m:
                module_name = m.group(1)

        if module_name:
            evidence.append(f"Modul yang tidak ditemukan: {module_name}")
            parts     = module_name.split(".")
            sys_path  = list(sys.path)
            found_any = False

            for p in sys_path:
                base      = p
                all_exist = True
                for part in parts:
                    base = os.path.join(base, part)
                    if not os.path.exists(base):
                        all_exist = False
                        break
                if all_exist:
                    found_any = True
                    break

            if not found_any:
                root_cause    = f"Modul '{module_name}' tidak ditemukan di PYTHONPATH."
                suggested_fix = (
                    f"Pastikan '{module_name}' terinstal: "
                    f"pip install {module_name.split('.')[0]}"
                )
            else:
                missing_init: list[str] = []
                for i in range(1, len(parts)):
                    for p in sys_path:
                        init_path = os.path.join(p, *parts[:i], "__init__.py")
                        if os.path.exists(init_path):
                            break
                    else:
                        missing_init.append(".".join(parts[:i]))

                if missing_init:
                    root_cause    = f"__init__.py hilang untuk: {', '.join(missing_init)}"
                    suggested_fix = "Tambahkan __init__.py di setiap direktori subpackage."
                    severity      = Severity.CRITICAL
                    confidence    = 0.8
                    error_code    = ErrorCode.IMPORT_SUBMODULE_MISSING
                else:
                    root_cause    = (
                        f"Modul '{module_name}' tidak ditemukan, "
                        "periksa struktur direktori."
                    )
                    suggested_fix = "Periksa penamaan dan struktur direktori."
        else:
            root_cause    = f"ImportError: {msg}"
            suggested_fix = (
                "Periksa nama modul dan pastikan semua dependensi terinstal."
            )

        impact.append("Modul dependen tidak dapat diimpor — kegagalan cascade di seluruh sistem.")

        return RCAResult(
            severity=severity, category=Category.IMPORT, error_code=error_code,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=msg, confidence=confidence,
        )

# ─── CircularImportRule ─────────────────────────────────────────────────────
class CircularImportRule(RCARule):
    _CIRCULAR_HINTS = re.compile(
        r"(circular import|partially initialized module|most likely due to)",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        super().__init__(priority=95, category=Category.IMPORT, name="CircularImportRule")

    def match(self, exc, frames, context) -> bool:
        if not isinstance(exc, (ImportError, ModuleNotFoundError)):
            return False
        if self._CIRCULAR_HINTS.search(str(exc)):
            return True
        if not HAS_NETWORKX:
            return False
        filenames = [f.filename for f in frames if f.filename.endswith(".py")]
        return len(filenames) != len(set(filenames))

    def analyze(self, exc, frames, context) -> RCAResult | None:
        if self._CIRCULAR_HINTS.search(str(exc)) and not HAS_NETWORKX:
            return RCAResult(
                severity=Severity.CRITICAL, category=Category.IMPORT,
                error_code=ErrorCode.IMPORT_CIRCULAR,
                root_cause="Circular import terdeteksi dari pesan error.",
                evidence=[f"Pesan: {str(exc)[:200]}"],
                impact=["Circular import mencegah modul di-resolve — crash saat startup."],
                suggested_fix=(
                    "Pisahkan dependensi atau gunakan lazy import di dalam fungsi. "
                    "Install networkx untuk analisis graph yang lebih detail."
                ),
                raw_error=str(exc), confidence=0.7,
            )

        if not HAS_NETWORKX:
            return None

        filenames = list({f.filename for f in frames if f.filename.endswith(".py")})
        if len(filenames) < 2:
            return None

        def path_to_module(path: str) -> str:
            try:
                rel = Path(path).relative_to(Path.cwd())
                return ".".join(rel.with_suffix("").parts)
            except ValueError:
                return Path(path).stem

        G = nx.DiGraph()
        for filename in filenames:
            tree = get_ast(filename)
            if tree is None:
                continue
            mod = path_to_module(filename)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imp = alias.name.split(".")[0]
                        for other in filenames:
                            if path_to_module(other) == imp:
                                G.add_edge(mod, path_to_module(other))
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imp = node.module.split(".")[0]
                    for other in filenames:
                        if path_to_module(other) == imp:
                            G.add_edge(mod, path_to_module(other))

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(list, nx.simple_cycles(G))
                cycles = future.result(timeout=TIMEOUT_SECONDS)
            if cycles:
                cycle_path = " → ".join(cycles[0] + [cycles[0][0]])
                return RCAResult(
                    severity=Severity.CRITICAL, category=Category.IMPORT,
                    error_code=ErrorCode.IMPORT_CIRCULAR,
                    root_cause=f"Circular import terdeteksi: {cycle_path}",
                    evidence=[f"Modul terlibat: {', '.join(cycles[0])}"],
                    impact=["Circular import mencegah modul di-resolve — crash saat startup."],
                    suggested_fix=(
                        "Pisahkan dependensi atau gunakan lazy import di dalam fungsi. "
                        "Pola umum: pindahkan import ke dalam fungsi yang membutuhkannya."
                    ),
                    raw_error=str(exc), confidence=0.85,
                )
        except concurrent.futures.TimeoutError:
            _logger.warning("CircularImportRule: cycle detection timeout")
        except Exception as exc_inner:
            _logger.debug("CircularImportRule graph error: %s", exc_inner)

        return None

# ─── AttributeErrorRule ──────────────────────────────────────────────────────
class AttributeErrorRule(RCARule):
    def __init__(self) -> None:
        super().__init__(priority=90, category=Category.ATTRIBUTE, name="AttributeErrorRule")

    _PATTERNS = [
        re.compile(r"^'?(\w[\w.]*)'? object has no attribute '(\w+)'"),
        re.compile(r"^module '([^']+)' has no attribute '([^']+)'"),
    ]

    def match(self, exc, frames, context) -> bool:
        return isinstance(exc, AttributeError)

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg        = str(exc)
        evidence   : list[str] = []
        impact     : list[str] = []
        severity   = Severity.MEDIUM
        confidence = DEFAULT_CONFIDENCE
        error_code = ErrorCode.ATTR_MISSING
        root_cause = suggested_fix = ""

        obj_type = attr = None
        for pat in self._PATTERNS:
            m = pat.search(msg)
            if m:
                obj_type, attr = m.groups()
                break

        if obj_type == "NoneType" and attr:
            return RCAResult(
                severity=Severity.HIGH, category=Category.ATTRIBUTE,
                error_code=ErrorCode.ATTR_NONE_ACCESS,
                root_cause=(
                    f"Akses atribut '{attr}' pada objek None — "
                    "objek belum diinisialisasi atau return value yang diharapkan None."
                ),
                evidence=[f"AttributeError: {msg}"],
                impact=[
                    "Fungsi berhenti, kemungkinan objek belum di-inject atau return value None.",
                    "Pola ini sering terjadi pada hasil query database yang kosong.",
                ],
                suggested_fix=(
                    f"Pastikan objek tidak None sebelum mengakses '{attr}'. "
                    "Tambahkan guard: if obj is not None: ... "
                    "Atau gunakan Optional chaining: getattr(obj, 'attr', None)"
                ),
                raw_error=msg, confidence=0.92,
            )

        if obj_type and attr:
            evidence.append(f"Tipe '{obj_type}' tidak memiliki atribut '{attr}'")

            if frames:
                frame      = frames[-1]
                code_lines = get_code_context(frame.filename, frame.lineno)
                err_line   = _get_error_line(code_lines, frame.lineno)
                if err_line:
                    evidence.append(f"Baris {frame.lineno}: {err_line}")

                tree = get_ast(frame.filename)
                if tree:
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef) and node.name == obj_type:
                            attrs: set[str] = set()
                            for child in ast.walk(node):
                                if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                                    attrs.add(child.target.id)
                                elif isinstance(child, ast.Assign):
                                    for t in child.targets:
                                        if isinstance(t, ast.Name):
                                            attrs.add(t.id)
                                elif isinstance(child, ast.FunctionDef):
                                    for dec in child.decorator_list:
                                        if isinstance(dec, ast.Name) and dec.id == "property":
                                            attrs.add(child.name)
                            if attr not in attrs:
                                root_cause    = f"Atribut '{attr}' tidak didefinisikan di class '{obj_type}'."
                                suggested_fix = (
                                    f"Tambahkan '{attr}' ke __init__ atau definisi class '{obj_type}'. "
                                    f"Atribut yang ada: {sorted(attrs)[:10]}"
                                )
                                confidence = 0.85
                            else:
                                root_cause    = f"'{attr}' ada di class tapi instance yang digunakan salah tipe."
                                suggested_fix = "Periksa apakah objek adalah instance yang benar."
                            break

        if not root_cause:
            root_cause    = f"AttributeError: {msg}"
            suggested_fix = "Periksa atribut yang diakses dan tipe objek."

        impact.append("Fungsi/method yang mengakses atribut ini akan gagal.")

        return RCAResult(
            severity=severity, category=Category.ATTRIBUTE, error_code=error_code,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=msg, confidence=confidence,
        )

# ─── TypeErrorRule ──────────────────────────────────────────────────────────
class TypeErrorRule(RCARule):
    def __init__(self) -> None:
        super().__init__(priority=80, category=Category.TYPE, name="TypeErrorRule")
        self._compiled_patterns = [
            (
                re.compile(r"(\w+)\(\) takes (\d+) positional arguments? but (\d+) were given"),
                ErrorCode.TYPE_ARG_COUNT,
                lambda m: (
                    f"Fungsi '{m.group(1)}' menerima {m.group(2)} arg, diberikan {m.group(3)}.",
                    f"Sesuaikan jumlah argumen saat memanggil '{m.group(1)}'.",
                    0.85,
                ),
            ),
            (
                re.compile(r"(\w+)\(\) missing (\d+) required positional arguments?: (.+)"),
                ErrorCode.TYPE_MISSING_REQUIRED,
                lambda m: (
                    f"Argumen wajib tidak disediakan untuk '{m.group(1)}': {m.group(3)}.",
                    f"Berikan argumen yang diperlukan saat memanggil '{m.group(1)}'.",
                    0.8,
                ),
            ),
            (
                re.compile(r"unsupported operand type\(s\) for .+: '(\w+)' and '(\w+)'"),
                ErrorCode.TYPE_OPERAND,
                lambda m: (
                    f"Operasi tidak didukung antara tipe '{m.group(1)}' dan '{m.group(2)}'.",
                    "Pastikan kedua operand memiliki tipe yang kompatibel.",
                    0.7,
                ),
            ),
            (
                re.compile(r"'(\w+)' object is not callable"),
                ErrorCode.TYPE_NOT_CALLABLE,
                lambda m: (
                    f"Objek tipe '{m.group(1)}' dipanggil sebagai fungsi tapi tidak callable.",
                    "Periksa apakah Anda mengakses property bukan method.",
                    0.75,
                ),
            ),
            (
                re.compile(r"(\w+)\(\) got an unexpected keyword argument '(\w+)'"),
                ErrorCode.TYPE_UNEXPECTED_KEYWORD,
                lambda m: (
                    f"Keyword argument '{m.group(2)}' tidak valid untuk '{m.group(1)}'.",
                    f"Periksa nama parameter fungsi '{m.group(1)}' atau hapus argumen '{m.group(2)}'.",
                    0.8,
                ),
            ),
            (
                re.compile(r"'(\w+)' object is not iterable"),
                ErrorCode.TYPE_NOT_ITERABLE,
                lambda m: (
                    f"Objek tipe '{m.group(1)}' tidak iterable.",
                    f"Pastikan objek bertipe iterable (list, tuple, generator) bukan '{m.group(1)}'.",
                    0.8,
                ),
            ),
            (
                re.compile(r"'(\w+)' object is not subscriptable"),
                ErrorCode.TYPE_NOT_ITERABLE,
                lambda m: (
                    f"Objek tipe '{m.group(1)}' tidak mendukung subscript (indexing).",
                    "Pastikan Anda mengakses index pada tipe yang mendukung (list, dict, str).",
                    0.75,
                ),
            ),
        ]

    def match(self, exc, frames, context) -> bool:
        return isinstance(exc, TypeError)

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg        = str(exc)
        evidence   : list[str] = []
        impact     : list[str] = []
        severity   = Severity.MEDIUM
        confidence = DEFAULT_CONFIDENCE
        error_code = ErrorCode.TYPE_ARG_COUNT
        root_cause = suggested_fix = ""

        for pattern, code, handler in self._compiled_patterns:
            m = pattern.search(msg)
            if m:
                root_cause, suggested_fix, confidence = handler(m)
                error_code = code
                evidence.append(f"TypeError: {msg}")
                break
        else:
            root_cause    = f"TypeError: {msg}"
            suggested_fix = "Periksa tipe data yang digunakan."

        impact.append("Fungsi tidak dapat dijalankan, mempengaruhi alur eksekusi.")

        return RCAResult(
            severity=severity, category=Category.TYPE, error_code=error_code,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=msg, confidence=confidence,
        )

# ─── NameErrorRule ──────────────────────────────────────────────────────────
class NameErrorRule(RCARule):
    _BUILTIN_TYPOS: dict[str, str] = {
        "true"   : "True",
        "false"  : "False",
        "none"   : "None",
        "print_" : "print",
        "lenght" : "len",
        "lenth"  : "len",
        "pritn"  : "print",
        "pint"   : "print",
        "retrun" : "return",
        "improt" : "import",
        "clss"   : "class",
        "def_"   : "def",
    }

    def __init__(self) -> None:
        super().__init__(priority=85, category=Category.TYPE, name="NameErrorRule")

    def match(self, exc, frames, context) -> bool:
        return isinstance(exc, NameError)

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg        = str(exc)
        evidence   : list[str] = []
        impact     : list[str] = []
        root_cause = suggested_fix = ""
        confidence = 0.8

        m    = re.search(r"name '([^']+)' is not defined", msg)
        name = m.group(1) if m else None

        if name:
            evidence.append(f"Nama yang tidak dikenal: '{name}'")

            if name.lower() in self._BUILTIN_TYPOS:
                fix           = self._BUILTIN_TYPOS[name.lower()]
                root_cause    = f"Typo: '{name}' kemungkinan dimaksudkan '{fix}'."
                suggested_fix = f"Ganti '{name}' dengan '{fix}'."
                confidence    = 0.9
            else:
                if frames:
                    frame = frames[-1]
                    tree  = get_ast(frame.filename)
                    if tree:
                        defined_names: set[str] = set()
                        for node in ast.walk(tree):
                            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                                defined_names.add(node.name)
                            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                                defined_names.add(node.id)
                            elif isinstance(node, ast.Import):
                                for alias in node.names:
                                    defined_names.add(alias.asname or alias.name.split(".")[0])
                            elif isinstance(node, ast.ImportFrom):
                                for alias in node.names:
                                    defined_names.add(alias.asname or alias.name)

                        close = difflib.get_close_matches(name, defined_names, n=3, cutoff=0.6)
                        if close:
                            evidence.append(f"Nama mirip yang ada di file: {close}")
                            root_cause    = (
                                f"'{name}' tidak terdefinisi. Mungkin typo dari: {close[0]!r}?"
                            )
                            suggested_fix = (
                                f"Periksa ejaan variabel. Gunakan '{close[0]}' jika itu yang dimaksud."
                            )
                            confidence = 0.75
                        else:
                            root_cause    = (
                                f"'{name}' tidak terdefinisi di scope ini. "
                                "Mungkin belum diinisialisasi atau salah import."
                            )
                            suggested_fix = (
                                f"Pastikan '{name}' diimport atau didefinisikan sebelum digunakan."
                            )
                    else:
                        root_cause    = f"'{name}' tidak terdefinisi."
                        suggested_fix = f"Tambahkan definisi atau import untuk '{name}'."

                if frames:
                    frame = frames[-1]
                    code  = get_code_context(frame.filename, frame.lineno)
                    err   = _get_error_line(code, frame.lineno)
                    if err:
                        evidence.append(f"Baris {frame.lineno}: {err}")
        else:
            root_cause    = f"NameError: {msg}"
            suggested_fix = "Periksa semua nama variabel dan pastikan sudah didefinisikan."

        if not root_cause:
            root_cause = f"NameError: {msg}"

        impact.append("Eksekusi berhenti di baris ini — semua kode sesudahnya tidak jalan.")

        return RCAResult(
            severity=Severity.HIGH, category=Category.TYPE,
            error_code=ErrorCode.NAME_NOT_DEFINED,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=msg, confidence=confidence,
        )

# ─── KeyErrorRule ────────────────────────────────────────────────────────────
class KeyErrorRule(RCARule):
    _ERP_CONTEXTS: dict[str, tuple[str, str]] = {
        "account"  : ("Kode akun tidak terdaftar di chart of accounts.",
                      "Pastikan kode akun sudah didefinisikan di master akun ERP."),
        "period"   : ("Periode akuntansi tidak terdaftar atau sudah ditutup.",
                      "Buka periode yang dimaksud atau gunakan periode yang aktif."),
        "currency" : ("Kode mata uang tidak terdaftar di master currency.",
                      "Tambahkan kode mata uang ke konfigurasi ERP."),
        "journal"  : ("Kode jurnal tidak ditemukan di konfigurasi.",
                      "Pastikan jurnal sudah dikonfigurasi di modul akuntansi."),
        "company"  : ("Company ID tidak terdaftar di context ERP.",
                      "Pastikan company_id diset dengan benar di context."),
        "warehouse": ("Kode warehouse tidak ditemukan.",
                      "Periksa konfigurasi warehouse di modul inventory."),
        "tax"      : ("Kode pajak tidak terdaftar di konfigurasi ERP.",
                      "Periksa master data pajak dan pastikan kode sudah aktif."),
        "cost"     : ("Cost center/profit center tidak ditemukan.",
                      "Periksa konfigurasi cost center di modul akuntansi biaya."),
        "entity"   : ("Entity ID tidak ditemukan.",
                      "Pastikan legal entity sudah terdaftar dan aktif."),
        "project"  : ("Project ID tidak ditemukan.",
                      "Periksa master data project."),
    }

    def __init__(self) -> None:
        super().__init__(priority=85, category=Category.TYPE, name="KeyErrorRule")

    def match(self, exc, frames, context) -> bool:
        return isinstance(exc, KeyError)

    def analyze(self, exc, frames, context) -> RCAResult | None:
        raw   = str(exc)
        key   = exc.args[0] if exc.args else None
        key_s = repr(key) if key is not None else raw

        evidence   : list[str] = []
        impact     : list[str] = []
        root_cause = suggested_fix = ""
        confidence = 0.8
        matched_ctx: str | None = None

        evidence.append(f"Key yang tidak ditemukan: {key_s}")

        key_lower = str(key).lower() if key else ""
        for ctx_key, (ctx_cause, ctx_fix) in self._ERP_CONTEXTS.items():
            if ctx_key in key_lower:
                root_cause    = ctx_cause
                suggested_fix = ctx_fix
                confidence    = 0.85
                matched_ctx   = ctx_key
                break

        if not matched_ctx:
            if frames:
                frame = frames[-1]
                code  = get_code_context(frame.filename, frame.lineno)
                err   = _get_error_line(code, frame.lineno)
                if err:
                    evidence.append(f"Baris {frame.lineno}: {err}")
            root_cause    = (
                f"Key {key_s} tidak ditemukan di dict/mapping. "
                "Dict mungkin kosong, belum diisi, atau key salah."
            )
            suggested_fix = (
                f"Gunakan .get({key_s}, default) untuk akses aman, "
                "atau validasi keberadaan key dengan 'if key in d' sebelum akses."
            )

        impact.append("Operasi yang bergantung pada data ini akan gagal.")
        if matched_ctx in ("account", "period", "journal"):
            impact.append("Potensi kegagalan posting jurnal akuntansi — data transaksi tidak tersimpan.")

        return RCAResult(
            severity=Severity.HIGH, category=Category.TYPE,
            error_code=ErrorCode.KEY_NOT_FOUND,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=raw, confidence=confidence,
        )

# ─── IndexErrorRule ─────────────────────────────────────────────────────────
class IndexErrorRule(RCARule):
    _RANGE_PATTERN = re.compile(
        r"list index out of range|tuple index out of range|"
        r"string index out of range|index (\d+) is out of bounds"
    )

    def __init__(self) -> None:
        super().__init__(priority=84, category=Category.TYPE, name="IndexErrorRule")

    def match(self, exc, frames, context) -> bool:
        return isinstance(exc, (IndexError, StopIteration))

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg        = str(exc)
        evidence   : list[str] = []
        impact     : list[str] = []
        root_cause = suggested_fix = ""
        confidence = 0.75

        if isinstance(exc, StopIteration):
            root_cause    = "Iterator/generator habis (StopIteration) di luar konteks for-loop."
            suggested_fix = (
                "Gunakan next(iter, default) untuk akses aman, "
                "atau pastikan iterator tidak digunakan setelah habis."
            )
            confidence = 0.85
        else:
            if self._RANGE_PATTERN.search(msg):
                root_cause    = "Akses index di luar batas koleksi (list/tuple/string kosong atau index terlalu besar)."
                suggested_fix = (
                    "Periksa panjang list sebelum akses: 'if len(lst) > idx'. "
                    "Di ERP, pastikan result query tidak kosong sebelum ambil elemen pertama."
                )
            else:
                root_cause    = f"IndexError: {msg}"
                suggested_fix = "Periksa bounds sebelum akses index."

            if frames:
                frame = frames[-1]
                code  = get_code_context(frame.filename, frame.lineno)
                err   = _get_error_line(code, frame.lineno)
                if err:
                    evidence.append(f"Baris {frame.lineno}: {err}")
                    if re.search(r'\[0\]|\[-1\]|\.first\(\)', err):
                        evidence.append("Terdeteksi akses elemen pertama/terakhir tanpa validasi kosong.")
                        root_cause    = "Mengakses elemen [0] atau [-1] dari hasil query yang mungkin kosong."
                        suggested_fix = (
                            "Gunakan .first() dengan guard 'if result:', "
                            "atau tambahkan .limit(1) lalu cek panjang."
                        )
                        confidence = 0.88

        impact.append("Data processing terhenti — batch atau laporan tidak selesai diproses.")

        return RCAResult(
            severity=Severity.MEDIUM, category=Category.TYPE,
            error_code=ErrorCode.INDEX_OUT_OF_RANGE,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=msg, confidence=confidence,
        )

# ─── ValueErrorRule ─────────────────────────────────────────────────────────
class ValueErrorRule(RCARule):
    _ERP_PATTERNS: list[tuple[str, ErrorCode, Severity, str, str, float]] = [
        (r"account.*(invalid|not.found|not.exist|not.active)",
         ErrorCode.ERP_ACCOUNT_INVALID, Severity.CRITICAL,
         "Kode akun tidak valid atau tidak aktif.",
         "Periksa kode akun di Chart of Accounts dan pastikan status akun aktif.",
         0.9),
        (r"balance.*(mismatch|not.balance|debit.*credit|credit.*debit)",
         ErrorCode.ERP_BALANCE_MISMATCH, Severity.FATAL,
         "Jurnal tidak seimbang — total debit tidak sama dengan kredit.",
         "Periksa semua entri jurnal: total debit harus = total kredit sebelum posting.",
         0.95),
        (r"(negative|minus).*(amount|quantity|qty|stock)",
         ErrorCode.ERP_VALIDATION, Severity.HIGH,
         "Jumlah/quantity negatif tidak diizinkan di transaksi ini.",
         "Validasi input sebelum proses: amount harus >= 0 untuk transaksi debit.",
         0.88),
        (r"invalid.literal.*int|could not convert.*to.*int|"
         r"invalid.*float|could not convert.*to.*float",
         ErrorCode.VALUE_INVALID, Severity.HIGH,
         "Konversi tipe gagal: string tidak bisa dikonversi ke angka.",
         "Validasi input numerik sebelum konversi: gunakan try/except atau .isdigit().",
         0.9),
        (r"date.*format|invalid.*date|time.*format",
         ErrorCode.VALUE_INVALID, Severity.HIGH,
         "Format tanggal tidak valid.",
         "Gunakan format ISO 8601 (YYYY-MM-DD) atau validasi format sebelum parsing.",
         0.88),
        (r"\bduplicate\b|already.exist|unique.*constraint|unique.*violation",
         ErrorCode.ERP_VALIDATION, Severity.HIGH,
         "Duplicate entry — data dengan identifier ini sudah ada.",
         "Cek uniqueness sebelum insert, atau gunakan upsert jika update diizinkan.",
         0.85),
        (r"repository.*(save|persist|store).*fail",
         ErrorCode.REPOSITORY_MISMATCH, Severity.CRITICAL,
         "Repository gagal menyimpan entitas — constraint DB atau mismatch skema.",
         "Periksa mapping entitas ke tabel dan constraint database.",
         0.8),
        (r"math domain error",
         ErrorCode.VALUE_INVALID, Severity.MEDIUM,
         "Operasi matematika domain error (misal sqrt negatif, log nol).",
         "Validasi input agar berada dalam domain fungsi matematika.",
         0.8),
    ]

    _COMPILED: list[tuple[re.Pattern, ErrorCode, Severity, str, str, float]] | None = None

    def __init__(self) -> None:
        super().__init__(priority=83, category=Category.DDD, name="ValueErrorRule")
        if ValueErrorRule._COMPILED is None:
            ValueErrorRule._COMPILED = [
                (re.compile(p, re.IGNORECASE), code, sev, cause, fix, conf)
                for p, code, sev, cause, fix, conf in self._ERP_PATTERNS
            ]

    def match(self, exc, frames, context) -> bool:
        return isinstance(exc, ValueError)

    def analyze(self, exc, frames, context) -> RCAResult | None:
        raw = str(exc)

        # DETEKSI PERIOD CLOSED — LANGSUNG RETURN
        if re.search(r"(?:accounting\s+period|periode).*(?:closed|locked)", raw, re.I):
            return RCAResult(
                severity=Severity.CRITICAL, category=Category.DDD,
                error_code=ErrorCode.ERP_PERIOD_CLOSED,
                root_cause="Periode akuntansi sudah ditutup atau dikunci.",
                evidence=[f"Pesan: {raw[:300]}"],
                impact=["Posting jurnal tidak bisa dilakukan sampai periode dibuka."],
                suggested_fix="Buka kembali periode di modul akuntansi atau gunakan periode yang masih aktif.",
                raw_error=raw, confidence=0.95,
            )

        evidence   : list[str] = []
        impact     : list[str] = []
        root_cause = suggested_fix = ""
        confidence = DEFAULT_CONFIDENCE
        error_code = ErrorCode.VALUE_INVALID
        severity   = Severity.MEDIUM

        assert self._COMPILED is not None
        for pattern, code, sev, cause, fix, conf in self._COMPILED:
            if pattern.search(raw):
                error_code    = code
                severity      = sev
                root_cause    = cause
                suggested_fix = fix
                confidence    = conf
                evidence.append(f"Pesan error: {raw[:MAX_EVIDENCE_LENGTH]}")
                break

        if not root_cause:
            root_cause    = f"ValueError: {raw}"
            suggested_fix = "Validasi nilai input sebelum memproses."
            evidence.append(f"Pesan: {raw[:MAX_EVIDENCE_LENGTH]}")

        if frames:
            frame = frames[-1]
            code_lines = get_code_context(frame.filename, frame.lineno)
            err        = _get_error_line(code_lines, frame.lineno)
            if err:
                evidence.append(f"Baris {frame.lineno}: {err}")

        impact.append("Validasi gagal — transaksi atau data tidak diproses.")
        if severity in (Severity.FATAL, Severity.CRITICAL):
            impact.append("Integritas data akuntansi berisiko — diperlukan review segera.")

        return RCAResult(
            severity=severity, category=Category.DDD, error_code=error_code,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=raw, confidence=confidence,
        )

# ─── InfrastructureConnectionRule ───────────────────────────────────────────
class InfrastructureConnectionRule(RCARule):
    _DB_PATTERN = re.compile(
        r"(connection refused|could not connect|"
        r"lost connection|server closed|"
        r"operational.?error|can.?t connect|"
        r"database.*unavailable|too many connections|"
        r"connection.?timed?.out|no route to host|"
        r"SSL.*connection.*closed|SSL.*handshake)",
        re.IGNORECASE,
    )
    _REDIS_PATTERN = re.compile(
        r"(redis|connection.*6379|6379.*refused|redis.*timeout|redis.*connection)",
        re.IGNORECASE,
    )
    _KAFKA_PATTERN = re.compile(
        r"(kafka|broker.*unavailable|no.*broker|"
        r"kafka.*timeout|leader.*not.*available|connection.*9092)",
        re.IGNORECASE,
    )
    _HTTP_PATTERN = re.compile(
        r"(connection.*reset|remote.*disconnected|"
        r"name.*resolution.*failed|ssl.*error|"
        r"certificate.*verify.*failed|timeout.*read)",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        super().__init__(
            priority=90, category=Category.INFRASTRUCTURE,
            name="InfrastructureConnectionRule",
        )

    def match(self, exc, frames, context) -> bool:
        msg = str(exc)
        # JANGAN PROSES jika ini dead letter atau distributed lock
        if re.search(r"dead\s*letter|DistributedLockTimeout", msg, re.I):
            return False
        if isinstance(exc, (PermissionError, FileNotFoundError, IsADirectoryError, NotADirectoryError)):
            return False
        if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
            if not isinstance(exc, (PermissionError, FileNotFoundError)):
                return True
        if HAS_SQLALCHEMY and _SQLAlchemyError and isinstance(exc, _SQLAlchemyError):
            return True
        return bool(
            self._DB_PATTERN.search(msg)
            or self._REDIS_PATTERN.search(msg)
            or self._KAFKA_PATTERN.search(msg)
            or self._HTTP_PATTERN.search(msg)
        )

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg        = str(exc)
        evidence   = [f"Exception: {type(exc).__name__}: {msg[:200]}"]
        impact     : list[str] = []
        error_code = ErrorCode.DB_CONNECTION_FAIL
        root_cause = suggested_fix = ""
        confidence = 0.8

        if self._REDIS_PATTERN.search(msg):
            error_code    = ErrorCode.REDIS_FAIL
            root_cause    = "Koneksi ke Redis gagal — server tidak tersedia atau timeout."
            suggested_fix = (
                "Periksa status Redis server (redis-cli ping). "
                "Periksa konfigurasi host/port/password di settings ERP. "
                "Pastikan Redis tidak overloaded atau OOM."
            )
            impact.extend([
                "Cache ERP tidak tersedia — performa akan turun drastis.",
                "Session/token yang tersimpan di Redis akan hilang.",
                "Queue job yang bergantung Redis akan terhenti.",
            ])
            confidence = 0.88

        elif self._KAFKA_PATTERN.search(msg):
            error_code    = ErrorCode.KAFKA_FAIL
            root_cause    = "Koneksi ke Kafka broker gagal — broker tidak tersedia."
            suggested_fix = (
                "Periksa status Kafka broker (kafka-broker-api-versions.sh). "
                "Periksa konfigurasi bootstrap.servers. "
                "Pastikan topic sudah dibuat dan partisi aktif."
            )
            impact.extend([
                "Event streaming terhenti — domain events tidak terkirim.",
                "Eventual consistency rusak — subscriber tidak menerima update.",
            ])
            confidence = 0.88

        elif (self._DB_PATTERN.search(msg)
              or isinstance(exc, (ConnectionError, OSError, TimeoutError))
              or (HAS_SQLALCHEMY and _SQLAlchemyError and isinstance(exc, _SQLAlchemyError))):
            root_cause    = "Koneksi ke database gagal atau connection pool habis."
            suggested_fix = (
                "Periksa status database server. "
                "Cek konfigurasi DATABASE_URL di environment. "
                "Pastikan connection pool size cukup (SQLALCHEMY_POOL_SIZE). "
                "Periksa apakah ada koneksi yang menggantung (zombie connections)."
            )
            impact.extend([
                "Seluruh operasi database gagal — ERP tidak dapat menyimpan/membaca data.",
                "Transaksi aktif mungkin menggantung (orphaned transactions).",
            ])
            confidence = 0.85
            m = re.search(r"([\w.-]+):(\d+)", msg)
            if m:
                evidence.append(f"Target koneksi: {m.group(0)}")

        else:
            root_cause    = f"Kegagalan koneksi jaringan/infrastruktur: {type(exc).__name__}"
            suggested_fix = (
                "Periksa konektivitas jaringan. "
                "Verifikasi konfigurasi host, port, dan firewall."
            )
            impact.append("Layanan eksternal tidak dapat dijangkau.")

        if frames:
            frame = frames[-1]
            evidence.append(f"Lokasi error: {frame.filename}:{frame.lineno} in {frame.name}")

        return RCAResult(
            severity=Severity.FATAL, category=Category.INFRASTRUCTURE,
            error_code=error_code,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=msg, confidence=confidence,
        )

# ─── CQRSHandlerRule ────────────────────────────────────────────────────────
class CQRSHandlerRule(RCARule):
    _CMD_PATTERN = re.compile(
        r"\b(command[_\s]?handler|handle[_\s]?command|command[_\s]?bus|"
        r"command[_\s]?dispatcher|no[_\s]?handler.*command|"
        r"unregistered.*command|dispatch.*command)\b",
        re.IGNORECASE,
    )
    _QRY_PATTERN = re.compile(
        r"\b(query[_\s]?handler|handle[_\s]?query|query[_\s]?bus|"
        r"no[_\s]?handler.*query|unregistered.*query|"
        r"query[_\s]?dispatcher)\b",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        super().__init__(priority=72, category=Category.CQRS, name="CQRSHandlerRule")

    def match(self, exc, frames, context) -> bool:
        msg = str(exc)
        if self._CMD_PATTERN.search(msg) or self._QRY_PATTERN.search(msg):
            return True
        for f in frames:
            combined = f"{f.name} {f.filename}"
            if self._CMD_PATTERN.search(combined) or self._QRY_PATTERN.search(combined):
                return True
        return False

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg        = str(exc)
        evidence   : list[str] = []
        impact     : list[str] = []
        error_code = ErrorCode.COMMAND_HANDLER_MISSING
        root_cause = suggested_fix = ""
        confidence = 0.8

        is_query = bool(self._QRY_PATTERN.search(msg))
        if not is_query:
            for f in frames:
                if self._QRY_PATTERN.search(f"{f.name} {f.filename}"):
                    is_query = True
                    break

        if is_query:
            error_code    = ErrorCode.QUERY_HANDLER_MISSING
            root_cause    = "Query handler tidak terdaftar di QueryBus."
            suggested_fix = (
                "Daftarkan handler yang sesuai: "
                "query_bus.register(QueryClass, QueryHandler). "
                "Pastikan handler di-inject ke QueryBus di module bootstrap."
            )
            impact.extend([
                "Query tidak bisa dieksekusi — read side CQRS gagal.",
                "Tampilan data di UI mungkin kosong atau error.",
            ])
        else:
            root_cause    = "Command handler tidak terdaftar di CommandBus."
            suggested_fix = (
                "Daftarkan handler: "
                "command_bus.register(CommandClass, CommandHandler). "
                "Pastikan semua command handler ter-register di application bootstrap."
            )
            impact.extend([
                "Command tidak bisa dieksekusi — write side CQRS gagal.",
                "Operasi bisnis (create/update/delete) tidak berjalan.",
                "Domain events tidak akan dipublish — eventual consistency rusak.",
            ])

        m = re.search(r"'([A-Z]\w*(?:Command|Query|Handler))'", msg)
        if m:
            evidence.append(f"Class yang bermasalah: {m.group(1)}")
            confidence = 0.88

        cqrs_frames = [
            f for f in frames
            if self._CMD_PATTERN.search(f"{f.name} {f.filename}")
            or self._QRY_PATTERN.search(f"{f.name} {f.filename}")
        ]
        if cqrs_frames:
            frame = cqrs_frames[-1]
            evidence.append(f"Frame CQRS: {frame.name} di {frame.filename}:{frame.lineno}")
            code = get_code_context(frame.filename, frame.lineno)
            evidence.extend(code[:5])

        return RCAResult(
            severity=Severity.CRITICAL, category=Category.CQRS, error_code=error_code,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=msg, confidence=confidence,
        )

# ─── DomainRepositoryMismatchRule ──────────────────────────────────────────
class DomainRepositoryMismatchRule(RCARule):
    _REPO_PATTERN = re.compile(r"\breep(ository)?\b|\brepository\b", re.IGNORECASE)

    def __init__(self) -> None:
        super().__init__(priority=70, category=Category.DDD, name="RepositoryMismatchRule")

    def match(self, exc, frames, context) -> bool:
        if self._REPO_PATTERN.search(str(exc)):
            return True
        for f in frames:
            if self._REPO_PATTERN.search(f.name) or self._REPO_PATTERN.search(f.filename):
                return True
        return False

    def analyze(self, exc, frames, context) -> RCAResult | None:
        evidence   : list[str] = []
        impact     : list[str] = []
        severity   = Severity.CRITICAL
        confidence = DEFAULT_CONFIDENCE
        root_cause = suggested_fix = ""

        repo_frames = [
            f for f in frames
            if self._REPO_PATTERN.search(f.name) or self._REPO_PATTERN.search(f.filename)
        ]
        if repo_frames:
            frame = repo_frames[-1]
            evidence.append(f"Frame Repository: {frame.name} di {frame.filename}:{frame.lineno}")
            code = get_code_context(frame.filename, frame.lineno)
            evidence.extend(code[:5])
            mn = frame.name.lower()
            if "save" in mn:
                root_cause    = "Repository.save() gagal — kemungkinan mismatch skema atau constraint DB."
                suggested_fix = "Periksa mapping entitas ke tabel dan constraint database."
                confidence    = 0.75
            elif "find" in mn or "get" in mn or "fetch" in mn:
                root_cause    = "Repository query gagal — kemungkinan kolom/filter tidak valid."
                suggested_fix = "Periksa parameter query dan pastikan kolom ada di tabel."
                confidence    = 0.7
            elif "match" in mn:
                root_cause    = "Repository.match() tidak cocok dengan interface port."
                suggested_fix = "Pastikan implementasi match() sesuai dengan port yang diharapkan."
                confidence    = 0.7
            else:
                root_cause    = f"Repository method '{frame.name}' gagal."
                suggested_fix = "Periksa implementasi Repository terhadap interface port."
            impact.append("Semua operasi yang menggunakan repository ini akan gagal.")
        else:
            root_cause    = "Error berkaitan dengan Repository tanpa frame spesifik."
            suggested_fix = "Periksa implementasi Repository dan unit test."
            impact.append("Operasi repository mungkin bermasalah.")

        return RCAResult(
            severity=severity, category=Category.DDD, error_code=ErrorCode.REPOSITORY_MISMATCH,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=str(exc), confidence=confidence,
        )

# ─── EventPublishRule ──────────────────────────────────────────────────────
class EventPublishRule(RCARule):
    _EVENT_PATTERN = re.compile(
        r"\b(publish|dispatch|emit|event[_\s]bus|event[_\s]handler|domain[_\s]event)\b",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        super().__init__(priority=70, category=Category.DDD, name="EventPublishRule")

    def match(self, exc, frames, context) -> bool:
        if self._EVENT_PATTERN.search(str(exc)):
            return True
        for f in frames:
            if self._EVENT_PATTERN.search(f.name) or self._EVENT_PATTERN.search(f.filename):
                return True
        return False

    def analyze(self, exc, frames, context) -> RCAResult | None:
        evidence   : list[str] = []
        impact     : list[str] = []
        severity   = Severity.CRITICAL
        confidence = DEFAULT_CONFIDENCE
        root_cause = suggested_fix = ""

        event_frames = [
            f for f in frames
            if self._EVENT_PATTERN.search(f.name) or self._EVENT_PATTERN.search(f.filename)
        ]
        if event_frames:
            frame = event_frames[-1]
            evidence.append(f"Frame Event: {frame.name} di {frame.filename}:{frame.lineno}")
            code = get_code_context(frame.filename, frame.lineno)
            evidence.extend(code[:5])
            msg_lower = str(exc).lower()
            if "handler" in msg_lower or "listener" in msg_lower:
                root_cause    = "Event handler/listener tidak terdaftar di EventBus."
                suggested_fix = "Pastikan semua handler didaftarkan sebelum event dipublish."
                confidence    = 0.8
            else:
                root_cause    = f"Gagal publish/dispatch event: {str(exc)[:100]}"
                suggested_fix = "Periksa payload event dan pastikan EventBus aktif."
            impact.append("Event tidak diproses → efek samping hilang (notifikasi, audit log, update status).")
        else:
            root_cause    = "Error event tanpa frame spesifik."
            suggested_fix = "Periksa konfigurasi EventBus dan registrasi handler."

        return RCAResult(
            severity=severity, category=Category.DDD, error_code=ErrorCode.EVENT_PUBLISH_FAIL,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=str(exc), confidence=confidence,
        )

# ─── ContainerErrorRule ─────────────────────────────────────────────────────
class ContainerErrorRule(RCARule):
    _CONTAINER_KEYWORDS = re.compile(
        r"\b(container|dependency[_\s]injection|di[_\s]container|ioc|"
        r"resolve[_\s]service|service[_\s]provider|get\s*service|make\s*service)\b",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        super().__init__(priority=70, category=Category.DI, name="ContainerErrorRule")

    def match(self, exc, frames, context) -> bool:
        if self._CONTAINER_KEYWORDS.search(str(exc)):
            return True
        for f in frames:
            if self._CONTAINER_KEYWORDS.search(f"{f.name} {f.filename}"):
                return True
        return False

    def analyze(self, exc, frames, context) -> RCAResult | None:
        evidence   : list[str] = []
        impact     : list[str] = []
        severity   = Severity.CRITICAL
        confidence = DEFAULT_CONFIDENCE
        root_cause = suggested_fix = ""

        container_frames = [
            f for f in frames
            if self._CONTAINER_KEYWORDS.search(f"{f.name} {f.filename}")
        ]
        if container_frames:
            frame = container_frames[-1]
            evidence.append(f"Frame Container: {frame.name} di {frame.filename}:{frame.lineno}")
            code = get_code_context(frame.filename, frame.lineno)
            evidence.extend(code[:5])
            m = re.search(r"unable to resolve '([^']+)'", str(exc), re.IGNORECASE)
            if m:
                svc           = m.group(1)
                root_cause    = f"Service '{svc}' tidak terdaftar di container."
                suggested_fix = f"Daftarkan '{svc}' beserta semua dependency-nya di container."
                confidence    = 0.9
                evidence.append(f"Service yang gagal di-resolve: {svc}")
            elif "bind" in frame.name.lower():
                root_cause    = "Binding interface→implementasi gagal di container."
                suggested_fix = "Periksa binding di container — pastikan interface dan implementasi sesuai."
            else:
                root_cause    = f"Container error: {str(exc)[:100]}"
                suggested_fix = "Periksa konfigurasi container dan registrasi service."
            impact.append("Semua service yang bergantung pada container tidak dapat di-resolve.")
        else:
            root_cause    = "Error container tanpa frame spesifik."
            suggested_fix = "Periksa registrasi service di container."

        return RCAResult(
            severity=severity, category=Category.DI, error_code=ErrorCode.CONTAINER_RESOLVE_FAIL,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=str(exc), confidence=confidence,
        )

# ─── AggregateErrorRule ────────────────────────────────────────────────────
class AggregateErrorRule(RCARule):
    def __init__(self) -> None:
        super().__init__(priority=62, category=Category.DDD, name="AggregateErrorRule")

    def match(self, exc, frames, context) -> bool:
        if "aggregate" in str(exc).lower():
            return True
        for f in frames:
            if "aggregate" in f.name.lower() or "aggregate" in f.filename.lower():
                return True
        return False

    def analyze(self, exc, frames, context) -> RCAResult | None:
        evidence   : list[str] = []
        impact     : list[str] = []
        severity   = Severity.CRITICAL
        confidence = DEFAULT_CONFIDENCE
        root_cause = suggested_fix = ""

        agg_frames = [
            f for f in frames
            if "aggregate" in f.name.lower() or "aggregate" in f.filename.lower()
        ]
        if agg_frames:
            frame = agg_frames[-1]
            evidence.append(f"Frame Aggregate: {frame.name} di {frame.filename}:{frame.lineno}")
            code = get_code_context(frame.filename, frame.lineno)
            evidence.extend(code[:5])
            mn = frame.name.lower()
            if "apply" in mn or "when" in mn:
                root_cause    = "Event handler di Aggregate gagal — event tidak dikenal atau state tidak valid."
                suggested_fix = "Periksa method apply()/when() pada Aggregate, pastikan event sesuai tipe yang diharapkan."
                confidence    = 0.7
            elif "raise_event" in mn or "add_event" in mn:
                root_cause    = "Aggregate gagal menambahkan domain event."
                suggested_fix = "Periksa apakah EventBus aktif dan event terdaftar."
            else:
                root_cause    = f"Error pada Aggregate: {str(exc)[:100]}"
                suggested_fix = "Periksa logika bisnis Aggregate dan invariant yang diberlakukan."
            impact.append("State aggregate gagal berubah — transaksi tidak konsisten.")
        else:
            root_cause    = "Error Aggregate tanpa frame spesifik."
            suggested_fix = "Periksa implementasi Aggregate dan event sourcing."

        return RCAResult(
            severity=severity, category=Category.DDD, error_code=ErrorCode.AGGREGATE_ERROR,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=str(exc), confidence=confidence,
        )

# ─── UnitOfWorkErrorRule ──────────────────────────────────────────────────
class UnitOfWorkErrorRule(RCARule):
    _UOW_PATTERN = re.compile(r"unitofwork|\buow\b", re.IGNORECASE)

    def __init__(self) -> None:
        super().__init__(priority=60, category=Category.DDD, name="UnitOfWorkErrorRule")

    def match(self, exc, frames, context) -> bool:
        if self._UOW_PATTERN.search(str(exc)):
            return True
        for f in frames:
            if self._UOW_PATTERN.search(f"{f.name} {f.filename}"):
                return True
        return False

    def analyze(self, exc, frames, context) -> RCAResult | None:
        evidence   : list[str] = []
        impact     : list[str] = []
        severity   = Severity.CRITICAL
        confidence = DEFAULT_CONFIDENCE
        root_cause = suggested_fix = ""

        uow_frames = [
            f for f in frames
            if self._UOW_PATTERN.search(f"{f.name} {f.filename}")
        ]
        if uow_frames:
            frame = uow_frames[-1]
            evidence.append(f"Frame UoW: {frame.name} di {frame.filename}:{frame.lineno}")
            code = get_code_context(frame.filename, frame.lineno)
            evidence.extend(code[:5])
            mn = frame.name.lower()
            if "commit" in mn:
                root_cause    = "Gagal commit UnitOfWork — constraint DB atau error repository."
                suggested_fix = "Periksa constraint database dan pastikan semua repository valid sebelum commit."
                confidence    = 0.8
            elif "rollback" in mn:
                root_cause    = "Rollback UoW dipicu — error di operasi sebelumnya."
                suggested_fix = "Periksa operasi dalam transaksi. Rollback adalah gejala, bukan penyebab."
            elif "__exit__" in mn:
                root_cause    = "UoW context manager keluar dengan exception — kemungkinan commit gagal."
                suggested_fix = "Periksa apakah exception ditangani sebelum UoW exit atau tambahkan explicit rollback."
                confidence    = 0.75
            else:
                root_cause    = f"Error UoW: {str(exc)[:100]}"
                suggested_fix = "Periksa manajemen transaksi di UnitOfWork."
            impact.append("Transaksi database tidak konsisten — data mungkin tidak tersimpan.")
        else:
            root_cause    = "Error UoW tanpa frame spesifik."
            suggested_fix = "Periksa implementasi UnitOfWork dan integrasi repository."

        return RCAResult(
            severity=severity, category=Category.DDD, error_code=ErrorCode.UOW_ERROR,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=str(exc), confidence=confidence,
        )

# ─── TransactionIntegrityRule ──────────────────────────────────────────────
class TransactionIntegrityRule(RCARule):
    _TX_KEYWORDS = frozenset({
        "unitofwork", "transaction", "uow", "commit", "rollback", "session",
    })

    def __init__(self) -> None:
        super().__init__(
            priority=65, category=Category.DATABASE, name="TransactionIntegrityRule"
        )

    def match(self, exc, frames, context) -> bool:
        db_types: tuple[type, ...] = (ValueError, RuntimeError)
        if HAS_SQLALCHEMY and _SQLAlchemyError is not None:
            db_types = db_types + (_SQLAlchemyError,)
        if not isinstance(exc, db_types):
            return False
        for f in frames:
            text = f"{f.filename} {f.name}".lower()
            if any(k in text for k in self._TX_KEYWORDS):
                return True
        return False

    def analyze(self, exc, frames, context) -> RCAResult | None:
        exc_type = type(exc).__name__
        evidence = [
            f"Tipe exception: {exc_type}",
            f"Pesan: {str(exc)[:200]}",
            f"Frame transaksi aktif: {[f.name for f in frames[-3:]]}",
        ]
        return RCAResult(
            severity=Severity.CRITICAL, category=Category.DATABASE,
            error_code=ErrorCode.TRANSACTION_INTEGRITY,
            root_cause=f"Kegagalan {exc_type} di dalam konteks transaksi database.",
            evidence=evidence,
            impact=[
                "Potensi data tidak konsisten (Database Inconsistency).",
                "Transaksi mungkin menggantung (Orphaned Transaction).",
            ],
            suggested_fix=(
                "Verifikasi status transaksi terakhir di DB. "
                "Pastikan rollback terpicu pada setiap exception path."
            ),
            raw_error=str(exc), confidence=0.9,
        )

# ─── RecursionMemoryRule ──────────────────────────────────────────────────
class RecursionMemoryRule(RCARule):
    def __init__(self) -> None:
        super().__init__(
            priority=95, category=Category.PERFORMANCE, name="RecursionMemoryRule"
        )

    def match(self, exc, frames, context) -> bool:
        return isinstance(exc, (RecursionError, MemoryError))

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg      = str(exc)
        evidence : list[str] = []
        impact   : list[str] = []

        if isinstance(exc, RecursionError):
            if frames:
                names = [f.name for f in frames]
                top   = Counter(names).most_common(3)
                evidence.append(f"Fungsi yang paling banyak di stack: {top}")
                for fn, cnt in top:
                    if cnt > 5:
                        evidence.append(
                            f"Fungsi '{fn}' muncul {cnt}x di stack — kemungkinan infinite recursion."
                        )

            return RCAResult(
                severity=Severity.HIGH, category=Category.PERFORMANCE,
                error_code=ErrorCode.RECURSION_LIMIT,
                root_cause=(
                    "RecursionError: stack melebihi batas (default 1000 frame). "
                    "Kemungkinan infinite recursion atau struktur data circular."
                ),
                evidence=evidence,
                impact=[
                    "Proses batch ERP berhenti total.",
                    "Stack frame yang besar mengonsumsi memory — bisa trigger MemoryError.",
                ],
                suggested_fix=(
                    "1. Konversi rekursi ke iterasi menggunakan stack eksplisit. "
                    "2. Tambahkan base case yang tepat di fungsi rekursif. "
                    "3. Periksa apakah ada circular reference di objek domain. "
                    "4. Catatan: sys.setrecursionlimit() BUKAN solusi jangka panjang."
                ),
                raw_error=msg, confidence=0.92,
            )

        else:  # MemoryError
            if frames:
                last_frame = frames[-1]
                evidence.append(
                    f"MemoryError terjadi di: {last_frame.filename}:{last_frame.lineno}"
                )
                frame_count = len(frames)
                if frame_count > 20:
                    evidence.append(
                        f"Stack depth: {frame_count} frames — kemungkinan kebocoran memory."
                    )
            else:
                evidence.append("MemoryError (tidak ada traceback tersedia)")

            return RCAResult(
                severity=Severity.FATAL, category=Category.PERFORMANCE,
                error_code=ErrorCode.MEMORY_ERROR,
                root_cause=(
                    "Proses kehabisan memory. Di ERP, penyebab umum: "
                    "query tanpa limit yang mengambil jutaan row, "
                    "atau batch processing yang tidak menggunakan chunking."
                ),
                evidence=evidence,
                impact=[
                    "Proses ERP crash — data yang sedang diproses mungkin tidak tersimpan.",
                    "Server mungkin memerlukan restart — downtime.",
                    "Transaksi aktif akan di-rollback.",
                ],
                suggested_fix=(
                    "1. Gunakan pagination/chunking untuk query besar: query.yield_per(1000). "
                    "2. Hindari load seluruh dataset ke memory — gunakan generator. "
                    "3. Periksa apakah ada list yang terus bertambah tanpa dibersihkan. "
                    "4. Pertimbangkan meningkatkan memory server atau optimasi query."
                ),
                raw_error=msg, confidence=0.9,
            )

# ─── PermissionFileRule ────────────────────────────────────────────────────
class PermissionFileRule(RCARule):
    _CONFIG_EXTENSIONS = frozenset({'.py', '.cfg', '.ini', '.yaml', '.yml', '.env', '.json', '.toml'})

    def __init__(self) -> None:
        super().__init__(
            priority=88, category=Category.SECURITY, name="PermissionFileRule"
        )

    def match(self, exc, frames, context) -> bool:
        return isinstance(exc, (PermissionError, FileNotFoundError, IsADirectoryError, NotADirectoryError))

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg        = str(exc)
        raw        = msg
        evidence   : list[str] = []
        impact     : list[str] = []
        error_code = (
            ErrorCode.PERMISSION_DENIED if isinstance(exc, PermissionError)
            else ErrorCode.FILE_NOT_FOUND
        )
        severity = Severity.HIGH

        m    = re.search(r"'([^']+)'", msg)
        path = m.group(1) if m else None

        if isinstance(exc, PermissionError):
            root_cause    = f"Akses ditolak ke: {path or 'file/direktori'}"
            suggested_fix = (
                f"Periksa permission file/direktori: chmod 755 {path or '<path>'}. "
                "Pastikan user yang menjalankan ERP memiliki akses yang diperlukan. "
                "Di produksi, hindari menjalankan sebagai root."
            )
            evidence.append(f"Path yang ditolak: {path}")
            if path:
                evidence.append(f"Cek permission: ls -la {path}")
            impact.extend([
                "Operasi file/export/import di ERP gagal.",
                "Laporan yang memerlukan akses filesystem tidak bisa dibuat.",
            ])
        elif isinstance(exc, FileNotFoundError):
            root_cause    = f"File atau direktori tidak ditemukan: {path or 'unknown'}"
            suggested_fix = (
                f"Pastikan file '{path}' ada dan path benar. "
                "Periksa konfigurasi MEDIA_ROOT/STATIC_ROOT di ERP. "
                "Untuk template/config file, pastikan deployment menyertakan file tersebut."
            )
            evidence.append(f"Path yang tidak ditemukan: {path}")
            if path and Path(path).suffix in self._CONFIG_EXTENSIONS:
                evidence.append("File konfigurasi hilang — kemungkinan deployment tidak lengkap.")
                severity = Severity.CRITICAL
                impact.append("Konfigurasi ERP tidak lengkap — sistem mungkin tidak bisa start.")
            impact.append("Operasi yang memerlukan file ini tidak bisa berjalan.")
        else:
            root_cause    = f"Error file system: {type(exc).__name__}: {msg}"
            suggested_fix = "Periksa struktur direktori dan permission."
            impact.append("Operasi filesystem gagal.")

        if frames:
            frame = frames[-1]
            code  = get_code_context(frame.filename, frame.lineno)
            err   = _get_error_line(code, frame.lineno)
            if err:
                evidence.append(f"Baris {frame.lineno}: {err}")

        return RCAResult(
            severity=severity, category=Category.SECURITY, error_code=error_code,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=raw, confidence=0.9,
        )

# ─── PROJECT‑SPECIFIC RULES (semua digabung di sini, tidak ada duplikasi) ──

class AxiomViolationRule(RCARule):
    _AXIOM_PATTERNS: list[tuple[re.Pattern, str, str, Severity]] = [
        (
            re.compile(
                r"(double.?entry|debit.*credit.*unbalanced|credit.*debit.*unbalanced|"
                r"total.debit.*!=.*total.credit|jurnal.tidak.seimbang|unbalanced.journal)",
                re.I,
            ),
            "Pelanggaran aksioma Double-Entry: total debit ≠ total kredit.",
            "Validasi setiap JournalEntry: sum(debit_lines) == sum(credit_lines) "
            "sebelum persist. Periksa axioms/double_entry.py untuk constraint.",
            Severity.FATAL,
        ),
        (
            re.compile(
                r"(immutab|posted.journal.*modif|journal.*sudah.diposting|"
                r"cannot.modif.*posted|ImmutabilityViolation|tamper)",
                re.I,
            ),
            "Pelanggaran aksioma Immutability: journal yang sudah diposting tidak boleh diubah.",
            "Gunakan reversal journal (reverse_journal use-case) bukan edit langsung. "
            "Lihat axioms/immutability.py dan application/use_cases/reverse_journal.py.",
            Severity.FATAL,
        ),
        (
            re.compile(
                r"(accrual.basis|cash.basis.*not.allowed|AccrualBasisViolation|"
                r"transaksi.*belum.jatuh.tempo.*diakui|revenue.recognition.violation)",
                re.I,
            ),
            "Pelanggaran aksioma Accrual Basis: pengakuan pendapatan/biaya tidak sesuai periode.",
            "Periksa axioms/accrual_basis.py. Gunakan fiscal period yang benar. "
            "Revenue hanya diakui saat sudah earned (IFRS 15 / PSAK 72).",
            Severity.CRITICAL,
        ),
        (
            re.compile(
                r"(conservation.of.value|nilai.tidak.konsisten|ConservationOfValueError|"
                r"entity.isolation.*violated|cross.entity.contamination)",
                re.I,
            ),
            "Pelanggaran aksioma Conservation of Value atau Entity Isolation.",
            "Pastikan transaksi antar entitas (intercompany) menggunakan "
            "elimination entries. Lihat axioms/entity_isolation.py dan "
            "application/use_cases/intercompany_elimination.py.",
            Severity.CRITICAL,
        ),
        (
            re.compile(
                r"(AxiomViolation|axiom.*violation|pelanggaran.aksioma)",
                re.I,
            ),
            "Pelanggaran aksioma akuntansi terdeteksi.",
            "Periksa axioms/ untuk daftar lengkap aksioma. "
            "Trace exception ke axiom spesifik yang dilanggar.",
            Severity.FATAL,
        ),
    ]

    def __init__(self) -> None:
        super().__init__(priority=200, category=Category.DDD, name="AxiomViolationRule")

    def match(self, exc, frames, context) -> bool:
        cls_name = type(exc).__name__
        if any(k in cls_name for k in (
            "AxiomViolation", "DoubleEntry", "Immutability",
            "AccrualBasis", "ConservationOfValue", "EntityIsolation",
        )):
            return True
        msg = str(exc).lower()
        return any(p.search(msg) for p, *_ in self._AXIOM_PATTERNS)

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg = str(exc)
        for pattern, root_cause, fix, sev in self._AXIOM_PATTERNS:
            if pattern.search(msg):
                evidence = [f"Exception: {type(exc).__name__}: {msg[:300]}"]
                if frames:
                    frame = frames[-1]
                    code  = get_code_context(frame.filename, frame.lineno)
                    line  = _get_error_line(code, frame.lineno)
                    if line:
                        evidence.append(f"Lokasi: {frame.filename}:{frame.lineno} → {line}")
                    axiom_frames = [f for f in frames if "axiom" in f.filename.lower()]
                    if axiom_frames:
                        evidence.append(
                            f"Axiom file: {axiom_frames[-1].filename}:{axiom_frames[-1].lineno}"
                        )
                return RCAResult(
                    severity=sev, category=Category.DDD,
                    error_code=ErrorCode.ERP_VALIDATION,
                    root_cause=root_cause, evidence=evidence,
                    impact=[
                        "Integritas data akuntansi KRITIS terancam.",
                        "Laporan keuangan tidak dapat dipercaya jika ini lolos.",
                        "Auditor eksternal akan menolak laporan dengan temuan ini.",
                    ],
                    suggested_fix=fix, raw_error=msg, confidence=0.95,
                )
        return None

# ─── ConstitutionViolationRule ─────────────────────────────────────────────
class ConstitutionViolationRule(RCARule):
    _CONST_PATTERN = re.compile(
        r"(ConstitutionViolation|ForbiddenState|InvariantBroken|"
        r"SovereigntyViolation|constitutional.*invariant|"
        r"forbidden.state.detected|supreme.law.violated|"
        r"enforcement.engine.*reject)",
        re.I,
    )

    def __init__(self) -> None:
        super().__init__(priority=195, category=Category.DDD, name="ConstitutionViolationRule")

    def match(self, exc, frames, context) -> bool:
        return bool(self._CONST_PATTERN.search(str(exc))) or \
               any("constitution" in f.filename.lower() for f in frames)

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg    = str(exc)
        cframes= [f for f in frames if "constitution" in f.filename.lower()]
        evidence = [f"Constitutional violation: {type(exc).__name__}: {msg[:300]}"]
        if cframes:
            evidence.append(f"Constitution module: {cframes[-1].filename}:{cframes[-1].lineno}")
        return RCAResult(
            severity=Severity.FATAL, category=Category.DDD,
            error_code=ErrorCode.ERP_VALIDATION,
            root_cause=(
                "Pelanggaran Constitutional Invariant — kondisi yang dilarang secara absolut "
                "oleh constitution/forbidden_states.py terdeteksi. "
                "Sistem masuk ke state yang tidak valid."
            ),
            evidence=evidence,
            impact=[
                "Sistem ERP dalam kondisi tidak valid (forbidden state).",
                "Semua operasi berikutnya akan menghasilkan data tidak konsisten.",
                "Diperlukan rollback dan forensic audit segera.",
            ],
            suggested_fix=(
                "1. Hentikan operasi segera — jangan lanjutkan transaksi. "
                "2. Jalankan application/use_cases/disaster_recovery_replay.py untuk forensik. "
                "3. Periksa constitution/forbidden_states.py untuk state yang dilanggar. "
                "4. Gunakan constitution/amendment_protocol.py jika aturan perlu diubah (prosedur formal)."
            ),
            raw_error=msg, confidence=0.97,
        )

# ─── KernelGuardViolationRule ─────────────────────────────────────────────
class KernelGuardViolationRule(RCARule):
    _GUARD_PATTERNS: list[tuple[re.Pattern, str, str, str, Severity]] = [
        (
            re.compile(r"(PeriodLock|period.*locked|period.*closed|tutup.buku|"
                       r"fiscal.*period.*lock|posting.*closed.*period)", re.I),
            "PeriodLockViolation",
            "Periode fiskal sudah dikunci — tidak ada posting yang diizinkan.",
            "Minta approval dari Finance Manager untuk reopen period "
            "(application/use_cases/period_reopen_with_audit.py). "
            "Audit trail akan dicatat di audit/event_writer_immutable.py.",
            Severity.CRITICAL,
        ),
        (
            re.compile(r"(SodViolation|segregation.of.duties|sod.*enforc|"
                       r"user.*tidak.bisa.*approve.*sendiri|four.eyes|"
                       r"same.user.*creator.*approver)", re.I),
            "SodViolation (Segregation of Duties)",
            "Pelanggaran Segregation of Duties — user yang sama tidak boleh "
            "membuat dan menyetujui transaksi.",
            "Gunakan four-eyes approval workflow: "
            "application/use_cases/approve_journal_four_eyes.py. "
            "Periksa kernel/guards/sod_enforcer.py untuk aturan SOD.",
            Severity.FATAL,
        ),
        (
            re.compile(r"(BudgetExhausted|BudgetNotApproved|budget.*exceeded|"
                       r"melebihi.anggaran|over.budget|budget.*not.*available|"
                       r"BudgetAvailability)", re.I),
            "BudgetExhausted / BudgetNotApproved",
            "Transaksi melebihi anggaran yang tersedia atau anggaran belum disetujui.",
            "Periksa saldo anggaran di domain/budget/. "
            "Ajukan budget revision atau minta authorization dari budget owner. "
            "Lihat kernel/guards/budget_availability.py.",
            Severity.HIGH,
        ),
        (
            re.compile(r"(CreditLimitExceeded|credit.limit|batas.kredit|"
                       r"piutang.*melebihi.limit|over.credit.limit)", re.I),
            "CreditLimitExceeded",
            "Transaksi AR/penjualan melebihi credit limit pelanggan.",
            "Periksa domain/subledger_ar/ untuk credit limit pelanggan. "
            "Minta approval dari Credit Manager atau ubah credit limit di master data.",
            Severity.HIGH,
        ),
        (
            re.compile(r"(UnauthorizedOperation|not.authorized|tidak.berwenang|"
                       r"authority.matrix|tidak.memiliki.hak|permission.denied.*erp|"
                       r"AuthorityMatrix)", re.I),
            "UnauthorizedOperation",
            "Operasi tidak diizinkan — user tidak ada di authority matrix.",
            "Periksa kernel/guards/authority_matrix.py untuk permission yang diperlukan. "
            "Hubungi IAM administrator untuk grant permission: domain/iam/.",
            Severity.CRITICAL,
        ),
        (
            re.compile(r"(SystemFrozen|EmergencyFreeze|sistem.*dibekukan|"
                       r"emergency.freeze|system.frozen)", re.I),
            "SystemFrozenError (Emergency Freeze)",
            "Sistem ERP dalam kondisi Emergency Freeze — semua operasi diblokir.",
            "Hanya Super Admin yang bisa unfreeze: kernel/guards/emergency_freeze.py. "
            "Cari tahu penyebab freeze di audit/tamper_alert_trigger.py. "
            "Jangan bypass — ini keamanan darurat.",
            Severity.FATAL,
        ),
        (
            re.compile(r"(LegalEntityBoundary|batas.entitas.hukum|"
                       r"cross.entity.*not.allowed|intercompany.*not.configured|"
                       r"legal.entity.*mismatch)", re.I),
            "LegalEntityBoundaryViolation",
            "Transaksi melintasi batas entitas hukum yang tidak dikonfigurasi.",
            "Konfigurasikan intercompany relationship di domain/legal_entity/. "
            "Gunakan application/use_cases/intercompany_elimination.py untuk "
            "eliminasi transaksi lintas entitas yang valid.",
            Severity.CRITICAL,
        ),
        (
            re.compile(r"(AMLFlag|AMLFlagged|anti.money.laundering|suspicious.*transaction|"
                       r"transaksi.*mencurigakan|aml.*risk.score)", re.I),
            "AMLFlaggedTransaction",
            "Transaksi ditandai sebagai mencurigakan oleh sistem AML.",
            "Transaksi diblokir oleh kernel/guards/async_guards/anti_money_laundering.py. "
            "Review di compliance/aml_risk_scorer.py dan laporkan sesuai prosedur PPATK "
            "jika diperlukan. Jangan release tanpa persetujuan Compliance Officer.",
            Severity.FATAL,
        ),
        (
            re.compile(r"(FraudPattern|fraud.*detected|pola.*kecurangan|"
                       r"FraudPatternDetected|anomali.*transaksi)", re.I),
            "FraudPatternDetected",
            "Pola kecurangan terdeteksi oleh fraud detection engine.",
            "Transaksi diblokir oleh kernel/guards/async_guards/fraud_pattern_detector.py. "
            "Eskalasi ke Internal Audit segera. "
            "Jalankan audit/forensic_replayer.py untuk investigasi trail.",
            Severity.FATAL,
        ),
        (
            re.compile(r"(CurrencyMismatch|mata.uang.*tidak.cocok|currency.*mismatch|"
                       r"CurrencyValidat|forex.*rate.*missing)", re.I),
            "CurrencyMismatchError",
            "Mismatch mata uang — kurs tidak tersedia atau kode currency salah.",
            "Periksa domain/forex/ untuk kurs yang diperlukan. "
            "Jalankan application/use_cases/forex_revaluation.py jika kurs expired. "
            "Lihat kernel/guards/currency_validator.py.",
            Severity.HIGH,
        ),
        (
            re.compile(r"(TemporalConsistency|temporal.*violation|"
                       r"tanggal.*transaksi.*sebelum.*posting|backdate.*not.allowed)", re.I),
            "TemporalConsistencyError",
            "Pelanggaran konsistensi temporal — tanggal transaksi tidak valid.",
            "Periksa kernel/guards/temporal_consistency.py. "
            "Backdate hanya diizinkan dengan approval khusus di dalam periode yang terbuka.",
            Severity.HIGH,
        ),
        (
            re.compile(r"(RegulatoryViolation|regulat.*violat|kepatuhan.*gagal|"
                       r"compliance.*failed|OJK|PPATK|DJP.*rejected)", re.I),
            "RegulatoryViolation",
            "Pelanggaran aturan regulasi (OJK/PPATK/DJP) terdeteksi.",
            "Periksa compliance/ dan policy_engine/ untuk aturan yang dilanggar. "
            "Hubungi Compliance Officer sebelum melanjutkan.",
            Severity.FATAL,
        ),
    ]

    def __init__(self) -> None:
        super().__init__(priority=190, category=Category.DDD, name="KernelGuardViolationRule")

    def match(self, exc, frames, context) -> bool:
        cls_name = type(exc).__name__
        guard_class_patterns = (
            "PeriodLock", "SodViolation", "Budget", "CreditLimit",
            "Unauthorized", "SystemFrozen", "LegalEntity", "AML", "Fraud",
            "CurrencyMismatch", "Temporal", "Regulatory", "GuardException",
        )
        if any(k in cls_name for k in guard_class_patterns):
            return True
        if any("kernel/guards" in f.filename.replace("\\", "/").lower() or
               "kernel\\guards" in f.filename.lower()
               for f in frames):
            return True
        msg = str(exc)
        return any(p.search(msg) for p, *_ in self._GUARD_PATTERNS)

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg = str(exc)
        for pattern, exc_type, root_cause, fix, sev in self._GUARD_PATTERNS:
            if pattern.search(msg) or exc_type.lower().replace(" ", "") in type(exc).__name__.lower():
                evidence = [
                    f"Guard violation: {type(exc).__name__}",
                    f"Message: {msg[:300]}",
                ]
                guard_frames = [
                    f for f in frames
                    if "guard" in f.filename.replace("\\", "/").lower()
                ]
                if guard_frames:
                    gf = guard_frames[-1]
                    evidence.append(f"Guard file: {gf.filename}:{gf.lineno} in {gf.name}")
                if frames:
                    caller = frames[0]
                    evidence.append(
                        f"Dipanggil dari: {caller.filename}:{caller.lineno} in {caller.name}"
                    )
                return RCAResult(
                    severity=sev, category=Category.DDD,
                    error_code=ErrorCode.PERMISSION_DENIED
                    if "Unauthorized" in exc_type else ErrorCode.ERP_VALIDATION,
                    root_cause=root_cause, evidence=evidence,
                    impact=self._impact_for(exc_type),
                    suggested_fix=fix, raw_error=msg, confidence=0.93,
                )
        if any("kernel/guard" in f.filename.replace("\\","/").lower() for f in frames):
            return RCAResult(
                severity=Severity.CRITICAL, category=Category.DDD,
                error_code=ErrorCode.ERP_VALIDATION,
                root_cause=f"Kernel guard menolak operasi: {type(exc).__name__}",
                evidence=[f"Guard error: {msg[:300]}"],
                impact=["Operasi ditolak oleh sistem keamanan ERP."],
                suggested_fix="Periksa kernel/guards/ untuk guard yang aktif dan aturannya.",
                raw_error=msg, confidence=0.8,
            )
        return None

    @staticmethod
    def _impact_for(exc_type: str) -> list[str]:
        _impacts: dict[str, list[str]] = {
            "SodViolation": [
                "Pelanggaran SOD adalah temuan audit KRITIKAL (SOX control failure).",
                "Jika lolos, menciptakan risiko fraud dan salah saji material.",
                "Auditor Big 4 akan menerbitkan qualified opinion.",
            ],
            "AMLFlagged": [
                "Transaksi mencurigakan harus dilaporkan ke PPATK dalam 3 hari kerja.",
                "Kegagalan lapor = sanksi pidana bagi direksi.",
            ],
            "FraudPattern": [
                "Potensi kerugian finansial langsung.",
                "Reputasi perusahaan berisiko jika tidak segera ditangani.",
            ],
        }
        for key, impacts in _impacts.items():
            if key.lower() in exc_type.lower():
                return impacts
        return [
            "Operasi ditolak oleh kernel guard — tidak ada data yang dimodifikasi.",
            "Perlu tindakan korektif sebelum transaksi bisa dilanjutkan.",
        ]

# ─── InfrastructureDatabaseRule ────────────────────────────────────────────
class InfrastructureDatabaseRule(RCARule):
    _DB_PATTERNS = re.compile(
        r"(DatabaseException|ConnectionPoolExhausted|DatabaseTimeout|"
        r"DeadlockDetected|ForeignKeyViolation|UniqueConstraintViolation|"
        r"CheckConstraintViolation|NullConstraintViolation|"
        r"SchemaVersionMismatch|MigrationPending|"
        r"sqlalchemy.*error|psycopg2.*error|asyncpg.*error|"
        r"could not serialize access|deadlock detected|"
        r"duplicate key.*violates unique|"
        r"null value.*violates not-null|"
        r"foreign key.*violates|migration.*pending|"
        r"relation.*does not exist|column.*does not exist|"
        r"too many connections|remaining connection slots|"
        r"SSL connection.*been closed|server unexpectedly closed|"
        r"OperationalError|IntegrityError)",
        re.I,
    )

    _TABLE_TO_DOMAIN: dict[str, str] = {
        "journal": "domain/journal — Periksa JournalEntry aggregate",
        "account": "domain/coa — Periksa CoA aggregate",
        "ap_invoice": "domain/subledger_ap — Periksa AP Invoice aggregate",
        "ar_invoice": "domain/subledger_ar — Periksa AR Invoice aggregate",
        "payroll": "domain/payroll — Periksa Payroll aggregate",
        "fiscal_period": "domain/fiscal_period — Periksa FiscalPeriod",
        "fixed_asset": "domain/fixed_asset — Periksa FixedAsset aggregate",
        "inventory": "domain/inventory — Periksa Inventory aggregate",
        "budget": "domain/budget — Periksa Budget aggregate",
        "purchase_order": "domain/purchase_sales — Periksa PO aggregate",
        "sales_order": "domain/purchase_sales — Periksa SO aggregate",
        "tax": "domain/tax_transaction — Periksa TaxTransaction",
        "forex": "domain/forex — Periksa ForexRate",
        "audit_event": "audit/ — Audit event store bermasalah",
        "employee": "domain/customer_supplier_employee",
        "bank_cash": "domain/bank_cash — Periksa BankAccount aggregate",
        "manufacturing": "domain/manufacturing — Periksa Manufacturing aggregate",
    }

    def __init__(self) -> None:
        super().__init__(priority=185, category=Category.DATABASE, name="InfrastructureDatabaseRule")

    def match(self, exc, frames, context) -> bool:
        if self._DB_PATTERNS.search(str(exc)):
            return True
        cls_name = type(exc).__name__
        return any(k in cls_name for k in (
            "DatabaseException", "ConnectionPool", "Deadlock",
            "UniqueConstraint", "ForeignKey", "CheckConstraint",
            "Migration", "SchemaVersion", "SQLAlchemy",
            "OperationalError", "IntegrityError",
        ))

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg      = str(exc)
        evidence : list[str] = [f"DB Exception: {type(exc).__name__}: {msg[:300]}"]
        impact   : list[str] = []
        root_cause= suggested_fix = ""
        confidence= 0.85
        severity  = Severity.FATAL

        domain_hint = ""
        for f in frames:
            fname = f.filename.replace("\\", "/").lower()
            if "persistence_orm" in fname:
                for table_key, domain_desc in self._TABLE_TO_DOMAIN.items():
                    if table_key in fname:
                        domain_hint = domain_desc
                        evidence.append(f"ORM table file: {f.filename}")
                        break

        if re.search(r"deadlock", msg, re.I):
            root_cause    = "Deadlock terdeteksi di PostgreSQL — dua transaksi saling menunggu."
            suggested_fix = (
                "1. Pastikan urutan lock konsisten di seluruh aplikasi. "
                "2. Kurangi durasi transaksi — commit lebih awal. "
                "3. Periksa infrastructure/database/postgres_connection_pool_manager.py "
                "   untuk tuning pool timeout. "
                "4. Di production: aktifkan lock_timeout di PostgreSQL config."
            )
            impact.append("Semua transaksi yang terlibat di-rollback otomatis.")
            confidence = 0.92

        elif re.search(r"duplicate key|unique.*constraint|violates unique", msg, re.I):
            root_cause    = "Duplicate key violation — data yang sudah ada dicoba di-insert ulang."
            suggested_fix = (
                "1. Gunakan upsert pattern (INSERT ... ON CONFLICT DO UPDATE). "
                "2. Periksa apakah proses idempotency berjalan. "
                "3. Cek outbox pattern: application/outbox/outbox_relay_service.py "
                "   mungkin memproses event dua kali (at-least-once delivery)."
            )
            severity   = Severity.HIGH
            confidence = 0.9

        elif re.search(r"foreign key.*violates|violates.*foreign key", msg, re.I):
            root_cause    = "Foreign key violation — referenced record tidak ada."
            suggested_fix = (
                "1. Pastikan parent record dibuat sebelum child record. "
                "2. Periksa urutan insert di UnitOfWork (adapters/secondary_impl/sqlalchemy_unit_of_work_impl.py). "
                "3. Jika menggunakan Saga pattern, periksa saga state di application/sagas/."
            )
            severity   = Severity.CRITICAL
            confidence = 0.9

        elif re.search(r"too many connections|remaining connection slots", msg, re.I):
            root_cause    = "PostgreSQL connection pool habis — max_connections terlampaui."
            suggested_fix = (
                "1. Kurangi pool_size di config environment atau naikkan max_connections PostgreSQL. "
                "2. Pastikan semua session di-close setelah dipakai (gunakan UoW context manager). "
                "3. Aktifkan PgBouncer atau connection pooling di "
                "   infrastructure/database/postgres_connection_pool_manager.py. "
                "4. Periksa zombie connections dengan: SELECT count(*) FROM pg_stat_activity;"
            )
            impact.append("Semua request API baru akan gagal sampai connections freed.")
            confidence = 0.93

        elif re.search(r"migration.*pending|relation.*does not exist|column.*does not exist", msg, re.I):
            root_cause    = "Skema database tidak sinkron — migration belum dijalankan."
            suggested_fix = (
                "Jalankan: alembic upgrade head (dari folder migrations/). "
                "Periksa versi migration terbaru di migrations/. "
                "Pastikan deployment menjalankan migration sebelum start aplikasi."
            )
            severity   = Severity.FATAL
            confidence = 0.95

        else:
            root_cause    = f"Database error: {type(exc).__name__}: {msg[:200]}"
            suggested_fix = (
                "Periksa infrastructure/database/database_exceptions.py untuk error taxonomy. "
                "Cek PostgreSQL logs untuk detail error. "
                "Lihat infrastructure/telemetry/ untuk monitoring metrics."
            )

        if domain_hint:
            impact.append(f"Domain terdampak: {domain_hint}")
        impact.append("Operasi database gagal — data mungkin tidak tersimpan.")

        return RCAResult(
            severity=severity, category=Category.DATABASE,
            error_code=ErrorCode.DB_CONNECTION_FAIL,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=msg, confidence=confidence,
        )

# ─── MessageBrokerRule ─────────────────────────────────────────────────────
class MessageBrokerRule(RCARule):
    _BROKER_PATTERN = re.compile(
        r"(BrokerException|BrokerUnavailable|MessagePublishFailed|"
        r"ConsumerGroupError|DeadLetterQueueFull|DeadLetterQueue|"
        r"dead.letter|EventGatewayError|"
        r"KafkaProducerError|KafkaConsumerError|OutboxRelay|"
        r"event.*publish.*failed|domain.*event.*not.*sent|"
        r"outbox.*stuck|"
        r"message.*broker.*connection|topic.*not.*found|"
        r"consumer.*group.*rebalancing)",
        re.I,
    )

    def __init__(self) -> None:
        super().__init__(priority=180, category=Category.INFRASTRUCTURE, name="MessageBrokerRule")

    def match(self, exc, frames, context) -> bool:
        if self._BROKER_PATTERN.search(str(exc)):
            return True
        return any(
            any(k in f.filename.replace("\\", "/").lower()
                for k in ("kafka", "message_broker", "event_gateway", "outbox"))
            for f in frames
        )

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg     = str(exc)
        evidence= [f"Broker/Event error: {type(exc).__name__}: {msg[:300]}"]

        broker_frames = [
            f for f in frames
            if any(k in f.filename.replace("\\","/").lower()
                   for k in ("kafka", "message_broker", "event_gateway", "outbox"))
        ]
        if broker_frames:
            bf = broker_frames[-1]
            evidence.append(f"Broker file: {bf.filename}:{bf.lineno} in {bf.name}")

        if re.search(r"dead.letter|DeadLetter", msg, re.I):
            return RCAResult(
                severity=Severity.CRITICAL, category=Category.INFRASTRUCTURE,
                error_code=ErrorCode.KAFKA_FAIL,
                root_cause="Event masuk ke Dead Letter Queue — konsumer gagal memproses berulang kali.",
                evidence=evidence,
                impact=[
                    "Domain event tidak diproses — read model / projections tidak terupdate.",
                    "Eventual consistency rusak — UI bisa menampilkan data lama.",
                    "Jika outbox, transaksi DB sudah commit tapi event belum terkirim.",
                ],
                suggested_fix=(
                    "1. Periksa adapters/secondary_impl/kafka_dead_letter_handler.py "
                    "   untuk logic retry. "
                    "2. Inspect dead letter topic: kafka-console-consumer --topic dlq.*. "
                    "3. Fix konsumer error lalu replay dari DLQ. "
                    "4. Cek application/outbox/outbox_relay_service.py untuk stuck outbox."
                ),
                raw_error=msg, confidence=0.88,
            )

        if re.search(r"outbox.*stuck|OutboxRelay", msg, re.I):
            return RCAResult(
                severity=Severity.HIGH, category=Category.INFRASTRUCTURE,
                error_code=ErrorCode.KAFKA_FAIL,
                root_cause="Outbox relay stuck — event di tabel outbox tidak terkirim ke Kafka.",
                evidence=evidence,
                impact=[
                    "Domain events tertunda — subscriber tidak mendapat update.",
                    "Eventual consistency degraded.",
                ],
                suggested_fix=(
                    "1. Periksa application/outbox/outbox_poller.py — apakah poller berjalan. "
                    "2. Cek status tabel outbox di database. "
                    "3. Restart outbox relay service jika stuck."
                ),
                raw_error=msg, confidence=0.85,
            )

        return RCAResult(
            severity=Severity.FATAL, category=Category.INFRASTRUCTURE,
            error_code=ErrorCode.KAFKA_FAIL,
            root_cause=(
                "Message broker (Kafka) tidak tersedia atau error "
                f"— {type(exc).__name__}"
            ),
            evidence=evidence,
            impact=[
                "Domain events tidak terkirim — eventual consistency broken.",
                "Jika menggunakan Saga pattern, saga state mungkin terhenti.",
            ],
            suggested_fix=(
                "1. Periksa status Kafka broker. "
                "2. Cek adapters/secondary_impl/kafka_producer_wrapper.py "
                "   untuk retry/backoff configuration. "
                "3. Gunakan Outbox pattern (application/outbox/) sebagai fallback. "
                "4. Monitor di infrastructure/telemetry/."
            ),
            raw_error=msg, confidence=0.87,
        )

# ─── CachingRule ───────────────────────────────────────────────────────────
class CachingRule(RCARule):
    _CACHE_PATTERN = re.compile(
        r"(CachingException|CacheConnectionFailed|CacheSerializationError|"
        r"CacheKeyNotFound|RedisConnectionError|redis.*timeout|"
        r"cache.*miss.*critical|CacheInvalidationFailed|"
        r"lock.*acquisition.*failed|DistributedLockTimeout)",
        re.I,
    )

    def __init__(self) -> None:
        super().__init__(priority=170, category=Category.INFRASTRUCTURE, name="CachingRule")

    def match(self, exc, frames, context) -> bool:
        return self._CACHE_PATTERN.search(str(exc)) is not None or \
               any(k in type(exc).__name__ for k in ("Cache", "Redis", "Lock"))

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg = str(exc)
        if re.search(r"DistributedLock|lock.*acquisition", msg, re.I):
            return RCAResult(
                severity=Severity.HIGH, category=Category.INFRASTRUCTURE,
                error_code=ErrorCode.REDIS_FAIL,
                root_cause="Distributed lock tidak bisa diperoleh — mungkin ada proses lain yang memegang lock atau Redis down.",
                evidence=[f"Lock error: {msg[:200]}"],
                impact=["Operasi concurrent tidak bisa dieksekusi — terjadi bottleneck."],
                suggested_fix=(
                    "1. Periksa kernel/distributed_lock_redis.py untuk timeout config. "
                    "2. Pastikan Redis tersedia. "
                    "3. Periksa apakah ada lock yang tidak di-release (zombie lock)."
                ),
                raw_error=msg, confidence=0.88,
            )
        return RCAResult(
            severity=Severity.HIGH, category=Category.INFRASTRUCTURE,
            error_code=ErrorCode.REDIS_FAIL,
            root_cause=f"Cache layer error: {type(exc).__name__}: {msg[:200]}",
            evidence=[f"{type(exc).__name__}: {msg[:300]}"],
            impact=["Performa ERP degraded — setiap request harus ke database."],
            suggested_fix=(
                "1. Periksa status Redis server. "
                "2. Lihat infrastructure/caching/caching_exceptions.py. "
                "3. Aplikasi harus bisa fallback ke database jika cache down — "
                "   pastikan adapters/secondary_impl/redis_cache_adapter_impl.py "
                "   implementasikan graceful fallback."
            ),
            raw_error=msg, confidence=0.82,
        )

# ─── SagaOrchestrationRule ────────────────────────────────────────────────
class SagaOrchestrationRule(RCARule):
    _SAGA_PATTERN = re.compile(
        r"(SagaException|SagaCompensationFailed|SagaStepFailed|SagaTimeout|"
        r"SagaRollbackFailed|saga.*stuck|saga.*orphaned|"
        r"compensation.*failed|saga.*state.*invalid|"
        r"procurement.*saga|sales.*saga|payroll.*saga|"
        r"coretax.*saga|manufacturing.*saga)",
        re.I,
    )

    _SAGA_TYPES: dict[str, str] = {
        "procurement": "Procurement Saga (PO → GR → AP Invoice → Payment)",
        "sales"      : "Sales Saga (SO → Delivery → AR Invoice → Collection)",
        "payroll"    : "Payroll Saga (Payroll Run → Journal → Bank Transfer)",
        "coretax"    : "Coretax Submission Saga (Tax Filing → DJP Submission → Confirmation)",
        "manufacturing": "Manufacturing Saga (Work Order → BOM → Production → COGS)",
    }

    def __init__(self) -> None:
        super().__init__(priority=175, category=Category.DDD, name="SagaOrchestrationRule")

    def match(self, exc, frames, context) -> bool:
        if self._SAGA_PATTERN.search(str(exc)):
            return True
        if any(k in type(exc).__name__ for k in ("Saga", "Compensation")):
            return True
        return any("sagas" in f.filename.replace("\\", "/").lower() for f in frames)

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg         = str(exc)
        saga_frames = [f for f in frames if "sagas" in f.filename.replace("\\","/").lower()]
        evidence    = [f"Saga error: {type(exc).__name__}: {msg[:300]}"]

        saga_type = "Unknown Saga"
        for key, desc in self._SAGA_TYPES.items():
            if key in msg.lower() or any(key in f.filename.lower() for f in saga_frames):
                saga_type = desc
                break

        if saga_frames:
            sf = saga_frames[-1]
            evidence.append(f"Saga file: {sf.filename}:{sf.lineno} in {sf.name}")

        is_compensation = bool(re.search(r"compensation.*failed|compensat", msg, re.I))

        return RCAResult(
            severity=Severity.FATAL if is_compensation else Severity.CRITICAL,
            category=Category.DDD,
            error_code=ErrorCode.TRANSACTION_INTEGRITY,
            root_cause=(
                f"{'Kompensasi' if is_compensation else 'Eksekusi'} Saga gagal: {saga_type}. "
                f"Exception: {type(exc).__name__}: {msg[:150]}"
            ),
            evidence=evidence,
            impact=[
                f"Saga tidak selesai — state bisnis {saga_type} tidak konsisten.",
                "Data mungkin setengah-setengah: sebagian step sudah commit, sebagian belum.",
                "Kompensasi (rollback bisnis) diperlukan untuk semua step yang sudah sukses."
                if not is_compensation else
                "KRITIS: Kompensasi gagal — sistem dalam inconsistent state yang tidak bisa auto-recover.",
            ],
            suggested_fix=(
                "1. Periksa saga state di application/sagas/saga_state_store.py. "
                "2. Identifikasi step terakhir yang berhasil dari saga state. "
                "3. Jalankan manual compensation jika auto-compensation gagal. "
                "4. Lihat application/sagas/saga_orchestrator_base.py "
                "   untuk rollback mechanism. "
                "5. Monitor saga state di adapters/secondary_impl/saga_state_store_adapter.py."
                if not is_compensation else
                "KRITIS: "
                "1. Eskalasi ke Tim Teknis Senior segera. "
                "2. Jangan ada operasi baru sampai state di-resolve. "
                "3. Jalankan application/use_cases/disaster_recovery_replay.py. "
                "4. Manual data reconciliation mungkin diperlukan."
            ),
            raw_error=msg, confidence=0.91,
        )

# ─── BootstrapDIRule ───────────────────────────────────────────────────────
class BootstrapDIRule(RCARule):
    _DI_PATTERN = re.compile(
        r"(DIException|CircularDependency.*DI|ServiceNotRegistered|"
        r"PortNotBound|AdapterNotFound|BootstrapException|"
        r"DependencyResolutionFailed|ScopedContextError|"
        r"lifecycle.*hook.*failed|ioc.*container|"
        r"port.*not.*registered|adapter.*not.*found|"
        r"cannot.*resolve.*service|dependency.*cycle.*detected)",
        re.I,
    )

    def __init__(self) -> None:
        super().__init__(priority=180, category=Category.DI, name="BootstrapDIRule")

    def match(self, exc, frames, context) -> bool:
        if self._DI_PATTERN.search(str(exc)):
            return True
        if any(k in type(exc).__name__ for k in (
            "DI", "Bootstrap", "Container", "ServiceNot", "PortNot", "Adapter"
        )):
            return True
        return any(
            any(k in f.filename.replace("\\","/").lower()
                for k in ("bootstrap", "dependency_container", "ioc_container"))
            for f in frames
        )

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg = str(exc)
        evidence = [f"DI/Bootstrap error: {type(exc).__name__}: {msg[:300]}"]
        di_frames = [
            f for f in frames
            if any(k in f.filename.replace("\\","/").lower()
                   for k in ("bootstrap", "dependency_container", "ioc"))
        ]
        if di_frames:
            evidence.append(f"DI file: {di_frames[-1].filename}:{di_frames[-1].lineno}")

        is_circular = bool(re.search(r"circular.depend|cycle.*detected", msg, re.I))

        return RCAResult(
            severity=Severity.FATAL, category=Category.DI,
            error_code=ErrorCode.CONTAINER_RESOLVE_FAIL,
            root_cause=(
                "Circular dependency terdeteksi di DI Container — "
                "dua service saling bergantung."
                if is_circular else
                f"Service/Port tidak terdaftar di IoC Container: {msg[:200]}"
            ),
            evidence=evidence,
            impact=[
                "Aplikasi tidak bisa start — bootstrap gagal.",
                "Semua endpoint API tidak tersedia.",
            ],
            suggested_fix=(
                "1. Jalankan bootstrap/dependency_container/dependency_graph_validator.py "
                "   untuk visualisasi dependency graph. "
                "2. Pecah circular dependency dengan interface/port abstraction. "
                "3. Gunakan lazy injection atau factory pattern."
                if is_circular else
                "1. Daftarkan service di bootstrap/dependency_container/service_registry.py. "
                "2. Pastikan adapter ter-register di bootstrap/dependency_container/adapter_registry.py. "
                "3. Jalankan bootstrap/dependency_container/auto_register_ports.py "
                "   untuk auto-registration. "
                "4. Periksa bootstrap/health_probe.py untuk dependency health check."
            ),
            raw_error=msg, confidence=0.92,
        )

# ─── PolicyEngineRule ──────────────────────────────────────────────────────
class PolicyEngineRule(RCARule):
    _POLICY_PATTERNS: list[tuple[re.Pattern, str, str]] = [
        (
            re.compile(r"(IFRS9|IFRS 9|ifrs.*9|financial.*instrument.*classif|"
                       r"ECL.*calculation|expected.credit.loss)", re.I),
            "Pelanggaran IFRS 9 (Financial Instruments) — klasifikasi atau ECL calculation.",
            "Periksa policy_engine/ifrs/ifrs_09_financial_instruments.py. "
            "Pastikan aset keuangan diklasifikasi FVTPL/FVOCI/Amortized Cost dengan benar.",
        ),
        (
            re.compile(r"(IFRS15|IFRS 15|revenue.*recognition|performance.*obligation|"
                       r"contract.*asset.*liability|PSAK72|PSAK 72)", re.I),
            "Pelanggaran IFRS 15 / PSAK 72 (Revenue Recognition).",
            "Periksa policy_engine/ifrs/ifrs_15_revenue.py. "
            "5-step model: Identify contract → Performance obligations → "
            "Transaction price → Allocate → Recognize.",
        ),
        (
            re.compile(r"(IFRS16|IFRS 16|lease.*liability|right.of.use|ROU.*asset|"
                       r"PSAK73|PSAK 73|sewa.*guna)", re.I),
            "Pelanggaran IFRS 16 / PSAK 73 (Leases) — pengakuan ROU asset atau lease liability.",
            "Periksa policy_engine/ifrs/ifrs_16_leases.py. "
            "Pastikan lease classification (finance vs operating) sudah benar.",
        ),
        (
            re.compile(r"(IAS36|IAS 36|impairment.*test|goodwill.*impairment|"
                       r"PSAK48|nilai.pakai|recoverable.amount)", re.I),
            "Pelanggaran IAS 36 / PSAK 48 (Impairment Testing).",
            "Periksa policy_engine/ifrs/ias_36_impairment.py. "
            "Jalankan application/use_cases/impairment_testing_annual.py.",
        ),
        (
            re.compile(r"(IAS21|IAS 21|foreign.exchange|kurs.*revaluasi|"
                       r"forex.*revaluation|monetary.*item.*translat|PSAK10)", re.I),
            "Pelanggaran IAS 21 / PSAK 10 (Foreign Currency Translation).",
            "Periksa policy_engine/ifrs/ias_21_foreign_exchange.py. "
            "Jalankan forex revaluation: application/use_cases/forex_revaluation.py.",
        ),
        (
            re.compile(r"(PSAK25|PSAK 25|perubahan.estimasi|accounting.estimate|"
                       r"error.*prior.period|restatement|koreksi.*periode.lalu)", re.I),
            "Pelanggaran PSAK 25 (Perubahan Estimasi / Koreksi Error).",
            "Periksa policy_engine/psak/psak_25_policies_estimates_errors.py. "
            "Error prior period memerlukan restatement laporan keuangan sebelumnya.",
        ),
        (
            re.compile(r"(tax.*exception|PajakException|PPh.*error|PPN.*error|"
                       r"bupot.*gagal|e.faktur.*error|koretax.*reject|NTPN.*invalid|"
                       r"DJP.*response.*error)", re.I),
            "Error perpajakan Indonesia — PPh, PPN, atau integrasi Coretax DJP.",
            "Periksa policy_engine/tax_indonesia/tax_exceptions.py. "
            "Untuk Coretax: adapters/coretax_djp/coretax_exceptions.py. "
            "Validasi NTPN: adapters/coretax_djp/ntpn_validator.py. "
            "Retry submission: application/sagas/coretax_submission_saga.py.",
        ),
        (
            re.compile(r"(PolicyException|policy.*conflict|policy.*override|"
                       r"jurisdiction.*resolver|PolicyConflict)", re.I),
            "Policy engine conflict — dua policy bertentangan untuk transaksi ini.",
            "Periksa policy_engine/conflict_resolver.py untuk resolution strategy. "
            "Gunakan policy_engine/override_authorizer.py jika override diperlukan (dengan approval).",
        ),
    ]

    def __init__(self) -> None:
        super().__init__(priority=168, category=Category.DDD, name="PolicyEngineRule")

    def match(self, exc, frames, context) -> bool:
        if any(p.search(str(exc)) for p, *_ in self._POLICY_PATTERNS):
            return True
        return any(
            "policy_engine" in f.filename.replace("\\","/").lower() for f in frames
        )

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg = str(exc)
        for pattern, root_cause, fix in self._POLICY_PATTERNS:
            if pattern.search(msg):
                policy_frames = [
                    f for f in frames
                    if "policy_engine" in f.filename.replace("\\","/").lower()
                ]
                evidence = [f"Policy error: {type(exc).__name__}: {msg[:300]}"]
                if policy_frames:
                    pf = policy_frames[-1]
                    evidence.append(f"Policy file: {pf.filename}:{pf.lineno}")
                return RCAResult(
                    severity=Severity.CRITICAL, category=Category.DDD,
                    error_code=ErrorCode.ERP_VALIDATION,
                    root_cause=root_cause, evidence=evidence,
                    impact=[
                        "Laporan keuangan tidak comply dengan standar akuntansi.",
                        "Auditor eksternal akan memberikan qualified/adverse opinion.",
                    ],
                    suggested_fix=fix, raw_error=msg, confidence=0.9,
                )
        return RCAResult(
            severity=Severity.HIGH, category=Category.DDD,
            error_code=ErrorCode.ERP_VALIDATION,
            root_cause=f"Policy engine error: {type(exc).__name__}: {msg[:200]}",
            evidence=[f"{msg[:300]}"],
            impact=["Transaksi tidak comply dengan policy yang berlaku."],
            suggested_fix=(
                "Periksa policy_engine/ untuk policy yang relevan. "
                "Lihat policy_engine/interpreter.py untuk logic evaluasi."
            ),
            raw_error=msg, confidence=0.75,
        )

# ─── ComplianceRule ────────────────────────────────────────────────────────
class ComplianceRule(RCARule):
    _COMPLIANCE_PATTERN = re.compile(
        r"(ComplianceException|SOXControlFailed|AMLRiskExceeded|"
        r"GDPRViolation|SanctionListMatch|OJKValidationFailed|"
        r"sox.*control.*test.*fail|gdpr.*data.*retention|"
        r"sanction.*list.*hit|compliance.*deficiency|"
        r"EthicsViolation|ethics.*exception|"
        r"LegalException|sovereignty.*boundary|"
        r"data.*privacy.*violation)",
        re.I,
    )

    def __init__(self) -> None:
        super().__init__(priority=165, category=Category.SECURITY, name="ComplianceRule")

    def match(self, exc, frames, context) -> bool:
        return self._COMPLIANCE_PATTERN.search(str(exc)) is not None or \
               any(k in type(exc).__name__ for k in (
                   "Compliance", "SOX", "AML", "GDPR", "Sanction", "Ethics", "Legal"
               ))

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg = str(exc)
        if re.search(r"GDPRViolation|data.*privacy|privacy.*violat", msg, re.I):
            return RCAResult(
                severity=Severity.FATAL, category=Category.SECURITY,
                error_code=ErrorCode.PERMISSION_DENIED,
                root_cause="GDPR / Privasi Data Violation — data pribadi diproses tanpa basis hukum.",
                evidence=[f"{type(exc).__name__}: {msg[:300]}"],
                impact=[
                    "Potensi denda GDPR hingga 4% dari global annual turnover.",
                    "Wajib lapor ke otoritas privasi dalam 72 jam (jika terjadi breach).",
                ],
                suggested_fix=(
                    "1. Periksa compliance/gdpr_privacy_checker.py untuk aturan yang dilanggar. "
                    "2. Pastikan data retention policy diikuti. "
                    "3. Hubungi Data Protection Officer (DPO) segera."
                ),
                raw_error=msg, confidence=0.92,
            )
        if re.search(r"SanctionList|sanction.*hit", msg, re.I):
            return RCAResult(
                severity=Severity.FATAL, category=Category.SECURITY,
                error_code=ErrorCode.PERMISSION_DENIED,
                root_cause="Entitas terkena Sanction List — transaksi WAJIB diblokir.",
                evidence=[f"{type(exc).__name__}: {msg[:300]}"],
                impact=[
                    "Melanjutkan transaksi = pelanggaran hukum internasional.",
                    "Eksposur sanksi dari OFAC/UN/EU.",
                ],
                suggested_fix=(
                    "1. Blokir transaksi — JANGAN dilanjutkan tanpa clearance legal. "
                    "2. Periksa compliance/sanction_list_checker.py. "
                    "3. Laporkan ke Compliance Officer dan Legal segera."
                ),
                raw_error=msg, confidence=0.97,
            )
        if re.search(r"SOXControl|sox.*control", msg, re.I):
            return RCAResult(
                severity=Severity.CRITICAL, category=Category.SECURITY,
                error_code=ErrorCode.ERP_VALIDATION,
                root_cause="SOX Control Test Gagal — internal control yang dipersyaratkan tidak terpenuhi.",
                evidence=[f"{type(exc).__name__}: {msg[:300]}"],
                impact=[
                    "Temuan material weakness dalam SOX audit.",
                    "Auditor akan melaporkan defisiensi ke audit committee.",
                ],
                suggested_fix=(
                    "1. Periksa compliance/sox_control_tester.py untuk control yang gagal. "
                    "2. Identifikasi dan perbaiki control deficiency. "
                    "3. Dokumentasikan remediation plan di compliance/deficiency_tracker.py."
                ),
                raw_error=msg, confidence=0.9,
            )
        return RCAResult(
            severity=Severity.CRITICAL, category=Category.SECURITY,
            error_code=ErrorCode.ERP_VALIDATION,
            root_cause=f"Compliance violation: {type(exc).__name__}: {msg[:200]}",
            evidence=[f"{msg[:300]}"],
            impact=["Potensi pelanggaran regulasi — tindakan korektif segera diperlukan."],
            suggested_fix="Periksa compliance/ untuk detail aturan yang dilanggar.",
            raw_error=msg, confidence=0.8,
        )

# ─── AuditIntegrityRule ────────────────────────────────────────────────────
class AuditIntegrityRule(RCARule):
    _AUDIT_PATTERN = re.compile(
        r"(AuditException|TamperDetected|HashChainCorrupted|"
        r"ImmutableEventViolation|ForensicReplayError|"
        r"audit.*hash.*mismatch|event.*tampered|"
        r"hash.*chain.*broken|audit.*log.*corrupted|"
        r"tamper.*alert|forensic.*replay.*failed)",
        re.I,
    )

    def __init__(self) -> None:
        super().__init__(priority=195, category=Category.SECURITY, name="AuditIntegrityRule")

    def match(self, exc, frames, context) -> bool:
        if self._AUDIT_PATTERN.search(str(exc)):
            return True
        return any("audit/" in f.filename.replace("\\","/").lower() for f in frames)

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg = str(exc)
        is_tamper = bool(re.search(r"tamper|TamperDetected", msg, re.I))
        is_hash   = bool(re.search(r"hash.*chain|HashChain.*corrupt", msg, re.I))
        return RCAResult(
            severity=Severity.FATAL, category=Category.SECURITY,
            error_code=ErrorCode.PERMISSION_DENIED,
            root_cause=(
                "TAMPER TERDETEKSI — audit log dimanipulasi!"
                if is_tamper else
                "Hash chain audit rusak — kemungkinan data dimodifikasi di luar sistem."
                if is_hash else
                f"Audit integrity violation: {type(exc).__name__}: {msg[:200]}"
            ),
            evidence=[f"Audit error: {type(exc).__name__}: {msg[:300]}"],
            impact=[
                "🚨 KRITIS: Integritas audit trail tidak bisa dijamin.",
                "Laporan keuangan berpotensi tidak bisa dipercaya.",
                "Wajib lapor ke Board of Directors dan External Auditor.",
                "Forensic investigation oleh pihak independen mungkin diperlukan.",
            ],
            suggested_fix=(
                "🚨 TINDAKAN DARURAT: "
                "1. Hentikan semua operasi tulis ke sistem. "
                "2. Preserve semua log file — jangan hapus apapun. "
                "3. Jalankan audit/forensic_replayer.py untuk reconstruct timeline. "
                "4. Gunakan audit/hash_chain_builder.py untuk verifikasi chain. "
                "5. Hubungi Internal Audit dan Legal segera. "
                "6. Pertimbangkan blockchain notarization via "
                "   audit/regulatory_attestation_signer.py."
            ),
            raw_error=msg, confidence=0.98,
        )

# ─── CoretaxDJPRule ────────────────────────────────────────────────────────
class CoretaxDJPRule(RCARule):
    _CORETAX_PATTERN = re.compile(
        r"(CoretaxException|CoretaxAPIError|OAuth2.*DJP|DJP.*OAuth|"
        r"FakturPajak.*error|NTPNInvalid|NSFP.*habis|"
        r"SPT.*submission.*failed|e.Bupot.*error|eMeterai.*error|"
        r"coretax.*timeout|DJP.*server.*error|"
        r"nomor.seri.faktur.*habis|NSFPExhausted|"
        r"efaktur.*reject|spt.*masa.*error|"
        r"certificate.*DJP.*expired|signature.*DJP)",
        re.I,
    )

    def __init__(self) -> None:
        super().__init__(priority=172, category=Category.INFRASTRUCTURE, name="CoretaxDJPRule")

    def match(self, exc, frames, context) -> bool:
        if self._CORETAX_PATTERN.search(str(exc)):
            return True
        if any(k in type(exc).__name__ for k in ("Coretax", "DJP", "Faktur", "NTPN", "NSFP")):
            return True
        return any("coretax_djp" in f.filename.replace("\\","/").lower() for f in frames)

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg = str(exc)

        if re.search(r"NSFP.*habis|NSFPExhausted|nomor.seri.faktur.*habis", msg, re.I):
            return RCAResult(
                severity=Severity.FATAL, category=Category.INFRASTRUCTURE,
                error_code=ErrorCode.ERP_VALIDATION,
                root_cause="NSFP (Nomor Seri Faktur Pajak) habis — tidak bisa menerbitkan e-Faktur.",
                evidence=[f"NSFP Error: {msg[:300]}"],
                impact=[
                    "🚨 Penjualan TIDAK BISA diterbitkan faktur pajak sampai NSFP diisi ulang.",
                    "Potensi denda keterlambatan penerbitan faktur (max 2% dari DPP).",
                ],
                suggested_fix=(
                    "1. SEGERA request NSFP tambahan ke DJP Coretax portal. "
                    "2. Kelola stok NSFP di adapters/coretax_djp/nsfp_manager.py. "
                    "3. Set alert ketika NSFP < 100 nomor tersisa."
                ),
                raw_error=msg, confidence=0.97,
            )

        if re.search(r"NTPNInvalid|NTPN.*invalid|NTPN.*tidak.valid", msg, re.I):
            return RCAResult(
                severity=Severity.CRITICAL, category=Category.INFRASTRUCTURE,
                error_code=ErrorCode.ERP_VALIDATION,
                root_cause="NTPN (Nomor Transaksi Penerimaan Negara) tidak valid — konfirmasi pembayaran pajak gagal.",
                evidence=[f"NTPN Error: {msg[:300]}"],
                impact=[
                    "Pembayaran pajak tidak bisa dikonfirmasi di sistem DJP.",
                    "SPT tidak bisa disubmit tanpa NTPN yang valid.",
                ],
                suggested_fix=(
                    "1. Verifikasi NTPN di adapters/coretax_djp/ntpn_validator.py. "
                    "2. Cek status pembayaran di sistem bank/billing pembayaran pajak. "
                    "3. Hubungi KPP jika NTPN tidak muncul dalam 1x24 jam."
                ),
                raw_error=msg, confidence=0.95,
            )

        if re.search(r"OAuth2|oauth.*token.*expired|DJP.*auth", msg, re.I):
            return RCAResult(
                severity=Severity.HIGH, category=Category.INFRASTRUCTURE,
                error_code=ErrorCode.ERP_VALIDATION,
                root_cause="OAuth2 token DJP Coretax expired atau invalid.",
                evidence=[f"Auth Error: {msg[:300]}"],
                impact=["Semua operasi Coretax API tidak bisa dilakukan sampai re-auth."],
                suggested_fix=(
                    "1. Refresh token di adapters/coretax_djp/api_oauth2_client.py. "
                    "2. Periksa expiry time token dan implementasikan auto-refresh. "
                    "3. Pastikan certificate DJP belum expired."
                ),
                raw_error=msg, confidence=0.92,
            )

        return RCAResult(
            severity=Severity.HIGH, category=Category.INFRASTRUCTURE,
            error_code=ErrorCode.ERP_VALIDATION,
            root_cause=f"Coretax DJP API error: {type(exc).__name__}: {msg[:200]}",
            evidence=[f"{msg[:300]}"],
            impact=["Integrasi perpajakan dengan DJP terganggu."],
            suggested_fix=(
                "Periksa adapters/coretax_djp/coretax_exceptions.py. "
                "Monitor di adapters/coretax_djp/health_dashboard.py."
            ),
            raw_error=msg, confidence=0.78,
        )

# ─── SecurityHardeningRule ────────────────────────────────────────────────
class SecurityHardeningRule(RCARule):
    _SEC_PATTERN = re.compile(
        r"(SecurityException|EncryptionFailed|DecryptionFailed|"
        r"HSMError|PKCSError|KeyVaultError|SigningFailed|"
        r"CertificateExpired|TLSHandshakeFailed|"
        r"HashiCorpVault.*error|encryption.*key.*not.*found|"
        r"private.*key.*unavailable|signature.*verification.*failed|"
        r"security.*hardening.*violation)",
        re.I,
    )

    def __init__(self) -> None:
        super().__init__(priority=188, category=Category.SECURITY, name="SecurityHardeningRule")

    def match(self, exc, frames, context) -> bool:
        if self._SEC_PATTERN.search(str(exc)):
            return True
        return any(
            any(k in f.filename.replace("\\","/").lower()
                for k in ("security_hardening", "security/security", "hsm_pkcs", "key_vault"))
            for f in frames
        )

    def analyze(self, exc, frames, context) -> RCAResult | None:
        msg = str(exc)
        if re.search(r"CertificateExpired|TLS.*handshake|certificate.*expired", msg, re.I):
            return RCAResult(
                severity=Severity.FATAL, category=Category.SECURITY,
                error_code=ErrorCode.PERMISSION_DENIED,
                root_cause="Certificate TLS expired — koneksi aman tidak bisa dibuat.",
                evidence=[f"{type(exc).__name__}: {msg[:300]}"],
                impact=["Seluruh komunikasi HTTPS/API tidak bisa dilakukan."],
                suggested_fix=(
                    "1. Renew certificate segera. "
                    "2. Set alert 30 hari sebelum expiry di infrastructure/telemetry/. "
                    "3. Gunakan Let's Encrypt auto-renewal atau Vault PKI secrets engine."
                ),
                raw_error=msg, confidence=0.95,
            )
        if re.search(r"HSM|PKCS|SigningFailed|signature.*fail", msg, re.I):
            return RCAResult(
                severity=Severity.FATAL, category=Category.SECURITY,
                error_code=ErrorCode.PERMISSION_DENIED,
                root_cause="HSM/PKCS11 signing gagal — dokumen tidak bisa ditandatangani secara digital.",
                evidence=[f"{type(exc).__name__}: {msg[:300]}"],
                impact=[
                    "e-Faktur, SPT, dan dokumen legal tidak bisa di-sign.",
                    "Submission ke DJP tidak bisa dilakukan.",
                ],
                suggested_fix=(
                    "1. Periksa koneksi ke HSM di adapters/secondary_impl/hsm_pkcs11_signing_adapter.py. "
                    "2. Pastikan HSM token tidak terkunci (PIN error). "
                    "3. Cek slot dan certificate di HSM."
                ),
                raw_error=msg, confidence=0.9,
            )
        if re.search(r"KeyVault|HashiCorp|encryption.*key|private.*key", msg, re.I):
            return RCAResult(
                severity=Severity.FATAL, category=Category.SECURITY,
                error_code=ErrorCode.PERMISSION_DENIED,
                root_cause="Encryption key tidak bisa diambil dari Key Vault.",
                evidence=[f"{type(exc).__name__}: {msg[:300]}"],
                impact=["Data sensitif tidak bisa di-encrypt/decrypt."],
                suggested_fix=(
                    "1. Periksa koneksi ke HashiCorp Vault: adapters/secondary_impl/hashicorp_vault_adapter.py. "
                    "2. Pastikan Vault service running dan unsealed. "
                    "3. Cek policy Vault untuk service account yang digunakan."
                ),
                raw_error=msg, confidence=0.9,
            )
        return RCAResult(
            severity=Severity.CRITICAL, category=Category.SECURITY,
            error_code=ErrorCode.PERMISSION_DENIED,
            root_cause=f"Security error: {type(exc).__name__}: {msg[:200]}",
            evidence=[f"{msg[:300]}"],
            impact=["Operasi keamanan gagal — data atau sistem mungkin tidak terlindungi."],
            suggested_fix=(
                "Periksa security_hardening/ dan infrastructure/security/security_exceptions.py."
            ),
            raw_error=msg, confidence=0.8,
        )

# =============================================================================
#  RCAEngine (final)
# =============================================================================
class RCAEngine:
    VERSION = "5.0.0"

    def __init__(
        self,
        enable_networkx : bool = True,
        enable_jedi     : bool = True,
        enable_libcst   : bool = True,
        rule_timeout    : float = TIMEOUT_SECONDS,
    ) -> None:
        self._lock          = threading.RLock()
        self._rules         : list[RCARule]      = []
        self._rule_map      : dict[str, RCARule] = {}
        self._rule_timeout  = rule_timeout
        self._stats = {
            "total_analyses": 0,
            "total_time"    : 0.0,
            "cache_hits"    : 0,
            "cache_misses"  : 0,
            "rule_errors"   : 0,
        }
        self._enable_networkx = enable_networkx and HAS_NETWORKX
        self._enable_jedi     = enable_jedi     and HAS_JEDI
        self._enable_libcst   = enable_libcst   and HAS_LIBCST
        self._register_default_rules()

    def _register_default_rules(self) -> None:
        """Daftarkan semua aturan dalam urutan prioritas (sudah tidak ada duplikasi)."""
        all_rules = [
            # Infrastruktur spesifik (prioritas tinggi)
            InfrastructureDatabaseRule(),
            MessageBrokerRule(),
            CachingRule(),
            CoretaxDJPRule(),
            SecurityHardeningRule(),
            BootstrapDIRule(),
            SagaOrchestrationRule(),
            AuditIntegrityRule(),
            ComplianceRule(),
            PolicyEngineRule(),
            # Kernel & Axiom
            AxiomViolationRule(),
            ConstitutionViolationRule(),
            KernelGuardViolationRule(),
            # Domain & CQRS
            TransactionIntegrityRule(),
            CQRSHandlerRule(),
            DomainRepositoryMismatchRule(),
            EventPublishRule(),
            ContainerErrorRule(),
            AggregateErrorRule(),
            UnitOfWorkErrorRule(),
            # Built-in & generik
            InfrastructureConnectionRule(),
            RecursionMemoryRule(),
            PermissionFileRule(),
            ImportErrorRule(),
            CircularImportRule(),
            AttributeErrorRule(),
            TypeErrorRule(),
            NameErrorRule(),
            KeyErrorRule(),
            IndexErrorRule(),
            ValueErrorRule(),
        ]
        for rule in all_rules:
            self.register_rule(rule)

    def register_rule(self, rule: RCARule) -> None:
        with self._lock:
            if rule.name in self._rule_map:
                try:
                    self._rules.remove(self._rule_map[rule.name])
                except ValueError:
                    pass
            self._rules.append(rule)
            self._rule_map[rule.name] = rule
            self._rules.sort(key=lambda r: r.priority, reverse=True)

    def unregister_rule(self, name: str) -> bool:
        with self._lock:
            if name not in self._rule_map:
                return False
            rule = self._rule_map.pop(name)
            try:
                self._rules.remove(rule)
            except ValueError:
                pass
            return True

    def analyze(
        self,
        exception: BaseException,
        context  : dict[str, Any] | None = None,
    ) -> RCAResult:
        if not isinstance(exception, BaseException):
            raise TypeError(
                f"analyze() mengharapkan BaseException, bukan {type(exception).__name__}"
            )

        start_time = time.perf_counter()

        with self._lock:
            self._stats["total_analyses"] += 1

        # Gunakan copy.copy untuk menghindari RecursionError pada context bersiklus
        try:
            safe_context = copy.copy(context) if context else {}
        except Exception:
            safe_context = dict(context) if context else {}

        frames = get_traceback_frames(exception)

        all_exceptions   = get_all_causes(exception)
        combined_results : list[RCAResult] = []

        with self._lock:
            rules_snapshot = list(self._rules)

        for exc in all_exceptions:
            exc_frames = get_traceback_frames(exc) or frames
            for rule in rules_snapshot:
                if not rule.enabled:
                    continue
                try:
                    matched = self._run_with_timeout(
                        rule.match, self._rule_timeout,
                        exc, exc_frames, safe_context,
                    )
                except Exception as err:
                    _logger.warning("Rule %s.match() error: %s", rule.name, err)
                    with self._lock:
                        self._stats["rule_errors"] += 1
                    continue

                if not matched:
                    continue

                with rule._stats_lock:
                    rule._stats["matches"] += 1

                t0 = time.perf_counter()
                try:
                    res = self._run_with_timeout(
                        rule.analyze, self._rule_timeout,
                        exc, exc_frames, safe_context,
                    )
                except Exception as err:
                    _logger.warning("Rule %s.analyze() error: %s", rule.name, err)
                    with self._lock:
                        self._stats["rule_errors"] += 1
                    res = None

                elapsed_ms = (time.perf_counter() - t0) * 1000
                with rule._stats_lock:
                    if res is not None:
                        rule._stats["hits"]    += 1
                        combined_results.append(res)
                    else:
                        rule._stats["misses"]  += 1
                    rule._stats["time_ms"] += elapsed_ms

        if not combined_results:
            combined_results.append(self._fallback_analysis(exception, frames, safe_context))

        best = max(
            combined_results,
            key=lambda r: (r.severity.order, r.confidence),
        )

        # Agregasi evidence dan impact (deduplikasi)
        seen_evidence: set[str] = set()
        all_evidence  : list[str] = []
        for r in combined_results:
            for ev in r.evidence:
                ev_normalized = ev.strip()
                if ev_normalized and ev_normalized not in seen_evidence:
                    seen_evidence.add(ev_normalized)
                    all_evidence.append(ev)

        seen_impact: set[str] = set()
        all_impact  : list[str] = []
        for r in combined_results:
            for imp in r.impact:
                imp_normalized = imp.strip()
                if imp_normalized and imp_normalized not in seen_impact:
                    seen_impact.add(imp_normalized)
                    all_impact.append(imp)

        final = RCAResult(
            severity      = best.severity,
            category      = best.category,
            error_code    = best.error_code,
            root_cause    = best.root_cause,
            evidence      = all_evidence[:MAX_EVIDENCE_ITEMS],
            impact        = all_impact[:MAX_IMPACT_ITEMS],
            suggested_fix = best.suggested_fix,
            raw_error     = str(exception)[:MAX_EVIDENCE_LENGTH],
            confidence    = best.confidence,
            children      = [r for r in combined_results if r is not best][:MAX_CHILDREN],
        )

        elapsed = time.perf_counter() - start_time
        with self._lock:
            self._stats["total_time"] += elapsed

        _logger.debug("RCA: %s in %.2fms", final.summary(), elapsed * 1000)
        return final

    @staticmethod
    def _run_with_timeout(fn: Any, timeout: float, *args: Any, **kwargs: Any) -> Any:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(fn, *args, **kwargs)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                _logger.warning("Function %s timed out after %.2fs", fn.__qualname__, timeout)
                raise TimeoutError(f"{fn.__qualname__} timeout setelah {timeout}s")

    def _fallback_analysis(
        self,
        exception : BaseException,
        frames    : list[traceback.FrameSummary],
        context   : dict[str, Any],
    ) -> RCAResult:
        _severity_map: dict[type, Severity] = {
            KeyboardInterrupt : Severity.INFO,
            SystemExit        : Severity.INFO,
            StopIteration     : Severity.INFO,
            GeneratorExit     : Severity.INFO,
            Warning           : Severity.LOW,
            MemoryError       : Severity.FATAL,
            RecursionError    : Severity.HIGH,
            SystemError       : Severity.FATAL,
        }
        sev = Severity.HIGH
        for exc_type, mapped_sev in _severity_map.items():
            if isinstance(exception, exc_type):
                sev = mapped_sev
                break

        evidence = [f"{f.filename}:{f.lineno} in {f.name}" for f in frames[-5:]]

        return RCAResult(
            severity      = sev,
            category      = Category.UNKNOWN,
            error_code    = ErrorCode.UNKNOWN,
            root_cause    = f"Unhandled {type(exception).__name__}: {str(exception)[:200]}",
            evidence      = evidence,
            impact        = ["Program berhenti tidak normal — perlu investigasi lebih lanjut."],
            suggested_fix = "Tambahkan rule analisis spesifik atau periksa logika program.",
            raw_error     = str(exception)[:MAX_EVIDENCE_LENGTH],
            confidence    = 0.3,
        )

    def stats(self) -> dict[str, Any]:
        with self._lock:
            eng = dict(self._stats)
            eng["version"]    = self.VERSION
            eng["rule_count"] = len(self._rules)
            n = eng["total_analyses"]
            if n > 0:
                eng["avg_time_ms"] = eng["total_time"] / n * 1000
            else:
                eng["avg_time_ms"] = 0.0
            rules_stats = {r.name: r.stats() for r in self._rules}

        return {
            "engine": eng,
            "cache" : {
                "file"   : _file_cache.stats(),
                "ast"    : _ast_cache.stats(),
                "context": _context_cache.stats(),
            },
            "rules" : rules_stats,
        }

    def clear_cache(self) -> None:
        _file_cache.clear()
        _ast_cache.clear()
        _context_cache.clear()

# ── Singleton ─────────────────────────────────────────────────────────────────
_DEFAULT_ENGINE : RCAEngine | None = None
_ENGINE_LOCK    = threading.Lock()

def get_engine() -> RCAEngine:
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is None:
        with _ENGINE_LOCK:
            if _DEFAULT_ENGINE is None:
                _DEFAULT_ENGINE = RCAEngine()
    return _DEFAULT_ENGINE

def reset_engine() -> None:
    global _DEFAULT_ENGINE
    with _ENGINE_LOCK:
        _DEFAULT_ENGINE = None

def analyze_exception(
    exception: BaseException,
    context  : dict[str, Any] | None = None,
) -> RCAResult:
    return get_engine().analyze(exception, context)

analyze = analyze_exception

# ─── Self‑test (mencakup semua aturan) ──────────────────────────────────────
def self_test(verbose: bool = True) -> bool:
    engine = RCAEngine()
    passed = failed = 0

    def check(name: str, cond: bool, got: str = "") -> None:
        nonlocal passed, failed
        if cond:
            if verbose:
                print(f"  ✅ {name}")
            passed += 1
        else:
            if verbose:
                print(f"  ❌ {name}" + (f": {got}" if got else ""))
            failed += 1

    if verbose:
        print(f"\nRunning RCA Engine self-test v{RCAEngine.VERSION} ({engine.stats()['engine']['rule_count']} rules registered)…\n")

    # ── Import ────────────────────────────────────────────────────────────────
    try:
        raise ImportError("No module named 'nonexistent_xyz'")
    except Exception as e:
        r = engine.analyze(e)
        check("ImportErrorRule — module not found",
              r.error_code == ErrorCode.IMPORT_MODULE_NOT_FOUND, str(r.error_code))

    # ── Attribute ─────────────────────────────────────────────────────────────
    try:
        class _X: pass
        _X().missing_attr
    except Exception as e:
        r = engine.analyze(e)
        check("AttributeErrorRule — missing attr",
              r.category == Category.ATTRIBUTE, str(r.category))

    try:
        obj = None
        obj.something
    except Exception as e:
        r = engine.analyze(e)
        check("AttributeErrorRule — NoneType (ATTR_NONE_ACCESS)",
              r.error_code == ErrorCode.ATTR_NONE_ACCESS, str(r.error_code))

    # ── Type ──────────────────────────────────────────────────────────────────
    try:
        len(123)
    except Exception as e:
        r = engine.analyze(e)
        check("TypeErrorRule — not iterable",
              r.category == Category.TYPE, str(r.category))

    try:
        def _f(a: int, b: int) -> int: return a + b
        _f(1)
    except Exception as e:
        r = engine.analyze(e)
        check("TypeErrorRule — missing arg",
              r.error_code == ErrorCode.TYPE_MISSING_REQUIRED, str(r.error_code))

    # ── NameError ─────────────────────────────────────────────────────────────
    try:
        exec("print(undefined_variable_xyz)")
    except Exception as e:
        r = engine.analyze(e)
        check("NameErrorRule — undefined variable",
              r.error_code == ErrorCode.NAME_NOT_DEFINED, str(r.error_code))

    # ── KeyError ──────────────────────────────────────────────────────────────
    try:
        d: dict[str, str] = {}
        _ = d["account_code"]
    except Exception as e:
        r = engine.analyze(e)
        check("KeyErrorRule — account key (ERP context)",
              r.error_code == ErrorCode.KEY_NOT_FOUND, str(r.error_code))

    # ── IndexError ────────────────────────────────────────────────────────────
    try:
        lst: list[int] = []
        _ = lst[0]
    except Exception as e:
        r = engine.analyze(e)
        check("IndexErrorRule — empty list",
              r.error_code == ErrorCode.INDEX_OUT_OF_RANGE, str(r.error_code))

    # ── ValueError ERP ────────────────────────────────────────────────────────
    try:
        raise ValueError("Accounting period is closed and locked")
    except Exception as e:
        r = engine.analyze(e)
        check("ValueErrorRule — period closed (ERP_PERIOD_CLOSED)",
              r.error_code == ErrorCode.ERP_PERIOD_CLOSED, str(r.error_code))

    try:
        raise ValueError("Account 99999 is invalid or not active")
    except Exception as e:
        r = engine.analyze(e)
        check("ValueErrorRule — account invalid (ERP_ACCOUNT_INVALID)",
              r.error_code == ErrorCode.ERP_ACCOUNT_INVALID, str(r.error_code))

    try:
        raise ValueError("Balance mismatch: debit 1000 != credit 900")
    except Exception as e:
        r = engine.analyze(e)
        check("ValueErrorRule — balance mismatch (ERP_BALANCE_MISMATCH, FATAL)",
              r.error_code == ErrorCode.ERP_BALANCE_MISMATCH
              and r.severity == Severity.FATAL, str(r.error_code))

    # ── Infrastructure ────────────────────────────────────────────────────────
    try:
        raise ConnectionRefusedError("Connection refused to 127.0.0.1:5432")
    except Exception as e:
        r = engine.analyze(e)
        check("InfrastructureConnectionRule — DB connection refused (FATAL)",
              r.error_code == ErrorCode.DB_CONNECTION_FAIL
              and r.severity == Severity.FATAL, str(r.error_code))

    try:
        raise ConnectionError("Redis connection to localhost:6379 refused")
    except Exception as e:
        r = engine.analyze(e)
        check("InfrastructureConnectionRule — Redis (REDIS_FAIL)",
              r.error_code == ErrorCode.REDIS_FAIL, str(r.error_code))

    try:
        raise ConnectionError("Kafka broker at 10.0.0.1:9092 not available")
    except Exception as e:
        r = engine.analyze(e)
        check("InfrastructureConnectionRule — Kafka (KAFKA_FAIL)",
              r.error_code == ErrorCode.KAFKA_FAIL, str(r.error_code))

    # ── CQRS ──────────────────────────────────────────────────────────────────
    try:
        raise RuntimeError("No handler registered for command 'CreateInvoiceCommand'")
    except Exception as e:
        r = engine.analyze(e)
        check("CQRSHandlerRule — command handler missing",
              r.error_code == ErrorCode.COMMAND_HANDLER_MISSING, str(r.error_code))

    try:
        raise RuntimeError("No query handler found for 'GetLedgerBalanceQuery'")
    except Exception as e:
        r = engine.analyze(e)
        check("CQRSHandlerRule — query handler missing",
              r.error_code == ErrorCode.QUERY_HANDLER_MISSING, str(r.error_code))

    # ── Recursion / Memory ────────────────────────────────────────────────────
    try:
        raise RecursionError("maximum recursion depth exceeded")
    except Exception as e:
        r = engine.analyze(e)
        check("RecursionMemoryRule — RecursionError",
              r.error_code == ErrorCode.RECURSION_LIMIT, str(r.error_code))

    try:
        raise MemoryError()
    except Exception as e:
        r = engine.analyze(e)
        check("RecursionMemoryRule — MemoryError (FATAL)",
              r.error_code == ErrorCode.MEMORY_ERROR
              and r.severity == Severity.FATAL, str(r.error_code))

    # ── Permission / File ─────────────────────────────────────────────────────
    try:
        raise PermissionError(13, "Permission denied: '/etc/erp/secret.key'")
    except Exception as e:
        r = engine.analyze(e)
        check("PermissionFileRule — PermissionError",
              r.error_code == ErrorCode.PERMISSION_DENIED, str(r.error_code))

    try:
        raise FileNotFoundError(2, "No such file or directory: '/app/config.yaml'")
    except Exception as e:
        r = engine.analyze(e)
        check("PermissionFileRule — FileNotFoundError (CRITICAL for config)",
              r.error_code == ErrorCode.FILE_NOT_FOUND
              and r.severity == Severity.CRITICAL, str(r.error_code))

    # ── Domain ────────────────────────────────────────────────────────────────
    try:
        raise RuntimeError("Failed to dispatch domain_event to event_bus handler")
    except Exception as e:
        r = engine.analyze(e)
        check("EventPublishRule — domain event dispatch fail",
              r.error_code == ErrorCode.EVENT_PUBLISH_FAIL, str(r.error_code))

    try:
        raise RuntimeError("di_container unable to resolve 'IAccountingService'")
    except Exception as e:
        r = engine.analyze(e)
        check("ContainerErrorRule — resolve fail",
              r.error_code == ErrorCode.CONTAINER_RESOLVE_FAIL, str(r.error_code))

    # ── Axiom ──────────────────────────────────────────────────────────────────
    try:
        raise ValueError("AxiomViolation: double entry debit credit unbalanced — total debit 1500 != total kredit 1000")
    except Exception as e:
        r = engine.analyze(e)
        check("AxiomViolationRule — double entry unbalanced (FATAL)",
              r.severity == Severity.FATAL and "ouble" in r.root_cause, str(r.root_cause[:80]))

    try:
        raise RuntimeError("ImmutabilityViolation: posted journal entry cannot be modified after posting")
    except Exception as e:
        r = engine.analyze(e)
        check("AxiomViolationRule — immutability violation (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    # ── Constitution ──────────────────────────────────────────────────────────
    try:
        raise RuntimeError("ConstitutionViolation: ForbiddenState — negative equity not allowed by supreme law")
    except Exception as e:
        r = engine.analyze(e)
        check("ConstitutionViolationRule — forbidden state (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    # ── Kernel Guards ─────────────────────────────────────────────────────────
    try:
        raise PermissionError("PeriodLockViolation: fiscal period 2024-12 is locked and closed — posting not allowed")
    except Exception as e:
        r = engine.analyze(e)
        check("KernelGuardViolationRule — period lock (CRITICAL)",
              r.severity in (Severity.FATAL, Severity.CRITICAL), str(r.root_cause[:80]))

    try:
        raise PermissionError("SodViolation: same user cannot create and approve — four eyes principle violated")
    except Exception as e:
        r = engine.analyze(e)
        check("KernelGuardViolationRule — SOD violation (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    # ── Database ──────────────────────────────────────────────────────────────
    try:
        raise Exception("DatabaseException: deadlock detected while inserting into journal_line_table")
    except Exception as e:
        r = engine.analyze(e)
        check("InfrastructureDatabaseRule — deadlock",
              "eadlock" in r.root_cause, str(r.root_cause[:80]))

    try:
        raise Exception("remaining connection slots are reserved — too many connections to database 'erp_db'")
    except Exception as e:
        r = engine.analyze(e)
        check("InfrastructureDatabaseRule — connection pool exhausted (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    # ── Bootstrap DI ──────────────────────────────────────────────────────────
    try:
        raise RuntimeError("DIException: circular dependency detected — ServiceA depends on ServiceB which depends on ServiceA")
    except Exception as e:
        r = engine.analyze(e)
        check("BootstrapDIRule — circular DI dependency (FATAL)",
              r.severity == Severity.FATAL and "ircular" in r.root_cause, str(r.root_cause[:80]))

    # ── Message Broker ────────────────────────────────────────────────────────
    try:
        raise Exception("MessagePublishFailed: kafka dead letter queue full — event JournalPostedEvent not sent")
    except Exception as e:
        r = engine.analyze(e)
        check("MessageBrokerRule — dead letter queue",
              "dead.letter" in r.root_cause.lower() or "Dead Letter" in r.root_cause,
              str(r.root_cause[:80]))

    # ── Saga ──────────────────────────────────────────────────────────────────
    try:
        raise RuntimeError("SagaCompensationFailed: coretax_submission_saga compensation failed — system in inconsistent state")
    except Exception as e:
        r = engine.analyze(e)
        check("SagaOrchestrationRule — saga compensation failed (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    # ── Coretax ───────────────────────────────────────────────────────────────
    try:
        raise Exception("NSFPExhausted: nomor seri faktur pajak habis — tidak bisa menerbitkan e-Faktur baru")
    except Exception as e:
        r = engine.analyze(e)
        check("CoretaxDJPRule — NSFP habis (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    # ── Policy ────────────────────────────────────────────────────────────────
    try:
        raise ValueError("IFRS15 violation: revenue recognized before performance obligation satisfied for contract C-001")
    except Exception as e:
        r = engine.analyze(e)
        check("PolicyEngineRule — IFRS 15 revenue recognition",
              r.severity in (Severity.FATAL, Severity.CRITICAL), str(r.root_cause[:80]))

    # ── Compliance ────────────────────────────────────────────────────────────
    try:
        raise RuntimeError("GDPRViolation: data privacy violation — customer PII retained beyond 7 year limit")
    except Exception as e:
        r = engine.analyze(e)
        check("ComplianceRule — GDPR violation (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    try:
        raise RuntimeError("SanctionListMatch: entity 'PT XYZ' matched OFAC SDN list — transaction BLOCKED")
    except Exception as e:
        r = engine.analyze(e)
        check("ComplianceRule — sanction list hit (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    # ── Audit ─────────────────────────────────────────────────────────────────
    try:
        raise RuntimeError("TamperDetected: audit log hash chain broken at event #4521 — data may have been modified")
    except Exception as e:
        r = engine.analyze(e)
        check("AuditIntegrityRule — tamper detected (FATAL)",
              r.severity == Severity.FATAL and len(r.impact) >= 3, str(r.root_cause[:80]))

    # ── Security ──────────────────────────────────────────────────────────────
    try:
        raise RuntimeError("CertificateExpired: TLS certificate for api.coretax.pajak.go.id expired on 2024-01-15")
    except Exception as e:
        r = engine.analyze(e)
        check("SecurityHardeningRule — certificate expired (FATAL)",
              r.severity == Severity.FATAL, str(r.root_cause[:80]))

    # ── Caching ───────────────────────────────────────────────────────────────
    try:
        raise Exception("DistributedLockTimeout: lock acquisition failed for 'journal:2024-001' after 5s — Redis timeout")
    except Exception as e:
        r = engine.analyze(e)
        check("CachingRule — distributed lock timeout",
              r.severity == Severity.HIGH, str(r.root_cause[:80]))

    # ── Data quality ──────────────────────────────────────────────────────────
    r_hi = RCAResult(severity=Severity.HIGH, confidence=1.5)
    check("Confidence clamp upper", r_hi.confidence == 1.0, str(r_hi.confidence))
    r_lo = RCAResult(severity=Severity.LOW, confidence=-0.5)
    check("Confidence clamp lower", r_lo.confidence == 0.0, str(r_lo.confidence))

    # Circular ref in to_dict
    ra = RCAResult(severity=Severity.INFO)
    rb = RCAResult(severity=Severity.INFO)
    ra.children.append(rb)
    rb.children.append(ra)
    try:
        ra.to_dict()
        check("Circular ref protection in to_dict", True)
    except RecursionError:
        check("Circular ref protection in to_dict", False, "RecursionError!")

    # Severity ordering
    check("Severity ordering: FATAL > CRITICAL",
          Severity.FATAL > Severity.CRITICAL)
    check("Severity ordering: CRITICAL > HIGH",
          Severity.CRITICAL > Severity.HIGH)
    check("Severity ordering: LOW < MEDIUM",
          Severity.LOW < Severity.MEDIUM)

    # Tie-breaking
    r_low_conf  = RCAResult(severity=Severity.CRITICAL, confidence=0.5,
                             root_cause="low", error_code=ErrorCode.UNKNOWN)
    r_high_conf = RCAResult(severity=Severity.CRITICAL, confidence=0.9,
                             root_cause="high", error_code=ErrorCode.UNKNOWN)
    best = max([r_low_conf, r_high_conf],
               key=lambda r: (r.severity.order, r.confidence))
    check("Severity+confidence tie-breaking", best.root_cause == "high",
          f"got root_cause={best.root_cause}")

    # Input validation
    try:
        analyze_exception("not an exception")
        check("analyze_exception() input validation", False, "no TypeError raised")
    except TypeError:
        check("analyze_exception() input validation — TypeError on non-exception", True)

    # Sensitive keys
    check("_is_sensitive_key('password')", _is_sensitive_key("password"))
    check("_is_sensitive_key('username') == False", not _is_sensitive_key("username"))

    # reset_engine
    reset_engine()
    e1 = get_engine()
    e2 = get_engine()
    check("get_engine() returns same singleton after reset", e1 is e2)

    # Total rules
    stats = engine.stats()
    rule_cnt = stats["engine"]["rule_count"]
    check("Total rules terdaftar ≥ 30", rule_cnt >= 30, str(rule_cnt))

    if verbose:
        print()
        print(f"Self-test: {passed} passed, {failed} failed "
              f"({'✅ ALL PASS' if failed == 0 else '❌ SOME FAILED'})")
        print(f"Total rules aktif: {rule_cnt}")

    return failed == 0

# ── Benchmark ──────────────────────────────────────────────────────────────────
def benchmark(iterations: int = 500) -> dict[str, float]:
    import statistics
    engine = RCAEngine()
    try:
        try:
            raise ValueError("Root cause")
        except ValueError as e:
            raise RuntimeError("Wrapper") from e
    except Exception as exc:
        times: list[float] = []
        for _ in range(iterations):
            t0 = time.perf_counter()
            engine.analyze(exc)
            times.append((time.perf_counter() - t0) * 1000)

    times.sort()
    n = len(times)
    result = {
        "iterations": n,
        "total_ms"  : sum(times),
        "mean_ms"   : statistics.mean(times),
        "median_ms" : statistics.median(times),
        "p95_ms"    : times[int(n * 0.95)],
        "p99_ms"    : times[int(n * 0.99)],
        "min_ms"    : times[0],
        "max_ms"    : times[-1],
    }
    print(
        f"Benchmark ({n} iterations): "
        f"mean={result['mean_ms']:.2f}ms  "
        f"P50={result['median_ms']:.2f}ms  "
        f"P95={result['p95_ms']:.2f}ms  "
        f"P99={result['p99_ms']:.2f}ms  "
        f"max={result['max_ms']:.2f}ms"
    )
    return result

if __name__ == "__main__":
    ok = self_test(verbose=True)
    print()
    benchmark(iterations=500)
    print(f"\nRCA Engine v{RCAEngine.VERSION} ready. "
          f"{'All systems nominal.' if ok else 'WARNING: Self-test failures detected.'}")
    sys.exit(0 if ok else 1)
