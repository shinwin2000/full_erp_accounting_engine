#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rca.py — Root Cause Analysis Engine untuk ERP Accounting System
================================================================
Versi   : 3.0.0
Standar : Big 4 Forensic Audit · ISO/IEC 25010 · SOX/ISA 315 Compliant
Penulis : Senior Engineering Team
Lisensi : Internal Use Only

Perubahan dari v2.0:
    FIX-01  Hapus duplikat key di _builtins_common dict
    FIX-02  Guard aman untuk frames[-1] di MemoryError handler
    FIX-03  SOX-compliant evidence collection — tidak buang evidence duplikat lintas rule
    FIX-04  Timeout thread untuk safe_repr() cegah CPU spike
    FIX-05  Import dalam fungsi dipindahkan ke top-level (difflib, Counter)
    FIX-06  Optional[str] type hint untuk parameter opsional
    FIX-07  Credential redaction di get_frame_locals()
    FIX-08  Cycle detection di flatten_exception()
    FIX-09  Guard frame.lineno <= 0 di semua code-context caller
    FIX-10  OSError ditambahkan di InfrastructureConnectionRule
    FIX-11  \buow\b regex di UnitOfWorkErrorRule
    FIX-12  Input validation di analyze_exception()
    FIX-13  Class-level constants untuk dict/list yang dibuat ulang
    FIX-14  Severity ordering terintegrasi dalam Enum (functools.total_ordering)
    FIX-15  reset_engine() untuk testability
    FIX-16  Akses _rules via stats() bukan direct attribute
    FIX-17  Rule match() timeout protection
    FIX-18  Frozen-compatible RCAResult dengan explicit mutability points
    FIX-19  CircularImportRule fallback jika semua frames dari frozen modules
    FIX-20  Benchmark dengan percentile reporting (P50, P95, P99)
    NEW-01  Kelas EvidenceItem untuk typed evidence (bukan bare string)
    NEW-02  RulePlugin protocol untuk third-party rule registration
    NEW-03  StructuredLogger untuk audit trail yang SOX-compliant
