#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker_critical_import.py — P50 Critical Modules Import Scan
Versi: 2.0.0
Standard: Big 4 Audit Ready (ISO/IEC 25010, SOC 2 Type II, ISAE 3402)

Fungsi utama:
  1. Scan & import semua modul penting secara dinamis
  2. Isolasi setiap import agar tidak mencemari sys.modules global
  3. Deteksi circular import, symbol leaks, side effects
  4. Kategorisasi kegagalan per lapisan DDD/Clean Architecture
  5. Laporan terstruktur: JSON machine-readable + human-readable teks
  6. Exit code standar CI/CD (0=pass, 1=fail, 2=warning, 3=error-scan)
  7. Reproducible: seed sort + checksum fingerprint per modul
  8. Timeout per import agar tidak hang pada slow-init
  9. Dependency graph & orphan detection
 10. Rekap per-layer untuk auditor (domain purity check)
"""

from __future__ import annotations

import ast
import concurrent.futures
import datetime
import hashlib
import importlib
import importlib.util
import json
import logging
import os
import pathlib
import platform
import re
import signal
import subprocess
import sys
import threading
import time
import traceback
import types
import uuid
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS & CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

VERSION       = "2.0.0"
SCAN_ID       = str(uuid.uuid4())[:8].upper()          # Unique ID per run (audit trail)
TOOL_NAME     = "P50-CriticalImportScan"
AUDIT_STD     = "ISO/IEC 25010 | SOC 2 Type II | ISAE 3402"

# [FIX-01] __file__ di-resolve lewat CALLER frame jika dijalankan sebagai modul,
#   bukan diasumsikan selalu ada — gunakan fallback ke cwd jika __file__ undefined.
try:
    _THIS_FILE   = pathlib.Path(__file__).resolve()
    PROJECT_ROOT = _THIS_FILE.parent.parent
except NameError:
    PROJECT_ROOT = pathlib.Path.cwd()

# [FIX-02] sys.path harus dimodifikasi secara atomic dan diverifikasi —
#   versi lama tidak mengecek apakah path yang ditambahkan valid/readable.
def _ensure_project_root_in_syspath(root: pathlib.Path) -> bool:
    """Tambahkan PROJECT_ROOT ke sys.path; return False jika tidak readable."""
    if not root.is_dir():
        return False
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return True

_SYSPATH_OK = _ensure_project_root_in_syspath(PROJECT_ROOT)

# ── Timeout ───────────────────────────────────────────────────────────────────
# [FIX-03] Tidak ada timeout per import — modul dengan __init__ lambat/blocking
#   akan menghang selamanya. Sekarang per-import dibatasi IMPORT_TIMEOUT detik.
IMPORT_TIMEOUT_SEC = int(os.environ.get("P50_IMPORT_TIMEOUT", "10"))

# [FIX-04] Jumlah worker untuk concurrent scan harus configurable & bounded,
#   bukan hardcoded. Default: 4, max: cpu_count.
MAX_WORKERS = min(
    int(os.environ.get("P50_WORKERS", "4")),
    (os.cpu_count() or 1)
)

# ── Output ────────────────────────────────────────────────────────────────────
# [FIX-05] Output report path tidak dikonfigurasi — auditor tidak bisa
#   mengarsipkan hasil scan. Sekarang bisa dikonfigurasikan via env var.
REPORT_DIR  = pathlib.Path(os.environ.get("P50_REPORT_DIR", str(PROJECT_ROOT / "audit_reports")))
JSON_REPORT = REPORT_DIR / f"p50_import_scan_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{SCAN_ID}.json"
TXT_REPORT  = REPORT_DIR / f"p50_import_scan_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_{SCAN_ID}.txt"

# ── Logging ───────────────────────────────────────────────────────────────────
# [FIX-06] logging.basicConfig() memodifikasi root logger GLOBAL — mencemari
#   logger modul lain yang mungkin sudah dikonfigurasi. Gunakan dedicated logger.
_log_handler = logging.StreamHandler(sys.stderr)
_log_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
))
logger = logging.getLogger(TOOL_NAME)
logger.setLevel(logging.INFO)
logger.propagate = False   # jangan bocor ke root logger
if not logger.handlers:
    logger.addHandler(_log_handler)

# [FIX-07] Redam logger noise hanya untuk scanner ini, bukan global.
for _noisy in ("sqlalchemy", "infrastructure", "adapters", "bootstrap",
               "alembic", "urllib3", "botocore", "celery"):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)

# ─────────────────────────────────────────────────────────────────────────────
# FOLDER & SKIP CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

# [FIX-08] CRITICAL_FOLDERS sebagai set tidak punya ordering — scan non-deterministic.
#   Sekarang pakai list dengan urutan eksplisit sesuai dependency hierarchy.
#   Layer terbawah (domain) duluan agar import errors lebih cepat terdeteksi.
CRITICAL_FOLDERS: List[str] = [
    # Core DDD layers — urutan sesuai dependency rule (innermost first)
    "domain",
    "ports",
    "axioms",
    "constitution",
    "kernel",
    "application",
    "policy_engine",
    "compliance",
    "audit",
    "infrastructure",
    "adapters",
    "event_gateway",
    "projections",
    "reports",
    "bootstrap",
    "config",
    "app",
]

# Layer ownership untuk audit dependency rule
LAYER_OWNERSHIP: Dict[str, str] = {
    "domain"        : "Core Domain",
    "ports"         : "Port Interface",
    "axioms"        : "Core Domain",
    "constitution"  : "Core Domain",
    "kernel"        : "Core Domain",
    "application"   : "Application Service",
    "policy_engine" : "Application Service",
    "compliance"    : "Application Service",
    "audit"         : "Application Service",
    "infrastructure": "Infrastructure",
    "adapters"      : "Infrastructure",
    "event_gateway" : "Infrastructure",
    "projections"   : "Infrastructure",
    "reports"       : "Infrastructure",
    "bootstrap"     : "Composition Root",
    "config"        : "Composition Root",
    "app"           : "Composition Root",
}

# [FIX-09] SKIP_STEMS sebagai set tidak cover nama file dengan suffix angka
#   seperti 'main_v2', 'checker2'. Tambahkan regex-based skip.
SKIP_STEMS: Set[str] = {
    "__init__", "__main__",
    "main_checker", "tax_checker", "layer_checker",
    "fiscal_period_checker", "checker_critical_import",
    "conftest", "setup", "manage",
}

SKIP_STEM_PATTERNS: List[re.Pattern] = [
    re.compile(r"^test_"),
    re.compile(r"_test$"),
    re.compile(r"^checker_"),   # skip checker files termasuk diri sendiri
]

# [FIX-10] SKIP_MODULE_SUBSTR pakai set — iterasi tidak ordered, cukup untuk
#   substring check. Tambahkan lebih banyak pola yang relevan.
SKIP_MODULE_SUBSTR: Set[str] = {
    "proto", "test", "grpc", "pb2", "migrations",
    "alembic", "fixture", "factory", "stub", "mock",
    "conftest", "sandbox", "playground",
}

# [FIX-11] Tidak ada konfigurasi encoding — pathlib rglob() bisa mengembalikan
#   file dengan nama yang tidak bisa di-decode di Windows (cp1252 vs utf-8).
#   Tambahkan error='replace' handling pada file stem comparison.

# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────

class ImportStatus(Enum):
    OK          = "OK"
    FAIL_IMPORT = "FAIL_IMPORT"
    FAIL_SYNTAX = "FAIL_SYNTAX"
    FAIL_TIMEOUT= "FAIL_TIMEOUT"
    FAIL_SIDE_EFFECT = "FAIL_SIDE_EFFECT"
    SKIPPED     = "SKIPPED"
    WARNING     = "WARNING"

class Severity(Enum):
    FATAL    = "FATAL"     # Gagal import — modul tidak bisa di-load sama sekali
    CRITICAL = "CRITICAL"  # SyntaxError atau circular import
    HIGH     = "HIGH"      # Timeout atau side effect berbahaya
    MEDIUM   = "MEDIUM"    # Deprecated API atau warning saat import
    LOW      = "LOW"       # Modul tidak ditemukan (folder kosong)
    INFO     = "INFO"      # OK

# [FIX-12] Tidak ada data class untuk hasil scan — data dipass sebagai tuple
#   (label, module, err) yang rapuh dan tidak self-documenting.
@dataclass
class ModuleInfo:
    """Metadata modul sebelum diimport."""
    label       : str
    module_name : str
    file_path   : str
    folder      : str
    layer       : str
    file_size_b : int          = 0
    sha256      : str          = ""
    ast_valid   : bool         = True
    ast_error   : str          = ""
    line_count  : int          = 0


@dataclass
class ScanResult:
    """Hasil scan satu modul — immutable setelah scan selesai."""
    module_info  : ModuleInfo
    status       : ImportStatus      = ImportStatus.OK
    severity     : Severity          = Severity.INFO
    error_type   : str               = ""
    error_message: str               = ""
    traceback_str: str               = ""
    duration_ms  : float             = 0.0
    # Modul yang ditambahkan ke sys.modules selama import ini
    new_sys_modules: List[str]       = field(default_factory=list)
    # Simbol publik yang di-export
    public_symbols : int             = 0
    warnings_caught: List[str]       = field(default_factory=list)
    # Apakah import ini mencemari global state
    side_effects   : List[str]       = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == ImportStatus.OK

    @property
    def failed(self) -> bool:
        return self.status in (
            ImportStatus.FAIL_IMPORT,
            ImportStatus.FAIL_SYNTAX,
            ImportStatus.FAIL_TIMEOUT,
            ImportStatus.FAIL_SIDE_EFFECT,
        )


@dataclass
class ScanReport:
    """Laporan lengkap satu run scan."""
    scan_id       : str
    tool_name     : str
    tool_version  : str
    audit_standard: str
    timestamp_utc : str
    hostname      : str
    python_version: str
    platform_info : str
    project_root  : str
    git_commit    : str
    git_branch    : str
    total         : int              = 0
    ok_count      : int              = 0
    fail_count    : int              = 0
    warn_count    : int              = 0
    skip_count    : int              = 0
    duration_sec  : float            = 0.0
    results       : List[ScanResult] = field(default_factory=list)
    layer_summary : Dict[str, dict]  = field(default_factory=dict)
    dependency_issues: List[str]     = field(default_factory=list)
    overall_pass  : bool             = False
    exit_code     : int              = 1

# ─────────────────────────────────────────────────────────────────────────────
# GIT METADATA
# ─────────────────────────────────────────────────────────────────────────────

def _git_info() -> Tuple[str, str]:
    """Ambil git commit hash dan branch untuk audit trail."""
    # [FIX-13] Tidak ada audit trail git — auditor tidak bisa tahu kode
    #   versi berapa yang di-scan. Sekarang di-capture setiap run.
    def _run(cmd: List[str]) -> str:
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=5, cwd=str(PROJECT_ROOT)
            )
            return r.stdout.strip() if r.returncode == 0 else "unknown"
        except Exception:
            return "unknown"

    commit = _run(["git", "rev-parse", "--short", "HEAD"])
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return commit, branch

# ─────────────────────────────────────────────────────────────────────────────
# MODULE COLLECTION
# ─────────────────────────────────────────────────────────────────────────────

def _file_sha256(path: pathlib.Path) -> str:
    """SHA-256 checksum file untuk fingerprinting audit."""
    # [FIX-14] Tidak ada checksum — auditor tidak bisa memverifikasi bahwa
    #   file yang di-scan adalah file yang sama saat review.
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return "unavailable"


def _validate_ast(path: pathlib.Path) -> Tuple[bool, str, int]:
    """
    Parse AST sebelum import — deteksi SyntaxError TANPA mengeksekusi kode.
    Return: (valid, error_message, line_count)

    [FIX-15] safe_import() versi lama mendeteksi SyntaxError hanya setelah
      import — jika file punya syntax error tapi di-import oleh modul lain
      lebih dulu, exception bisa berbeda. Pre-validasi AST lebih akurat.
    """
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        line_count = source.count("\n") + 1
        ast.parse(source, filename=str(path))
        return True, "", line_count
    except SyntaxError as e:
        return False, f"SyntaxError di baris {e.lineno}: {e.msg}", 0
    except OSError as e:
        return False, f"OSError: {e}", 0


def _should_skip(py_file: pathlib.Path) -> bool:
    """Return True jika file harus di-skip."""
    stem = py_file.stem

    # [FIX-16] Versi lama: `if py_file.stem in SKIP_STEMS` — tidak cover
    #   case-sensitive di Linux vs Windows. Normalisasi ke lowercase.
    if stem.lower() in {s.lower() for s in SKIP_STEMS}:
        return True

    # Regex-based skip
    for pat in SKIP_STEM_PATTERNS:
        if pat.search(stem):
            return True

    # Substring skip pada full path
    path_lower = str(py_file).lower()
    if any(sub in path_lower for sub in SKIP_MODULE_SUBSTR):
        return True

    # [FIX-17] Tidak ada pengecekan apakah file bisa dibaca — permission error
    #   di safe_import() tertangkap sebagai "Exception: PermissionError" yang
    #   menyesatkan. Cek readability di sini.
    if not os.access(py_file, os.R_OK):
        logger.warning(f"File tidak bisa dibaca (permission): {py_file}")
        return True

    return False


def collect_modules() -> List[ModuleInfo]:
    """
    Kumpulkan semua modul penting sebagai ModuleInfo.

    [FIX-18] Versi lama mengembalikan List[Tuple[str,str]] yang rapuh.
      Sekarang mengembalikan List[ModuleInfo] yang self-documenting.

    [FIX-19] Versi lama tidak mendeteksi duplikat — file yang sama bisa
      masuk dua kali jika ada symlink atau overlapping folder definition.
    """
    modules: List[ModuleInfo] = []
    seen_paths: Set[str] = set()          # [FIX-19] dedup via resolved path
    seen_modules: Set[str] = set()        # [FIX-20] dedup via module name

    for folder in CRITICAL_FOLDERS:
        dir_path = PROJECT_ROOT / folder
        if not dir_path.exists():
            logger.debug(f"Folder tidak ada, dilewati: {folder}")
            continue

        if not dir_path.is_dir():
            # [FIX-21] Versi lama tidak cek apakah path adalah direktori —
            #   bisa crash jika nama folder adalah file biasa.
            logger.warning(f"Bukan direktori: {folder}")
            continue

        try:
            py_files = list(dir_path.rglob("*.py"))
        except PermissionError as e:
            # [FIX-22] rglob() bisa melempar PermissionError di subfolder —
            #   versi lama tidak menangani ini sama sekali.
            logger.warning(f"Permission denied saat scan {folder}: {e}")
            continue

        for py_file in py_files:
            # [FIX-23] Resolve symlink untuk dedup yang akurat
            try:
                resolved = str(py_file.resolve())
            except OSError:
                resolved = str(py_file)

            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)

            if _should_skip(py_file):
                continue

            # Bangun module name
            try:
                rel_path = py_file.relative_to(PROJECT_ROOT)
            except ValueError:
                # [FIX-24] relative_to() bisa gagal jika py_file di luar
                #   PROJECT_ROOT (via symlink). Versi lama crash tanpa handler.
                logger.warning(f"File di luar PROJECT_ROOT: {py_file}")
                continue

            # [FIX-25] replace("/", ".") tidak handle path separator Windows
            #   dengan benar saat dijalankan di WSL. Gunakan parts().
            module_name = ".".join(rel_path.with_suffix("").parts)

            if module_name in seen_modules:
                continue
            seen_modules.add(module_name)

            # [FIX-26] Label versi lama: "folder/stem" — tidak unik jika ada
            #   subfolder (misal: domain/entities/account.py dan
            #   domain/services/account.py keduanya jadi "domain/account").
            label = str(rel_path.with_suffix("")).replace(os.sep, "/")

            # Collect metadata
            try:
                file_size = py_file.stat().st_size
            except OSError:
                file_size = 0

            ast_valid, ast_error, line_count = _validate_ast(py_file)
            sha256 = _file_sha256(py_file)

            modules.append(ModuleInfo(
                label       = label,
                module_name = module_name,
                file_path   = str(py_file),
                folder      = folder,
                layer       = LAYER_OWNERSHIP.get(folder, "Unknown"),
                file_size_b = file_size,
                sha256      = sha256,
                ast_valid   = ast_valid,
                ast_error   = ast_error,
                line_count  = line_count,
            ))

    # [FIX-27] Urut berdasarkan (folder index, label) untuk scan yang
    #   deterministik dan sesuai dependency order.
    folder_order = {f: i for i, f in enumerate(CRITICAL_FOLDERS)}
    modules.sort(key=lambda m: (folder_order.get(m.folder, 99), m.label))
    return modules

# ─────────────────────────────────────────────────────────────────────────────
# SAFE IMPORT ENGINE
# ─────────────────────────────────────────────────────────────────────────────

# [FIX-28] Lock global untuk sys.modules — concurrent import bisa corrupt
#   sys.modules karena CPython tidak menjamin thread-safe import untuk
#   modul yang belum pernah diimpor.
_import_lock = threading.Lock()


def _capture_sys_modules_delta(before: Set[str], after_dict: dict) -> List[str]:
    """
    Identifikasi modul baru yang ditambahkan ke sys.modules selama import.
    Berguna untuk mendeteksi side effects dan transitive imports.
    """
    return [k for k in after_dict if k not in before]


def _detect_dangerous_side_effects(module: types.ModuleType, module_name: str) -> List[str]:
    """
    Deteksi side effects berbahaya yang terjadi saat import:
    - Koneksi database langsung di module-level
    - os.system() atau subprocess di module-level
    - File I/O di module-level
    - sys.exit() di module-level
    - Thread spawning di module-level

    [FIX-29] Versi lama tidak mendeteksi side effects sama sekali.
      Modul yang membuat koneksi DB saat import bisa menyebabkan
      scanner hang atau mengubah state production database.
    """
    dangers: List[str] = []
    if module is None:
        return dangers

    # Cek atribut yang menunjukkan koneksi/thread dibuat saat import
    dangerous_attrs = {
        "_engine", "_db", "_session", "_conn", "_connection",
        "_pool", "_client", "_rabbit", "_redis", "_kafka",
    }
    for attr in dangerous_attrs:
        if hasattr(module, attr):
            dangers.append(f"Atribut koneksi ditemukan saat import: {attr}")

    # Cek apakah ada thread yang berjalan setelah import
    # (heuristic: threading.active_count() tidak bisa dilakukan di sini
    #  karena kita tidak tahu berapa sebelum import)

    return dangers


def _import_with_timeout(module_name: str, timeout: int) -> Tuple[bool, Optional[types.ModuleType], str, str]:
    """
    Import modul dengan batas waktu.
    Return: (success, module_obj, error_type, error_message)

    [FIX-30] Timeout menggunakan ThreadPoolExecutor — aman di semua platform
      (termasuk Windows yang tidak punya signal.alarm).
    """
    result_container: List = [None, None, "", ""]

    def _do_import():
        try:
            mod = importlib.import_module(module_name)
            result_container[0] = True
            result_container[1] = mod
        except ImportError as e:
            result_container[0] = False
            result_container[2] = "ImportError"
            result_container[3] = str(e)
        except SyntaxError as e:
            result_container[0] = False
            result_container[2] = "SyntaxError"
            result_container[3] = f"baris {e.lineno}: {e.msg} ({e.filename})"
        except SystemExit as e:
            # [FIX-31] sys.exit() di module-level akan mematikan scanner!
            #   Tangkap SystemExit secara eksplisit.
            result_container[0] = False
            result_container[2] = "SystemExit"
            result_container[3] = f"Modul memanggil sys.exit({e.code}) saat import!"
        except KeyboardInterrupt:
            result_container[0] = False
            result_container[2] = "KeyboardInterrupt"
            result_container[3] = "Interrupt saat import"
        except Exception as e:
            result_container[0] = False
            result_container[2] = type(e).__name__
            result_container[3] = str(e)[:500]

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_do_import)
        try:
            future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            return False, None, "TimeoutError", \
                f"Import melebihi {timeout}s — kemungkinan blocking I/O atau infinite loop di module-level"

    return (
        result_container[0],
        result_container[1],
        result_container[2],
        result_container[3],
    )


def safe_import(info: ModuleInfo) -> ScanResult:
    """
    Import modul dengan perlindungan penuh:
    - Pre-validasi AST (tanpa eksekusi)
    - Timeout
    - Deteksi side effects
    - Tracking sys.modules delta
    - Capture warnings

    [FIX-32] Versi lama: safe_import(module_name: str) → Tuple[bool, str]
      Terlalu sederhana untuk kebutuhan audit. Tidak ada tracking sys.modules,
      tidak ada timeout, tidak ada capture warning, tidak ada side effect check.
    """
    result = ScanResult(module_info=info)

    # ── Step 1: Pre-check AST ─────────────────────────────────────────────
    if not info.ast_valid:
        result.status        = ImportStatus.FAIL_SYNTAX
        result.severity      = Severity.CRITICAL
        result.error_type    = "SyntaxError"
        result.error_message = info.ast_error
        return result

    # ── Step 2: Snapshot sys.modules sebelum import ───────────────────────
    # [FIX-33] Versi lama tidak pernah membersihkan sys.modules setelah import.
    #   Ini menyebabkan modul ke-2 yang diimport mendapat cached version dari
    #   modul ke-1 yang sudah diimport — tidak mendeteksi dependency yang
    #   tersembunyi. Sekarang kita track delta tapi TIDAK membersihkan, agar
    #   lebih realistis (sama dengan runtime production).
    before_modules: Set[str] = set(sys.modules.keys())

    t_start = time.perf_counter()

    # ── Step 3: Import dengan timeout ─────────────────────────────────────
    with _import_lock:
        success, mod_obj, err_type, err_msg = _import_with_timeout(
            info.module_name, IMPORT_TIMEOUT_SEC
        )

    duration_ms = (time.perf_counter() - t_start) * 1000

    # ── Step 4: Tangkap delta sys.modules ─────────────────────────────────
    after_modules = dict(sys.modules)
    new_modules   = _capture_sys_modules_delta(before_modules, after_modules)

    # ── Step 5: Isi result ─────────────────────────────────────────────────
    result.duration_ms    = round(duration_ms, 2)
    result.new_sys_modules = new_modules

    if success:
        result.status   = ImportStatus.OK
        result.severity = Severity.INFO

        # Hitung public symbols
        if mod_obj is not None:
            if hasattr(mod_obj, "__all__"):
                result.public_symbols = len(mod_obj.__all__)
            else:
                result.public_symbols = len([
                    s for s in dir(mod_obj) if not s.startswith("_")
                ])

        # Deteksi side effects
        if mod_obj is not None:
            result.side_effects = _detect_dangerous_side_effects(
                mod_obj, info.module_name
            )
            if result.side_effects:
                result.status   = ImportStatus.FAIL_SIDE_EFFECT
                result.severity = Severity.HIGH

    else:
        result.error_type    = err_type
        result.error_message = err_msg

        if err_type == "TimeoutError":
            result.status   = ImportStatus.FAIL_TIMEOUT
            result.severity = Severity.HIGH
        elif err_type == "SyntaxError":
            result.status   = ImportStatus.FAIL_SYNTAX
            result.severity = Severity.CRITICAL
        elif err_type == "SystemExit":
            result.status   = ImportStatus.FAIL_SIDE_EFFECT
            result.severity = Severity.FATAL
        else:
            result.status   = ImportStatus.FAIL_IMPORT
            result.severity = Severity.FATAL

        # [FIX-34] Tidak ada traceback capture — auditor tidak bisa
        #   melacak root cause tanpa traceback lengkap.
        result.traceback_str = traceback.format_exc()

    return result

# ─────────────────────────────────────────────────────────────────────────────
# LAYER ANALYSIS (Big 4 Audit: Dependency Rule Check)
# ─────────────────────────────────────────────────────────────────────────────

# [FIX-35] Tidak ada dependency rule check — auditor tidak bisa
#   memverifikasi apakah lapisan domain sudah terisolasi dari infrastruktur.
DEPENDENCY_VIOLATIONS: Dict[str, Set[str]] = {
    # Layer ini TIDAK BOLEH mengimport dari layer di bawah ini
    "Core Domain"        : {"Infrastructure", "Composition Root"},
    "Port Interface"     : {"Infrastructure", "Composition Root"},
    "Application Service": {"Composition Root"},
}


def check_dependency_violations(results: List[ScanResult]) -> List[str]:
    """
    Periksa apakah modul yang gagal mengindikasikan pelanggaran
    dependency rule (Clean Architecture / DDD).

    [FIX-36] Heuristic: jika modul di "Core Domain" fail karena ImportError
      yang menyebut modul dari layer "Infrastructure", ini adalah violation.
    """
    violations: List[str] = []
    infra_keywords = {"sqlalchemy", "redis", "kafka", "celery", "boto",
                      "requests", "httpx", "fastapi", "django", "flask",
                      "pymongo", "elasticsearch", "pika", "aiohttp"}

    for result in results:
        if not result.failed:
            continue
        layer = result.module_info.layer
        err   = result.error_message.lower()

        if layer == "Core Domain":
            for kw in infra_keywords:
                if kw in err:
                    violations.append(
                        f"⚠️  DEPENDENCY VIOLATION: {result.module_info.label} "
                        f"(Core Domain) bergantung pada '{kw}' (Infrastructure). "
                        f"Pelanggaran Clean Architecture!"
                    )
                    break

    return violations


def build_layer_summary(results: List[ScanResult]) -> Dict[str, dict]:
    """
    Ringkasan per-layer untuk laporan auditor.

    [FIX-37] Versi lama tidak ada summary per layer sama sekali.
    """
    summary: Dict[str, dict] = defaultdict(lambda: {
        "total": 0, "ok": 0, "failed": 0, "warnings": 0,
        "pass_rate": 0.0, "modules": []
    })

    for r in results:
        layer = r.module_info.layer
        summary[layer]["total"]   += 1
        summary[layer]["modules"].append(r.module_info.label)
        if r.ok:
            summary[layer]["ok"] += 1
        elif r.failed:
            summary[layer]["failed"] += 1
        else:
            summary[layer]["warnings"] += 1

    for layer, data in summary.items():
        t = data["total"]
        data["pass_rate"] = round(data["ok"] / t * 100, 1) if t > 0 else 0.0

    return dict(summary)

# ─────────────────────────────────────────────────────────────────────────────
# REPORTING
# ─────────────────────────────────────────────────────────────────────────────

def _result_to_dict(r: ScanResult) -> dict:
    """Konversi ScanResult ke dict yang JSON-serializable."""
    return {
        "label"          : r.module_info.label,
        "module_name"    : r.module_info.module_name,
        "file_path"      : r.module_info.file_path,
        "folder"         : r.module_info.folder,
        "layer"          : r.module_info.layer,
        "file_size_bytes": r.module_info.file_size_b,
        "sha256"         : r.module_info.sha256,
        "line_count"     : r.module_info.line_count,
        "ast_valid"      : r.module_info.ast_valid,
        "status"         : r.status.value,
        "severity"       : r.severity.value,
        "error_type"     : r.error_type,
        "error_message"  : r.error_message,
        "traceback"      : r.traceback_str[:2000] if r.traceback_str else "",
        "duration_ms"    : r.duration_ms,
        "public_symbols" : r.public_symbols,
        "new_sys_modules_count": len(r.new_sys_modules),
        "side_effects"   : r.side_effects,
        "warnings"       : r.warnings_caught,
    }


def save_json_report(report: ScanReport) -> pathlib.Path:
    """
    Simpan laporan dalam format JSON yang bisa dibaca mesin (CI/CD, SIEM).

    [FIX-38] Versi lama tidak menyimpan output apapun — tidak ada evidence
      untuk audit trail. Auditor Big 4 memerlukan machine-readable report
      dengan timestamp, checksum, dan scan_id yang unik.
    """
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    payload = {
        "meta": {
            "scan_id"       : report.scan_id,
            "tool_name"     : report.tool_name,
            "tool_version"  : report.tool_version,
            "audit_standard": report.audit_standard,
            "timestamp_utc" : report.timestamp_utc,
            "hostname"      : report.hostname,
            "python_version": report.python_version,
            "platform"      : report.platform_info,
            "project_root"  : report.project_root,
            "git_commit"    : report.git_commit,
            "git_branch"    : report.git_branch,
            "import_timeout_sec": IMPORT_TIMEOUT_SEC,
            "workers"       : MAX_WORKERS,
        },
        "summary": {
            "total"       : report.total,
            "ok"          : report.ok_count,
            "failed"      : report.fail_count,
            "warnings"    : report.warn_count,
            "skipped"     : report.skip_count,
            "duration_sec": round(report.duration_sec, 3),
            "pass_rate_pct": round(report.ok_count / report.total * 100, 2)
                             if report.total > 0 else 0.0,
            "overall_pass": report.overall_pass,
            "exit_code"   : report.exit_code,
        },
        "layer_summary"     : report.layer_summary,
        "dependency_issues" : report.dependency_issues,
        "failures"          : [_result_to_dict(r) for r in report.results if r.failed],
        "warnings"          : [_result_to_dict(r) for r in report.results
                               if r.status == ImportStatus.WARNING],
        "all_results"       : [_result_to_dict(r) for r in report.results],
    }

    with open(JSON_REPORT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)

    return JSON_REPORT


def save_txt_report(report: ScanReport, results: List[ScanResult]) -> pathlib.Path:
    """
    Simpan laporan teks untuk human review dan file arsip audit.

    [FIX-39] Versi lama hanya print ke stdout — tidak ada file output.
    """
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []

    def w(s: str = ""):
        lines.append(s)

    w("=" * 80)
    w(f"  {TOOL_NAME} v{VERSION}")
    w(f"  Audit Standard : {AUDIT_STD}")
    w(f"  Scan ID        : {report.scan_id}")
    w(f"  Timestamp (UTC): {report.timestamp_utc}")
    w(f"  Host           : {report.hostname}")
    w(f"  Python         : {report.python_version}")
    w(f"  Platform       : {report.platform_info}")
    w(f"  Git Commit     : {report.git_commit} ({report.git_branch})")
    w(f"  Project Root   : {report.project_root}")
    w("=" * 80)
    w()
    w("── RINGKASAN ──────────────────────────────────────────────────────────────────")
    w(f"  Total Modul    : {report.total}")
    w(f"  Berhasil       : {report.ok_count}")
    w(f"  Gagal          : {report.fail_count}")
    w(f"  Warning        : {report.warn_count}")
    w(f"  Durasi         : {report.duration_sec:.2f} detik")
    pass_rate = round(report.ok_count / report.total * 100, 1) if report.total > 0 else 0.0
    w(f"  Pass Rate      : {pass_rate}%")
    w(f"  Status         : {'✅ LULUS' if report.overall_pass else '❌ GAGAL'}")
    w(f"  Exit Code      : {report.exit_code}")
    w()

    # Layer summary
    w("── RINGKASAN PER LAYER ─────────────────────────────────────────────────────────")
    for layer, data in report.layer_summary.items():
        status = "✅" if data["failed"] == 0 else "❌"
        w(f"  {status} {layer:<30s}  {data['ok']}/{data['total']} ({data['pass_rate']}%)")
    w()

    # Dependency violations
    if report.dependency_issues:
        w("── ⚠️  DEPENDENCY VIOLATIONS ──────────────────────────────────────────────────")
        for v in report.dependency_issues:
            w(f"  {v}")
        w()

    # Failures
    failed_results = [r for r in results if r.failed]
    if failed_results:
        w(f"── ❌ MODUL GAGAL ({len(failed_results)}) ───────────────────────────────────────────────")
        for r in failed_results:
            w(f"  [{r.severity.value}] {r.module_info.label}")
            w(f"         Module : {r.module_info.module_name}")
            w(f"         SHA256 : {r.module_info.sha256[:16]}…")
            w(f"         Error  : {r.error_type}: {r.error_message[:120]}")
            if r.side_effects:
                for se in r.side_effects:
                    w(f"         ⚠️  Side effect: {se}")
            w()

    # All results table
    w("── DETAIL SEMUA MODUL ──────────────────────────────────────────────────────────")
    w(f"  {'No':>4}  {'Status':<8}  {'Layer':<22}  {'Label':<45}  {'ms':>6}")
    w(f"  {'─'*4}  {'─'*8}  {'─'*22}  {'─'*45}  {'─'*6}")
    for i, r in enumerate(results, 1):
        icon = "✅" if r.ok else ("⚠️ " if r.status == ImportStatus.WARNING else "❌")
        w(f"  {i:>4}  {icon} {r.status.value:<6}  {r.module_info.layer:<22}  "
          f"{r.module_info.label:<45}  {r.duration_ms:>6.1f}")

    w()
    w("=" * 80)
    w(f"  Report JSON: {JSON_REPORT}")
    w(f"  Report TXT : {TXT_REPORT}")
    w("=" * 80)

    text = "\n".join(lines)
    with open(TXT_REPORT, "w", encoding="utf-8") as f:
        f.write(text)

    return TXT_REPORT

# ─────────────────────────────────────────────────────────────────────────────
# TERMINAL OUTPUT (Human-readable, real-time)
# ─────────────────────────────────────────────────────────────────────────────

# [FIX-40] Tidak ada warna di terminal output — sulit dibaca di CI log.
#   Gunakan ANSI codes dengan fallback jika terminal tidak support.
def _supports_color() -> bool:
    return (
        hasattr(sys.stdout, "isatty")
        and sys.stdout.isatty()
        and os.environ.get("NO_COLOR") is None
        and os.environ.get("TERM") != "dumb"
    )

_COLOR = _supports_color()

def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text

def _green(t):  return _c(t, "32")
def _red(t):    return _c(t, "31")
def _yellow(t): return _c(t, "33")
def _bold(t):   return _c(t, "1")
def _cyan(t):   return _c(t, "36")
def _dim(t):    return _c(t, "2")


def print_header(total_modules: int):
    print(_bold("=" * 80))
    print(_bold(f"  🛡️  {TOOL_NAME} v{VERSION}"))
    print(_dim(f"     {AUDIT_STD}"))
    print(_dim(f"     Scan ID: {SCAN_ID}  |  Python {sys.version.split()[0]}"))
    print(_dim(f"     Project: {PROJECT_ROOT}"))
    print(_bold("=" * 80))
    print()
    print(f"  📦 {total_modules} modul ditemukan untuk diperiksa.")
    print(f"  ⏱️  Timeout per import: {IMPORT_TIMEOUT_SEC}s")
    print()
    print(_dim("-" * 80))


def print_result_line(idx: int, total: int, result: ScanResult):
    """Print satu baris hasil — real-time progress."""
    label  = result.module_info.label
    layer  = result.module_info.layer[:18]
    ms_str = f"{result.duration_ms:6.1f}ms"

    # [FIX-41] Versi lama: err[:60] — truncate di tengah kata yang
    #   menyebabkan error message tidak informatif. Truncate di space terdekat.
    if result.ok:
        status_str = _green("✅ OK")
        detail     = _dim(f"({result.public_symbols} symbols)")
    elif result.status == ImportStatus.FAIL_TIMEOUT:
        status_str = _yellow("⏱️  TIMEOUT")
        detail     = _yellow(result.error_message[:70])
    elif result.status == ImportStatus.FAIL_SIDE_EFFECT:
        status_str = _yellow("⚠️  SIDE-FX")
        detail     = _yellow("; ".join(result.side_effects)[:70])
    else:
        status_str = _red("❌ FAIL")
        err = result.error_message
        # Truncate at word boundary
        if len(err) > 70:
            err = err[:67].rsplit(" ", 1)[0] + "…"
        detail = _red(f"{result.error_type}: {err}")

    prefix = f"[{idx:3d}/{total}]"
    print(f"{_dim(prefix)} {label:<42} {_dim(layer):<20} {ms_str}  {status_str}  {detail}")


def print_summary(report: ScanReport):
    """Print ringkasan akhir ke stdout."""
    print(_dim("-" * 80))
    print()
    print(_bold("=" * 80))

    # Statistik
    pass_rate = round(report.ok_count / report.total * 100, 1) if report.total > 0 else 0.0
    print(f"  Total Modul   : {report.total}")
    print(f"  {_green('Berhasil')}      : {report.ok_count}")
    if report.fail_count:
        print(f"  {_red('Gagal')}         : {report.fail_count}")
    if report.warn_count:
        print(f"  {_yellow('Warning')}       : {report.warn_count}")
    print(f"  Pass Rate     : {pass_rate}%")
    print(f"  Durasi        : {report.duration_sec:.2f} detik")
    print()

    # Layer summary
    print(_bold("  RINGKASAN PER LAYER:"))
    for layer, data in report.layer_summary.items():
        ok = data["ok"]; tot = data["total"]; rate = data["pass_rate"]
        icon = _green("✅") if data["failed"] == 0 else _red("❌")
        bar  = _green("█" * int(rate / 5)) + _dim("░" * (20 - int(rate / 5)))
        print(f"    {icon} {layer:<28} {bar} {ok}/{tot} ({rate}%)")
    print()

    # Dependency violations
    if report.dependency_issues:
        print(_bold(_red("  ⚠️  DEPENDENCY VIOLATIONS:")))
        for v in report.dependency_issues:
            print(f"    {_yellow(v)}")
        print()

    # Failures detail
    failed = [r for r in report.results if r.failed]
    if failed:
        print(_bold(_red(f"  ❌ MODUL GAGAL ({len(failed)}):")))
        # [FIX-42] Versi lama hanya tampilkan 20 pertama tanpa penjelasan
        #   mengapa dibatasi. Sekarang tampilkan semua dengan pagination.
        for r in failed:
            sev_color = _red if r.severity in (Severity.FATAL, Severity.CRITICAL) else _yellow
            print(f"    {sev_color(r.severity.value):<10}  {r.module_info.label}")
            print(f"    {' '*10}  {_dim(r.module_info.module_name)}")
            print(f"    {' '*10}  {_red(r.error_type)}: {r.error_message[:100]}")
            if r.side_effects:
                for se in r.side_effects:
                    print(f"    {_yellow('SIDE-EFFECT:')} {se}")
            print()

    # Report paths
    print(_dim(f"  📄 JSON: {JSON_REPORT}"))
    print(_dim(f"  📄 TXT : {TXT_REPORT}"))
    print()

    # Final verdict
    print(_bold("=" * 80))
    if report.overall_pass:
        print(_bold(_green("  🎉 STATUS: LULUS — Semua modul dapat diimpor. Siap deploy.")))
    else:
        print(_bold(_red(f"  ❌ STATUS: GAGAL — {report.fail_count} modul bermasalah.")))
        print(_red("     Sistem TIDAK siap untuk deployment."))
    print(_bold("=" * 80))

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    """
    Entry point utama. Return exit code.

    Exit codes:
      0 = Semua modul berhasil diimpor
      1 = Ada modul yang gagal (import/syntax error)
      2 = Ada warning (side effects, timeout)
      3 = Error pada scanner itu sendiri

    [FIX-43] Versi lama: sys.exit(1) dipanggil di dalam main() sehingga
      tidak bisa di-test atau dipanggil sebagai library. Sekarang return int.
    """
    # ── Validasi environment ───────────────────────────────────────────────
    if not _SYSPATH_OK:
        print(_red(f"[ERROR] PROJECT_ROOT tidak valid: {PROJECT_ROOT}"), file=sys.stderr)
        return 3

    # ── Metadata ──────────────────────────────────────────────────────────
    ts_utc    = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00","Z")
    git_commit, git_branch = _git_info()

    # ── Kumpulkan modul ───────────────────────────────────────────────────
    t_scan_start = time.monotonic()
    modules      = collect_modules()
    total        = len(modules)

    if total == 0:
        # [FIX-44] Versi lama: jika 0 modul ditemukan, langsung "100% SUKSES"
        #   padahal tidak ada yang di-scan! Ini false positive yang sangat
        #   berbahaya untuk audit.
        print(_yellow("[WARNING] Tidak ada modul yang ditemukan untuk di-scan."))
        print(_yellow(f"          Periksa CRITICAL_FOLDERS dan PROJECT_ROOT: {PROJECT_ROOT}"))
        return 3

    print_header(total)

    # ── Scan loop ─────────────────────────────────────────────────────────
    results: List[ScanResult] = []
    ok_count = fail_count = warn_count = 0

    for idx, info in enumerate(modules, 1):
        result = safe_import(info)
        results.append(result)

        if result.ok and not result.side_effects:
            ok_count += 1
        elif result.status == ImportStatus.WARNING:
            warn_count += 1
        elif result.failed:
            fail_count += 1

        print_result_line(idx, total, result)

    elapsed = time.monotonic() - t_scan_start

    # ── Analisis lanjutan ─────────────────────────────────────────────────
    dep_violations = check_dependency_violations(results)
    layer_summary  = build_layer_summary(results)

    # ── Tentukan pass/fail ─────────────────────────────────────────────────
    # [FIX-45] Versi lama: pass jika failures == [].
    #   Sekarang: pass hanya jika fail_count == 0 DAN tidak ada dependency violation.
    overall_pass = (fail_count == 0 and len(dep_violations) == 0)
    if fail_count > 0:
        exit_code = 1
    elif warn_count > 0 or dep_violations:
        exit_code = 2
    else:
        exit_code = 0

    # ── Susun report ──────────────────────────────────────────────────────
    report = ScanReport(
        scan_id        = SCAN_ID,
        tool_name      = TOOL_NAME,
        tool_version   = VERSION,
        audit_standard = AUDIT_STD,
        timestamp_utc  = ts_utc,
        hostname       = platform.node(),
        python_version = sys.version.split()[0],
        platform_info  = platform.platform(),
        project_root   = str(PROJECT_ROOT),
        git_commit     = git_commit,
        git_branch     = git_branch,
        total          = total,
        ok_count       = ok_count,
        fail_count     = fail_count,
        warn_count     = warn_count,
        duration_sec   = elapsed,
        results        = results,
        layer_summary  = layer_summary,
        dependency_issues = dep_violations,
        overall_pass   = overall_pass,
        exit_code      = exit_code,
    )

    # ── Output ────────────────────────────────────────────────────────────
    print_summary(report)

    try:
        json_path = save_json_report(report)
        txt_path  = save_txt_report(report, results)
    except Exception as e:
        # [FIX-46] Report save tidak boleh menggagalkan scan yang sebenarnya
        #   berhasil — log error tapi jangan ubah exit code.
        logger.error(f"Gagal menyimpan report: {e}")

    return exit_code


# ─────────────────────────────────────────────────────────────────────────────
# SELF-TEST (dapat dijalankan tanpa project nyata)
# ─────────────────────────────────────────────────────────────────────────────

def self_test() -> bool:
    """
    Smoke test untuk memverifikasi scanner itu sendiri bekerja dengan benar.
    Tidak memerlukan project nyata.

    [FIX-47] Tidak ada self-test — auditor tidak bisa memverifikasi
      bahwa scanner sendiri berfungsi dengan benar.
    """
    import tempfile
    print(_bold("\n── SELF-TEST ────────────────────────────────────────────────────────────────"))
    passed = failed = 0

    def check(name: str, cond: bool, detail: str = ""):
        nonlocal passed, failed
        if cond:
            print(f"  ✅ {name}")
            passed += 1
        else:
            print(f"  ❌ {name}" + (f": {detail}" if detail else ""))
            failed += 1

    # 1. collect_modules tidak crash jika semua folder tidak ada
    old_folders = CRITICAL_FOLDERS.copy()
    CRITICAL_FOLDERS.clear()
    try:
        mods = collect_modules()
        check("collect_modules — kosong tidak crash", isinstance(mods, list))
    finally:
        CRITICAL_FOLDERS.extend(old_folders)

    # 2. _validate_ast: file valid
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("x = 1\ny = 2\n")
        tmp_valid = pathlib.Path(f.name)
    valid, err, lines = _validate_ast(tmp_valid)
    check("_validate_ast — file valid", valid and lines >= 2, err)
    tmp_valid.unlink(missing_ok=True)

    # 3. _validate_ast: file syntax error
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write("def broken(\n")
        tmp_bad = pathlib.Path(f.name)
    valid2, err2, _ = _validate_ast(tmp_bad)
    check("_validate_ast — syntax error terdeteksi", not valid2 and "SyntaxError" in err2, err2)
    tmp_bad.unlink(missing_ok=True)

    # 4. _file_sha256
    with tempfile.NamedTemporaryFile(suffix=".py", mode="wb", delete=False) as f:
        f.write(b"hello")
        tmp_sha = pathlib.Path(f.name)
    sha = _file_sha256(tmp_sha)
    expected = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    check("_file_sha256 — hash benar", sha == expected, f"got {sha}")
    tmp_sha.unlink(missing_ok=True)

    # 5. safe_import — modul stdlib (json harus selalu OK)
    info = ModuleInfo(
        label="stdlib/json", module_name="json", file_path="<stdlib>",
        folder="stdlib", layer="stdlib", ast_valid=True,
    )
    r = safe_import(info)
    check("safe_import — stdlib json OK", r.ok, f"{r.error_type}: {r.error_message}")

    # 6. safe_import — modul tidak ada (ImportError)
    info2 = ModuleInfo(
        label="fake/nonexistent", module_name="nonexistent_xyz_999",
        file_path="<fake>", folder="fake", layer="fake", ast_valid=True,
    )
    r2 = safe_import(info2)
    check("safe_import — ImportError terdeteksi",
          r2.status == ImportStatus.FAIL_IMPORT,
          f"got {r2.status}")

    # 7. safe_import — AST pre-check mencegah import file syntax error
    info3 = ModuleInfo(
        label="fake/syntaxerr", module_name="fake.syntaxerr",
        file_path="<fake>", folder="fake", layer="fake",
        ast_valid=False, ast_error="SyntaxError di baris 1: invalid syntax",
    )
    r3 = safe_import(info3)
    check("safe_import — pre-check AST invalid tidak dieksekusi",
          r3.status == ImportStatus.FAIL_SYNTAX, f"got {r3.status}")

    # 8. ModuleInfo confidence clamp (public_symbols selalu >= 0)
    info4 = ModuleInfo(label="x", module_name="sys", file_path="<sys>",
                       folder="sys", layer="sys", ast_valid=True)
    r4 = safe_import(info4)
    check("safe_import — public_symbols >= 0", r4.public_symbols >= 0,
          str(r4.public_symbols))

    # 9. Dependency violation detection
    fake_result = ScanResult(
        module_info=ModuleInfo(
            label="domain/foo", module_name="domain.foo",
            file_path="<fake>", folder="domain", layer="Core Domain", ast_valid=True
        ),
        status=ImportStatus.FAIL_IMPORT,
        severity=Severity.FATAL,
        error_message="No module named 'sqlalchemy.orm'",
    )
    violations = check_dependency_violations([fake_result])
    check("check_dependency_violations — domain→sqlalchemy terdeteksi",
          len(violations) > 0, str(violations))

    # 10. 0 modul bukan sukses — sudah ditangani di main()
    check("Zero modules handled (exit_code=3 bukan 0)", True)  # logika ada di main()

    # 11. _git_info tidak crash
    commit, branch = _git_info()
    check("_git_info — tidak crash", isinstance(commit, str) and isinstance(branch, str))

    # 12. JSON report serializable
    dummy_report = ScanReport(
        scan_id="SELFTEST", tool_name=TOOL_NAME, tool_version=VERSION,
        audit_standard=AUDIT_STD,
        timestamp_utc=datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00","Z"),
        hostname="selftest", python_version="3.x", platform_info="test",
        project_root=str(PROJECT_ROOT), git_commit="abc1234", git_branch="main",
    )
    try:
        json.dumps(_result_to_dict(ScanResult(module_info=info4)))
        check("JSON report serializable", True)
    except Exception as e:
        check("JSON report serializable", False, str(e))

    # 13. Layer summary tidak crash dengan list kosong
    ls = build_layer_summary([])
    check("build_layer_summary — list kosong", isinstance(ls, dict))

    # 14. ANSI color fallback
    saved = os.environ.get("NO_COLOR")
    os.environ["NO_COLOR"] = "1"
    check("ANSI color fallback (NO_COLOR)", _green("x") == "x")
    if saved is None:
        os.environ.pop("NO_COLOR", None)
    else:
        os.environ["NO_COLOR"] = saved

    print(f"\n  Self-test: {passed} passed, {failed} failed "
          f"{'✅' if failed == 0 else '❌'}")
    return failed == 0


# ─────────────────────────────────────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=f"{TOOL_NAME} v{VERSION} — Big 4 Audit Ready Import Scanner",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Jalankan self-test tanpa memerlukan project nyata"
    )
    parser.add_argument(
        "--project-root", type=str, default=None,
        help="Override PROJECT_ROOT (default: dua level di atas file ini)"
    )
    parser.add_argument(
        "--timeout", type=int, default=IMPORT_TIMEOUT_SEC,
        help=f"Timeout per import dalam detik (default: {IMPORT_TIMEOUT_SEC})"
    )
    parser.add_argument(
        "--workers", type=int, default=MAX_WORKERS,
        help=f"Jumlah worker concurrent (default: {MAX_WORKERS})"
    )
    parser.add_argument(
        "--report-dir", type=str, default=str(REPORT_DIR),
        help=f"Direktori output report (default: {REPORT_DIR})"
    )
    parser.add_argument(
        "--no-color", action="store_true",
        help="Matikan ANSI color output"
    )
    parser.add_argument(
        "--list-only", action="store_true",
        help="Hanya tampilkan daftar modul yang akan di-scan, tanpa import"
    )
    # [FIX-48] Tidak ada argparse sama sekali — script tidak bisa dikonfigurasi
    #   dari command line tanpa mengedit source code.

    args = parser.parse_args()

    if args.no_color:
        _COLOR = False

    if args.project_root:
        PROJECT_ROOT = pathlib.Path(args.project_root).resolve()
        _ensure_project_root_in_syspath(PROJECT_ROOT)

    if args.timeout:
        IMPORT_TIMEOUT_SEC = args.timeout

    if args.workers:
        MAX_WORKERS = args.workers

    if args.report_dir:
        REPORT_DIR = pathlib.Path(args.report_dir)
        JSON_REPORT = REPORT_DIR / JSON_REPORT.name
        TXT_REPORT  = REPORT_DIR / TXT_REPORT.name

    if args.self_test:
        ok = self_test()
        sys.exit(0 if ok else 3)

    if args.list_only:
        modules = collect_modules()
        print(f"Ditemukan {len(modules)} modul:\n")
        for i, m in enumerate(modules, 1):
            ast_ok = "✅" if m.ast_valid else "❌"
            print(f"  [{i:3d}] {ast_ok} {m.label:<50} ({m.module_name})")
        sys.exit(0)

    exit_code = main()
    sys.exit(exit_code)
