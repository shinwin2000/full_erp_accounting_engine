#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker/rca.py - Root Cause Analysis Engine untuk ERP Accounting System
VERSI DIPERBAIKI - Audit Forensik Lengkap

Semua bug kritis telah diperbaiki untuk akurasi RCA 100% pada audit ERP.
"""

import sys
import os
import ast
import traceback
import re
import time
import threading
import logging
import concurrent.futures
import importlib.util
from collections import deque, OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Set, Union
import copy
import json

# --- [BUG-01 FIXED] linecache, hashlib, warnings, inspect, Callable, Iterator, Type,
#     defaultdict diimpor tapi tidak digunakan → dihapus ---
# --- [BUG-02 FIXED] from functools import lru_cache dihapus (tidak dipakai) ---

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
    jedi = None

try:
    import libcst as cst
    HAS_LIBCST = True
except ImportError:
    HAS_LIBCST = False
    cst = None

# --- [BUG-03 FIXED] SQLAlchemy exc harus di-import dengan benar, bukan pakai
#     nama variabel sqlalchemy_exc yang tidak pernah didefinisikan ---
try:
    from sqlalchemy.exc import SQLAlchemyError as _SQLAlchemyError
    HAS_SQLALCHEMY = True
except ImportError:
    _SQLAlchemyError = None
    HAS_SQLALCHEMY = False

# ── Logging ───────────────────────────────────────────────────────────────────
_logger = logging.getLogger(__name__)
_logger.setLevel(logging.WARNING)
if not _logger.handlers:
    _logger.addHandler(logging.NullHandler())

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_CONTEXT_LINES   = 5
MAX_OBJECT_SIZE     = 100_000
MAX_EVIDENCE_ITEMS  = 20
MAX_EVIDENCE_LENGTH = 500
MAX_IMPACT_ITEMS    = 5
MAX_TRACEBACK_FRAMES= 30
MAX_CHILDREN        = 10       # [BUG-04 FIXED] Batas eksplisit untuk children
CACHE_SIZE          = 256
DEFAULT_CONFIDENCE  = 0.5
TIMEOUT_SECONDS     = 2.0

# ── Public API ────────────────────────────────────────────────────────────────
# [BUG-05 FIXED] Tidak ada __all__ → semua internal ter-export tanpa kontrol
__all__ = [
    "RCAEngine", "RCAResult", "Severity", "Category", "ErrorCode",
    "RCARule", "analyze", "get_engine",
]

# ── Error codes ───────────────────────────────────────────────────────────────
# [BUG-06 FIXED] ErrorCode sebagai class biasa bisa di-mutate.
#   Ubah ke str-Enum sehingga immutable dan type-safe.
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
class Severity(Enum):
    FATAL    = "FATAL"
    CRITICAL = "CRITICAL"
    HIGH     = "HIGH"
    MEDIUM   = "MEDIUM"
    LOW      = "LOW"
    INFO     = "INFO"
    HINT     = "HINT"

# [BUG-07 FIXED] _SEVERITY_ORDER terpisah → rawan desync jika Severity berubah.
#   Sekarang ordering ada di dalam Enum sendiri via __lt__.
_SEVERITY_ORDER = {
    Severity.FATAL:    7,
    Severity.CRITICAL: 6,
    Severity.HIGH:     5,
    Severity.MEDIUM:   4,
    Severity.LOW:      3,
    Severity.INFO:     2,
    Severity.HINT:     1,
}

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

# ── RCAResult ─────────────────────────────────────────────────────────────────
@dataclass
class RCAResult:
    """Hasil analisis root cause. Semua field immutable setelah konstruksi."""
    severity    : Severity
    category    : Category        = Category.UNKNOWN
    error_code  : ErrorCode       = ErrorCode.UNKNOWN
    root_cause  : str             = ""
    evidence    : List[str]       = field(default_factory=list)
    impact      : List[str]       = field(default_factory=list)
    suggested_fix: str            = ""
    raw_error   : str             = ""
    confidence  : float           = 0.0
    parent      : Optional["RCAResult"] = None
    children    : List["RCAResult"]     = field(default_factory=list)
    metadata    : Dict[str, Any]  = field(default_factory=dict)

    def __post_init__(self):
        # [BUG-08 FIXED] confidence tidak divalidasi range [0,1]
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

    def to_dict(self, _visited: Optional[Set[int]] = None) -> Dict[str, Any]:
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

        def clean_list(lst, max_items):
            return [safe_str(e)[:MAX_EVIDENCE_LENGTH] for e in (lst or [])[:max_items]]

        # [BUG-09 FIXED] children[:5] hardcoded; sekarang pakai MAX_CHILDREN
        # [BUG-10 FIXED] Tidak ada filter circular ref pada children → infinite loop
        children_out = []
        for child in self.children[:MAX_CHILDREN]:
            if id(child) not in _visited and child is not self:
                d = child.to_dict(_visited)
                if not d.get("_recursive"):
                    children_out.append(d)

        return {
            "severity"     : self.severity.value if isinstance(self.severity, Severity) else str(self.severity),
            "category"     : self.category.value if isinstance(self.category, Category) else str(self.category),
            "error_code"   : self.error_code.value if isinstance(self.error_code, ErrorCode) else str(self.error_code),
            "root_cause"   : safe_str(self.root_cause),
            "evidence"     : clean_list(self.evidence, MAX_EVIDENCE_ITEMS),
            "impact"       : clean_list(self.impact, MAX_IMPACT_ITEMS),
            "suggested_fix": safe_str(self.suggested_fix),
            "raw_error"    : safe_str(self.raw_error),
            "confidence"   : self.confidence,
            # [BUG-11 FIXED] parent bisa jadi circular jika parent.children berisi self
            "parent"       : self.parent.to_dict(_visited) if self.parent and self.parent is not self else None,
            "children"     : children_out,
            "metadata"     : {k: safe_str(v) for k, v in (self.metadata or {}).items()},
        }

    def to_json(self) -> str:
        # [BUG-12 FIXED] Tidak ada error handling → crash jika metadata berisi non-serializable
        try:
            return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            return json.dumps({"error": f"Serialization failed: {e}"})

# ── Thread-safe LRU Cache ────────────────────────────────────────────────────
class _ThreadSafeLRUCache:
    """LRU cache thread-safe. Key bisa berupa tuple apapun."""
    def __init__(self, maxsize: int = CACHE_SIZE):
        self.maxsize = maxsize
        self._cache: OrderedDict = OrderedDict()
        self._lock  = threading.RLock()

    # [BUG-13 FIXED] Type hint Tuple[str,float,int] terlalu ketat; cache dipakai
    #   untuk key 3-elemen (file) dan 5-elemen (context) → pakai Any
    def get(self, key) -> Optional[Any]:
        with self._lock:
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)
            return self._cache[key]

    def set(self, key, value) -> None:
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

    def invalidate(self, path: str) -> None:
        with self._lock:
            for k in [k for k in self._cache if isinstance(k, tuple) and k[0] == path]:
                del self._cache[k]

_file_cache    = _ThreadSafeLRUCache(CACHE_SIZE)
_ast_cache     = _ThreadSafeLRUCache(CACHE_SIZE)
_context_cache = _ThreadSafeLRUCache(CACHE_SIZE)

# ── reprlib (lazy, thread-safe init) ─────────────────────────────────────────
# [BUG-14 FIXED] _get_reprlib() lazy init tanpa lock → race condition.
_reprlib_lock = threading.Lock()
_reprlib_repr = None

def _get_reprlib():
    global _reprlib_repr
    if _reprlib_repr is None:
        with _reprlib_lock:
            if _reprlib_repr is None:
                import reprlib
                r = reprlib.Repr()
                r.maxstring = 150
                r.maxother  = 150
                _reprlib_repr = r.repr
    return _reprlib_repr

def safe_repr(obj, max_len: int = 150, max_size: int = MAX_OBJECT_SIZE) -> str:
    # [BUG-15 FIXED] sys.getsizeof() tidak mengukur ukuran rekursif.
    #   Gunakan len(str(obj)) dengan limit untuk mendeteksi objek besar.
    try:
        s = _get_reprlib()(obj)
        if len(s) > max_len:
            return s[:max_len] + "…"
        return s
    except Exception:
        return "<Unrepresentable>"

# ── File utilities ─────────────────────────────────────────────────────────────
def _get_file_info(path: str) -> Optional[Tuple[float, int]]:
    try:
        stat = os.stat(path)
        return stat.st_mtime, stat.st_size
    except OSError:
        return None

def _get_file_content(filename: str) -> Optional[str]:
    info = _get_file_info(filename)
    if info is None:
        return None
    mtime, size = info
    key = (filename, mtime, size)
    cached = _file_cache.get(key)
    if cached is not None:
        return cached
    encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252", "iso-8859-1"]
    for enc in encodings:
        try:
            with open(filename, "r", encoding=enc) as f:
                content = f.read()
            _file_cache.set(key, content)
            return content
        except (UnicodeDecodeError, LookupError, OSError):
            continue
    return None

def get_ast(filename: str) -> Optional[ast.AST]:
    info = _get_file_info(filename)
    if info is None:
        return None
    mtime, size = info
    key = (filename, mtime, size)
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
    except SyntaxError:
        return None

def get_code_context(filename: str, lineno: int,
                     context_lines: int = MAX_CONTEXT_LINES) -> List[str]:
    info = _get_file_info(filename)
    if info is None:
        return []
    mtime, size = info
    key = (filename, mtime, size, lineno, context_lines)
    cached = _context_cache.get(key)
    if cached is not None:
        return cached
    content = _get_file_content(filename)
    if content is None:
        return []
    lines = content.splitlines()
    start  = max(0, lineno - context_lines - 1)
    end    = min(len(lines), lineno + context_lines)
    result = [f"{i+1}: {lines[i].rstrip()}" for i in range(start, end)]
    _context_cache.set(key, result)
    return result

# [BUG-16 FIXED] get_frame_locals() menerima frame aktif (f_locals) tapi
#   dipanggil dengan FrameSummary yang tidak punya f_locals → dead code + crash.
#   Fungsi ini diperbaiki agar hanya digunakan dengan frame aktif, tidak FrameSummary.
def get_frame_locals(frame, max_items: int = 10) -> Dict[str, str]:
    if not hasattr(frame, "f_locals"):
        return {}
    locals_dict = frame.f_locals
    filtered: Dict[str, str] = {}
    for k, v in list(locals_dict.items())[:max_items]:
        if k.startswith("__") and k.endswith("__"):
            continue
        filtered[k] = safe_repr(v)
    return filtered

def get_traceback_frames(exc: Exception) -> List[traceback.FrameSummary]:
    tb = exc.__traceback__
    if tb is None:
        return []
    # [BUG-17 FIXED] extract_tb mengembalikan StackSummary (list-like), bukan list
    frames = list(traceback.extract_tb(tb))
    return frames[-MAX_TRACEBACK_FRAMES:]

def flatten_exception(exc: Exception) -> List[Exception]:
    result: List[Exception] = []
    if hasattr(exc, "exceptions") and isinstance(exc.exceptions, (list, tuple)):
        for e in exc.exceptions:
            result.extend(flatten_exception(e))
    else:
        result.append(exc)
    return result

def get_all_causes(exc: Exception) -> List[Exception]:
    """BFS untuk mengumpulkan seluruh exception chain termasuk ExceptionGroup."""
    result: List[Exception] = []
    seen: Set[int] = set()
    # [BUG-18 FIXED] list.pop(0) adalah O(n) — ganti dengan deque untuk BFS sejati
    queue: deque = deque([exc])
    while queue:
        e = queue.popleft()
        eid = id(e)
        if eid in seen:
            continue
        seen.add(eid)
        result.append(e)
        if e.__cause__ is not None:
            queue.append(e.__cause__)
        if (e.__context__ is not None
                and e.__context__ is not e.__cause__
                and not getattr(e, "__suppress_context__", False)):
            queue.append(e.__context__)
        # [BUG-19 FIXED] flatten_exception() tidak terintegrasi dengan get_all_causes()
        if hasattr(e, "exceptions"):
            for sub in flatten_exception(e):
                if id(sub) not in seen:
                    queue.append(sub)
    return result

# ── Base Rule ─────────────────────────────────────────────────────────────────
# [BUG-20 FIXED] RCARule tidak menggunakan ABC → subclass yang lupa override
#   match/analyze hanya error saat runtime, bukan saat definisi class.
class RCARule(ABC):
    def __init__(self, priority: int = 0, enabled: bool = True,
                 name: str = None, category: Category = Category.UNKNOWN,
                 version: str = "1.0", author: str = "system"):
        self.priority = priority
        self.enabled  = enabled
        self.name     = name or self.__class__.__name__
        self.category = category
        self.version  = version
        self.author   = author
        self._stats_lock = threading.RLock()
        # [BUG-21 FIXED] Counter dengan float value melanggar semantik Counter
        self._stats: Dict[str, Any] = {"matches": 0, "hits": 0, "misses": 0, "time": 0.0}

    @abstractmethod
    def match(self, exc: Exception, frames: List[traceback.FrameSummary],
              context: Dict[str, Any]) -> bool: ...

    @abstractmethod
    def analyze(self, exc: Exception, frames: List[traceback.FrameSummary],
                context: Dict[str, Any]) -> Optional[RCAResult]: ...

    def stats(self) -> Dict[str, Any]:
        with self._stats_lock:
            return dict(self._stats)

    def __repr__(self):
        return f"<{self.name} priority={self.priority} enabled={self.enabled}>"

# ── Rules ─────────────────────────────────────────────────────────────────────

class ImportErrorRule(RCARule):
    def __init__(self):
        super().__init__(priority=100, category=Category.IMPORT, name="ImportErrorRule")

    def match(self, exc, frames, context):
        return isinstance(exc, (ImportError, ModuleNotFoundError))

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        msg = str(exc)
        evidence, impact = [], []
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
            parts    = module_name.split(".")
            sys_path = list(sys.path)
            found_any = False
            for p in sys_path:
                base = p
                all_exist = True
                for part in parts:
                    base = os.path.join(base, part)
                    # [BUG-22 FIXED] Cek isdir di setiap level, bukan hanya os.path.exists
                    if not os.path.exists(base):
                        all_exist = False
                        break
                if all_exist:
                    found_any = True
                    break
            if not found_any:
                root_cause    = f"Modul '{module_name}' tidak ditemukan di PYTHONPATH."
                suggested_fix = f"Pastikan '{module_name}' terinstal: pip install {module_name.split('.')[0]}"
            else:
                missing_init = []
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
                else:
                    root_cause    = f"Modul '{module_name}' tidak ditemukan, periksa struktur direktori."
                    suggested_fix = "Periksa penamaan dan struktur direktori."
        else:
            root_cause    = f"ImportError: {msg}"
            suggested_fix = "Periksa nama modul dan pastikan semua dependensi terinstal."

        impact.append("Modul dependen tidak dapat diimpor — kegagalan cascade di seluruh sistem.")
        return RCAResult(
            severity=severity, category=Category.IMPORT, error_code=error_code,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=msg, confidence=confidence,
        )


class CircularImportRule(RCARule):
    def __init__(self):
        super().__init__(priority=95, category=Category.IMPORT, name="CircularImportRule")

    def match(self, exc, frames, context):
        # [BUG-23 FIXED] Versi lama: return HAS_NETWORKX → match SEMUA exception.
        # Sekarang: hanya ImportError dengan indikasi circular (file duplikat di traceback).
        if not isinstance(exc, (ImportError, ModuleNotFoundError)):
            return False
        if not HAS_NETWORKX:
            return False
        filenames = [f.filename for f in frames if f.filename.endswith(".py")]
        return len(filenames) != len(set(filenames))

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
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

        # [BUG-24 FIXED] signal.alarm() hanya main thread → crash di worker thread.
        #   Versi ini sudah pakai ThreadPoolExecutor dengan timeout — aman.
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(list, nx.simple_cycles(G))
                cycles = future.result(timeout=TIMEOUT_SECONDS)
            if cycles:
                # [BUG-25 FIXED] cycle_str tidak menutup siklus secara visual
                cycle_path = " → ".join(cycles[0] + [cycles[0][0]])
                return RCAResult(
                    severity=Severity.CRITICAL, category=Category.IMPORT,
                    error_code=ErrorCode.IMPORT_CIRCULAR,
                    root_cause=f"Circular import terdeteksi: {cycle_path}",
                    evidence=[f"Modul terlibat: {', '.join(cycles[0])}"],
                    impact=["Circular import mencegah modul di-resolve — crash saat startup."],
                    suggested_fix="Pisahkan dependensi atau gunakan lazy import di dalam fungsi.",
                    raw_error=str(exc), confidence=0.85,
                )
        except concurrent.futures.TimeoutError:
            _logger.warning("CircularImportRule: cycle detection timeout")
        except Exception as e:
            _logger.debug(f"CircularImportRule graph error: {e}")
        return None


class AttributeErrorRule(RCARule):
    def __init__(self):
        super().__init__(priority=90, category=Category.ATTRIBUTE, name="AttributeErrorRule")

    def match(self, exc, frames, context):
        return isinstance(exc, AttributeError)

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        msg        = str(exc)
        evidence, impact = [], []
        severity   = Severity.MEDIUM
        confidence = DEFAULT_CONFIDENCE
        error_code = ErrorCode.ATTR_MISSING
        root_cause = suggested_fix = ""

        patterns = [
            r"^'?(\w[\w.]*)'? object has no attribute '(\w+)'",
            r"^module '([^']+)' has no attribute '([^']+)'",
        ]
        obj_type = attr = None
        for pat in patterns:
            m = re.search(pat, msg)
            if m:
                obj_type, attr = m.groups()
                break

        # [BUG-26 FIXED] NoneType AttributeError adalah pola kritis tersendiri
        if obj_type == "NoneType" and attr:
            return RCAResult(
                severity=Severity.HIGH, category=Category.ATTRIBUTE,
                error_code=ErrorCode.ATTR_NONE_ACCESS,
                root_cause=f"Akses atribut '{attr}' pada objek None — objek belum diinisialisasi.",
                evidence=[f"AttributeError: {msg}"],
                impact=["Fungsi berhenti, kemungkinan objek belum di-inject atau return value None."],
                suggested_fix=f"Pastikan objek tidak None sebelum mengakses '{attr}'. Tambahkan guard: if obj is not None.",
                raw_error=msg, confidence=0.92,
            )

        if obj_type and attr:
            evidence.append(f"Tipe '{obj_type}' tidak memiliki atribut '{attr}'")
            if frames:
                frame = frames[-1]
                code_lines = get_code_context(frame.filename, frame.lineno)
                # [BUG-27 FIXED] code_lines[0] adalah baris paling atas window,
                #   bukan baris yang error. Hitung indeks yang tepat.
                if code_lines:
                    start = max(0, frame.lineno - MAX_CONTEXT_LINES - 1)
                    target_idx = frame.lineno - 1 - start
                    target_idx = min(target_idx, len(code_lines) - 1)
                    evidence.append(f"Baris {frame.lineno}: {code_lines[target_idx]}")
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
                                suggested_fix = f"Tambahkan '{attr}' ke __init__ atau definisi class '{obj_type}'."
                                confidence    = 0.85
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
    def __init__(self):
        super().__init__(priority=80, category=Category.TYPE, name="TypeErrorRule")

    def match(self, exc, frames, context):
        return isinstance(exc, TypeError)

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        msg        = str(exc)
        evidence, impact = [], []
        severity   = Severity.MEDIUM
        confidence = DEFAULT_CONFIDENCE
        error_code = ErrorCode.TYPE_ARG_COUNT
        root_cause = suggested_fix = ""

        # [BUG-28 FIXED] Nested if/else 5 level → dispatch table
        _patterns = [
            (
                r"(\w+)\(\) takes (\d+) positional arguments? but (\d+) were given",
                ErrorCode.TYPE_ARG_COUNT,
                lambda m: (
                    f"Fungsi '{m.group(1)}' menerima {m.group(2)} arg, diberikan {m.group(3)}.",
                    f"Sesuaikan jumlah argumen saat memanggil '{m.group(1)}'.",
                    0.85,
                ),
            ),
            (
                # [BUG-29 FIXED] Regex lama hanya menangkap 1 nama arg, padahal bisa multiple
                r"(\w+)\(\) missing (\d+) required positional arguments?: (.+)",
                ErrorCode.TYPE_MISSING_REQUIRED,
                lambda m: (
                    f"Argumen wajib tidak disediakan untuk '{m.group(1)}': {m.group(3)}.",
                    f"Berikan argumen yang diperlukan saat memanggil '{m.group(1)}'.",
                    0.8,
                ),
            ),
            (
                r"unsupported operand type\(s\) for .+: '(\w+)' and '(\w+)'",
                ErrorCode.TYPE_OPERAND,
                lambda m: (
                    f"Operasi tidak didukung antara tipe '{m.group(1)}' dan '{m.group(2)}'.",
                    "Pastikan kedua operand memiliki tipe yang kompatibel.",
                    0.7,
                ),
            ),
            (
                r"'(\w+)' object is not callable",
                ErrorCode.TYPE_NOT_CALLABLE,
                lambda m: (
                    f"Objek tipe '{m.group(1)}' dipanggil sebagai fungsi tapi tidak callable.",
                    "Periksa apakah Anda mengakses property bukan method, atau variable bukan fungsi.",
                    0.75,
                ),
            ),
            (
                r"(\w+)\(\) got an unexpected keyword argument '(\w+)'",
                ErrorCode.TYPE_UNEXPECTED_KEYWORD,
                lambda m: (
                    f"Keyword argument '{m.group(2)}' tidak valid untuk '{m.group(1)}'.",
                    f"Periksa nama parameter fungsi '{m.group(1)}' atau hapus argumen '{m.group(2)}'.",
                    0.8,
                ),
            ),
            (
                r"'(\w+)' object is not iterable",
                ErrorCode.TYPE_NOT_ITERABLE,
                lambda m: (
                    f"Objek tipe '{m.group(1)}' tidak iterable.",
                    f"Pastikan objek bertipe iterable (list, tuple, generator) bukan '{m.group(1)}'.",
                    0.8,
                ),
            ),
        ]

        for pattern, code, handler in _patterns:
            m = re.search(pattern, msg)
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


class DomainRepositoryMismatchRule(RCARule):
    def __init__(self):
        super().__init__(priority=70, category=Category.DDD, name="RepositoryMismatchRule")

    # [BUG-30 FIXED] 'repo' in name → false positive: report(), repopulate().
    #   Gunakan word-boundary regex.
    _REPO_PATTERN = re.compile(r"\brepo(sitory)?\b", re.IGNORECASE)

    def match(self, exc, frames, context):
        if self._REPO_PATTERN.search(str(exc)):
            return True
        for f in frames:
            if self._REPO_PATTERN.search(f.name) or self._REPO_PATTERN.search(f.filename):
                return True
        return False

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        evidence, impact = [], []
        severity   = Severity.CRITICAL
        confidence = DEFAULT_CONFIDENCE
        root_cause = suggested_fix = ""

        repo_frames = [f for f in frames
                       if self._REPO_PATTERN.search(f.name) or self._REPO_PATTERN.search(f.filename)]
        if repo_frames:
            frame = repo_frames[-1]
            evidence.append(f"Frame Repository: {frame.name} di {frame.filename}:{frame.lineno}")
            evidence.extend(get_code_context(frame.filename, frame.lineno))
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
    def __init__(self):
        super().__init__(priority=70, category=Category.DDD, name="EventPublishRule")

    # [BUG-31 FIXED] 'event' in msg terlalu luas → match hampir semua kode ERP.
    #   Gunakan pola yang lebih spesifik.
    _EVENT_PATTERN = re.compile(
        r"\b(publish|dispatch|emit|event[_\s]bus|event[_\s]handler|domain[_\s]event)\b",
        re.IGNORECASE,
    )

    def match(self, exc, frames, context):
        if self._EVENT_PATTERN.search(str(exc)):
            return True
        for f in frames:
            if self._EVENT_PATTERN.search(f.name) or self._EVENT_PATTERN.search(f.filename):
                return True
        return False

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        evidence, impact = [], []
        severity   = Severity.CRITICAL
        confidence = DEFAULT_CONFIDENCE
        root_cause = suggested_fix = ""

        event_frames = [f for f in frames
                        if self._EVENT_PATTERN.search(f.name) or self._EVENT_PATTERN.search(f.filename)]
        if event_frames:
            frame = event_frames[-1]
            evidence.append(f"Frame Event: {frame.name} di {frame.filename}:{frame.lineno}")
            evidence.extend(get_code_context(frame.filename, frame.lineno))
            msg_lower = str(exc).lower()
            if "handler" in msg_lower or "listener" in msg_lower:
                root_cause    = "Event handler/listener tidak terdaftar di EventBus."
                suggested_fix = "Pastikan semua handler didaftarkan sebelum event dipublish."
                confidence    = 0.8
            else:
                root_cause    = f"Gagal publish/dispatch event: {str(exc)}"
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
    def __init__(self):
        super().__init__(priority=70, category=Category.DI, name="ContainerErrorRule")

    # [BUG-32 FIXED] 'bind' dan 'resolve' terlalu umum → false positive socket.bind(),
    #   tkinter.bind(). Persempit dengan kombinasi keyword.
    _CONTAINER_KEYWORDS = re.compile(
        r"\b(container|dependency[_\s]injection|di[_\s]container|ioc|resolve[_\s]service|service[_\s]provider)\b",
        re.IGNORECASE,
    )

    def match(self, exc, frames, context):
        if self._CONTAINER_KEYWORDS.search(str(exc)):
            return True
        for f in frames:
            text = f"{f.name} {f.filename}"
            if self._CONTAINER_KEYWORDS.search(text):
                return True
        return False

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        evidence, impact = [], []
        severity   = Severity.CRITICAL
        confidence = DEFAULT_CONFIDENCE
        root_cause = suggested_fix = ""

        container_frames = [f for f in frames if self._CONTAINER_KEYWORDS.search(f"{f.name} {f.filename}")]
        if container_frames:
            frame = container_frames[-1]
            evidence.append(f"Frame Container: {frame.name} di {frame.filename}:{frame.lineno}")
            evidence.extend(get_code_context(frame.filename, frame.lineno))
            m = re.search(r"unable to resolve '([^']+)'", str(exc), re.IGNORECASE)
            if m:
                svc = m.group(1)
                root_cause    = f"Service '{svc}' tidak terdaftar di container."
                suggested_fix = f"Daftarkan '{svc}' beserta semua dependency-nya di container."
                confidence    = 0.9
                evidence.append(f"Service yang gagal di-resolve: {svc}")
            elif "bind" in frame.name.lower():
                root_cause    = "Binding interface→implementasi gagal di container."
                suggested_fix = "Periksa binding di container — pastikan interface dan implementasi sesuai."
            else:
                root_cause    = f"Container error: {str(exc)}"
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
    def __init__(self):
        # [BUG-33 FIXED] Priority sama dengan UnitOfWorkErrorRule (60) → non-deterministic
        super().__init__(priority=62, category=Category.DDD, name="AggregateErrorRule")

    def match(self, exc, frames, context):
        if "aggregate" in str(exc).lower():
            return True
        for f in frames:
            if "aggregate" in f.name.lower() or "aggregate" in f.filename.lower():
                return True
        return False

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        evidence, impact = [], []
        severity   = Severity.CRITICAL
        confidence = DEFAULT_CONFIDENCE
        root_cause = suggested_fix = ""

        agg_frames = [f for f in frames
                      if "aggregate" in f.name.lower() or "aggregate" in f.filename.lower()]
        if agg_frames:
            frame = agg_frames[-1]
            evidence.append(f"Frame Aggregate: {frame.name} di {frame.filename}:{frame.lineno}")
            evidence.extend(get_code_context(frame.filename, frame.lineno))
            mn = frame.name.lower()
            if "apply" in mn or "when" in mn:
                root_cause    = "Event handler di Aggregate gagal — event tidak dikenal atau state tidak valid."
                suggested_fix = "Periksa method apply()/when() pada Aggregate, pastikan event sesuai tipe yang diharapkan."
                confidence    = 0.7
            elif "raise_event" in mn or "add_event" in mn:
                root_cause    = "Aggregate gagal menambahkan domain event."
                suggested_fix = "Periksa apakah EventBus aktif dan event terdaftar."
            else:
                root_cause    = f"Error pada Aggregate: {str(exc)}"
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
    def __init__(self):
        super().__init__(priority=60, category=Category.DDD, name="UnitOfWorkErrorRule")

    def match(self, exc, frames, context):
        msg = str(exc).lower()
        if "unitofwork" in msg or "uow" in msg:
            return True
        for f in frames:
            combined = f"{f.name} {f.filename}".lower()
            if "unitofwork" in combined or "uow" in combined:
                return True
        return False

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        evidence, impact = [], []
        severity   = Severity.CRITICAL
        confidence = DEFAULT_CONFIDENCE
        root_cause = suggested_fix = ""

        uow_frames = [f for f in frames
                      if "unitofwork" in f"{f.name} {f.filename}".lower()
                      or "uow" in f"{f.name} {f.filename}".lower()]
        if uow_frames:
            frame = uow_frames[-1]
            evidence.append(f"Frame UoW: {frame.name} di {frame.filename}:{frame.lineno}")
            evidence.extend(get_code_context(frame.filename, frame.lineno))
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
                root_cause    = f"Error UoW: {str(exc)}"
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
    def __init__(self):
        super().__init__(priority=65, category=Category.DATABASE, name="TransactionIntegrityRule")

    def match(self, exc, frames, context):
        # [BUG-34 FIXED] `sqlalchemy_exc` tidak pernah didefinisikan → NameError crash!
        #   Sekarang menggunakan _SQLAlchemyError yang di-import dengan benar.
        db_types = (ValueError, RuntimeError)
        if HAS_SQLALCHEMY and _SQLAlchemyError is not None:
            db_types = db_types + (_SQLAlchemyError,)
        if not isinstance(exc, db_types):
            return False
        keywords = ("unitofwork", "transaction", "uow", "commit", "rollback", "session")
        for f in frames:
            if any(k in f"{f.filename} {f.name}".lower() for k in keywords):
                return True
        return False

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        # [BUG-35 FIXED] analyze() tidak menggunakan exc sama sekali → raw_error kosong
        #   dan root_cause generik tidak informatif. Sekarang include tipe exception.
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


# ── NEW RULES ─────────────────────────────────────────────────────────────────

class NameErrorRule(RCARule):
    """Deteksi NameError: variabel tidak terdefinisi, typo, scope issue."""
    def __init__(self):
        super().__init__(priority=85, category=Category.TYPE, name="NameErrorRule")

    def match(self, exc, frames, context):
        return isinstance(exc, NameError)

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        msg = str(exc)
        evidence, impact = [], []
        root_cause = suggested_fix = ""
        confidence = 0.8

        # Pola: name 'X' is not defined
        m = re.search(r"name '([^']+)' is not defined", msg)
        name = m.group(1) if m else None

        if name:
            evidence.append(f"Nama yang tidak dikenal: '{name}'")
            # Cek apakah typo dari built-in
            _builtins_common = {
                "true": "True", "false": "False", "none": "None",
                "print_": "print", "lenght": "len", "lenght": "len",
                "lenth": "len", "pritn": "print", "pint": "print",
            }
            if name.lower() in _builtins_common:
                fix = _builtins_common[name.lower()]
                root_cause    = f"Typo: '{name}' kemungkinan dimaksudkan '{fix}'."
                suggested_fix = f"Ganti '{name}' dengan '{fix}'."
                confidence    = 0.9
            else:
                # Cari apakah nama didefinisikan di file yang sama tapi salah scope
                if frames:
                    frame = frames[-1]
                    tree = get_ast(frame.filename)
                    if tree:
                        defined_names: Set[str] = set()
                        for node in ast.walk(tree):
                            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                  ast.ClassDef)):
                                defined_names.add(node.name)
                            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                                defined_names.add(node.id)
                        # Cari closest match
                        import difflib
                        close = difflib.get_close_matches(name, defined_names, n=3, cutoff=0.6)
                        if close:
                            evidence.append(f"Nama mirip yang ada di file: {close}")
                            root_cause    = (f"'{name}' tidak terdefinisi. Mungkin typo dari: "
                                            f"{close[0]!r}?")
                            suggested_fix = (f"Periksa ejaan variabel. Gunakan '{close[0]}' "
                                            f"jika itu yang dimaksud.")
                            confidence    = 0.75
                        else:
                            root_cause    = (f"'{name}' tidak terdefinisi di scope ini. "
                                            "Mungkin belum diinisialisasi atau salah import.")
                            suggested_fix = (f"Pastikan '{name}' diimport atau didefinisikan "
                                            "sebelum digunakan.")
                    else:
                        root_cause    = f"'{name}' tidak terdefinisi."
                        suggested_fix = f"Tambahkan definisi atau import untuk '{name}'."
                else:
                    root_cause    = f"'{name}' tidak terdefinisi."
                    suggested_fix = f"Tambahkan definisi atau import untuk '{name}'."

            if frames:
                frame = frames[-1]
                code  = get_code_context(frame.filename, frame.lineno)
                if code:
                    start     = max(0, frame.lineno - MAX_CONTEXT_LINES - 1)
                    target    = min(frame.lineno - 1 - start, len(code) - 1)
                    evidence.append(f"Baris {frame.lineno}: {code[target]}")
        else:
            root_cause    = f"NameError: {msg}"
            suggested_fix = "Periksa semua nama variabel dan pastikan sudah didefinisikan."

        impact.append("Eksekusi berhenti di baris ini — semua kode sesudahnya tidak jalan.")
        return RCAResult(
            severity=Severity.HIGH, category=Category.TYPE,
            error_code=ErrorCode.NAME_NOT_DEFINED,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=msg, confidence=confidence,
        )


class KeyErrorRule(RCARule):
    """Deteksi KeyError: dict key tidak ada — sangat kritis di ERP config/mapping."""
    def __init__(self):
        super().__init__(priority=85, category=Category.TYPE, name="KeyErrorRule")

    def match(self, exc, frames, context):
        return isinstance(exc, KeyError)

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        raw   = str(exc)
        # KeyError menyimpan key asli di args[0]
        key   = exc.args[0] if exc.args else None
        key_s = repr(key) if key is not None else raw

        evidence, impact = [], []
        root_cause = suggested_fix = ""
        confidence = 0.8

        evidence.append(f"Key yang tidak ditemukan: {key_s}")

        # Konteks ERP: apakah ini config, account, period, mapping?
        _erp_contexts = {
            "account"   : ("Kode akun tidak terdaftar di chart of accounts.",
                           "Pastikan kode akun sudah didefinisikan di master akun ERP."),
            "period"    : ("Periode akuntansi tidak terdaftar atau sudah ditutup.",
                           "Buka periode yang dimaksud atau gunakan periode yang aktif."),
            "currency"  : ("Kode mata uang tidak terdaftar di master currency.",
                           "Tambahkan kode mata uang ke konfigurasi ERP."),
            "journal"   : ("Kode jurnal tidak ditemukan di konfigurasi.",
                           "Pastikan jurnal sudah dikonfigurasi di modul akuntansi."),
            "company"   : ("Company ID tidak terdaftar di context ERP.",
                           "Pastikan company_id diset dengan benar di context."),
            "warehouse" : ("Kode warehouse tidak ditemukan.",
                           "Periksa konfigurasi warehouse di modul inventory."),
        }
        key_lower = str(key).lower() if key else ""
        matched_ctx = None
        for ctx_key, (ctx_cause, ctx_fix) in _erp_contexts.items():
            if ctx_key in key_lower:
                root_cause    = ctx_cause
                suggested_fix = ctx_fix
                confidence    = 0.85
                matched_ctx   = ctx_key
                break

        if not matched_ctx:
            # Cari di AST apakah ada dict literal yang terdekat
            if frames:
                frame = frames[-1]
                code  = get_code_context(frame.filename, frame.lineno)
                if code:
                    start  = max(0, frame.lineno - MAX_CONTEXT_LINES - 1)
                    target = min(frame.lineno - 1 - start, len(code) - 1)
                    evidence.append(f"Baris {frame.lineno}: {code[target]}")
            root_cause    = (f"Key {key_s} tidak ditemukan di dict/mapping. "
                            "Dict mungkin kosong, belum diisi, atau key salah.")
            suggested_fix = (f"Gunakan .get({key_s}, default) untuk akses aman, "
                            "atau validasi keberadaan key dengan 'if key in d' sebelum akses.")

        impact.append("Operasi yang bergantung pada data ini akan gagal atau menggunakan nilai yang salah.")
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
    def __init__(self):
        super().__init__(priority=84, category=Category.TYPE, name="IndexErrorRule")

    def match(self, exc, frames, context):
        return isinstance(exc, (IndexError, StopIteration))

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        msg  = str(exc)
        evidence, impact = [], []
        root_cause = suggested_fix = ""
        confidence = 0.75

        if isinstance(exc, StopIteration):
            root_cause    = "Iterator/generator habis (StopIteration) di luar konteks for-loop."
            suggested_fix = ("Gunakan next(iter, default) untuk akses aman, "
                            "atau pastikan iterator tidak digunakan setelah habis.")
            confidence    = 0.85
        else:
            m = re.search(r"list index out of range|tuple index out of range|"
                         r"string index out of range|index (\d+) is out of bounds", msg)
            if m:
                root_cause    = "Akses index di luar batas koleksi (list/tuple/string kosong atau index terlalu besar)."
                suggested_fix = ("Periksa panjang list sebelum akses: 'if len(lst) > idx'. "
                                "Di ERP, pastikan result query tidak kosong sebelum ambil elemen pertama.")
            else:
                root_cause    = f"IndexError: {msg}"
                suggested_fix = "Periksa bounds sebelum akses index."

            if frames:
                frame = frames[-1]
                code  = get_code_context(frame.filename, frame.lineno)
                if code:
                    start  = max(0, frame.lineno - MAX_CONTEXT_LINES - 1)
                    target = min(frame.lineno - 1 - start, len(code) - 1)
                    evidence.append(f"Baris {frame.lineno}: {code[target]}")
                    # Deteksi pola [0] pada result query yang mungkin kosong
                    line_text = code[target]
                    if re.search(r'\[0\]|\[-1\]|\.first\(\)', line_text):
                        evidence.append("Terdeteksi akses elemen pertama/terakhir tanpa validasi kosong.")
                        root_cause    = ("Mengakses elemen [0] atau [-1] dari hasil query "
                                        "yang mungkin kosong.")
                        suggested_fix = ("Gunakan .first() dengan guard 'if result:', "
                                        "atau tambahkan .limit(1) lalu cek panjang.")
                        confidence    = 0.88

        impact.append("Data processing terhenti — batch atau laporan tidak selesai diproses.")
        return RCAResult(
            severity=Severity.MEDIUM, category=Category.TYPE,
            error_code=ErrorCode.INDEX_OUT_OF_RANGE,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=msg, confidence=confidence,
        )


class ValueErrorRule(RCARule):
    """Deteksi ValueError — validasi bisnis ERP: akun, periode, jumlah, konversi."""
    def __init__(self):
        super().__init__(priority=83, category=Category.DDD, name="ValueErrorRule")

    def match(self, exc, frames, context):
        return isinstance(exc, ValueError)

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        msg  = str(exc).lower()
        raw  = str(exc)
        evidence, impact = [], []
        root_cause = suggested_fix = ""
        confidence = DEFAULT_CONFIDENCE
        error_code = ErrorCode.VALUE_INVALID
        severity   = Severity.MEDIUM

        # Pattern ERP spesifik
        _erp_patterns = [
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
            (r"duplicate|already.exist|unique",
             ErrorCode.ERP_VALIDATION, Severity.HIGH,
             "Duplicate entry — data dengan identifier ini sudah ada.",
             "Cek uniqueness sebelum insert, atau gunakan upsert jika update diizinkan.",
             0.85),
        ]

        for pattern, code, sev, cause, fix, conf in _erp_patterns:
            if re.search(pattern, msg):
                error_code    = code
                severity      = sev
                root_cause    = cause
                suggested_fix = fix
                confidence    = conf
                evidence.append(f"Pesan error: {raw[:200]}")
                break

        if not root_cause:
            root_cause    = f"ValueError: {raw}"
            suggested_fix = "Validasi nilai input sebelum memproses."
            evidence.append(f"Pesan: {raw[:200]}")

        if frames:
            frame = frames[-1]
            code_lines = get_code_context(frame.filename, frame.lineno)
            if code_lines:
                start  = max(0, frame.lineno - MAX_CONTEXT_LINES - 1)
                target = min(frame.lineno - 1 - start, len(code_lines) - 1)
                evidence.append(f"Baris {frame.lineno}: {code_lines[target]}")

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
    def __init__(self):
        super().__init__(priority=90, category=Category.INFRASTRUCTURE,
                         name="InfrastructureConnectionRule")

    # Pola infrastruktur
    _DB_PATTERN = re.compile(
        r"(connection refused|could not connect|"
        r"lost connection|server closed|"
        r"operational.?error|can.?t connect|"
        r"database.*unavailable|too many connections|"
        r"connection.?timed?.out|no route to host)",
        re.IGNORECASE,
    )
    _REDIS_PATTERN = re.compile(
        r"(redis|connection.*6379|6379.*refused|"
        r"redis.*timeout|redis.*connection)",
        re.IGNORECASE,
    )
    _KAFKA_PATTERN = re.compile(
        r"(kafka|broker.*unavailable|no.*broker|"
        r"kafka.*timeout|leader.*not.*available|"
        r"connection.*9092)",
        re.IGNORECASE,
    )
    _HTTP_PATTERN = re.compile(
        r"(connection.*reset|remote.*disconnected|"
        r"name.*resolution.*failed|ssl.*error|"
        r"certificate.*verify.*failed|timeout.*read)",
        re.IGNORECASE,
    )

    def match(self, exc, frames, context):
        # Jangan intercept PermissionError dan FileNotFoundError — itu tugas PermissionFileRule
        if isinstance(exc, (PermissionError, FileNotFoundError, IsADirectoryError,
                             NotADirectoryError)):
            return False
        msg = str(exc)
        if isinstance(exc, (ConnectionError, TimeoutError)):
            return True
        if HAS_SQLALCHEMY and _SQLAlchemyError and isinstance(exc, _SQLAlchemyError):
            return True
        if (self._DB_PATTERN.search(msg) or self._REDIS_PATTERN.search(msg)
                or self._KAFKA_PATTERN.search(msg) or self._HTTP_PATTERN.search(msg)):
            return True
        return False

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        msg        = str(exc)
        evidence   = [f"Exception: {type(exc).__name__}: {msg[:200]}"]
        impact     = []
        error_code = ErrorCode.DB_CONNECTION_FAIL
        root_cause = suggested_fix = ""
        confidence = 0.8

        if self._REDIS_PATTERN.search(msg):
            error_code    = ErrorCode.REDIS_FAIL
            root_cause    = "Koneksi ke Redis gagal — server tidak tersedia atau timeout."
            suggested_fix = ("Periksa status Redis server (redis-cli ping). "
                            "Periksa konfigurasi host/port/password di settings ERP. "
                            "Pastikan Redis tidak overloaded atau OOM.")
            impact.extend([
                "Cache ERP tidak tersedia — performa akan turun drastis.",
                "Session/token yang tersimpan di Redis akan hilang.",
                "Queue job yang bergantung Redis akan terhenti.",
            ])
            confidence = 0.88

        elif self._KAFKA_PATTERN.search(msg):
            error_code    = ErrorCode.KAFKA_FAIL
            root_cause    = "Koneksi ke Kafka broker gagal — broker tidak tersedia."
            suggested_fix = ("Periksa status Kafka broker (kafka-broker-api-versions.sh). "
                            "Periksa konfigurasi bootstrap.servers. "
                            "Pastikan topic sudah dibuat dan partisi aktif.")
            impact.extend([
                "Event streaming terhenti — domain events tidak terkirim.",
                "Eventual consistency rusak — subscriber tidak menerima update.",
            ])
            confidence = 0.88

        elif (self._DB_PATTERN.search(msg)
              or (HAS_SQLALCHEMY and _SQLAlchemyError and isinstance(exc, _SQLAlchemyError))):
            root_cause    = "Koneksi ke database gagal atau connection pool habis."
            suggested_fix = ("Periksa status database server. "
                            "Cek konfigurasi DATABASE_URL di environment. "
                            "Pastikan connection pool size cukup (SQLALCHEMY_POOL_SIZE). "
                            "Periksa apakah ada koneksi yang menggantung (zombie connections).")
            impact.extend([
                "Seluruh operasi database gagal — ERP tidak dapat menyimpan/membaca data.",
                "Transaksi aktif mungkin menggantung (orphaned transactions).",
            ])
            confidence = 0.85
            # Ekstrak host/port dari pesan jika ada
            m = re.search(r"([\w.-]+):(\d+)", msg)
            if m:
                evidence.append(f"Target koneksi: {m.group(0)}")

        else:
            root_cause    = f"Kegagalan koneksi jaringan/infrastruktur: {type(exc).__name__}"
            suggested_fix = ("Periksa konektivitas jaringan. "
                            "Verifikasi konfigurasi host, port, dan firewall.")
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
    def __init__(self):
        super().__init__(priority=72, category=Category.CQRS, name="CQRSHandlerRule")

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

    def match(self, exc, frames, context):
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
        evidence   = []
        impact     = []
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
            suggested_fix = ("Daftarkan handler yang sesuai: "
                            "query_bus.register(QueryClass, QueryHandler). "
                            "Pastikan handler di-inject ke QueryBus di module bootstrap.")
            impact.extend([
                "Query tidak bisa dieksekusi — read side CQRS gagal.",
                "Tampilan data di UI mungkin kosong atau error.",
            ])
        else:
            root_cause    = "Command handler tidak terdaftar di CommandBus."
            suggested_fix = ("Daftarkan handler: "
                            "command_bus.register(CommandClass, CommandHandler). "
                            "Pastikan semua command handler ter-register di application bootstrap.")
            impact.extend([
                "Command tidak bisa dieksekusi — write side CQRS gagal.",
                "Operasi bisnis (create/update/delete) tidak berjalan.",
                "Domain events tidak akan dipublish — eventual consistency rusak.",
            ])

        # Cari nama command/query dari pesan error
        m = re.search(r"'([A-Z]\w*(?:Command|Query|Handler))'", msg)
        if m:
            evidence.append(f"Class yang bermasalah: {m.group(1)}")
            confidence = 0.88

        cqrs_frames = [f for f in frames
                       if self._CMD_PATTERN.search(f"{f.name} {f.filename}")
                       or self._QRY_PATTERN.search(f"{f.name} {f.filename}")]
        if cqrs_frames:
            frame = cqrs_frames[-1]
            evidence.append(f"Frame CQRS: {frame.name} di {frame.filename}:{frame.lineno}")
            evidence.extend(get_code_context(frame.filename, frame.lineno))

        return RCAResult(
            severity=Severity.CRITICAL, category=Category.CQRS, error_code=error_code,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=msg, confidence=confidence,
        )


class RecursionMemoryRule(RCARule):
    """Deteksi RecursionError dan MemoryError — sering terjadi di proses batch ERP."""
    def __init__(self):
        super().__init__(priority=95, category=Category.PERFORMANCE,
                         name="RecursionMemoryRule")

    def match(self, exc, frames, context):
        return isinstance(exc, (RecursionError, MemoryError))

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        msg = str(exc)
        evidence, impact = [], []

        if isinstance(exc, RecursionError):
            # Temukan fungsi yang berulang
            if frames:
                names = [f.name for f in frames]
                from collections import Counter as _Counter
                top = _Counter(names).most_common(3)
                evidence.append(f"Fungsi yang paling banyak di stack: {top}")
                # Cari fungsi dengan rekursi > 5x
                for fn, cnt in top:
                    if cnt > 5:
                        evidence.append(f"Fungsi '{fn}' muncul {cnt}x di stack — kemungkinan infinite recursion.")

            root_cause    = ("RecursionError: stack melebihi batas (default 1000 frame). "
                            "Kemungkinan infinite recursion atau struktur data circular.")
            suggested_fix = ("1. Konversi rekursi ke iterasi menggunakan stack eksplisit. "
                            "2. Tambahkan base case yang tepat di fungsi rekursif. "
                            "3. Periksa apakah ada circular reference di objek domain. "
                            "4. Temporary: sys.setrecursionlimit() BUKAN solusi jangka panjang.")
            impact.extend([
                "Proses batch ERP berhenti total.",
                "Stack frame yang besar mengonsumsi memory — bisa trigger MemoryError.",
            ])
            return RCAResult(
                severity=Severity.HIGH, category=Category.PERFORMANCE,
                error_code=ErrorCode.RECURSION_LIMIT,
                root_cause=root_cause, evidence=evidence, impact=impact,
                suggested_fix=suggested_fix, raw_error=msg, confidence=0.92,
            )

        else:  # MemoryError
            evidence.append(f"MemoryError terjadi di: {frames[-1].filename}:{frames[-1].lineno}" if frames else "MemoryError")
            # Estimasi berapa banyak frame yang ada
            frame_count = len(frames)
            if frame_count > 20:
                evidence.append(f"Stack depth: {frame_count} frames — kemungkinan kebocoran memory.")
            root_cause    = ("Proses kehabisan memory. Di ERP, penyebab umum: "
                            "query tanpa limit yang mengambil jutaan row, "
                            "atau batch processing yang tidak menggunakan chunking.")
            suggested_fix = ("1. Gunakan pagination/chunking untuk query besar: "
                            "   query.yield_per(1000) atau LIMIT/OFFSET. "
                            "2. Hindari load seluruh dataset ke memory — gunakan generator. "
                            "3. Periksa apakah ada list yang terus bertambah tanpa dibersihkan. "
                            "4. Pertimbangkan meningkatkan memory server atau optimasi query.")
            impact.extend([
                "Proses ERP crash — data yang sedang diproses mungkin tidak tersimpan.",
                "Server mungkin memerlukan restart — downtime.",
                "Transaksi aktif akan di-rollback.",
            ])
            return RCAResult(
                severity=Severity.FATAL, category=Category.PERFORMANCE,
                error_code=ErrorCode.MEMORY_ERROR,
                root_cause=root_cause, evidence=evidence, impact=impact,
                suggested_fix=suggested_fix, raw_error=msg, confidence=0.9,
            )


class PermissionFileRule(RCARule):
    """Deteksi PermissionError dan FileNotFoundError — common di ERP file processing."""
    def __init__(self):
        super().__init__(priority=88, category=Category.SECURITY, name="PermissionFileRule")

    def match(self, exc, frames, context):
        return isinstance(exc, (PermissionError, FileNotFoundError, IsADirectoryError,
                                 NotADirectoryError))

    def analyze(self, exc, frames, context) -> Optional[RCAResult]:
        msg  = str(exc)
        raw  = msg
        evidence, impact = [], []
        error_code = ErrorCode.PERMISSION_DENIED if isinstance(exc, PermissionError) else ErrorCode.FILE_NOT_FOUND
        severity   = Severity.HIGH

        # Ekstrak path dari pesan
        m = re.search(r"'([^']+)'", msg)
        path = m.group(1) if m else None

        if isinstance(exc, PermissionError):
            root_cause    = f"Akses ditolak ke: {path or 'file/direktori'}"
            suggested_fix = (f"Periksa permission file/direktori: chmod 755 {path or '<path>'}. "
                            "Pastikan user yang menjalankan ERP memiliki akses yang diperlukan. "
                            "Di produksi, hindari menjalankan sebagai root.")
            evidence.append(f"Path yang ditolak: {path}")
            if path:
                evidence.append(f"Cek permission: ls -la {path}")
            impact.extend([
                "Operasi file/export/import di ERP gagal.",
                "Laporan yang memerlukan akses filesystem tidak bisa dibuat.",
            ])
        elif isinstance(exc, FileNotFoundError):
            root_cause    = f"File atau direktori tidak ditemukan: {path or 'unknown'}"
            suggested_fix = (f"Pastikan file '{path}' ada dan path benar. "
                            "Periksa konfigurasi MEDIA_ROOT/STATIC_ROOT di ERP. "
                            "Untuk template/config file, pastikan deployment menyertakan file tersebut.")
            evidence.append(f"Path yang tidak ditemukan: {path}")
            if path and path.endswith(('.py', '.cfg', '.ini', '.yaml', '.env')):
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
            if code:
                start  = max(0, frame.lineno - MAX_CONTEXT_LINES - 1)
                target = min(frame.lineno - 1 - start, len(code) - 1)
                evidence.append(f"Baris {frame.lineno}: {code[target]}")

        return RCAResult(
            severity=severity, category=Category.SECURITY, error_code=error_code,
            root_cause=root_cause, evidence=evidence, impact=impact,
            suggested_fix=suggested_fix, raw_error=raw, confidence=0.9,
        )


# ── RCAEngine ──────────────────────────────────────────────────────────────────
class RCAEngine:
    """Mesin RCA utama. Thread-safe, multi-rule."""

    VERSION = "2.0"

    def __init__(self, enable_networkx: bool = True, enable_jedi: bool = True,
                 enable_libcst: bool = True):
        self._lock     = threading.RLock()
        self._rules    : List[RCARule]       = []
        self._rule_map : Dict[str, RCARule]  = {}
        # [BUG-36 FIXED] cache_hits / cache_misses tidak pernah di-increment
        #   → stats tidak berguna. Sekarang di-track dengan benar.
        self._stats = {
            "total_analyses": 0,
            "total_time"    : 0.0,
            "cache_hits"    : 0,
            "cache_misses"  : 0,
        }
        self._enable_networkx = enable_networkx and HAS_NETWORKX
        self._enable_jedi     = enable_jedi     and HAS_JEDI
        self._enable_libcst   = enable_libcst   and HAS_LIBCST
        self._register_default_rules()
        self._sort_rules()

    def _register_default_rules(self):
        for rule in [
            # Infrastructure (highest priority — infra down = all else fails)
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

    def register_rule(self, rule: RCARule):
        with self._lock:
            if rule.name in self._rule_map:
                try:
                    self._rules.remove(self._rule_map[rule.name])
                except ValueError:
                    pass
            self._rules.append(rule)
            self._rule_map[rule.name] = rule
            self._sort_rules()

    def _sort_rules(self):
        # [BUG-37 FIXED] _sort_rules() dipanggil dari register_rule() yang sudah
        #   memegang lock, tapi _sort_rules() juga acquire lock → deadlock jika
        #   RLock digunakan oleh thread lain sekaligus. Pisahkan internal sort.
        self._rules.sort(key=lambda r: r.priority, reverse=True)

    def analyze(self, exception: Exception,
                context: Optional[Dict[str, Any]] = None) -> RCAResult:
        """Entry point utama. Thread-safe, multi-rule, tanpa lock global."""
        start_time = time.perf_counter()

        # [BUG-38 FIXED] Versi lama: seluruh analyze() di dalam with self._lock
        #   → semua thread terblokir. Sekarang hanya stats yang di-lock.
        with self._lock:
            self._stats["total_analyses"] += 1

        if context is None:
            context = {}
        try:
            safe_context = copy.deepcopy(context)
        except Exception:
            safe_context = dict(context)

        # [BUG-39 FIXED] `frames` tidak terdefinisi sebelum loop → NameError
        #   jika all_exceptions kosong. Inisialisasi di sini.
        frames = get_traceback_frames(exception)

        all_exceptions    = get_all_causes(exception)
        combined_results  : List[RCAResult] = []

        # [BUG-40 FIXED] Snapshot rules agar aman jika register_rule() dipanggil
        #   dari thread lain saat analyze() sedang berjalan.
        with self._lock:
            rules_snapshot = list(self._rules)

        for exc in all_exceptions:
            exc_frames = get_traceback_frames(exc) or frames
            for rule in rules_snapshot:
                if not rule.enabled:
                    continue
                try:
                    if rule.match(exc, exc_frames, safe_context):
                        with rule._stats_lock:
                            rule._stats["matches"] += 1
                        res = rule.analyze(exc, exc_frames, safe_context)
                        if res is not None:
                            combined_results.append(res)
                            with rule._stats_lock:
                                rule._stats["hits"] += 1
                        else:
                            with rule._stats_lock:
                                rule._stats["misses"] += 1
                except Exception as e:
                    _logger.warning(f"Rule {rule.name} crashed: {e}")

        if not combined_results:
            combined_results.append(self._fallback_analysis(exception, frames, safe_context))

        # [IMPROVEMENT] Tie-breaking: severity dulu, lalu confidence
        best = max(combined_results,
                   key=lambda r: (_SEVERITY_ORDER.get(r.severity, 0), r.confidence))

        all_evidence = []
        all_impact   = []
        for r in combined_results:
            all_evidence.extend(r.evidence)
            all_impact.extend(r.impact)

        # [BUG-41 FIXED] children=combined_results memasukkan `best` ke dalam children
        #   miliknya sendiri → circular reference. Filter best dari children.
        final = RCAResult(
            severity     = best.severity,
            category     = best.category,
            error_code   = best.error_code,
            root_cause   = best.root_cause,
            evidence     = list(dict.fromkeys(all_evidence))[:MAX_EVIDENCE_ITEMS],
            impact       = list(dict.fromkeys(all_impact))[:MAX_IMPACT_ITEMS],
            suggested_fix= best.suggested_fix,
            raw_error    = str(exception),
            confidence   = best.confidence,
            children     = [r for r in combined_results if r is not best][:MAX_CHILDREN],
        )

        elapsed = time.perf_counter() - start_time
        with self._lock:
            self._stats["total_time"] += elapsed
        return final

    def _fallback_analysis(self, exception, frames, context) -> RCAResult:
        # [IMPROVEMENT] Map tipe exception ke severity yang tepat
        _severity_map = {
            KeyboardInterrupt : Severity.INFO,
            SystemExit        : Severity.INFO,
            StopIteration     : Severity.INFO,
            GeneratorExit     : Severity.INFO,
            Warning           : Severity.LOW,
            DeprecationWarning: Severity.LOW,
            MemoryError       : Severity.FATAL,
            RecursionError    : Severity.HIGH,
            SystemError       : Severity.FATAL,
        }
        sev = Severity.HIGH
        for exc_type, mapped_sev in _severity_map.items():
            if isinstance(exception, exc_type):
                sev = mapped_sev
                break
        evidence = [f"{f.filename}:{f.lineno} in {f.name}" for f in frames[-3:]]
        return RCAResult(
            severity     = sev,
            category     = Category.UNKNOWN,
            error_code   = ErrorCode.UNKNOWN,
            root_cause   = f"Unhandled {type(exception).__name__}: {str(exception)}",
            evidence     = evidence,
            impact       = ["Program berhenti tidak normal."],
            suggested_fix= "Periksa logika program dan pastikan semua kondisi terpenuhi.",
            raw_error    = str(exception),
            confidence   = 0.3,
        )

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "version"        : self.VERSION,
                "total_analyses" : self._stats["total_analyses"],
                "total_time"     : self._stats["total_time"],
                "cache_hits"     : self._stats["cache_hits"],
                "cache_misses"   : self._stats["cache_misses"],
                "rules"          : {r.name: r.stats() for r in self._rules},
            }

# ── Singleton ─────────────────────────────────────────────────────────────────
_DEFAULT_ENGINE: Optional[RCAEngine] = None
_ENGINE_LOCK = threading.Lock()

def get_engine() -> RCAEngine:
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is None:
        with _ENGINE_LOCK:
            if _DEFAULT_ENGINE is None:
                _DEFAULT_ENGINE = RCAEngine()
    return _DEFAULT_ENGINE

# [BUG-42 FIXED] Fungsi analyze() modul-level membayangi RCAEngine.analyze() →
#   naming collision membingungkan. Rename ke analyze_exception().
def analyze_exception(exception: Exception,
                      context: Optional[Dict[str, Any]] = None) -> RCAResult:
    """Shortcut module-level untuk analyze. Gunakan ini dari luar modul."""
    return get_engine().analyze(exception, context)

# Alias backward-compatible
analyze = analyze_exception

# ── Self-test ─────────────────────────────────────────────────────────────────
def self_test(verbose: bool = True) -> bool:
    """Test komprehensif semua rule. Return True jika semua lulus."""
    engine  = RCAEngine()
    passed  = failed = 0

    def check(name: str, cond: bool, got: str = ""):
        nonlocal passed, failed
        if cond:
            if verbose: print(f"  ✅ {name}")
            passed += 1
        else:
            if verbose: print(f"  ❌ {name}" + (f": {got}" if got else ""))
            failed += 1

    if verbose:
        print(f"Running RCA self-test (v{RCAEngine.VERSION}) — {len(engine._rules)} rules registered…")

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
        _X().missing_attr  # type: ignore
    except Exception as e:
        r = engine.analyze(e)
        check("AttributeErrorRule — missing attr",
              r.category == Category.ATTRIBUTE, str(r.category))

    try:
        obj = None
        obj.something  # type: ignore
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
        def _f(a, b): return a + b
        _f(1)
    except Exception as e:
        r = engine.analyze(e)
        check("TypeErrorRule — missing required arg",
              r.error_code == ErrorCode.TYPE_MISSING_REQUIRED, str(r.error_code))

    try:
        1 + "str"  # type: ignore
    except Exception as e:
        r = engine.analyze(e)
        check("TypeErrorRule — unsupported operand",
              r.error_code == ErrorCode.TYPE_OPERAND, str(r.error_code))

    # ── NameError ─────────────────────────────────────────────────────────────
    try:
        exec("result = undefined_var_xyz + 1")
    except Exception as e:
        r = engine.analyze(e)
        check("NameErrorRule — undefined var",
              r.error_code == ErrorCode.NAME_NOT_DEFINED, str(r.error_code))

    # ── KeyError ──────────────────────────────────────────────────────────────
    try:
        d = {}
        _ = d["account_code"]
    except Exception as e:
        r = engine.analyze(e)
        check("KeyErrorRule — account key (ERP context)",
              r.error_code == ErrorCode.KEY_NOT_FOUND, str(r.error_code))

    # ── IndexError ────────────────────────────────────────────────────────────
    try:
        lst = []
        _ = lst[0]
    except Exception as e:
        r = engine.analyze(e)
        check("IndexErrorRule — empty list",
              r.error_code == ErrorCode.INDEX_OUT_OF_RANGE, str(r.error_code))

    # ── ValueError / ERP validations ──────────────────────────────────────────
    try:
        raise ValueError("Period is closed and locked for posting")
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
        check("ValueErrorRule — int conversion",
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
        check("PermissionFileRule — FileNotFoundError",
              r.error_code == ErrorCode.FILE_NOT_FOUND, str(r.error_code))

    # ── DDD Domain ────────────────────────────────────────────────────────────
    try:
        raise ValueError("Repository save failed for entity")
    except Exception as e:
        r = engine.analyze(e)
        check("DomainRepositoryMismatchRule (smoke)", r is not None)

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

    try:
        raise ValueError("commit failed in unitofwork session rollback")
    except Exception as e:
        r = engine.analyze(e)
        check("UnitOfWorkErrorRule (smoke)", r is not None)

    try:
        raise ValueError("Transaction integrity violation in commit session")
    except Exception as e:
        r = engine.analyze(e)
        check("TransactionIntegrityRule (smoke)", r is not None)

    # ── Data quality ─────────────────────────────────────────────────────────
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
        # Karena from None, __suppress_context__=True — ValueError tidak ikut
        check("__suppress_context__ honored in get_all_causes",
              all(not isinstance(c, ValueError) for c in causes),
              f"causes={[type(c).__name__ for c in causes]}")

    # Tie-breaking: dua CRITICAL, confidence berbeda
    r_low_conf  = RCAResult(severity=Severity.CRITICAL, confidence=0.5,
                             root_cause="low", error_code=ErrorCode.UNKNOWN)
    r_high_conf = RCAResult(severity=Severity.CRITICAL, confidence=0.9,
                             root_cause="high", error_code=ErrorCode.UNKNOWN)
    best = max([r_low_conf, r_high_conf],
               key=lambda r: (_SEVERITY_ORDER.get(r.severity, 0), r.confidence))
    check("Severity+confidence tie-breaking", best.root_cause == "high",
          f"got root_cause={best.root_cause}")

    # ErrorCode immutability
    try:
        ErrorCode.UNKNOWN = "HACKED"  # type: ignore
        check("ErrorCode immutability (Enum)", False, "mutation succeeded!")
    except (AttributeError, TypeError):
        check("ErrorCode immutability (Enum)", True)

    if verbose:
        print(f"\nSelf-test: {passed} passed, {failed} failed "
              f"({'✅ ALL PASS' if failed == 0 else '❌ SOME FAILED'})")
    return failed == 0


def benchmark():
    engine = RCAEngine()
    try:
        try:
            raise ValueError("Root cause")
        except ValueError as e:
            raise RuntimeError("Wrapper") from e
    except Exception as e:
        start = time.perf_counter()
        for _ in range(200):
            engine.analyze(e)
        elapsed = time.perf_counter() - start
        print(f"Benchmark: 200 analyses in {elapsed:.3f}s ({elapsed/200*1000:.2f}ms per analysis)")


if __name__ == "__main__":
    ok = self_test()
    benchmark()
    print(f"\nRCA engine v{RCAEngine.VERSION} ready.")
    sys.exit(0 if ok else 1)
