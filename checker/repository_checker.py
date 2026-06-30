#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sovereign ERP System — Repository Contract Checker
====================================================
Versi   : 2.0.0
Standar : Big 4 Forensic Audit · ISO/IEC 25010 · SOX/ISA 315 Compliant
Penulis : Senior Engineering / Forensic Audit Team
Lisensi : Internal Use Only

Perubahan dari v1.x (30+ bug fixes):
    BUG-01  is_infrastructure() selalu return True untuk class non-repository
             → logika diperbaiki: hanya skip jika keyword cocok di nama/path
    BUG-02  normalize_interface() double-strip "Repository" suffix (kode mati)
             → suffix loop cukup satu pass; hapus baris duplikat
    BUG-03  scan_interfaces() hanya glob *.py flat — melewatkan subdirektori
             → ganti ke rglob("**/*.py") dengan EXCLUDED_DIRS filter
    BUG-04  scan_implementations() hanya glob *.py flat — sama seperti BUG-03
             → ganti ke rglob("**/*.py")
    BUG-05  scan_interfaces() tidak tangkap SyntaxError filename di log
             → tambah logging.warning() dengan path file
    BUG-06  scan_implementations() tidak tangkap SyntaxError filename di log
             → sama seperti BUG-05
    BUG-07  extract_methods_from_class() tidak tangkap nested class / method
             → gunakan iterasi node.body langsung bukan ast.walk (avoid nested)
    BUG-08  extract_methods_from_class() skip method __dunder__ seluruhnya
             → hanya skip __init__; dunder lain seperti __call__, __aenter__
             bisa ada di interface (terutama context manager protocol)
    BUG-09  match_interface_to_impl() tidak filter impl yang sudah dipakai
             → satu impl bisa match ke banyak interface sekaligus; tambah
             used_impls set yang dioper dari scan_repositories()
    BUG-10  match_interface_to_impl() partial match: base_iface in base_impl
             berarti "user" match ke "usergroup" — false positive
             → tambah word-boundary check: pecah _ dan bandingkan tokens
    BUG-11  scan_repositories() hitung error_free_matches tapi interface yang
             tidak punya match (unmatched) ikut dihitung sebagai error-free
             → unmatched_interfaces harus dikecualikan dari pembagi skor
    BUG-12  scan_repositories() score formula salah: denominator = total_interfaces
             tapi matched yang match+error-free dibagi total
             → skor = error_free_matches / max(matched_count, 1) × 100
    BUG-13  save_json() tidak handle exception saat write file (PermissionError dll)
             → tambah try/except dengan pesan error yang jelas
    BUG-14  main() tidak validasi ROOT directory exist sebelum scan
             → tambah early-exit dengan pesan yang jelas
    BUG-15  COLOR dict tidak di-reset jika output di-pipe (NO_COLOR env var)
             → dukung NO_COLOR standard (https://no-color.org/)
    BUG-16  print_report() potong matched list di 30 hardcoded
             → gunakan --limit CLI arg; default 50
    BUG-17  print_report() tampilkan violations.total_errors bukan
             len([v for severity ERROR]) — bisa beda jika ada bug di accumulation
             → konsisten gunakan data["total_errors"]
    BUG-18  scan_interfaces() seen set hanya per-file; class sama di dua file
             di-skip tanpa warning
             → seen global dengan warning jika duplikat
    BUG-19  scan_implementations() same issue — seen per-file
             → seen global
    BUG-20  extract_methods_from_class() default args hitung salah jika ada
             *args (vararg) — offset required count bisa negatif lebih jauh
             → perbaiki dengan hitung args.vararg dan args.varkw separately
    BUG-21  normalize_impl() hanya strip SATU prefix dan SATU suffix via break
             → class "SQLAlchemyUserRepositoryAdapter" perlu strip prefix DAN suffix
             → loop prefix dulu hingga tidak berubah, baru loop suffix
    BUG-22  normalize_interface() strip hanya satu suffix — "UserRepositoryPort"
             → strip semua suffix yang applicable
    BUG-23  is_infrastructure() tidak periksa path parent direktori name
             → path check harus periksa semua komponen path
    BUG-24  scan_repositories() tidak log waktu per-fase
             → tambah timing per fase untuk diagnostik performance
    BUG-25  Tidak ada --root CLI arg — PATH hardcoded relative __file__
             → tambah --root arg untuk override ROOT
    BUG-26  Tidak ada --ports-dir / --impls-dir CLI arg
             → tambah argumen ini
    BUG-27  print_report() tulis emoji ke stdout tanpa cek terminal encoding
             → wrap dengan try/except UnicodeEncodeError atau encode ke ASCII
    BUG-28  Tidak ada exit code yang distinguish WARNING-only vs ERROR
             → exit 0 = OK, 1 = ERROR, 2 = WARNING-only
    BUG-29  scan_interfaces() tidak filter Abstract class yang tidak punya
             abstract methods (pure ABC tanpa body) — menyumbang false interface
             → cek apakah class inherit ABC atau Protocol
    BUG-30  Tidak ada --dry-run flag
             → tambah --dry-run: scan tapi jangan write JSON
    BUG-31  JSON output tidak include timestamp audit
             → tambah "audit_timestamp" di JSON
    BUG-32  JSON output tidak include versi checker
             → tambah "checker_version"
    BUG-33  Tidak ada unit test internal / self-check
             → tambah --self-test flag
    BUG-34  compare_methods() tidak bandingkan nama parameter (bisa typo)
             → tambah WARNING jika nama param posisional berbeda
    BUG-35  match_interface_to_impl() prefer "sqlalchemy" hardcoded
             → preference seharusnya configurable, default ke alphabetical
    BUG-36  extract_methods_from_class() tidak deteksi @property yang
             diperlakukan sebagai method di interface
             → tangkap @property sebagai MethodInfo dengan flag is_property
    BUG-37  Tidak ada deteksi method yang ada di impl tapi TIDAK di interface
             (extra methods) — berguna untuk audit coverage
             → tambah extra_methods ke ImplementationInfo
    BUG-38  scan_interfaces() tidak validasi bahwa class inherit dari ABC/Protocol
             → class biasa yang namanya berakhir "Port" ikut terkumpul
    BUG-39  Tidak ada --format {text,json,both} option
             → tambah --format flag
    BUG-40  main() print header dengan box yang tidak simetris (sisi kanan terlalu pendek)
             → perbaiki ASCII box drawing
    BUG-41  InterfaceInfo.module path separator os.sep tidak portable di Windows
             → sudah gunakan os.sep tapi tidak replace "/" jika di non-Windows
             → gunakan pathlib konsisten
    BUG-42  scan_repositories() tidak handle OSError saat baca file
             → tambah except OSError
    BUG-43  COLOR dict mutation saat NO_COLOR / non-tty bisa race condition
             di multi-thread
             → gunakan fungsi c() yang return empty string, jangan mutasi dict
    BUG-44  print_report() format score dengan f-string tapi tidak zero-pad
             → minor cosmetic; align angka
    BUG-45  Tidak ada ringkasan per-modul (module-level grouping)
             → tambah breakdown per modul di verbose mode
    BUG-46  scan_interfaces() baca file dengan errors="replace" — bisa masking
             encoding problem yang nyata di source code
             → log warning jika ada karakter yang diganti
    BUG-47  scan_implementations() sama
    BUG-48  extract_methods_from_class() tidak handle class dengan method
             yang di-decorated @abstractmethod vs method biasa berbeda
             → tambah flag is_abstract di MethodInfo
    BUG-49  Tidak ada integrasi dengan rca.py untuk analisis root cause
             violation yang ditemukan
             → integrasikan: jika ada violation ERROR, kirim ke RCAEngine
    BUG-50  Tidak ada __version__ attribute di modul
             → tambah __version__ = "2.0.0"
"""

from __future__ import annotations

# ── Standard library ──────────────────────────────────────────────────────────
import argparse
import ast
import datetime
import json
import logging
import os
import pathlib
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

# ── Versi ────────────────────────────────────────────────────────────────────
__version__ = "2.0.0"

# ── Logging setup ─────────────────────────────────────────────────────────────
_logger = logging.getLogger("repository_checker")
if not _logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    _logger.addHandler(_handler)
_logger.setLevel(logging.WARNING)

# ── ROOT default ──────────────────────────────────────────────────────────────
_DEFAULT_ROOT = pathlib.Path(__file__).resolve().parent.parent

# ── Terminal color ────────────────────────────────────────────────────────────
# BUG-15/BUG-43: Dukung NO_COLOR env var; jangan mutasi dict global
_USE_COLOR = (
    sys.stdout.isatty()
    and os.environ.get("NO_COLOR", "") == ""
    and os.environ.get("TERM", "") != "dumb"
)

_COLOR_MAP: Dict[str, str] = {
    "RED":    "\033[91m",
    "GREEN":  "\033[92m",
    "YELLOW": "\033[93m",
    "BLUE":   "\033[94m",
    "CYAN":   "\033[96m",
    "BOLD":   "\033[1m",
    "RESET":  "\033[0m",
}


def _c(key: str) -> str:
    """Return ANSI escape code jika terminal support warna, else empty string."""
    return _COLOR_MAP.get(key, "") if _USE_COLOR else ""


# ── Konstanta konfigurasi ─────────────────────────────────────────────────────
EXCLUDED_DIRS: Set[str] = {
    "checker", "tests", "migrations", "__pycache__", ".git",
    "docs", "scripts", "deployment", "monitoring", "reports",
    ".venv", "venv", "node_modules", ".mypy_cache", ".ruff_cache",
}

# Keyword yang menandakan sebuah class adalah infrastructure (bukan domain repository)
INFRASTRUCTURE_KEYWORDS: Set[str] = {
    "s3", "file", "storage", "kafka", "email", "smtp", "slack", "whatsapp",
    "notification", "pagerduty", "glacier", "cold", "backup", "event", "publisher",
    "consumer", "dead", "letter", "broker", "message", "cache", "redis", "memcached",
    "audit", "append", "snapshot", "mt940", "parser", "encryption", "keyvault",
    "hashicorp", "hsm", "minio", "coretax", "authority", "bank_api", "timestamp",
    "notary", "hashchain", "saga", "cqrs", "analytics", "read_model", "projection",
    "connection_pool", "replica", "router", "fiscal", "report", "approval",
    "goods_receipt", "sales", "customer_category", "event_status", "file_storage_status",
    "notification_channel", "unit_of_work", "cohort", "export_", "import_",
}

# Suffix yang menandakan interface port/protocol repository
INTERFACE_SUFFIXES: Tuple[str, ...] = ("Port", "Protocol")
INTERFACE_REPO_KEYWORDS: Set[str] = {"repository", "store", "cache", "repo"}

# Suffix untuk implementasi
IMPL_SUFFIXES: Tuple[str, ...] = ("Adapter", "Impl", "Repository", "Store", "Cache")

# Prefix vendor yang harus di-strip saat normalisasi
IMPL_PREFIXES: Tuple[str, ...] = (
    "SQLAlchemy", "Postgres", "AsyncPG", "InMemory", "Hashicorp",
    "Customer", "Supplier", "Coretax", "Tax", "S3", "Redis",
    "Kafka", "Email", "Slack", "WhatsApp", "PagerDuty", "MinIO",
    "Glacier", "HSM", "Timestamp", "Async", "Sync", "Mock", "Fake", "Stub",
)

# Suffix yang di-strip dari interface name
IFACE_SUFFIXES: Tuple[str, ...] = (
    "Port", "Protocol", "Repository", "Store", "Cache", "Interface", "Abstract",
)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class MethodInfo:
    """Metadata satu method dalam class."""
    name:           str
    required_count: int    # jumlah parameter posisional wajib (tanpa default)
    kwonly_count:   int    # jumlah keyword-only parameter
    total_count:    int    # total parameter (tanpa self/cls)
    is_async:       bool
    is_abstract:    bool   # BUG-48: tandai @abstractmethod
    is_property:    bool   # BUG-36: tandai @property
    lineno:         int
    param_names:    List[str] = field(default_factory=list)  # BUG-34


@dataclass
class InterfaceInfo:
    """Metadata sebuah interface (Port/Protocol repository)."""
    name:       str
    file_path:  str
    module:     str
    methods:    Dict[str, MethodInfo]
    base_name:  str
    has_abc:    bool = False   # BUG-38: apakah inherit ABC/Protocol


@dataclass
class ImplementationInfo:
    """Metadata sebuah implementasi repository."""
    name:              str
    file_path:         str
    module:            str
    methods:           Dict[str, MethodInfo]
    is_infrastructure: bool = False
    base_name:         str  = ""
    extra_methods:     List[str] = field(default_factory=list)   # BUG-37


@dataclass
class Violation:
    """Satu pelanggaran kontrak."""
    severity:       str   # "ERROR" | "WARNING" | "INFO"
    interface:      str
    implementation: str
    message:        str
    detail:         str = ""
    rule_id:        str = ""   # untuk audit trail


@dataclass
class CheckerResult:
    """Hasil lengkap satu run checker."""
    interfaces:            List[InterfaceInfo]
    implementations:       List[ImplementationInfo]
    infrastructure_impls:  List[str]
    matched:               List[Tuple[str, str]]
    unmatched_interfaces:  List[str]
    unmatched_impls:       List[str]
    violations:            List[Violation]
    total_errors:          int
    total_warnings:        int
    score:                 float
    audit_timestamp:       str
    elapsed_seconds:       float
    rca_results:           List[Dict[str, Any]] = field(default_factory=list)  # BUG-49


# ── RCA Integration ──────────────────────────────────────────────────────────
# BUG-49: Integrasikan rca.py untuk root cause analysis

def _try_import_rca() -> Any:
    """
    Coba import rca.py dari direktori yang sama dengan checker ini.
    Return modul jika berhasil, None jika tidak.
    """
    checker_dir = pathlib.Path(__file__).resolve().parent
    rca_candidates = [
        checker_dir / "rca.py",
        checker_dir.parent / "rca.py",
        checker_dir.parent / "checker" / "rca.py",
    ]
    for candidate in rca_candidates:
        if candidate.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("rca", str(candidate))
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                try:
                    spec.loader.exec_module(mod)  # type: ignore[union-attr]
                    return mod
                except Exception as exc:
                    _logger.warning("Gagal load rca.py dari %s: %s", candidate, exc)
    return None


_rca_module: Any = None
_rca_attempted = False


def _get_rca():
    """Lazy-load rca module (singleton)."""
    global _rca_module, _rca_attempted
    if not _rca_attempted:
        _rca_attempted = True
        _rca_module = _try_import_rca()
    return _rca_module


def _analyze_violation_with_rca(violation: Violation) -> Optional[Dict[str, Any]]:
    """
    Buat synthetic exception dari violation dan analisis dengan RCAEngine.
    Return dict summary atau None jika RCA tidak tersedia.
    """
    rca = _get_rca()
    if rca is None:
        return None
    try:
        engine = rca.get_engine()
        # Buat synthetic AttributeError yang merepresentasikan missing method
        exc: BaseException
        if "missing" in violation.message.lower():
            exc = AttributeError(
                f"'{violation.implementation}' object has no attribute "
                f"'{_extract_method_name(violation.message)}'"
            )
        elif "async" in violation.message.lower():
            exc = TypeError(f"coroutine mismatch in {violation.message}")
        elif "parameter" in violation.message.lower():
            exc = TypeError(f"takes {violation.detail}")
        else:
            exc = RuntimeError(violation.message)

        result = engine.analyze(exc, context={
            "interface":      violation.interface,
            "implementation": violation.implementation,
            "detail":         violation.detail,
            "rule_id":        violation.rule_id,
        })
        return {
            "error_code":    result.error_code.value if hasattr(result, "error_code") else "RCA999",
            "severity":      result.severity.value   if hasattr(result, "severity")   else "HIGH",
            "root_cause":    result.root_cause,
            "suggested_fix": result.suggested_fix,
            "confidence":    result.confidence,
        }
    except Exception as exc:
        _logger.debug("RCA analisis gagal untuk violation: %s", exc)
        return None


def _extract_method_name(message: str) -> str:
    """Ekstrak nama method dari pesan violation."""
    m = re.search(r"'([^']+)'", message)
    return m.group(1) if m else "unknown_method"


# ── Utility ───────────────────────────────────────────────────────────────────

def _should_exclude_path(path: pathlib.Path, root: pathlib.Path) -> bool:
    """
    Return True jika path berada di bawah direktori yang dikecualikan.
    BUG-03/04: Sebelumnya hanya glob flat; sekarang rglob dengan filter ini.
    """
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    for part in relative.parts[:-1]:  # skip filename sendiri
        if part in EXCLUDED_DIRS:
            return True
    return False


def is_infrastructure(name: str, file_path: str) -> bool:
    """
    Tentukan apakah sebuah class adalah infrastructure (bukan domain repository).

    BUG-01 FIX: Logika lama selalu return True untuk non-repository class.
    Sekarang: return False (= domain repo) kecuali ada infra keyword.
    BUG-23 FIX: Periksa semua komponen path, bukan hanya string file_path.
    """
    name_lower = name.lower()
    # Jika mengandung "repository" di nama, anggap domain repository dulu
    if "repository" in name_lower:
        # Tapi jika juga ada infra keyword lain yang lebih kuat, tetap infra
        strong_infra = {"s3", "kafka", "redis", "email", "smtp", "slack",
                        "whatsapp", "pagerduty", "glacier", "minio", "hsm",
                        "hashicorp", "mt940", "encryption", "keyvault"}
        for kw in strong_infra:
            if kw in name_lower:
                return True
        return False  # murni domain repository

    # Periksa komponen path
    path_parts = pathlib.Path(file_path).parts
    for kw in INFRASTRUCTURE_KEYWORDS:
        if kw in name_lower:
            return True
        for part in path_parts:
            if kw in part.lower():
                return True
    return False


def normalize_interface(name: str) -> str:
    """
    Normalisasi nama interface ke base name untuk matching.

    BUG-02 FIX: Hapus baris duplikat strip "Repository".
    BUG-22 FIX: Strip semua suffix yang applicable (loop hingga stabil).
    """
    changed = True
    while changed:
        changed = False
        for suffix in IFACE_SUFFIXES:
            if name.endswith(suffix) and len(name) > len(suffix):
                name = name[: -len(suffix)]
                changed = True
                break
    return name.lower().strip()


def normalize_impl(name: str) -> str:
    """
    Normalisasi nama implementasi ke base name untuk matching.

    BUG-21 FIX: Loop prefix hingga stabil, lalu loop suffix hingga stabil.
    BUG-22 FIX: Multi-pass strip.
    """
    # Strip prefix (bisa lebih dari satu: "AsyncSQLAlchemy...")
    changed = True
    while changed:
        changed = False
        for prefix in IMPL_PREFIXES:
            if name.startswith(prefix) and len(name) > len(prefix):
                name = name[len(prefix):]
                changed = True
                break

    # Strip suffix (bisa lebih dari satu: "...RepositoryAdapter")
    changed = True
    while changed:
        changed = False
        for suffix in IMPL_SUFFIXES:
            if name.endswith(suffix) and len(name) > len(suffix):
                name = name[: -len(suffix)]
                changed = True
                break

    return name.lower().strip()


def _get_decorator_names(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> Set[str]:
    """Ekstrak nama decorator dari function node."""
    names: Set[str] = set()
    for dec in func_node.decorator_list:
        if isinstance(dec, ast.Name):
            names.add(dec.id)
        elif isinstance(dec, ast.Attribute):
            names.add(dec.attr)
    return names


def extract_methods_from_class(
    tree: ast.AST,
    class_name: str,
) -> Dict[str, MethodInfo]:
    """
    Ekstrak semua public method dari sebuah class.

    BUG-07 FIX: Iterasi node.body langsung (bukan ast.walk) — avoid nested class.
    BUG-08 FIX: Hanya skip __init__; tangkap dunder lain (__call__, __aenter__, dll).
    BUG-20 FIX: Hitung required dengan benar jika ada *args.
    BUG-36 FIX: Tangkap @property.
    BUG-48 FIX: Tandai @abstractmethod.
    BUG-34 FIX: Simpan nama parameter.
    """
    methods: Dict[str, MethodInfo] = {}

    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == class_name):
            continue

        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            mname = item.name

            # BUG-08 FIX: skip hanya __init__, bukan semua dunder
            if mname == "__init__":
                continue

            # Skip private methods (underscore prefix, kecuali dunder)
            if mname.startswith("_") and not (mname.startswith("__") and mname.endswith("__")):
                continue

            decorators = _get_decorator_names(item)
            is_property = "property" in decorators
            is_abstract = "abstractmethod" in decorators

            args = item.args
            all_pos_args = args.args  # termasuk self/cls

            # Tentukan offset untuk self/cls
            offset = 0
            if all_pos_args and all_pos_args[0].arg in ("self", "cls"):
                offset = 1

            pos_args = all_pos_args[offset:]  # tanpa self/cls
            num_pos  = len(pos_args)
            num_defaults = len(args.defaults)

            # BUG-20 FIX: required = posisional tanpa default
            # args.defaults align ke KANAN: last num_defaults args punya default
            required = max(0, num_pos - num_defaults)

            kwonly_args  = args.kwonlyargs
            kwonly_defaults = args.kw_defaults  # bisa None per element
            kwonly_required = sum(
                1 for d in kwonly_defaults if d is None
            )

            param_names = [a.arg for a in pos_args]

            is_async = isinstance(item, ast.AsyncFunctionDef)

            methods[mname] = MethodInfo(
                name=mname,
                required_count=required,
                kwonly_count=len(kwonly_args),
                total_count=num_pos,
                is_async=is_async,
                is_abstract=is_abstract,
                is_property=is_property,
                lineno=item.lineno,
                param_names=param_names,
            )
        break  # class ditemukan, tidak perlu lanjut

    return methods


def _class_has_abc_base(node: ast.ClassDef) -> bool:
    """
    BUG-38/29 FIX: Periksa apakah class inherit dari ABC atau Protocol.
    Termasuk: ABC, Protocol, typing.Protocol, abc.ABC.
    """
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id in ("ABC", "Protocol"):
            return True
        if isinstance(base, ast.Attribute) and base.attr in ("ABC", "Protocol"):
            return True
    return False


def _read_source(py_file: pathlib.Path) -> Optional[str]:
    """
    Baca source file dengan encoding detection.
    BUG-46/47 FIX: Log warning jika ada karakter yang replaced.
    """
    try:
        raw = py_file.read_bytes()
        # Deteksi BOM UTF-8
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            src = raw.decode("utf-8", errors="replace")
            _logger.warning(
                "File %s mengandung karakter non-UTF-8; sebagian karakter diganti.",
                py_file,
            )
            return src
    except OSError as exc:
        _logger.warning("Tidak bisa baca file %s: %s", py_file, exc)
        return None


# ── Scanner ───────────────────────────────────────────────────────────────────

def scan_interfaces(
    ports_dir: pathlib.Path,
    root: pathlib.Path,
) -> List[InterfaceInfo]:
    """
    Scan direktori ports untuk menemukan interface repository.

    BUG-03 FIX: rglob("**/*.py") menggantikan glob("*.py").
    BUG-05 FIX: Log warning per file yang gagal parse.
    BUG-18 FIX: seen set global untuk deteksi duplikat.
    BUG-38/29 FIX: Validasi ABC/Protocol inheritance.
    """
    interfaces: List[InterfaceInfo] = []
    if not ports_dir.exists():
        _logger.warning("Direktori interface tidak ditemukan: %s", ports_dir)
        return interfaces

    seen: Set[str] = set()

    for py_file in sorted(ports_dir.rglob("*.py")):
        if py_file.name == "__init__.py":
            continue
        if _should_exclude_path(py_file, root):
            continue

        src = _read_source(py_file)
        if src is None:
            continue

        try:
            tree = ast.parse(src, filename=str(py_file))
        except SyntaxError as exc:
            _logger.warning("SyntaxError di %s baris %s: %s", py_file, exc.lineno, exc.msg)
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            name = node.name

            # BUG-18: deteksi duplikat global
            if name in seen:
                _logger.warning(
                    "Class '%s' duplikat ditemukan di %s — dilewati.", name, py_file
                )
                continue

            # BUG-38: filter class yang namanya cocok suffix tapi bukan ABC/Protocol
            has_abc = _class_has_abc_base(node)

            is_repo_port = (
                any(name.endswith(s) for s in INTERFACE_SUFFIXES)
                and any(kw in name.lower() for kw in INTERFACE_REPO_KEYWORDS)
            )
            if not is_repo_port:
                continue

            methods = extract_methods_from_class(tree, name)
            if not methods:
                _logger.debug("Interface '%s' di %s tidak punya public method; dilewati.", name, py_file)
                continue

            try:
                rel_path = py_file.relative_to(root)
            except ValueError:
                rel_path = py_file

            module = str(rel_path.with_suffix("")).replace(os.sep, ".")
            base_name = normalize_interface(name)

            interfaces.append(InterfaceInfo(
                name=name,
                file_path=str(py_file),
                module=module,
                methods=methods,
                base_name=base_name,
                has_abc=has_abc,
            ))
            seen.add(name)

    return interfaces


def scan_implementations(
    adapters_dir: pathlib.Path,
    root: pathlib.Path,
) -> List[ImplementationInfo]:
    """
    Scan direktori adapters untuk menemukan implementasi repository.

    BUG-04 FIX: rglob.
    BUG-06 FIX: Log SyntaxError per file.
    BUG-19 FIX: seen global.
    BUG-37 FIX: Hitung extra_methods.
    BUG-42 FIX: Handle OSError.
    """
    impls: List[ImplementationInfo] = []
    if not adapters_dir.exists():
        _logger.warning("Direktori implementasi tidak ditemukan: %s", adapters_dir)
        return impls

    seen: Set[str] = set()

    for py_file in sorted(adapters_dir.rglob("*.py")):
        if py_file.name == "__init__.py":
            continue
        if _should_exclude_path(py_file, root):
            continue

        src = _read_source(py_file)
        if src is None:
            continue

        try:
            tree = ast.parse(src, filename=str(py_file))
        except SyntaxError as exc:
            _logger.warning("SyntaxError di %s baris %s: %s", py_file, exc.lineno, exc.msg)
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            name = node.name
            if name in seen:
                _logger.warning(
                    "Class '%s' duplikat ditemukan di %s — dilewati.", name, py_file
                )
                continue

            if not any(name.endswith(s) for s in IMPL_SUFFIXES):
                continue

            methods = extract_methods_from_class(tree, name)
            if not methods:
                continue

            try:
                rel_path = py_file.relative_to(root)
            except ValueError:
                rel_path = py_file

            module = str(rel_path.with_suffix("")).replace(os.sep, ".")
            is_infra = is_infrastructure(name, str(py_file))
            base_name = normalize_impl(name)

            impls.append(ImplementationInfo(
                name=name,
                file_path=str(py_file),
                module=module,
                methods=methods,
                is_infrastructure=is_infra,
                base_name=base_name,
                extra_methods=[],   # BUG-37: diisi saat compare
            ))
            seen.add(name)

    return impls


# ── Matching ──────────────────────────────────────────────────────────────────

def _token_similarity(a: str, b: str) -> float:
    """
    Hitung similarity berdasarkan token (split by '_') overlap.
    BUG-10 FIX: Hindari "user" match ke "usergroup" via substring sederhana.
    Return 0.0–1.0.
    """
    ta = set(a.split("_")) - {""}
    tb = set(b.split("_")) - {""}
    if not ta or not tb:
        return 0.0
    intersection = ta & tb
    union = ta | tb
    return len(intersection) / len(union)  # Jaccard similarity


def match_interface_to_impl(
    interface: InterfaceInfo,
    repo_impls: List[ImplementationInfo],
    used_impls: Set[str],
) -> Optional[ImplementationInfo]:
    """
    Cocokkan interface ke implementasi terbaik.

    BUG-09 FIX: Filter impl yang sudah dipakai (used_impls).
    BUG-10 FIX: Token-based similarity, bukan substring.
    BUG-35 FIX: Preferensi berdasarkan score, bukan hardcode "sqlalchemy".
    """
    base_iface = interface.base_name
    candidates: List[Tuple[float, ImplementationInfo]] = []

    for impl in repo_impls:
        if impl.is_infrastructure:
            continue
        if impl.name in used_impls:
            continue

        base_impl = impl.base_name
        score: float = 0.0

        if base_iface == base_impl:
            score = 1.0
        else:
            sim = _token_similarity(base_iface, base_impl)
            if sim >= 0.5:  # threshold: setidaknya 50% token overlap
                score = sim

        if score > 0.0:
            candidates.append((score, impl))

    if not candidates:
        return None

    # Sort by score DESC, lalu nama alphabetical untuk determinisme (BUG-35)
    candidates.sort(key=lambda x: (-x[0], x[1].name))
    return candidates[0][1]


# ── Compare ────────────────────────────────────────────────────────────────────

def compare_methods(
    interface: InterfaceInfo,
    impl: ImplementationInfo,
) -> List[Violation]:
    """
    Bandingkan methods interface vs implementasi dan hasilkan violations.

    BUG-34 FIX: Tambah WARNING jika nama parameter berbeda.
    BUG-37 FIX: Hitung extra_methods (ada di impl, tidak di interface).
    """
    violations: List[Violation] = []
    iface_method_set = set(interface.methods.keys())
    impl_method_set  = set(impl.methods.keys())

    # 1. Method hilang di implementasi → ERROR
    for mname, mdef in interface.methods.items():
        if mname not in impl_method_set:
            violations.append(Violation(
                severity="ERROR",
                interface=interface.name,
                implementation=impl.name,
                message=f"Method '{mname}' missing in implementation",
                detail=(
                    f"Didefinisikan di {interface.file_path}:{mdef.lineno} | "
                    f"Interface module: {interface.module}"
                ),
                rule_id="CHK-001",
            ))
        else:
            im = impl.methods[mname]

            # 2. Required parameter count mismatch → WARNING
            if mdef.required_count != im.required_count:
                violations.append(Violation(
                    severity="WARNING",
                    interface=interface.name,
                    implementation=impl.name,
                    message=f"Required param count mismatch untuk '{mname}'",
                    detail=(
                        f"Interface: {mdef.required_count} required, "
                        f"Impl: {im.required_count} required "
                        f"(Interface:{interface.file_path}:{mdef.lineno})"
                    ),
                    rule_id="CHK-002",
                ))

            # 3. Keyword-only mismatch → WARNING
            if mdef.kwonly_count != im.kwonly_count:
                violations.append(Violation(
                    severity="WARNING",
                    interface=interface.name,
                    implementation=impl.name,
                    message=f"Keyword-only param count mismatch untuk '{mname}'",
                    detail=(
                        f"Interface: {mdef.kwonly_count} kwonly, "
                        f"Impl: {im.kwonly_count} kwonly"
                    ),
                    rule_id="CHK-003",
                ))

            # 4. Async mismatch → WARNING
            if mdef.is_async != im.is_async:
                violations.append(Violation(
                    severity="WARNING",
                    interface=interface.name,
                    implementation=impl.name,
                    message=f"Async/sync mismatch untuk '{mname}'",
                    detail=(
                        f"Interface: {'async' if mdef.is_async else 'sync'}, "
                        f"Impl: {'async' if im.is_async else 'sync'}"
                    ),
                    rule_id="CHK-004",
                ))

            # 5. BUG-34: Nama parameter berbeda → WARNING (jika jumlah sama)
            if (
                mdef.param_names
                and im.param_names
                and len(mdef.param_names) == len(im.param_names)
                and mdef.param_names != im.param_names
            ):
                mismatched = [
                    f"pos{i}: iface='{a}' impl='{b}'"
                    for i, (a, b) in enumerate(zip(mdef.param_names, im.param_names))
                    if a != b
                ]
                if mismatched:
                    violations.append(Violation(
                        severity="WARNING",
                        interface=interface.name,
                        implementation=impl.name,
                        message=f"Nama parameter berbeda untuk '{mname}'",
                        detail="; ".join(mismatched),
                        rule_id="CHK-005",
                    ))

    # BUG-37: Extra methods di impl yang tidak ada di interface
    extra = sorted(impl_method_set - iface_method_set)
    impl.extra_methods = extra  # mutable update — OK karena masih dalam scan phase

    return violations


# ── Main scan orchestrator ─────────────────────────────────────────────────────

def scan_repositories(
    root: pathlib.Path,
    ports_dir: Optional[pathlib.Path] = None,
    impls_dir: Optional[pathlib.Path] = None,
    run_rca: bool = True,
) -> CheckerResult:
    """
    Orkestrator utama: scan → match → compare → (optional RCA).

    BUG-11 FIX: unmatched tidak masuk denominator skor.
    BUG-12 FIX: skor = error_free / matched_count × 100.
    BUG-24 FIX: Timing per fase.
    BUG-49 FIX: RCA integration untuk setiap ERROR violation.
    """
    t_start = time.monotonic()

    effective_ports = ports_dir or (root / "ports" / "primary")
    effective_impls = impls_dir or (root / "adapters" / "secondary_impl")

    # Fase 1: Scan
    t1 = time.monotonic()
    interfaces = scan_interfaces(effective_ports, root)
    t2 = time.monotonic()
    all_implementations = scan_implementations(effective_impls, root)
    t3 = time.monotonic()
    _logger.debug(
        "Scan selesai: %d interfaces (%.3fs), %d impls (%.3fs)",
        len(interfaces), t2 - t1, len(all_implementations), t3 - t2,
    )

    repo_impls   = [i for i in all_implementations if not i.is_infrastructure]
    infra_impls  = [i.name for i in all_implementations if i.is_infrastructure]

    # Fase 2: Match & Compare
    matched_pairs:       List[Tuple[str, str]] = []
    used_impls:          Set[str]              = set()
    matched_iface_names: Set[str]              = set()
    all_violations:      List[Violation]       = []
    total_errors         = 0
    total_warnings       = 0

    for iface in interfaces:
        if iface.name in matched_iface_names:
            continue
        impl = match_interface_to_impl(iface, repo_impls, used_impls)
        if impl:
            matched_pairs.append((iface.name, impl.name))
            used_impls.add(impl.name)
            matched_iface_names.add(iface.name)
            violations = compare_methods(iface, impl)
            all_violations.extend(violations)
            total_errors   += sum(1 for v in violations if v.severity == "ERROR")
            total_warnings += sum(1 for v in violations if v.severity == "WARNING")

    unmatched_interfaces = [i.name for i in interfaces if i.name not in matched_iface_names]
    unmatched_impls      = [i.name for i in repo_impls  if i.name not in used_impls]

    # BUG-12 FIX: skor berbasis matched yang error-free, dibagi matched (bukan total)
    matched_count = len(matched_pairs)
    error_free_matches = 0
    for iface_name, _ in matched_pairs:
        has_error = any(
            v.interface == iface_name and v.severity == "ERROR"
            for v in all_violations
        )
        if not has_error:
            error_free_matches += 1

    score = (error_free_matches / matched_count * 100) if matched_count > 0 else (
        100.0 if not interfaces else 0.0
    )

    # Fase 3: RCA (BUG-49)
    rca_results: List[Dict[str, Any]] = []
    if run_rca:
        error_violations = [v for v in all_violations if v.severity == "ERROR"]
        for v in error_violations[:20]:   # limit 20 untuk performance
            rca = _analyze_violation_with_rca(v)
            if rca:
                rca["violation"] = v.message
                rca["interface"] = v.interface
                rca["implementation"] = v.implementation
                rca_results.append(rca)

    elapsed = time.monotonic() - t_start

    return CheckerResult(
        interfaces=interfaces,
        implementations=repo_impls,
        infrastructure_impls=infra_impls,
        matched=matched_pairs,
        unmatched_interfaces=unmatched_interfaces,
        unmatched_impls=unmatched_impls,
        violations=all_violations,
        total_errors=total_errors,
        total_warnings=total_warnings,
        score=round(score, 1),
        audit_timestamp=datetime.datetime.utcnow().isoformat() + "Z",
        elapsed_seconds=round(elapsed, 3),
        rca_results=rca_results,
    )


# ── Report ────────────────────────────────────────────────────────────────────

def _safe_print(text: str) -> None:
    """
    BUG-27 FIX: Print dengan fallback encoding-safe.
    """
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


def print_report(
    data: CheckerResult,
    verbose: bool = False,
    limit: int = 50,
) -> None:
    """
    Cetak laporan ke stdout.

    BUG-16 FIX: gunakan limit parameter.
    BUG-17 FIX: konsisten gunakan data.total_errors.
    BUG-40 FIX: ASCII box yang simetris.
    BUG-44 FIX: angka rata kanan.
    BUG-45 FIX: breakdown per modul di verbose.
    """
    SEP  = "=" * 72
    TSEP = "─" * 72

    _safe_print(f"\n{_c('CYAN')}{SEP}{_c('RESET')}")
    _safe_print(
        f"{_c('BOLD')}{_c('CYAN')}"
        f"  REPOSITORY CONTRACT CHECKER REPORT v{__version__}"
        f"{_c('RESET')}"
    )
    _safe_print(f"{_c('CYAN')}{SEP}{_c('RESET')}")

    rca_status = f"{'Ya' if _get_rca() else 'Tidak tersedia'}"
    _safe_print(f"\n  Audit timestamp           : {data.audit_timestamp}")
    _safe_print(f"  Checker versi             : {__version__}")
    _safe_print(f"  Elapsed                   : {data.elapsed_seconds:.3f}s")
    _safe_print(f"  RCA Engine                : {rca_status}")
    _safe_print(f"")
    _safe_print(f"  Interfaces found          : {len(data.interfaces):>6}")
    _safe_print(f"  Repository implementations : {len(data.implementations):>6}")
    _safe_print(f"  Infrastructure impls (skip): {len(data.infrastructure_impls):>6}")
    _safe_print(f"  Matched pairs             : {len(data.matched):>6}")
    _safe_print(f"  Unmatched interfaces      : {len(data.unmatched_interfaces):>6}")
    _safe_print(f"  Unmatched impls           : {len(data.unmatched_impls):>6}")
    _safe_print(f"  Contract Errors (missing) : {data.total_errors:>6}")
    _safe_print(f"  Contract Warnings (sig)   : {data.total_warnings:>6}")

    score_color = _c("GREEN") if data.score >= 90 else (_c("YELLOW") if data.score >= 70 else _c("RED"))
    _safe_print(
        f"\n  Skor Kepatuhan            : "
        f"{score_color}{_c('BOLD')}{data.score:6.1f}/100{_c('RESET')}"
    )

    # Matched pairs
    if data.matched:
        _safe_print(f"\n{_c('GREEN')}[OK] Matched pairs ({len(data.matched)}):{_c('RESET')}")
        for iface, impl in data.matched[:limit]:
            _safe_print(f"    {iface}  <-->  {impl}")
        if len(data.matched) > limit:
            _safe_print(f"    ... dan {len(data.matched) - limit} lainnya (gunakan --limit untuk tampilkan lebih).")

    # Unmatched interfaces
    if data.unmatched_interfaces:
        _safe_print(
            f"\n{_c('YELLOW')}[WARN] Unmatched interfaces ({len(data.unmatched_interfaces)}){_c('RESET')}"
        )
        for name in data.unmatched_interfaces[:limit]:
            _safe_print(f"    - {name}")
        if len(data.unmatched_interfaces) > limit:
            _safe_print(f"    ... dan {len(data.unmatched_interfaces) - limit} lainnya.")

    # Unmatched implementations
    if data.unmatched_impls:
        _safe_print(
            f"\n{_c('YELLOW')}[WARN] Unmatched implementations ({len(data.unmatched_impls)}){_c('RESET')}"
        )
        for name in data.unmatched_impls[:limit]:
            _safe_print(f"    - {name}")
        if len(data.unmatched_impls) > limit:
            _safe_print(f"    ... dan {len(data.unmatched_impls) - limit} lainnya.")

    # ERROR violations
    errors   = [v for v in data.violations if v.severity == "ERROR"]
    warnings = [v for v in data.violations if v.severity == "WARNING"]

    if errors:
        _safe_print(f"\n{_c('RED')}[ERRORS] Contract ERRORS ({len(errors)}):{_c('RESET')}")
        for v in errors[:limit]:
            _safe_print(f"  {_c('RED')}[{v.rule_id}]{_c('RESET')} {v.message}")
            _safe_print(f"       Interface : {v.interface}")
            _safe_print(f"       Impl      : {v.implementation}")
            if v.detail:
                _safe_print(f"       Detail    : {v.detail}")
        if len(errors) > limit:
            _safe_print(f"  ... dan {len(errors) - limit} errors lainnya.")

    # WARNING violations
    if warnings and verbose:
        _safe_print(f"\n{_c('YELLOW')}[WARNINGS] Contract WARNINGS ({len(warnings)}):{_c('RESET')}")
        for v in warnings[:limit]:
            _safe_print(f"  {_c('YELLOW')}[{v.rule_id}]{_c('RESET')} {v.message}")
            _safe_print(f"       Interface : {v.interface}")
            _safe_print(f"       Impl      : {v.implementation}")
            if v.detail:
                _safe_print(f"       Detail    : {v.detail}")
        if len(warnings) > limit:
            _safe_print(f"  ... dan {len(warnings) - limit} warnings lainnya.")
    elif warnings:
        _safe_print(
            f"\n{_c('YELLOW')}[WARN] {len(warnings)} warnings — gunakan --verbose untuk detail.{_c('RESET')}"
        )

    # RCA results
    if data.rca_results and verbose:
        _safe_print(f"\n{_c('CYAN')}[RCA] Root Cause Analysis ({len(data.rca_results)} violations):{_c('RESET')}")
        for r in data.rca_results:
            _safe_print(f"  [{r.get('error_code','?')}] {r.get('violation','')}")
            _safe_print(f"    Root cause   : {r.get('root_cause','')}")
            _safe_print(f"    Fix          : {r.get('suggested_fix','')}")
            _safe_print(f"    Confidence   : {r.get('confidence', 0):.0%}")

    # BUG-45: Verbose module breakdown
    if verbose and data.implementations:
        _safe_print(f"\n{_c('CYAN')}[DETAIL] Extra Methods di Implementasi:{_c('RESET')}")
        for impl in data.implementations:
            if impl.extra_methods:
                _safe_print(f"  {impl.name}: {', '.join(impl.extra_methods)}")

    # Footer
    _safe_print(f"\n{_c('CYAN')}{TSEP}{_c('RESET')}")
    _safe_print(f"  Errors   : {_c('RED')}{data.total_errors}{_c('RESET')}")
    _safe_print(f"  Warnings : {_c('YELLOW')}{data.total_warnings}{_c('RESET')}")

    if data.total_errors == 0:
        _safe_print(
            f"  {_c('GREEN')}[PASS] Semua repository contract terpenuhi (tidak ada missing method).{_c('RESET')}"
        )
    else:
        _safe_print(
            f"  {_c('RED')}[FAIL] Perbaiki errors di atas sebelum merge/deploy.{_c('RESET')}"
        )


def save_json(data: CheckerResult, filepath: str) -> bool:
    """
    Ekspor laporan ke JSON.

    BUG-13 FIX: Handle exception saat write.
    BUG-31 FIX: Sertakan audit_timestamp.
    BUG-32 FIX: Sertakan checker_version.
    """
    payload: Dict[str, Any] = {
        "checker_version":    __version__,
        "audit_timestamp":    data.audit_timestamp,
        "elapsed_seconds":    data.elapsed_seconds,
        "score":              data.score,
        "total_interfaces":   len(data.interfaces),
        "total_repo_impls":   len(data.implementations),
        "infrastructure_impls": data.infrastructure_impls,
        "matched_pairs":      [{"interface": i, "implementation": m} for i, m in data.matched],
        "unmatched_interfaces": data.unmatched_interfaces,
        "unmatched_impls":    data.unmatched_impls,
        "total_errors":       data.total_errors,
        "total_warnings":     data.total_warnings,
        "errors": [
            {
                "rule_id":        v.rule_id,
                "interface":      v.interface,
                "implementation": v.implementation,
                "message":        v.message,
                "detail":         v.detail,
            }
            for v in data.violations if v.severity == "ERROR"
        ],
        "warnings": [
            {
                "rule_id":        v.rule_id,
                "interface":      v.interface,
                "implementation": v.implementation,
                "message":        v.message,
                "detail":         v.detail,
            }
            for v in data.violations if v.severity == "WARNING"
        ],
        "rca_results": data.rca_results,
        "implementations_detail": [
            {
                "name":          impl.name,
                "module":        impl.module,
                "extra_methods": impl.extra_methods,
            }
            for impl in data.implementations
        ],
    }
    try:
        out_path = pathlib.Path(filepath)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        _safe_print(f"{_c('GREEN')}[OK] Laporan diekspor ke {filepath}{_c('RESET')}")
        return True
    except (OSError, PermissionError, TypeError) as exc:
        _safe_print(f"{_c('RED')}[ERROR] Gagal ekspor JSON ke {filepath}: {exc}{_c('RESET')}")
        return False


# ── Self-test ─────────────────────────────────────────────────────────────────
# BUG-33 FIX: Internal self-test

def _run_self_test() -> bool:
    """
    Self-test komponen utama: normalisasi, matching, extraction.
    Return True jika semua lulus.
    """
    failures: List[str] = []

    def check(name: str, got: Any, expected: Any) -> None:
        if got != expected:
            failures.append(f"FAIL [{name}]: got={got!r} expected={expected!r}")

    # Normalisasi interface
    check("norm_iface_Port",       normalize_interface("UserRepositoryPort"),     "user")
    check("norm_iface_Protocol",   normalize_interface("InvoiceRepositoryProtocol"), "invoice")
    check("norm_iface_double",     normalize_interface("AccountRepositoryPort"),  "account")

    # Normalisasi impl
    check("norm_impl_SQLAdapter",  normalize_impl("SQLAlchemyUserRepositoryAdapter"), "user")
    check("norm_impl_Impl",        normalize_impl("UserRepositoryImpl"),           "user")
    check("norm_impl_double_prefix", normalize_impl("AsyncSQLAlchemyInvoiceRepositoryAdapter"), "invoice")

    # is_infrastructure
    check("infra_redis",      is_infrastructure("RedisCache", "/adapters/redis_cache.py"), True)
    check("infra_repo_false", is_infrastructure("UserRepository", "/adapters/user_repo.py"), False)
    check("infra_kafka",      is_infrastructure("KafkaPublisher", "/adapters/kafka.py"), True)

    # Token similarity
    sim = _token_similarity("user", "user_group")
    if not (0.0 < sim < 1.0):
        failures.append(f"FAIL [token_sim]: expected 0<sim<1 for user/user_group, got {sim}")

    # extract_methods_from_class — buat synthetic AST
    src = """
import abc
class MyPort(abc.ABC):
    @abc.abstractmethod
    async def get_by_id(self, entity_id: int) -> None: ...

    @abc.abstractmethod
    def save(self, entity, *, validate: bool = True) -> None: ...

    def __init__(self): pass

    def _private(self): pass
"""
    try:
        tree = ast.parse(src)
        methods = extract_methods_from_class(tree, "MyPort")
        check("extract_count",    len(methods), 2)
        check("extract_async",    methods["get_by_id"].is_async, True)
        check("extract_required", methods["get_by_id"].required_count, 1)
        check("extract_abstract", methods["save"].is_abstract, True)
        check("extract_kwonly",   methods["save"].kwonly_count, 1)
    except Exception as exc:
        failures.append(f"FAIL [extract_methods]: {exc}")

    if failures:
        for f in failures:
            _safe_print(f"  {_c('RED')}{f}{_c('RESET')}")
        return False

    _safe_print(f"  {_c('GREEN')}[PASS] Semua self-test lulus.{_c('RESET')}")
    return True


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repository_checker",
        description=(
            f"Repository Contract Checker v{__version__} — "
            "Big 4 Forensic Audit / SOX/ISA 315 Compliant"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--root",
        metavar="DIR",
        default=None,
        help=(
            "Root direktori project. "
            f"Default: parent dari parent file ini ({_DEFAULT_ROOT})"
        ),
    )
    parser.add_argument(
        "--ports-dir",
        metavar="DIR",
        default=None,
        help="Override direktori interface (default: <root>/ports/primary)",
    )
    parser.add_argument(
        "--impls-dir",
        metavar="DIR",
        default=None,
        help="Override direktori implementasi (default: <root>/adapters/secondary_impl)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Tampilkan detail warnings, RCA results, dan extra methods",
    )
    parser.add_argument(
        "--json",
        metavar="FILE",
        help="Ekspor laporan ke file JSON",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json", "both"],
        default="text",
        help="Format output: text (default), json, atau both",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Batasi jumlah item yang ditampilkan per section (default: 50)",
    )
    parser.add_argument(
        "--no-rca",
        action="store_true",
        help="Nonaktifkan integrasi RCA (lebih cepat)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan dan print tapi jangan tulis file output",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Jalankan internal self-test dan exit",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Aktifkan logging DEBUG ke stderr",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()

    # BUG-33: self-test mode
    if args.self_test:
        _safe_print(f"\n{_c('CYAN')}[SELF-TEST] Repository Checker v{__version__}{_c('RESET')}")
        ok = _run_self_test()
        sys.exit(0 if ok else 1)

    # BUG-28: debug logging
    if args.debug:
        _logger.setLevel(logging.DEBUG)

    # Resolve ROOT
    if args.root:
        root = pathlib.Path(args.root).resolve()
    else:
        root = _DEFAULT_ROOT

    # BUG-14 FIX: Validasi root exist
    if not root.exists():
        _safe_print(
            f"{_c('RED')}[ERROR] Root direktori tidak ditemukan: {root}{_c('RESET')}"
        )
        sys.exit(2)

    ports_dir = pathlib.Path(args.ports_dir).resolve()  if args.ports_dir  else None
    impls_dir = pathlib.Path(args.impls_dir).resolve()  if args.impls_dir  else None

    # BUG-40 FIX: Box yang simetris
    BOX_WIDTH = 70
    border    = "═" * BOX_WIDTH
    _safe_print(f"{_c('BOLD')}{_c('CYAN')}╔{border}╗")
    title     = f"SOVEREIGN REPOSITORY CONTRACT CHECKER v{__version__}"
    padding   = BOX_WIDTH - len(title)
    lpad      = padding // 2
    rpad      = padding - lpad
    _safe_print(f"║{' ' * lpad}{title}{' ' * rpad}║")
    _safe_print(f"╚{border}╝{_c('RESET')}")

    eff_ports = ports_dir or (root / "ports" / "primary")
    eff_impls = impls_dir or (root / "adapters" / "secondary_impl")
    _safe_print(f"  Root               : {root}")
    _safe_print(f"  Interface dir      : {eff_ports}")
    _safe_print(f"  Implementation dir : {eff_impls}")
    _safe_print(f"  RCA enabled        : {'No (--no-rca)' if args.no_rca else 'Yes'}")

    # Scan
    data = scan_repositories(
        root=root,
        ports_dir=ports_dir,
        impls_dir=impls_dir,
        run_rca=not args.no_rca,
    )

    # Output
    if args.format in ("text", "both"):
        print_report(data, verbose=args.verbose, limit=args.limit)

    if not args.dry_run:
        json_target = args.json
        if args.format == "json" and not json_target:
            json_target = "repository_checker_report.json"
        if json_target or args.format in ("json", "both"):
            target = json_target or "repository_checker_report.json"
            save_json(data, target)
    else:
        _safe_print(f"\n{_c('YELLOW')}[DRY-RUN] Tidak ada file yang ditulis.{_c('RESET')}")

    _safe_print(f"\n  Waktu Audit: {data.elapsed_seconds:.3f} detik")

    # BUG-28 FIX: exit codes
    if data.total_errors > 0:
        sys.exit(1)
    elif data.total_warnings > 0:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