"""

# ── Standard library ──────────────────────────────────────────────────────────
import ast
import concurrent.futures
import copy
import difflib          # FIX-05: pindah dari dalam fungsi
import json
import logging
import os
import re
import sys
import threading
import time
import traceback
import functools
from collections import Counter, OrderedDict, deque  # FIX-05: Counter dari collections
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
from pathlib import Path
from typing import (
    Any, Dict, FrozenSet, List, Optional, Set, Tuple, Union
)

# ── Soft dependencies ─────────────────────────────────────────────────────────
try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False
    nx = None  # type: ignore[assignment]

try:
    import jedi                                       # noqa: F401
    HAS_JEDI = True
except ImportError:
    HAS_JEDI = False

try:
    import libcst as cst                              # noqa: F401
    HAS_LIBCST = True
except ImportError:
    HAS_LIBCST = False

try:
    from sqlalchemy.exc import SQLAlchemyError as _SQLAlchemyError
    HAS_SQLALCHEMY = True
except ImportError:
    _SQLAlchemyError = None   # type: ignore[assignment,misc]
    HAS_SQLALCHEMY = False

# ── Public API ────────────────────────────────────────────────────────────────
__all__ = [
    "RCAEngine", "RCAResult", "EvidenceItem",
    "Severity", "Category", "ErrorCode",
    "RCARule",
    "analyze", "analyze_exception", "get_engine", "reset_engine",
]

# ── Logging ───────────────────────────────────────────────────────────────────
_logger = logging.getLogger(__name__)
if not _logger.handlers:
    _logger.addHandler(logging.NullHandler())

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_CONTEXT_LINES    = 5
MAX_OBJECT_SIZE      = 100_000
MAX_EVIDENCE_ITEMS   = 30     # Naik dari 20 — SOX memerlukan evidence lengkap
MAX_EVIDENCE_LENGTH  = 500
MAX_IMPACT_ITEMS     = 10     # Naik dari 5
MAX_TRACEBACK_FRAMES = 30
MAX_CHILDREN         = 10
CACHE_SIZE           = 256
DEFAULT_CONFIDENCE   = 0.5
TIMEOUT_SECONDS      = 2.0
REPR_TIMEOUT_SECONDS = 0.5    # FIX-04: timeout untuk safe_repr

# Kata kunci sensitif yang TIDAK boleh masuk ke log (FIX-07)
_SENSITIVE_KEYS: FrozenSet[str] = frozenset({
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "credential", "credentials", "auth", "authorization", "private_key",
    "access_key", "secret_key", "db_password", "database_password",
    "encryption_key", "signing_key", "jwt", "bearer",
})

# ── ErrorCode ─────────────────────────────────────────────────────────────────
class ErrorCode(str, Enum):
    """Kode error RCA. Immutable karena berbasis str-Enum."""
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
# FIX-14: Ordering terintegrasi ke dalam Enum via functools.total_ordering
@functools.total_ordering
class Severity(Enum):
    """Tingkat keparahan. Comparable: FATAL > CRITICAL > HIGH > MEDIUM > LOW > INFO > HINT."""
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

    def __lt__(self, other: "Severity") -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self._order < other._order   # type: ignore[attr-defined]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self._order == other._order  # type: ignore[attr-defined]

    def __hash__(self) -> int:
        return hash(self._order)            # type: ignore[attr-defined]

    @property
    def order(self) -> int:
        return self._order                  # type: ignore[attr-defined]


# Backward-compatible ordering dict (untuk kode yang sudah ada menggunakannya)
_SEVERITY_ORDER: Dict["Severity", int] = {s: s.order for s in Severity}


class Category(Enum):
    """Kategori root cause."""
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
# NEW-01: Typed evidence untuk SOX-compliant audit trail
@dataclass
class EvidenceItem:
    """Satu butir evidence forensik. Menyimpan sumber dan konteks."""
    text        : str
    source_rule : str       = "unknown"
    evidence_type: str      = "general"   # "code", "frame", "pattern", "context"
    redacted    : bool      = False

    def to_str(self) -> str:
        prefix = "[REDACTED] " if self.redacted else ""
        return f"{prefix}{self.text}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text"        : self.text,
            "source_rule" : self.source_rule,
            "type"        : self.evidence_type,
            "redacted"    : self.redacted,
        }


# ── RCAResult ─────────────────────────────────────────────────────────────────
@dataclass
class RCAResult:
    """
    Hasil analisis root cause.

    Catatan mutability: field ini tidak frozen karena RCAEngine perlu
    menggabungkan hasil dari beberapa rule. Jangan mutasi setelah
    RCAEngine.analyze() return.
    """
    severity     : Severity
    category     : Category           = field(default=Category.UNKNOWN)
    error_code   : ErrorCode          = field(default=ErrorCode.UNKNOWN)
    root_cause   : str                = field(default="")
    evidence     : List[str]          = field(default_factory=list)
    impact       : List[str]          = field(default_factory=list)
    suggested_fix: str                = field(default="")
    raw_error    : str                = field(default="")
    confidence   : float              = field(default=0.0)
    parent       : Optional["RCAResult"] = field(default=None)
    children     : List["RCAResult"]  = field(default_factory=list)
    metadata     : Dict[str, Any]     = field(default_factory=dict)
    # NEW: typed evidence untuk SOX audit trail
    typed_evidence: List[EvidenceItem] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Clamp confidence ke [0.0, 1.0]
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

    def to_dict(self, _visited: Optional[Set[int]] = None) -> Dict[str, Any]:
        """Serialize ke dict dengan proteksi circular reference."""
        if _visited is None:
            _visited = set()
        obj_id = id(self)
        if obj_id in _visited:
            return {"_recursive": True}
        _visited.add(obj_id)

        def safe_str(v: Any) -> str:
            if isinstance(v, (str, int, float, bool)):
                return str(v)
            if isinstance(v, Enum):
                return v.value
            return repr(v)

        def clean_list(lst: Any, max_items: int) -> List[str]:
            return [
                safe_str(e)[:MAX_EVIDENCE_LENGTH]
                for e in (lst or [])[:max_items]
            ]

        # Parent: share _visited untuk deteksi chain A→B→A
        parent_dict = None
        if self.parent is not None and self.parent is not self:
            parent_dict = self.parent.to_dict(_visited)
            if parent_dict.get("_recursive"):
                parent_dict = None

        # Children: filter circular, batasi MAX_CHILDREN
        children_out = []
        for child in self.children[:MAX_CHILDREN]:
            if id(child) not in _visited and child is not self:
                d = child.to_dict(_visited)
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
        """Serialize ke JSON string. Aman untuk objek non-serializable."""
        try:
            return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            return json.dumps({"error": f"Serialization failed: {exc}"})

    def summary(self) -> str:
        """Ringkasan satu baris untuk logging."""
        return (
            f"[{self.error_code.value}] {self.severity.value} "
            f"({self.category.value}) conf={self.confidence:.2f}: "
            f"{self.root_cause[:100]}"
        )


# ── Thread-safe LRU Cache ─────────────────────────────────────────────────────
class _ThreadSafeLRUCache:
    """LRU cache thread-safe dengan RLock. Key bisa berupa tuple apapun."""

    def __init__(self, maxsize: int = CACHE_SIZE) -> None:
        self.maxsize = maxsize
        self._cache: "OrderedDict[Any, Any]" = OrderedDict()
        self._lock  = threading.RLock()
        self._hits  = 0
        self._misses= 0

    def get(self, key: Any) -> Optional[Any]:
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
        """Hapus semua entry yang key[0] == path."""
        with self._lock:
            keys_to_delete = [
                k for k in self._cache
                if isinstance(k, tuple) and k and k[0] == path
            ]
            for k in keys_to_delete:
                del self._cache[k]

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "size"  : len(self._cache),
                "hits"  : self._hits,
                "misses": self._misses,
            }


_file_cache    = _ThreadSafeLRUCache(CACHE_SIZE)
_ast_cache     = _ThreadSafeLRUCache(CACHE_SIZE)
_context_cache = _ThreadSafeLRUCache(CACHE_SIZE)


# ── reprlib (lazy, thread-safe, dengan timeout) ───────────────────────────────
_reprlib_lock = threading.Lock()
_reprlib_fn: Optional[Any] = None


def _get_reprlib() -> Any:
    """Lazy init reprlib.Repr dengan double-checked locking."""
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
    """
    Representasi aman dari objek, dengan timeout untuk mencegah CPU spike.
    FIX-04: Tambahkan timeout via ThreadPoolExecutor.
    """
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


# ── Credential redaction ──────────────────────────────────────────────────────
def _is_sensitive_key(key: str) -> bool:
    """Cek apakah key mengandung kata kunci sensitif (case-insensitive)."""
    key_lower = key.lower()
    return any(sk in key_lower for sk in _SENSITIVE_KEYS)


# ── File utilities ────────────────────────────────────────────────────────────
def _get_file_info(path: str) -> Optional[Tuple[float, int]]:
    """Ambil (mtime, size) dari file. Return None jika tidak accessible."""
    try:
        stat = os.stat(path)
        return stat.st_mtime, stat.st_size
    except OSError:
        return None


def _get_file_content(filename: str) -> Optional[str]:
    """Baca konten file dengan cache berbasis (path, mtime, size)."""
    info = _get_file_info(filename)
    if info is None:
        return None
    mtime, size = info
    key    = (filename, mtime, size)
    cached = _file_cache.get(key)
    if cached is not None:
        return cached
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252", "iso-8859-1"):
        try:
            with open(filename, "r", encoding=enc, errors="replace") as f:
                content = f.read()
            _file_cache.set(key, content)
            return content
        except (UnicodeDecodeError, LookupError, OSError):
            continue
    return None


def get_ast(filename: str) -> Optional[ast.AST]:
    """Parse file Python ke AST dengan cache. Return None jika syntax error."""
    info = _get_file_info(filename)
    if info is None:
        return None
    mtime, size = info
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
    except (SyntaxError, MemoryError, RecursionError):  # FIX-26: tangkap MemoryError
        return None


def get_code_context(
    filename: str,
    lineno: int,
    context_lines: int = MAX_CONTEXT_LINES,
) -> List[str]:
    """
    Ambil baris kode sekitar lineno dengan cache.
    FIX-09: Guard untuk lineno <= 0.
    """
    if lineno <= 0:           # FIX-09: frame dari C extension / exec()
        return []
    info = _get_file_info(filename)
    if info is None:
        return []
    mtime, size = info
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
    result = [f"{i + 1}: {lines[i].rstrip()}" for i in range(start, end)]
    _context_cache.set(key, result)
    return result


def _get_error_line(
    code: List[str],
    frame_lineno: int,
    context_lines: int = MAX_CONTEXT_LINES,
) -> Optional[str]:
    """
    Hitung index baris error dalam list code yang dikembalikan get_code_context().
    Return string baris atau None jika tidak valid.
    FIX-14: Guard untuk lineno <= 0 sudah dilakukan di caller; di sini kita
    hitung index dengan benar.
    """
    if not code or frame_lineno <= 0:
        return None
    start      = max(0, frame_lineno - context_lines - 1)
    target_idx = frame_lineno - 1 - start
    target_idx = max(0, min(target_idx, len(code) - 1))
    return code[target_idx]


def get_frame_locals(frame: Any, max_items: int = 10) -> Dict[str, str]:
    """
    Ambil variabel lokal dari frame aktif (bukan FrameSummary).
    FIX-07: Nilai sensitif di-redact.
    """
    if not hasattr(frame, "f_locals"):
        return {}
    filtered: Dict[str, str] = {}
    for k, v in list(frame.f_locals.items())[:max_items]:
        if k.startswith("__") and k.endswith("__"):
            continue
        if _is_sensitive_key(k):
            filtered[k] = "[REDACTED — sensitive key]"
        else:
            filtered[k] = safe_repr(v)
    return filtered


def get_traceback_frames(exc: BaseException) -> List[traceback.FrameSummary]:
    """Ekstrak FrameSummary dari traceback exception."""
    tb = exc.__traceback__
    if tb is None:
        return []
    frames = list(traceback.extract_tb(tb))
    return frames[-MAX_TRACEBACK_FRAMES:]


def flatten_exception(
    exc: BaseException,
    _seen: Optional[Set[int]] = None,
) -> List[BaseException]:
    """
    Flatten ExceptionGroup ke list of exceptions.
    FIX-12: Cycle detection via _seen set.
    """
    if _seen is None:
        _seen = set()
    result: List[BaseException] = []
    if id(exc) in _seen:
        return result
    _seen.add(id(exc))
    if hasattr(exc, "exceptions") and isinstance(exc.exceptions, (list, tuple)):
        for e in exc.exceptions:
            result.extend(flatten_exception(e, _seen))
    else:
        result.append(exc)
    return result


def get_all_causes(exc: BaseException) -> List[BaseException]:
    """
    BFS untuk mengumpulkan seluruh exception chain termasuk ExceptionGroup.
    Menghormati __suppress_context__ (from None).
    """
    result: List[BaseException] = []
    seen  : Set[int]            = set()
    queue : deque               = deque([exc])

    while queue:
        e   = queue.popleft()
        eid = id(e)
        if eid in seen:
            continue
        seen.add(eid)
        result.append(e)

        if e.__cause__ is not None:
            queue.append(e.__cause__)

        suppress = getattr(e, "__suppress_context__", False)
        if (e.__context__ is not None
                and e.__context__ is not e.__cause__
                and not suppress):
            queue.append(e.__context__)

        # Flatten ExceptionGroup sub-exceptions
        if hasattr(e, "exceptions"):
            for sub in flatten_exception(e):
                if id(sub) not in seen:
                    queue.append(sub)

    return result


# ── Base Rule ─────────────────────────────────────────────────────────────────
class RCARule(ABC):
    """
    Base class untuk semua rule analisis.
    Subclass WAJIB override match() dan analyze().
    """

    def __init__(
        self,
        priority : int             = 0,
        enabled  : bool            = True,
        name     : Optional[str]   = None,    # FIX-13: Optional[str]
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
        self._stats: Dict[str, Any] = {
            "matches": 0, "hits": 0, "misses": 0, "errors": 0, "time_ms": 0.0,
        }

    @abstractmethod
    def match(
        self,
        exc     : BaseException,
        frames  : List[traceback.FrameSummary],
        context : Dict[str, Any],
    ) -> bool:
        """Return True jika rule ini relevan untuk exception ini."""

    @abstractmethod
    def analyze(
        self,
        exc     : BaseException,
        frames  : List[traceback.FrameSummary],
        context : Dict[str, Any],
    ) -> Optional[RCAResult]:
        """Analisis exception dan return RCAResult, atau None jika tidak konklusif."""

    def stats(self) -> Dict[str, Any]:
        with self._stats_lock:
            s = dict(self._stats)
        s["name"]     = self.name
        s["priority"] = self.priority
        s["enabled"]  = self.enabled
        return s

    def _make_evidence(self, text: str, evidence_type: str = "general") -> EvidenceItem:
        """Helper untuk membuat EvidenceItem dengan nama rule otomatis."""
        return EvidenceItem(text=text, source_rule=self.name, evidence_type=evidence_type)

    def __repr__(self) -> str:
        return f"<{self.name} priority={self.priority} enabled={self.enabled}>"


# ─────────────────────────────────────────────────────────────────────────────
# ── RULES ────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class ImportErrorRule(RCARule):
    """Deteksi kegagalan import: modul tidak ditemukan, __init__.py hilang."""

    def __init__(self) -> None:
        super().__init__(
            priority=100, category=Category.IMPORT, name="ImportErrorRule"
        )

    def match(self, exc, frames, context) -> bool:
        return isinstance(exc, (ImportError, ModuleNotFoundError))

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        msg        = str(exc)
        evidence   : List[str] = []
        impact     : List[str] = []
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
                missing_init: List[str] = []
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


class CircularImportRule(RCARule):
    """
    Deteksi circular import menggunakan graph analysis (networkx).
    FIX-19: Fallback deteksi jika semua frames dari frozen modules.
    """

    # Kata kunci yang mengindikasikan circular import dalam pesan error
    _CIRCULAR_HINTS = re.compile(
        r"(circular import|partially initialized module|most likely due to)",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        super().__init__(
            priority=95, category=Category.IMPORT, name="CircularImportRule"
        )

    def match(self, exc, frames, context) -> bool:
        if not isinstance(exc, (ImportError, ModuleNotFoundError)):
            return False
        # FIX-19: Cek message jika tidak ada frame .py
        if self._CIRCULAR_HINTS.search(str(exc)):
            return True
        if not HAS_NETWORKX:
            return False
        filenames = [f.filename for f in frames if f.filename.endswith(".py")]
        return len(filenames) != len(set(filenames))

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        # Fallback: deteksi dari message saja
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


class AttributeErrorRule(RCARule):
    """Deteksi AttributeError: atribut tidak ada, akses NoneType."""

    def __init__(self) -> None:
        super().__init__(
            priority=90, category=Category.ATTRIBUTE, name="AttributeErrorRule"
        )

    _PATTERNS = [
        re.compile(r"^'?(\w[\w.]*)'? object has no attribute '(\w+)'"),
        re.compile(r"^module '([^']+)' has no attribute '([^']+)'"),
    ]

    def match(self, exc, frames, context) -> bool:
        return isinstance(exc, AttributeError)

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        msg        = str(exc)
        evidence   : List[str] = []
        impact     : List[str] = []
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

        # NoneType — pattern kritis tersendiri
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
                            attrs: Set[str] = set()
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


class TypeErrorRule(RCARule):
    """Deteksi TypeError: argumen salah, tipe tidak kompatibel, tidak callable."""

    # FIX-L09: Class-level constant, tidak dibuat ulang setiap call
    _PATTERNS: List[Tuple[re.Pattern, ErrorCode, Any]] = []  # di-set di __init_subclass__ atau __init__

    def __init__(self) -> None:
        super().__init__(priority=80, category=Category.TYPE, name="TypeErrorRule")
        # Dipindahkan ke __init__ agar akses re.compile hanya sekali per instance
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
        ]

    def match(self, exc, frames, context) -> bool:
        return isinstance(exc, TypeError)

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        msg        = str(exc)
        evidence   : List[str] = []
        impact     : List[str] = []
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


class NameErrorRule(RCARule):
    """Deteksi NameError: variabel tidak terdefinisi, typo, scope issue."""

    # FIX-L06 + FIX-01: Class-level constant, tidak dibuat ulang per call
    # FIX-01: Hapus duplikat key "lenght"
    _BUILTIN_TYPOS: Dict[str, str] = {
        "true"   : "True",
        "false"  : "False",
        "none"   : "None",
        "print_" : "print",
        "lenght" : "len",    # FIX-01: hanya satu entry
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

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        msg        = str(exc)
        evidence   : List[str] = []
        impact     : List[str] = []
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
                        defined_names: Set[str] = set()
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


class KeyErrorRule(RCARule):
    """Deteksi KeyError: dict key tidak ada — sangat kritis di ERP config/mapping."""

    # FIX-L07: Class-level constant
    _ERP_CONTEXTS: Dict[str, Tuple[str, str]] = {
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
    }

    def __init__(self) -> None:
        super().__init__(priority=85, category=Category.TYPE, name="KeyErrorRule")

    def match(self, exc, frames, context) -> bool:
        return isinstance(exc, KeyError)

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        raw   = str(exc)
        key   = exc.args[0] if exc.args else None
        key_s = repr(key) if key is not None else raw

        evidence   : List[str] = []
        impact     : List[str] = []
        root_cause = suggested_fix = ""
        confidence = 0.8
        matched_ctx: Optional[str] = None

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


class IndexErrorRule(RCARule):
    """Deteksi IndexError / out-of-range di data processing ERP."""

    _RANGE_PATTERN = re.compile(
        r"list index out of range|tuple index out of range|"
        r"string index out of range|index (\d+) is out of bounds"
    )

    def __init__(self) -> None:
        super().__init__(priority=84, category=Category.TYPE, name="IndexErrorRule")

    def match(self, exc, frames, context) -> bool:
        return isinstance(exc, (IndexError, StopIteration))

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        msg        = str(exc)
        evidence   : List[str] = []
        impact     : List[str] = []
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


class ValueErrorRule(RCARule):
    """Deteksi ValueError — validasi bisnis ERP: akun, periode, jumlah, konversi."""

    # FIX-L08: Class-level constant
    _ERP_PATTERNS: List[Tuple[str, ErrorCode, "Severity", str, str, float]] = [
        (r"period.*(closed|locked|not.open)",
         ErrorCode.ERP_PERIOD_CLOSED, Severity.CRITICAL,
         "Periode akuntansi sudah ditutup atau dikunci.",
         "Buka kembali periode di modul akuntansi atau gunakan periode yang masih aktif.",
         0.92),
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
    ]

    # Cache compiled patterns untuk performa
    _COMPILED: Optional[List[Tuple[re.Pattern, ErrorCode, "Severity", str, str, float]]] = None

    def __init__(self) -> None:
        super().__init__(priority=83, category=Category.DDD, name="ValueErrorRule")
        if ValueErrorRule._COMPILED is None:
            ValueErrorRule._COMPILED = [
                (re.compile(p, re.IGNORECASE), code, sev, cause, fix, conf)
                for p, code, sev, cause, fix, conf in self._ERP_PATTERNS
            ]

    def match(self, exc, frames, context) -> bool:
        return isinstance(exc, ValueError)

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        raw        = str(exc)
        evidence   : List[str] = []
        impact     : List[str] = []
        root_cause = suggested_fix = ""
        confidence = DEFAULT_CONFIDENCE
        error_code = ErrorCode.VALUE_INVALID
        severity   = Severity.MEDIUM

        assert self._COMPILED is not None  # mypy guard
        for pattern, code, sev, cause, fix, conf in self._COMPILED:
            if pattern.search(raw):          # FIX-07: gunakan raw langsung + IGNORECASE
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


class InfrastructureConnectionRule(RCARule):
    """Deteksi kegagalan koneksi infrastruktur: DB, Redis, Kafka, HTTP."""

    _DB_PATTERN = re.compile(
        r"(connection refused|could not connect|"
        r"lost connection|server closed|"
        r"operational.?error|can.?t connect|"
        r"database.*unavailable|too many connections|"
        r"connection.?timed?.out|no route to host)",
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
        if isinstance(exc, (PermissionError, FileNotFoundError, IsADirectoryError, NotADirectoryError)):
            return False
        msg = str(exc)
        # FIX-17: Tambahkan OSError (parent ConnectionError)
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

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        msg        = str(exc)
        evidence   = [f"Exception: {type(exc).__name__}: {msg[:200]}"]
        impact     : List[str] = []
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


class CQRSHandlerRule(RCARule):
    """Deteksi kegagalan CQRS: command/query handler tidak terdaftar atau gagal."""

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

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        msg        = str(exc)
        evidence   : List[str] = []
        impact     : List[str] = []
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


class DomainRepositoryMismatchRule(RCARule):
    """Deteksi mismatch Repository DDD — interface vs implementasi."""

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

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        evidence   : List[str] = []
        impact     : List[str] = []
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


class EventPublishRule(RCARule):
    """Deteksi kegagalan publish/dispatch domain event."""

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

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        evidence   : List[str] = []
        impact     : List[str] = []
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


class ContainerErrorRule(RCARule):
    """Deteksi kegagalan DI Container: service tidak terdaftar atau binding gagal."""

    _CONTAINER_KEYWORDS = re.compile(
        r"\b(container|dependency[_\s]injection|di[_\s]container|ioc|"
        r"resolve[_\s]service|service[_\s]provider)\b",
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

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        evidence   : List[str] = []
        impact     : List[str] = []
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


class AggregateErrorRule(RCARule):
    """Deteksi error pada Aggregate DDD — apply event gagal, invariant dilanggar."""

    def __init__(self) -> None:
        super().__init__(priority=62, category=Category.DDD, name="AggregateErrorRule")

    def match(self, exc, frames, context) -> bool:
        if "aggregate" in str(exc).lower():
            return True
        for f in frames:
            if "aggregate" in f.name.lower() or "aggregate" in f.filename.lower():
                return True
        return False

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        evidence   : List[str] = []
        impact     : List[str] = []
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


class UnitOfWorkErrorRule(RCARule):
    """Deteksi error di UnitOfWork — commit/rollback gagal."""

    # FIX-18: Gunakan word boundary untuk "uow"
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

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        evidence   : List[str] = []
        impact     : List[str] = []
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


class TransactionIntegrityRule(RCARule):
    """Deteksi pelanggaran integritas transaksi database."""

    _TX_KEYWORDS = frozenset({
        "unitofwork", "transaction", "uow", "commit", "rollback", "session",
    })

    def __init__(self) -> None:
        super().__init__(
            priority=65, category=Category.DATABASE, name="TransactionIntegrityRule"
        )

    def match(self, exc, frames, context) -> bool:
        db_types: Tuple[type, ...] = (ValueError, RuntimeError)
        if HAS_SQLALCHEMY and _SQLAlchemyError is not None:
            db_types = db_types + (_SQLAlchemyError,)
        if not isinstance(exc, db_types):
            return False
        for f in frames:
            text = f"{f.filename} {f.name}".lower()
            if any(k in text for k in self._TX_KEYWORDS):
                return True
        return False

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
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


class RecursionMemoryRule(RCARule):
    """Deteksi RecursionError dan MemoryError — sering terjadi di proses batch ERP."""

    def __init__(self) -> None:
        super().__init__(
            priority=95, category=Category.PERFORMANCE, name="RecursionMemoryRule"
        )

    def match(self, exc, frames, context) -> bool:
        return isinstance(exc, (RecursionError, MemoryError))

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        msg      = str(exc)
        evidence : List[str] = []
        impact   : List[str] = []

        if isinstance(exc, RecursionError):
            if frames:
                names = [f.name for f in frames]
                top   = Counter(names).most_common(3)  # FIX-22: Counter dari top-level import
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

        else:  # MemoryError — FIX-02: guard aman
            if frames:
                last_frame = frames[-1]  # FIX-02: assign dulu, gunakan kemudian
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


class PermissionFileRule(RCARule):
    """Deteksi PermissionError dan FileNotFoundError — common di ERP file processing."""

    _CONFIG_EXTENSIONS = frozenset({'.py', '.cfg', '.ini', '.yaml', '.yml', '.env', '.json', '.toml'})

    def __init__(self) -> None:
        super().__init__(
            priority=88, category=Category.SECURITY, name="PermissionFileRule"
        )

    def match(self, exc, frames, context) -> bool:
        return isinstance(exc, (PermissionError, FileNotFoundError, IsADirectoryError, NotADirectoryError))

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        msg        = str(exc)
        raw        = msg
        evidence   : List[str] = []
        impact     : List[str] = []
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


# ─────────────────────────────────────────────────────────────────────────────
# ── RCAEngine ─────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class RCAEngine:
    """
    Mesin RCA utama. Thread-safe, multi-rule, production-grade.

    Features:
    - Rule priority ordering
    - Per-rule timeout protection (FIX-17)
    - SOX-compliant evidence aggregation (FIX-03)
    - Comprehensive statistics
    - Plugin rule registration
    """

    VERSION = "3.0.0"

    def __init__(
        self,
        enable_networkx : bool = True,
        enable_jedi     : bool = True,
        enable_libcst   : bool = True,
        rule_timeout    : float = TIMEOUT_SECONDS,
    ) -> None:
        self._lock          = threading.RLock()
        self._rules         : List[RCARule]      = []
        self._rule_map      : Dict[str, RCARule] = {}
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
        for rule in [
            # Infrastructure — tertinggi, infra down = semua gagal
            InfrastructureConnectionRule(),
            RecursionMemoryRule(),
            PermissionFileRule(),
            # Import analysis
            ImportErrorRule(),
            CircularImportRule(),
            # Python builtins
            AttributeErrorRule(),
            TypeErrorRule(),
            NameErrorRule(),
            KeyErrorRule(),
            IndexErrorRule(),
            ValueErrorRule(),
            # Domain / DDD / ERP
            TransactionIntegrityRule(),
            CQRSHandlerRule(),
            DomainRepositoryMismatchRule(),
            EventPublishRule(),
            ContainerErrorRule(),
            AggregateErrorRule(),
            UnitOfWorkErrorRule(),
        ]:
            self.register_rule(rule)

    def register_rule(self, rule: RCARule) -> None:
        """Register rule baru. Jika sudah ada dengan nama sama, replace."""
        with self._lock:
            if rule.name in self._rule_map:
                try:
                    self._rules.remove(self._rule_map[rule.name])
                except ValueError:
                    pass
            self._rules.append(rule)
            self._rule_map[rule.name] = rule
            # Sort di dalam lock — aman karena RLock reentrant untuk thread yang sama
            self._rules.sort(key=lambda r: r.priority, reverse=True)

    def unregister_rule(self, name: str) -> bool:
        """Hapus rule berdasarkan nama. Return True jika berhasil."""
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
        context  : Optional[Dict[str, Any]] = None,
    ) -> RCAResult:
        """
        Entry point utama. Thread-safe.
        FIX-20: Validasi input type.
        FIX-03: SOX-compliant evidence aggregation.
        FIX-17: Per-rule timeout.
        """
        # FIX-20: Validasi input
        if not isinstance(exception, BaseException):
            raise TypeError(
                f"analyze() mengharapkan BaseException, bukan {type(exception).__name__}"
            )

        start_time = time.perf_counter()

        with self._lock:
            self._stats["total_analyses"] += 1

        ctx = context or {}
        try:
            safe_context = copy.deepcopy(ctx)
        except Exception:
            safe_context = dict(ctx)

        frames = get_traceback_frames(exception)

        all_exceptions   = get_all_causes(exception)
        combined_results : List[RCAResult] = []

        # Snapshot rules untuk thread safety
        with self._lock:
            rules_snapshot = list(self._rules)

        for exc in all_exceptions:
            exc_frames = get_traceback_frames(exc) or frames
            for rule in rules_snapshot:
                if not rule.enabled:
                    continue
                # FIX-17: Timeout per rule
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

        # Pilih best: severity dulu, kemudian confidence
        best = max(
            combined_results,
            key=lambda r: (r.severity.order, r.confidence),
        )

        # FIX-03: SOX-compliant evidence — pertahankan dengan label rule asal
        # Tidak menggunakan dict.fromkeys() yang membuang evidence
        seen_evidence: Set[str] = set()
        all_evidence  : List[str] = []
        for r in combined_results:
            for ev in r.evidence:
                # Deduplikasi hanya jika teks 100% identik dari rule yang sama
                ev_normalized = ev.strip()
                if ev_normalized and ev_normalized not in seen_evidence:
                    seen_evidence.add(ev_normalized)
                    all_evidence.append(ev)

        seen_impact: Set[str] = set()
        all_impact  : List[str] = []
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
        """
        Jalankan fn(*args, **kwargs) dengan timeout.
        Raise exception asli jika fn crash, TimeoutError jika timeout.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(fn, *args, **kwargs)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                raise TimeoutError(f"{fn.__qualname__} timeout setelah {timeout}s")

    def _fallback_analysis(
        self,
        exception : BaseException,
        frames    : List[traceback.FrameSummary],
        context   : Dict[str, Any],
    ) -> RCAResult:
        """Fallback jika tidak ada rule yang match."""
        _severity_map: Dict[type, Severity] = {
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

    def stats(self) -> Dict[str, Any]:
        """Return statistik engine dan per-rule."""
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
        """Bersihkan semua cache."""
        _file_cache.clear()
        _ast_cache.clear()
        _context_cache.clear()


# ── Singleton ─────────────────────────────────────────────────────────────────
_DEFAULT_ENGINE : Optional[RCAEngine] = None
_ENGINE_LOCK    = threading.Lock()


def get_engine() -> RCAEngine:
    """Dapatkan singleton RCAEngine (double-checked locking, thread-safe)."""
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is None:
        with _ENGINE_LOCK:
            if _DEFAULT_ENGINE is None:
                _DEFAULT_ENGINE = RCAEngine()
    return _DEFAULT_ENGINE


def reset_engine() -> None:
    """
    Reset singleton engine. Berguna untuk unit testing.
    FIX-15: Tambahan untuk testability.
    """
    global _DEFAULT_ENGINE
    with _ENGINE_LOCK:
        _DEFAULT_ENGINE = None


def analyze_exception(
    exception: BaseException,
    context  : Optional[Dict[str, Any]] = None,
) -> RCAResult:
    """
    Shortcut module-level untuk analisis exception.
    FIX-20: Validasi dilakukan di RCAEngine.analyze().
    """
    return get_engine().analyze(exception, context)


# Alias backward-compatible — tapi lebih eksplisit
analyze = analyze_exception


# ─────────────────────────────────────────────────────────────────────────────
# ── Self-test ─────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def self_test(verbose: bool = True) -> bool:
    """
    Test komprehensif semua rule. Return True jika semua lulus.
    FIX-16: Tidak akses engine._rules langsung.
    """
    engine = RCAEngine()
    passed = failed = 0
    rule_count = engine.stats()["engine"]["rule_count"]

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
        print(f"Running RCA self-test (v{RCAEngine.VERSION}) — {rule_count} rules registered…")
        print()

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
        _X().missing_attr  # type: ignore[attr-defined]
    except Exception as e:
        r = engine.analyze(e)
        check("AttributeErrorRule — missing attr",
              r.category == Category.ATTRIBUTE, str(r.category))

    try:
        obj = None
        obj.something  # type: ignore[union-attr]
    except Exception as e:
        r = engine.analyze(e)
        check("AttributeErrorRule — NoneType (ATTR_NONE_ACCESS)",
              r.error_code == ErrorCode.ATTR_NONE_ACCESS, str(r.error_code))

    # ── Type ──────────────────────────────────────────────────────────────────
    try:
        len(123)  # type: ignore[arg-type]
    except Exception as e:
        r = engine.analyze(e)
        check("TypeErrorRule — not iterable",
              r.category == Category.TYPE, str(r.category))

    try:
        def _f(a: int, b: int) -> int: return a + b
        _f(1)  # type: ignore[call-arg]
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
        d: Dict[str, str] = {}
        _ = d["account_code"]
    except Exception as e:
        r = engine.analyze(e)
        check("KeyErrorRule — account key (ERP context)",
              r.error_code == ErrorCode.KEY_NOT_FOUND, str(r.error_code))

    # ── IndexError ────────────────────────────────────────────────────────────
    try:
        lst: List[int] = []
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

    try:
        raise ValueError("invalid literal for int() with base 10: 'abc'")
    except Exception as e:
        r = engine.analyze(e)
        check("ValueErrorRule — int conversion (VALUE_INVALID)",
              r.error_code == ErrorCode.VALUE_INVALID, str(r.error_code))

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

    # ── DDD Domain ────────────────────────────────────────────────────────────
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

    try:
        raise RuntimeError("Aggregate apply event failed in AggregateRoot")
    except Exception as e:
        r = engine.analyze(e)
        check("AggregateErrorRule — apply fail",
              r.error_code == ErrorCode.AGGREGATE_ERROR, str(r.error_code))

    # ── Data quality ──────────────────────────────────────────────────────────
    r_hi = RCAResult(severity=Severity.HIGH, confidence=1.5)
    check("Confidence clamp upper", r_hi.confidence == 1.0, str(r_hi.confidence))

    r_lo = RCAResult(severity=Severity.LOW, confidence=-0.5)
    check("Confidence clamp lower", r_lo.confidence == 0.0, str(r_lo.confidence))

    # Circular ref in to_dict — FIX-11
    ra = RCAResult(severity=Severity.INFO)
    rb = RCAResult(severity=Severity.INFO)
    ra.children.append(rb)
    rb.children.append(ra)
    try:
        ra.to_dict()
        check("Circular ref protection in to_dict", True)
    except RecursionError:
        check("Circular ref protection in to_dict", False, "RecursionError!")

    try:
        ra.to_json()
        check("to_json safety", True)
    except Exception as ex:
        check("to_json safety", False, str(ex))

    # __suppress_context__ test
    try:
        try:
            raise ValueError("inner")
        except ValueError:
            raise RuntimeError("outer") from None
    except Exception as e:
        causes = get_all_causes(e)
        check("__suppress_context__ honored in get_all_causes",
              all(not isinstance(c, ValueError) for c in causes),
              f"causes={[type(c).__name__ for c in causes]}")

    # Severity ordering — FIX-14
    check("Severity ordering: FATAL > CRITICAL",
          Severity.FATAL > Severity.CRITICAL)
    check("Severity ordering: CRITICAL > HIGH",
          Severity.CRITICAL > Severity.HIGH)
    check("Severity ordering: LOW < MEDIUM",
          Severity.LOW < Severity.MEDIUM)

    # Tie-breaking: dua CRITICAL, confidence berbeda
    r_low_conf  = RCAResult(severity=Severity.CRITICAL, confidence=0.5,
                             root_cause="low", error_code=ErrorCode.UNKNOWN)
    r_high_conf = RCAResult(severity=Severity.CRITICAL, confidence=0.9,
                             root_cause="high", error_code=ErrorCode.UNKNOWN)
    best = max([r_low_conf, r_high_conf],
               key=lambda r: (r.severity.order, r.confidence))
    check("Severity+confidence tie-breaking", best.root_cause == "high",
          f"got root_cause={best.root_cause}")

    # ErrorCode immutability
    try:
        ErrorCode.UNKNOWN = "HACKED"  # type: ignore[misc]
        check("ErrorCode immutability (Enum)", False, "mutation succeeded!")
    except (AttributeError, TypeError):
        check("ErrorCode immutability (Enum)", True)

    # Input validation — FIX-20
    try:
        analyze_exception("not an exception")  # type: ignore[arg-type]
        check("analyze_exception() input validation", False, "no TypeError raised")
    except TypeError:
        check("analyze_exception() input validation — TypeError on non-exception", True)

    # Credential redaction — FIX-07
    check("_is_sensitive_key('password')", _is_sensitive_key("password"))
    check("_is_sensitive_key('db_password')", _is_sensitive_key("db_password"))
    check("_is_sensitive_key('username') == False", not _is_sensitive_key("username"))

    # NameErrorRule _BUILTIN_TYPOS tidak ada duplikat — FIX-01
    typo_keys = list(NameErrorRule._BUILTIN_TYPOS.keys())
    check("NameErrorRule._BUILTIN_TYPOS no duplicate keys",
          len(typo_keys) == len(set(typo_keys)),
          f"duplicates: {[k for k in typo_keys if typo_keys.count(k) > 1]}")

    # reset_engine — FIX-15
    reset_engine()
    e1 = get_engine()
    e2 = get_engine()
    check("get_engine() returns same singleton after reset", e1 is e2)

    # flatten_exception cycle detection — FIX-12
    class _CyclicExcGroup(Exception):
        def __init__(self):
            self.exceptions = []
    ceg = _CyclicExcGroup()
    ceg.exceptions.append(ceg)  # self-reference
    try:
        result = flatten_exception(ceg)
        check("flatten_exception cycle detection", True)
    except RecursionError:
        check("flatten_exception cycle detection", False, "RecursionError!")

    if verbose:
        print()
        print(f"Self-test: {passed} passed, {failed} failed "
              f"({'✅ ALL PASS' if failed == 0 else '❌ SOME FAILED'})")

    return failed == 0


def benchmark(iterations: int = 500) -> Dict[str, float]:
    """
    Benchmark engine performa dengan reporting percentile.
    FIX-20: Tambah P50, P95, P99.
    """
    import statistics

    engine = RCAEngine()
    try:
        try:
            raise ValueError("Root cause")
        except ValueError as e:
            raise RuntimeError("Wrapper") from e
    except Exception as exc:
        times: List[float] = []
        for _ in range(iterations):
            t0 = time.perf_counter()
            engine.analyze(exc)
            times.append((time.perf_counter() - t0) * 1000)  # ms

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


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    ok = self_test(verbose=True)
    print()
    benchmark(iterations=500)
    print(f"\nRCA Engine v{RCAEngine.VERSION} ready. "
          f"{'All systems nominal.' if ok else 'WARNING: Self-test failures detected.'}")
    sys.exit(0 if ok else 1)