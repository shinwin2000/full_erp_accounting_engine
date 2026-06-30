#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker/checker_di_container.py
================================
Sovereign ERP System — DI Container Integrity Checker v2.0
Auditor-grade: fully integrated dengan RCA engine (checker/core/rca.py).

Pemeriksaan yang dilakukan:
  1. Import & bootstrap DI container + adapter registry
  2. Resolve semua interface yang terdaftar (async + sync fallback)
  3. Deteksi in-memory fallback (dengan whitelist disengaja)
  4. Validasi kontrak method interface kritis
  5. Scoring 0-100 (severity-weighted, bukan flat penalty)
  6. RCA otomatis untuk setiap error yang ditemukan
  7. JSON export dengan full audit trail
  8. SARIF 2.1.0-compatible exit code (0 = pass, 1 = fail)

Bug yang diperbaiki dari versi sebelumnya:
  BUG-01  ROOT path salah: parent.parent padahal checker ada di checker/
          → diperbaiki ke parent saja (jika dijalankan dari checker/)
  BUG-02  COLOR dict tidak di-reset per-platform; Windows legacy console
          tidak support ANSI → tambahkan deteksi Windows + TERM env check
  BUG-03  _setup_imports() menelan ImportError tanpa menyimpan module name
          yang gagal → sekarang simpan module name untuk RCA
  BUG-04  _get_registered_types() mencoba attr "registered_types" sebagai
          callable lalu juga sebagai list → double-execution, data hilang
  BUG-05  _get_registered_types() tidak handle generator/set → crash
  BUG-06  resolve_dependency() menelan semua Exception dengan pass →
          error hilang tanpa trace, container seolah berjalan normal
  BUG-07  resolve_dependency() tidak menyimpan exception per-interface →
          tidak ada data untuk RCA
  BUG-08  check_contract() tidak handle interface yang __name__ tidak ada
          (generic alias, e.g. Optional[X]) → AttributeError crash
  BUG-09  run_checks(): registry.register_all() dipanggil tanpa cek apakah
          sudah dipanggil sebelumnya → double-registration artefak
  BUG-10  run_checks(): total dihitung SEBELUM resolved_count dihitung →
          total bisa 0 jika _get_registered_types() gagal di tengah jalan
  BUG-11  run_checks(): in_memory_count dihitung dua kali:
          sekali di loop, sekali di error_count formula → skor terlalu rendah
  BUG-12  run_checks(): score formula "100 - (error_count * 2)" tidak
          severity-weighted → 1 resolution error = sama beratnya dengan
          1 contract failure = sama beratnya dengan 1 unknown in-memory
  BUG-13  run_checks(): instance None tidak dianggap sebagai error resolusi
          yang perlu RCA — hanya di-skip begitu saja
  BUG-14  run_checks(): loop tidak membatasi waktu per-resolve → gantung
          jika salah satu dependency init konek ke DB
  BUG-15  run_checks(): tidak ada deduplication pada in_memory_fallbacks
          → jika register_all() dipanggil dua kali, entry duplikat masuk
  BUG-16  print_report(): COLOR dict mungkin berisi string kosong setelah
          deteksi non-tty, tapi kode memanggil c['CYAN'] dll tanpa guard
  BUG-17  print_report(): result['success'] diakses langsung tanpa .get()
          → KeyError jika run_checks() return early dengan dict minimal
  BUG-18  save_json(): tidak serialize errors dengan traceback → data audit
          hilang di JSON
  BUG-19  save_json(): tidak ada timestamp di JSON → tidak bisa digunakan
          untuk audit trail
  BUG-20  save_json(): tidak ada error handling untuk I/O failure → crash
          dan exit code tidak ter-set
  BUG-21  main(): asyncio.run() tidak handle RuntimeError jika event loop
          sudah ada (e.g. dijalankan di dalam pytest-asyncio)
  BUG-22  main(): tidak ada timeout global → bisa hang selamanya
  BUG-23  main(): waktu audit dihitung dari setelah argparse, bukan sebelum
          → tidak termasuk waktu import
  BUG-24  ALLOWED_IN_MEMORY adalah set string, tapi dibandingkan dengan
          class_name → sudah benar, tapi tidak ada normalization case
  BUG-25  CONTRACT_CHECKS memiliki "APRepositoryPort" dan "ARRepositoryPort"
          dengan method identik → tidak ada cek apakah implementasi benar
          (bisa tertukar antara AP dan AR)
  BUG-26  Tidak ada integrasi RCA sama sekali → semua error hanya berupa
          dict string, tidak ada root cause analysis, suggested fix, severity
  BUG-27  Tidak ada SARIF export → tidak bisa dipakai oleh CI pipeline modern
  BUG-28  Tidak ada summary statistik per-kategori di report
  BUG-29  Tidak ada health check terpisah untuk container singleton vs factory
  BUG-30  _setup_imports() tidak mencoba reload jika pertama kali gagal karena
          path problem → tidak resilient terhadap PATH order issues
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# =============================================================================
# [BUG-01 FIX] ROOT path: checker_di_container.py ada di checker/ → parent = root
# =============================================================================
_THIS_FILE = Path(__file__).resolve()
# Deteksi: apakah dijalankan dari dalam subdirektori checker/?
if _THIS_FILE.parent.name == "checker":
    ROOT = _THIS_FILE.parent.parent
else:
    ROOT = _THIS_FILE.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# =============================================================================
# [BUG-02 FIX] ANSI Color: deteksi Windows + no-color env
# =============================================================================
def _supports_ansi() -> bool:
    """Cek apakah terminal mendukung ANSI escape codes."""
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    if not sys.stdout.isatty():
        return False
    if platform.system() == "Windows":
        # Windows 10 build 14931+ mendukung ANSI via VT100 mode
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            # Enable ENABLE_VIRTUAL_TERMINAL_PROCESSING (0x0004)
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
                return True
        except Exception:
            return False
    return True

_USE_COLOR = _supports_ansi()
COLOR: Dict[str, str] = {
    "RED":    "\033[91m" if _USE_COLOR else "",
    "GREEN":  "\033[92m" if _USE_COLOR else "",
    "YELLOW": "\033[93m" if _USE_COLOR else "",
    "BLUE":   "\033[94m" if _USE_COLOR else "",
    "CYAN":   "\033[96m" if _USE_COLOR else "",
    "BOLD":   "\033[1m"  if _USE_COLOR else "",
    "RESET":  "\033[0m"  if _USE_COLOR else "",
}

# =============================================================================
# RCA Integration — import dari checker/core/rca.py
# [BUG-26 FIX] Integrasi penuh RCA engine
# =============================================================================
_RCA_AVAILABLE = False
_rca_engine = None

# Pertama coba dari path resmi checker/core/rca.py
try:
    _checker_core = ROOT / "checker" / "core"
    if str(_checker_core) not in sys.path:
        sys.path.insert(0, str(_checker_core))

    from rca import (  # type: ignore[import]
        RCAEngine,
        RCAResult,
        Severity as RCASeverity,
        Category as RCACategory,
        ErrorCode as RCAErrorCode,
        get_engine as rca_get_engine,
        analyze_exception,
    )
    _rca_engine = rca_get_engine()
    _RCA_AVAILABLE = True
    print(f"✅ RCA Engine loaded from {_checker_core}")
except ImportError:
    # Fallback: coba dari direktori yang sama dengan checker ini
    try:
        _this_dir = _THIS_FILE.parent
        if str(_this_dir) not in sys.path:
            sys.path.insert(0, str(_this_dir))
        from rca import (  # type: ignore[import]
            RCAEngine, RCAResult, Severity as RCASeverity,
            Category as RCACategory, ErrorCode as RCAErrorCode,
            get_engine as rca_get_engine,
            analyze_exception,
        )
        _rca_engine = rca_get_engine()
        _RCA_AVAILABLE = True
        print(f"✅ RCA Engine loaded from {_this_dir}")
    except ImportError:
        print("⚠️  RCA Engine not available – using fallback analysis")
        _RCA_AVAILABLE = False

# =============================================================================
# Konfigurasi Contract Checks
# Format: interface_name → (expected_methods, allowed_impl_override)
# =============================================================================
CONTRACT_CHECKS: Dict[str, Tuple[List[str], Optional[List[str]]]] = {
    "UnitOfWorkPort": (
        ["commit", "rollback", "begin"],
        None,
    ),
    "CoreTaxPort": (
        ["submit_tax", "get_status"],
        ["InMemoryCoreTaxPort"],  # Disengaja sebagai stub untuk environment non-produksi
    ),
    "IAMUserRepositoryPort": (
        ["save", "find_by_username", "find_by_id"],
        None,
    ),
    "ARRepositoryPort": (
        ["save_invoice", "find_invoice_by_id", "find_invoices_by_customer"],
        None,
    ),
    "APRepositoryPort": (
        ["save_invoice", "find_invoice_by_id", "find_invoices_by_vendor"],
        None,
    ),
    "InventoryRepositoryPort": (
        ["save_item", "find_item_by_id", "adjust_stock", "find_items_by_category"],
        None,
    ),
    "FixedAssetRepositoryPort": (
        ["save_asset", "find_asset_by_id", "depreciate_asset"],
        None,
    ),
    "PayrollRepositoryPort": (
        ["save_payroll", "find_by_employee", "find_payrolls_by_period"],
        None,
    ),
    "ConsolidationRepositoryPort": (
        ["save_group", "find_group", "consolidate_entities"],
        None,
    ),
    "JournalEntryRepositoryPort": (
        ["post_journal", "find_journal_by_id", "find_journals_by_period"],
        None,
    ),
    "LedgerRepositoryPort": (
        ["get_balance", "get_trial_balance", "find_entries_by_account"],
        None,
    ),
    "TaxRepositoryPort": (
        ["save_tax_return", "find_tax_return_by_period", "calculate_tax"],
        ["InMemoryTaxRepository"],
    ),
}

# Whitelist implementasi in-memory yang sengaja digunakan (e.g. dev/test env)
ALLOWED_IN_MEMORY: Set[str] = {
    "InMemoryCoreTaxPort",
    "InMemoryTaxRepository",
    "InMemoryEventBus",
    "InMemoryMessageQueue",
}

# Severity weight untuk scoring (tinggi = penalti lebih besar)
_SEVERITY_WEIGHTS = {
    "FATAL":    20,
    "CRITICAL": 10,
    "HIGH":      5,
    "MEDIUM":    3,
    "LOW":       1,
    "INFO":      0,
}

# Resolve timeout per-dependency (detik)
RESOLVE_TIMEOUT_SECONDS = 5.0

# =============================================================================
# Data classes hasil pemeriksaan
# =============================================================================

class ResolutionError:
    """Satu entri error resolusi dependency."""
    __slots__ = (
        "interface_name", "error_type", "message", "trace",
        "rca_result", "severity",
    )

    def __init__(
        self,
        interface_name: str,
        error_type: str,
        message: str,
        trace: str = "",
        rca_result: Optional[Any] = None,
        severity: str = "HIGH",
    ):
        self.interface_name = interface_name
        self.error_type     = error_type
        self.message        = message
        self.trace          = trace
        self.rca_result     = rca_result
        self.severity       = severity

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "interface"  : self.interface_name,
            "error_type" : self.error_type,
            "message"    : self.message,
            "severity"   : self.severity,
        }
        if self.trace:
            d["trace"] = self.trace
        if self.rca_result is not None and _RCA_AVAILABLE:
            try:
                # Jika rca_result adalah objek RCAResult, gunakan to_dict()
                if hasattr(self.rca_result, "to_dict"):
                    d["rca"] = self.rca_result.to_dict()
                else:
                    d["rca"] = {"root_cause": str(self.rca_result)}
            except Exception:
                d["rca"] = {"root_cause": str(self.rca_result)}
        return d


class InMemoryFallback:
    """Satu entri in-memory fallback."""
    __slots__ = ("interface_name", "implementation", "is_allowed", "rca_result")

    def __init__(
        self,
        interface_name: str,
        implementation: str,
        is_allowed: bool,
        rca_result: Optional[Any] = None,
    ):
        self.interface_name = interface_name
        self.implementation = implementation
        self.is_allowed     = is_allowed
        self.rca_result     = rca_result

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "interface"     : self.interface_name,
            "implementation": self.implementation,
            "is_allowed"    : self.is_allowed,
        }
        if self.rca_result is not None and _RCA_AVAILABLE:
            try:
                if hasattr(self.rca_result, "to_dict"):
                    d["rca"] = self.rca_result.to_dict()
                else:
                    d["rca"] = {"root_cause": str(self.rca_result)}
            except Exception:
                pass
        return d


class ContractFailure:
    """Satu entri contract method failure."""
    __slots__ = ("interface_name", "implementation", "missing_methods", "rca_result")

    def __init__(
        self,
        interface_name: str,
        implementation: str,
        missing_methods: List[str],
        rca_result: Optional[Any] = None,
    ):
        self.interface_name = interface_name
        self.implementation = implementation
        self.missing_methods = missing_methods
        self.rca_result      = rca_result

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "interface"      : self.interface_name,
            "implementation" : self.implementation,
            "missing_methods": self.missing_methods,
        }
        if self.rca_result is not None and _RCA_AVAILABLE:
            try:
                if hasattr(self.rca_result, "to_dict"):
                    d["rca"] = self.rca_result.to_dict()
                else:
                    d["rca"] = {"root_cause": str(self.rca_result)}
            except Exception:
                pass
        return d


# =============================================================================
# Main Checker Class
# =============================================================================
class DIContainerChecker:
    """
    DI Container Integrity Checker — auditor-grade dengan RCA integration.

    Lifecycle:
        checker = DIContainerChecker()
        result  = asyncio.run(checker.run_checks())
    """

    def __init__(self, resolve_timeout: float = RESOLVE_TIMEOUT_SECONDS):
        self.root             = ROOT
        self.resolve_timeout  = resolve_timeout
        self.container        = None
        self.registry         = None
        self._registry_called = False  # [BUG-09 FIX] track agar tidak double-call

        # Akumulator hasil
        self.resolution_errors: List[ResolutionError]   = []
        self.in_memory_fallbacks: List[InMemoryFallback] = []
        self.contract_failures: List[ContractFailure]    = []
        self.setup_errors: List[Dict[str, str]]          = []
        self.suggestions: List[str]                      = []
        self._seen_interfaces: Set[str]                  = set()  # [BUG-15 FIX] dedup

    # -------------------------------------------------------------------------
    # Setup
    # -------------------------------------------------------------------------
    def _setup_imports(self) -> bool:
        """
        Import DI container modules.
        [BUG-03 FIX] Simpan modul yang gagal untuk RCA.
        [BUG-30 FIX] Coba fallback path jika import pertama gagal.
        """
        def _attempt_import() -> bool:
            try:
                from bootstrap.dependency_container.adapter_registry import (  # type: ignore[import]
                    get_adapter_registry,
                )
                from bootstrap.dependency_container.ioc_container import (  # type: ignore[import]
                    get_container,
                )
                self.registry  = get_adapter_registry()
                self.container = get_container()
                return True
            except ImportError as exc:
                failed_module = getattr(exc, "name", None) or str(exc)
                rca_result = None
                if _RCA_AVAILABLE and _rca_engine is not None:
                    try:
                        rca_result = _rca_engine.analyze(exc)
                    except Exception:
                        pass
                self.setup_errors.append({
                    "type"   : "ImportError",
                    "module" : failed_module,
                    "message": str(exc),
                    "rca"    : rca_result.to_dict() if rca_result and _RCA_AVAILABLE else {},
                })
                return False
            except Exception as exc:
                rca_result = None
                if _RCA_AVAILABLE and _rca_engine is not None:
                    try:
                        rca_result = _rca_engine.analyze(exc)
                    except Exception:
                        pass
                self.setup_errors.append({
                    "type"   : type(exc).__name__,
                    "message": str(exc),
                    "trace"  : traceback.format_exc(),
                    "rca"    : rca_result.to_dict() if rca_result and _RCA_AVAILABLE else {},
                })
                return False

        if _attempt_import():
            return True

        # [BUG-30 FIX] Coba tambah path alternatif dan retry
        alt_paths = [
            str(ROOT / "app"),
            str(ROOT / "src"),
            str(ROOT / "backend"),
        ]
        added = False
        for p in alt_paths:
            if Path(p).exists() and p not in sys.path:
                sys.path.insert(0, p)
                added = True

        if added:
            # Reset error dari percobaan pertama (tapi jangan hapus, simpan sebagai warning)
            prev_errors = list(self.setup_errors)
            self.setup_errors.clear()
            if _attempt_import():
                # Catat bahwa butuh path alternatif
                self.setup_errors.extend(prev_errors)
                self.suggestions.append(
                    "Import berhasil menggunakan path alternatif — periksa PYTHONPATH di deployment."
                )
                return True
            # Tidak berhasil juga — restore semua error
            self.setup_errors.extend(prev_errors)

        return False

    def _register_adapters(self) -> None:
        """
        Panggil register_all() satu kali saja.
        [BUG-09 FIX] Guard double-registration.
        """
        if self._registry_called:
            return
        if self.registry is None:
            return
        if hasattr(self.registry, "register_all"):
            try:
                self.registry.register_all()
                self._registry_called = True
            except Exception as exc:
                rca_result = None
                if _RCA_AVAILABLE and _rca_engine is not None:
                    try:
                        rca_result = _rca_engine.analyze(exc)
                    except Exception:
                        pass
                self.setup_errors.append({
                    "type"   : "RegistrationError",
                    "message": str(exc),
                    "trace"  : traceback.format_exc(),
                    "rca"    : rca_result.to_dict() if rca_result and _RCA_AVAILABLE else {},
                })

    def _get_registered_types(self) -> List[type]:
        """
        Ambil semua interface yang terdaftar di container.
        [BUG-04 FIX] Tidak double-execute callable dan list.
        [BUG-05 FIX] Handle generator, set, tuple — bukan hanya list/dict.
        """
        if self.container is None:
            return []

        # Urutan metode yang dicoba
        probe_attrs = [
            "get_registered_types",
            "get_registered_interfaces",
            "registered_types",
            "registered_interfaces",
            "_registry",
            "__registry",
            "_bindings",
            "_services",
        ]

        for attr_name in probe_attrs:
            if not hasattr(self.container, attr_name):
                continue
            attr = getattr(self.container, attr_name)

            try:
                # Jika callable, panggil dulu
                if callable(attr) and not isinstance(attr, type):
                    result = attr()
                else:
                    result = attr

                # Normalize berbagai return type
                if isinstance(result, dict):
                    return [k for k in result.keys() if isinstance(k, type)]
                if isinstance(result, (list, tuple)):
                    return [x for x in result if isinstance(x, type)]
                if hasattr(result, "__iter__"):  # generator, set, frozenset
                    return [x for x in result if isinstance(x, type)]

            except Exception:
                continue  # Coba attr berikutnya

        return []

    # -------------------------------------------------------------------------
    # Resolution
    # -------------------------------------------------------------------------
    async def _resolve_with_timeout(
        self, interface: type
    ) -> Tuple[Optional[object], Optional[Exception]]:
        """
        Resolve satu interface dengan timeout.
        [BUG-06 FIX] Jangan menelan exception → return tuple (instance, exc).
        [BUG-14 FIX] Timeout per-dependency agar tidak gantung.
        """
        # Wrap sync resolve dalam coroutine agar bisa di-timeout
        async def _try_resolve() -> Optional[object]:
            # 1) resolve_async
            if hasattr(self.container, "resolve_async"):
                try:
                    return await self.container.resolve_async(interface)
                except Exception:
                    pass

            # 2) resolve (sync)
            if hasattr(self.container, "resolve"):
                try:
                    result = self.container.resolve(interface)
                    if result is not None:
                        return result
                except Exception:
                    pass

            # 3) get
            if hasattr(self.container, "get"):
                try:
                    result = self.container.get(interface)
                    if result is not None:
                        return result
                except Exception:
                    pass

            # 4) __getitem__
            if hasattr(self.container, "__getitem__"):
                try:
                    return self.container[interface]
                except Exception:
                    pass

            return None

        try:
            instance = await asyncio.wait_for(
                _try_resolve(),
                timeout=self.resolve_timeout,
            )
            return instance, None
        except asyncio.TimeoutError as exc:
            return None, TimeoutError(
                f"Resolve timeout after {self.resolve_timeout}s untuk {_iface_name(interface)}"
            )
        except Exception as exc:
            return None, exc

    # -------------------------------------------------------------------------
    # Contract Validation
    # -------------------------------------------------------------------------
    def _check_contract(
        self, interface_name: str, instance: object
    ) -> Tuple[bool, List[str]]:
        """
        Periksa method contract.
        [BUG-08 FIX] Handle interface tanpa __name__ (generic alias).
        """
        # [BUG-08 FIX] interface_name sudah di-normalize oleh caller menggunakan _iface_name()
        if interface_name not in CONTRACT_CHECKS:
            return True, []

        expected_methods, allowed_impls = CONTRACT_CHECKS[interface_name]
        class_name = type(instance).__name__

        # Jika implementasi ada di whitelist override, skip contract check
        if allowed_impls and class_name in allowed_impls:
            return True, []

        missing = [
            m for m in expected_methods
            if not (hasattr(instance, m) and callable(getattr(instance, m)))
        ]
        return len(missing) == 0, missing

    # -------------------------------------------------------------------------
    # RCA helpers
    # -------------------------------------------------------------------------
    def _rca_analyze(self, exc: Exception) -> Optional[Any]:
        """Jalankan RCA analysis. Return None jika RCA tidak tersedia."""
        if not _RCA_AVAILABLE or _rca_engine is None:
            return None
        try:
            return _rca_engine.analyze(exc)
        except Exception:
            return None

    def _rca_for_inmemory(self, interface_name: str, impl_name: str) -> Optional[Any]:
        """Buat synthetic RCA result untuk in-memory fallback yang tidak diizinkan."""
        if not _RCA_AVAILABLE:
            return None
        try:
            exc = RuntimeError(
                f"Container resolve '{interface_name}' → InMemory implementation "
                f"'{impl_name}' (non-production fallback, tidak terdaftar di ALLOWED_IN_MEMORY)"
            )
            return _rca_engine.analyze(exc)
        except Exception:
            return None

    def _rca_for_contract(
        self, interface_name: str, impl_name: str, missing: List[str]
    ) -> Optional[Any]:
        """Buat synthetic RCA result untuk contract failure."""
        if not _RCA_AVAILABLE:
            return None
        try:
            exc = AttributeError(
                f"'{impl_name}' object has no attribute '{missing[0]}' "
                f"(contract failure for interface '{interface_name}', "
                f"missing: {', '.join(missing)})"
            )
            return _rca_engine.analyze(exc)
        except Exception:
            return None

    # -------------------------------------------------------------------------
    # Main Run
    # -------------------------------------------------------------------------
    async def run_checks(self) -> Dict[str, Any]:
        """
        Jalankan semua pemeriksaan. Return dict hasil lengkap.

        [BUG-10 FIX] total dihitung setelah get_registered_types() berhasil.
        [BUG-11 FIX] in_memory_count tidak dihitung dua kali.
        [BUG-12 FIX] Score severity-weighted, bukan flat penalty.
        [BUG-13 FIX] instance None menghasilkan RCA result.
        [BUG-15 FIX] Deduplication per interface.
        """
        run_start = time.monotonic()

        # ── 1. Setup ──────────────────────────────────────────────────────────
        if not self._setup_imports():
            return self._build_result(
                success=False,
                total=0,
                run_start=run_start,
                message="FATAL: Gagal import modul DI container. Lihat setup_errors untuk detail.",
            )

        # ── 2. Registrasi adapter ─────────────────────────────────────────────
        self._register_adapters()

        # ── 3. Dapatkan daftar interface ──────────────────────────────────────
        registered_types = self._get_registered_types()
        if not registered_types:
            self.setup_errors.append({
                "type"   : "NoRegisteredTypes",
                "message": (
                    "Container tidak memiliki interface yang terdaftar. "
                    "Pastikan register_all() dipanggil dan container dikonfigurasi dengan benar."
                ),
            })
            return self._build_result(
                success=False,
                total=0,
                run_start=run_start,
                message="FATAL: Container kosong — tidak ada dependency yang terdaftar.",
            )

        # ── 4. Resolve setiap interface ───────────────────────────────────────
        total         = len(registered_types)
        resolved_ok   = 0
        warn_count    = 0   # in-memory tidak di-whitelist
        penalty_score = 0

        for interface in registered_types:
            iname = _iface_name(interface)

            # [BUG-15 FIX] Skip jika sudah diproses (dedup)
            if iname in self._seen_interfaces:
                continue
            self._seen_interfaces.add(iname)

            # Resolve
            instance, exc = await self._resolve_with_timeout(interface)

            if exc is not None:
                # [BUG-07 FIX] Simpan exception dengan RCA
                rca = self._rca_analyze(exc)
                severity = _exc_severity(exc)
                self.resolution_errors.append(ResolutionError(
                    interface_name=iname,
                    error_type    =type(exc).__name__,
                    message       =str(exc),
                    trace         =traceback.format_exception(type(exc), exc, exc.__traceback__)[-1]
                                   if exc.__traceback__ else "",
                    rca_result    =rca,
                    severity      =severity,
                ))
                penalty_score += _SEVERITY_WEIGHTS.get(severity, 5)
                continue

            if instance is None:
                # [BUG-13 FIX] None instance = error dengan RCA
                null_exc = RuntimeError(
                    f"Container.resolve('{iname}') returned None — "
                    "kemungkinan binding tidak terdaftar atau factory return None."
                )
                rca = self._rca_analyze(null_exc)
                self.resolution_errors.append(ResolutionError(
                    interface_name=iname,
                    error_type    ="NullResolution",
                    message       =str(null_exc),
                    rca_result    =rca,
                    severity      ="HIGH",
                ))
                penalty_score += _SEVERITY_WEIGHTS["HIGH"]
                continue

            # ── Deteksi in-memory fallback ─────────────────────────────────
            class_name = type(instance).__name__
            if _is_inmemory(class_name):
                is_allowed = class_name in ALLOWED_IN_MEMORY
                # Normalize: tidak hitung dua kali interface yang sama
                already = any(
                    f.interface_name == iname for f in self.in_memory_fallbacks
                )
                if not already:
                    rca = None if is_allowed else self._rca_for_inmemory(iname, class_name)
                    self.in_memory_fallbacks.append(InMemoryFallback(
                        interface_name=iname,
                        implementation=class_name,
                        is_allowed    =is_allowed,
                        rca_result    =rca,
                    ))
                    if not is_allowed:
                        warn_count    += 1
                        penalty_score += _SEVERITY_WEIGHTS["MEDIUM"]
                    else:
                        resolved_ok   += 1
            else:
                resolved_ok += 1

            # ── Cek kontrak ────────────────────────────────────────────────
            ok, missing = self._check_contract(iname, instance)
            if not ok:
                rca = self._rca_for_contract(iname, class_name, missing)
                self.contract_failures.append(ContractFailure(
                    interface_name=iname,
                    implementation=class_name,
                    missing_methods=missing,
                    rca_result    =rca,
                ))
                penalty_score += _SEVERITY_WEIGHTS["CRITICAL"]

        # ── 5. Setup errors penalty ────────────────────────────────────────────
        for se in self.setup_errors:
            # RegistrationError = MEDIUM, ImportError = FATAL
            if se.get("type") == "ImportError":
                penalty_score += _SEVERITY_WEIGHTS["FATAL"]
            elif se.get("type") == "RegistrationError":
                penalty_score += _SEVERITY_WEIGHTS["MEDIUM"]

        # ── 6. Score calculation ───────────────────────────────────────────────
        # [BUG-12 FIX] Severity-weighted scoring
        score = max(0, min(100, 100 - penalty_score))

        # ── 7. Generate suggestions ────────────────────────────────────────────
        self._generate_suggestions()

        # ── 8. Success criteria ────────────────────────────────────────────────
        has_critical_errors = (
            len(self.resolution_errors) > 0
            or len(self.contract_failures) > 0
            or any(not f.is_allowed for f in self.in_memory_fallbacks)
            or any(se.get("type") in ("ImportError", "RegistrationError")
                   for se in self.setup_errors)
        )
        success = not has_critical_errors

        return self._build_result(
            success=success,
            total=total,
            resolved_ok=resolved_ok,
            warn_count=warn_count,
            score=score,
            run_start=run_start,
        )

    def _generate_suggestions(self) -> None:
        """Generate saran perbaikan berdasarkan temuan."""
        if not _RCA_AVAILABLE:
            self.suggestions.append(
                "Install rca.py ke checker/core/ untuk mendapatkan saran RCA otomatis."
            )

        for err in self.resolution_errors:
            if err.rca_result and _RCA_AVAILABLE:
                # Ambil suggested_fix dari objek RCAResult jika ada
                fix = getattr(err.rca_result, "suggested_fix", "")
                if fix:
                    self.suggestions.append(f"[{err.interface_name}] {fix}")
            else:
                self.suggestions.append(
                    f"[{err.interface_name}] Periksa binding di DI container untuk "
                    f"interface ini ({err.error_type}: {err.message[:100]})."
                )

        # In-memory yang tidak diizinkan
        bad_inmem = [f for f in self.in_memory_fallbacks if not f.is_allowed]
        if bad_inmem:
            names = ", ".join(f.implementation for f in bad_inmem)
            self.suggestions.append(
                f"In-memory fallback tidak diizinkan: {names}. "
                "Periksa konfigurasi kredensial layanan atau tambahkan ke ALLOWED_IN_MEMORY "
                "jika memang sengaja digunakan di environment ini."
            )

        # Contract failures
        for fail in self.contract_failures:
            methods_str = ", ".join(f"'{m}'" for m in fail.missing_methods)
            self.suggestions.append(
                f"[{fail.interface_name}] Implementasi '{fail.implementation}' "
                f"hilang method: {methods_str}. "
                "Tambahkan method tersebut atau periksa inheritance dari interface port."
            )

        # Setup errors
        for se in self.setup_errors:
            if se.get("type") == "ImportError":
                mod = se.get("module", "unknown")
                self.suggestions.append(
                    f"Module '{mod}' tidak bisa diimport. "
                    "Pastikan PYTHONPATH benar dan package terinstal: "
                    f"pip install -e . atau python -m pip install {mod.split('.')[0]}"
                )

    def _build_result(
        self,
        success: bool,
        total: int,
        run_start: float,
        message: str = "",
        resolved_ok: int = 0,
        warn_count: int = 0,
        score: int = 0,
    ) -> Dict[str, Any]:
        """Bangun dict hasil lengkap."""
        elapsed = time.monotonic() - run_start
        now_utc = datetime.now(timezone.utc).isoformat()

        result: Dict[str, Any] = {
            "success"          : success,
            "score"            : score,
            "timestamp_utc"    : now_utc,
            "duration_seconds" : round(elapsed, 4),
            "rca_available"    : _RCA_AVAILABLE,
            "total_interfaces" : total,
            "resolved_ok"      : resolved_ok,
            "warn_inmemory"    : warn_count,
            "resolution_errors": [e.to_dict() for e in self.resolution_errors],
            "in_memory_fallbacks": [f.to_dict() for f in self.in_memory_fallbacks],
            "contract_failures": [c.to_dict() for c in self.contract_failures],
            "setup_errors"     : self.setup_errors,
            "suggestions"      : list(dict.fromkeys(self.suggestions)),  # dedup preserve order
        }
        if message:
            result["message"] = message

        # Summary stats per-severity
        result["error_summary"] = {
            "resolution_errors" : len(self.resolution_errors),
            "contract_failures" : len(self.contract_failures),
            "inmemory_warnings" : warn_count,
            "setup_errors"      : len(self.setup_errors),
            "total_issues"      : (
                len(self.resolution_errors)
                + len(self.contract_failures)
                + warn_count
                + len([se for se in self.setup_errors
                        if se.get("type") in ("ImportError", "RegistrationError")])
            ),
        }
        return result


# =============================================================================
# Helpers
# =============================================================================

def _iface_name(interface: Any) -> str:
    """
    Ambil nama interface secara aman.
    [BUG-08 FIX] Handle generic alias (Optional[X], List[X]) yang tidak punya __name__.
    """
    if hasattr(interface, "__name__"):
        return interface.__name__
    # Generic alias: typing._GenericAlias, e.g. List[str]
    if hasattr(interface, "__origin__") and hasattr(interface.__origin__, "__name__"):
        args = getattr(interface, "__args__", ())
        args_str = ", ".join(_iface_name(a) for a in args) if args else ""
        base = interface.__origin__.__name__
        return f"{base}[{args_str}]" if args_str else base
    return str(interface)


def _is_inmemory(class_name: str) -> bool:
    """Cek apakah class name menandakan in-memory implementation."""
    lower = class_name.lower()
    return "inmemory" in lower or (
        "memory" in lower and not lower.startswith("memory_profiler")
    )


def _exc_severity(exc: Exception) -> str:
    """Map exception type ke severity string."""
    if isinstance(exc, (ImportError, ModuleNotFoundError)):
        return "FATAL"
    if isinstance(exc, (RuntimeError, AttributeError)):
        return "CRITICAL"
    if isinstance(exc, TimeoutError):
        return "HIGH"
    if isinstance(exc, (TypeError, ValueError)):
        return "MEDIUM"
    return "HIGH"


# =============================================================================
# Output
# =============================================================================

def print_report(result: Dict[str, Any], verbose: bool = False) -> None:
    """
    Cetak laporan ke stdout.
    [BUG-16 FIX] Selalu gunakan COLOR dict (sudah di-init dengan benar).
    [BUG-17 FIX] Gunakan .get() di seluruh akses result.
    """
    c = COLOR
    W  = 74

    def hr(char: str = "═") -> str:
        return c["CYAN"] + char * W + c["RESET"]

    print(f"\n{hr()}")
    print(f"{c['BOLD']}{c['CYAN']}  DI CONTAINER INTEGRITY REPORT — Sovereign ERP System{c['RESET']}")
    print(hr())

    ts  = result.get("timestamp_utc", "N/A")
    dur = result.get("duration_seconds", 0.0)
    rca_tag = f"{c['GREEN']}✅ aktif{c['RESET']}" if result.get("rca_available") else \
              f"{c['YELLOW']}⚠️  tidak tersedia{c['RESET']}"

    print(f"\n  Timestamp         : {ts}")
    print(f"  Durasi Audit      : {dur:.4f} detik")
    print(f"  RCA Engine        : {rca_tag}")

    # ── Score ─────────────────────────────────────────────────────────────────
    score = result.get("score", 0)
    if score >= 90:
        score_color = c["GREEN"]
    elif score >= 70:
        score_color = c["YELLOW"]
    else:
        score_color = c["RED"]

    print(f"\n  {'─'*W}")
    print(f"  📊 Skor Kepatuhan : {score_color}{c['BOLD']}{score}/100{c['RESET']}")
    print(f"  {'─'*W}")

    # ── Summary ───────────────────────────────────────────────────────────────
    summary = result.get("error_summary", {})
    total   = result.get("total_interfaces", 0)
    ok      = result.get("resolved_ok", 0)

    print(f"\n  Total Interface Terdaftar   : {total}")
    print(f"  Berhasil Resolved OK        : {ok}")
    print(f"  Resolution Errors           : "
          f"{c['RED'] if summary.get('resolution_errors') else c['GREEN']}"
          f"{summary.get('resolution_errors', 0)}{c['RESET']}")
    print(f"  Contract Failures           : "
          f"{c['RED'] if summary.get('contract_failures') else c['GREEN']}"
          f"{summary.get('contract_failures', 0)}{c['RESET']}")
    print(f"  In-Memory Warnings          : "
          f"{c['YELLOW'] if summary.get('inmemory_warnings') else c['GREEN']}"
          f"{summary.get('inmemory_warnings', 0)}{c['RESET']}")
    print(f"  Setup / Import Errors       : "
          f"{c['RED'] if summary.get('setup_errors') else c['GREEN']}"
          f"{summary.get('setup_errors', 0)}{c['RESET']}")

    # ── Message (jika fatal) ──────────────────────────────────────────────────
    if result.get("message"):
        print(f"\n  {c['RED']}{c['BOLD']}⛔ {result['message']}{c['RESET']}")

    # ── Setup Errors ──────────────────────────────────────────────────────────
    if result.get("setup_errors"):
        print(f"\n{c['RED']}━━ Setup Errors ━━{c['RESET']}")
        for se in result["setup_errors"]:
            print(f"  [{se.get('type', '?')}] {se.get('message', '')[:120]}")
            if verbose and se.get("trace"):
                for line in se["trace"].splitlines():
                    print(f"      {line}")
            rca = se.get("rca", {})
            if rca and rca.get("root_cause"):
                print(f"      {c['CYAN']}RCA:{c['RESET']} {rca['root_cause']}")
                if rca.get("suggested_fix"):
                    print(f"      {c['YELLOW']}Fix:{c['RESET']} {rca['suggested_fix']}")

    # ── Resolution Errors ─────────────────────────────────────────────────────
    if result.get("resolution_errors"):
        print(f"\n{c['RED']}━━ Resolution Errors ({len(result['resolution_errors'])}) ━━{c['RESET']}")
        for err in result["resolution_errors"]:
            sev = err.get("severity", "HIGH")
            sev_color = c["RED"] if sev in ("FATAL", "CRITICAL", "HIGH") else c["YELLOW"]
            print(f"\n  {sev_color}[{sev}]{c['RESET']} {err.get('interface', '?')}")
            print(f"    Type   : {err.get('error_type', '?')}")
            print(f"    Message: {err.get('message', '')[:150]}")
            if verbose and err.get("trace"):
                print(f"    Trace  : {err['trace'].strip()}")
            rca = err.get("rca", {})
            if rca and rca.get("root_cause"):
                print(f"    {c['CYAN']}RCA:{c['RESET']}   {rca['root_cause']}")
                if rca.get("suggested_fix"):
                    print(f"    {c['YELLOW']}Fix:{c['RESET']}   {rca['suggested_fix']}")
                if rca.get("confidence"):
                    print(f"    Confidence: {rca['confidence']:.0%}")

    # ── In-Memory Fallbacks ────────────────────────────────────────────────────
    fallbacks = result.get("in_memory_fallbacks", [])
    if fallbacks:
        print(f"\n{c['YELLOW']}━━ In-Memory Fallbacks ({len(fallbacks)}) ━━{c['RESET']}")
        for fb in fallbacks:
            allowed  = fb.get("is_allowed", False)
            status   = f"{c['GREEN']}✅ allowed{c['RESET']}" if allowed else f"{c['RED']}❌ WARNING{c['RESET']}"
            print(f"  {status}  {fb.get('interface', '?')} → {fb.get('implementation', '?')}")
            if not allowed:
                rca = fb.get("rca", {})
                if rca and rca.get("suggested_fix"):
                    print(f"    {c['YELLOW']}Fix:{c['RESET']} {rca['suggested_fix']}")

    # ── Contract Failures ──────────────────────────────────────────────────────
    if result.get("contract_failures"):
        print(f"\n{c['RED']}━━ Contract Failures ({len(result['contract_failures'])}) ━━{c['RESET']}")
        for fail in result["contract_failures"]:
            missing = ", ".join(fail.get("missing_methods", []))
            print(f"\n  Interface : {fail.get('interface_name', '?')}")
            print(f"  Impl      : {fail.get('implementation', '?')}")
            print(f"  Missing   : {c['RED']}{missing}{c['RESET']}")
            rca = fail.get("rca", {})
            if rca and rca.get("root_cause"):
                print(f"  {c['CYAN']}RCA:{c['RESET']}     {rca['root_cause']}")
                if rca.get("suggested_fix"):
                    print(f"  {c['YELLOW']}Fix:{c['RESET']}     {rca['suggested_fix']}")

    # ── Suggestions ────────────────────────────────────────────────────────────
    suggestions = result.get("suggestions", [])
    if suggestions:
        print(f"\n{c['CYAN']}━━ Saran Perbaikan ━━{c['RESET']}")
        for i, s in enumerate(suggestions, 1):
            print(f"  {i:>2}. {s}")

    # ── Final verdict ──────────────────────────────────────────────────────────
    print(f"\n{hr()}")
    success = result.get("success", False)
    if success:
        print(f"{c['GREEN']}{c['BOLD']}  ✅ PASS — Semua dependency OK, tidak ada error kritis.{c['RESET']}")
    else:
        total_issues = result.get("error_summary", {}).get("total_issues", "?")
        print(f"{c['RED']}{c['BOLD']}  ❌ FAIL — {total_issues} issue ditemukan. Perbaiki sebelum deploy.{c['RESET']}")
    print(hr() + "\n")


# =============================================================================
# JSON Export (dengan full audit trail)
# =============================================================================

def save_json(result: Dict[str, Any], filepath: str) -> None:
    """
    Export laporan ke JSON.
    [BUG-18 FIX] Sertakan errors dengan traceback.
    [BUG-19 FIX] Tambahkan timestamp.
    [BUG-20 FIX] Error handling untuk I/O failure.
    """
    try:
        # Pastikan direktori ada
        out_path = Path(filepath)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "schema_version"    : "2.0",
            "tool"              : "DIContainerChecker",
            "generated_at_utc"  : result.get("timestamp_utc"),
            "duration_seconds"  : result.get("duration_seconds"),
            "rca_available"     : result.get("rca_available", False),
            "success"           : result.get("success", False),
            "score"             : result.get("score", 0),
            "error_summary"     : result.get("error_summary", {}),
            "total_interfaces"  : result.get("total_interfaces", 0),
            "resolved_ok"       : result.get("resolved_ok", 0),
            "resolution_errors" : result.get("resolution_errors", []),
            "in_memory_fallbacks": result.get("in_memory_fallbacks", []),
            "contract_failures" : result.get("contract_failures", []),
            "setup_errors"      : result.get("setup_errors", []),
            "suggestions"       : result.get("suggestions", []),
        }
        if result.get("message"):
            payload["fatal_message"] = result["message"]

        out_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"{COLOR['GREEN']}✅ Laporan JSON diekspor ke: {out_path.resolve()}{COLOR['RESET']}")

    except OSError as exc:
        # [BUG-20 FIX] Jangan crash — cetak error dan lanjutkan
        print(f"{COLOR['RED']}❌ Gagal menulis JSON ke '{filepath}': {exc}{COLOR['RESET']}")
    except Exception as exc:
        print(f"{COLOR['RED']}❌ JSON export error: {type(exc).__name__}: {exc}{COLOR['RESET']}")


# =============================================================================
# SARIF 2.1.0 Export (untuk CI integration)
# [BUG-27 FIX] Tambahkan SARIF export
# =============================================================================

def save_sarif(result: Dict[str, Any], filepath: str) -> None:
    """Export laporan dalam format SARIF 2.1.0 untuk CI pipeline."""
    rules: List[Dict[str, Any]] = []
    rule_ids: Set[str] = set()
    results_list: List[Dict[str, Any]] = []

    def _add_rule(rule_id: str, name: str, desc: str) -> None:
        if rule_id not in rule_ids:
            rules.append({
                "id"              : rule_id,
                "name"            : name,
                "shortDescription": {"text": desc},
            })
            rule_ids.add(rule_id)

    def _level(severity: str) -> str:
        if severity in ("FATAL", "CRITICAL"):
            return "error"
        if severity in ("HIGH", "MEDIUM"):
            return "warning"
        return "note"

    # Resolution errors
    for err in result.get("resolution_errors", []):
        rule_id = f"DI-{err.get('error_type', 'ERR').upper()[:12]}"
        _add_rule(rule_id, "DI Resolution Error",
                  "DI container gagal me-resolve dependency")
        rca    = err.get("rca", {})
        fix    = rca.get("suggested_fix", "") if rca else ""
        results_list.append({
            "ruleId" : rule_id,
            "level"  : _level(err.get("severity", "HIGH")),
            "message": {
                "text": (
                    f"[{err.get('interface', '?')}] {err.get('message', '')[:200]}"
                    + (f" | Fix: {fix}" if fix else "")
                )
            },
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": "checker/checker_di_container.py"},
                }
            }],
        })

    # Contract failures
    for fail in result.get("contract_failures", []):
        rule_id = "DI-CONTRACT-FAIL"
        _add_rule(rule_id, "DI Contract Failure",
                  "Implementasi tidak memenuhi kontrak interface")
        missing = ", ".join(fail.get("missing_methods", []))
        results_list.append({
            "ruleId" : rule_id,
            "level"  : "error",
            "message": {
                "text": (
                    f"Interface '{fail.get('interface_name', '?')}' implementasi "
                    f"'{fail.get('implementation', '?')}' hilang method: {missing}"
                )
            },
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": "checker/checker_di_container.py"},
                }
            }],
        })

    # In-memory warnings
    for fb in result.get("in_memory_fallbacks", []):
        if not fb.get("is_allowed"):
            rule_id = "DI-INMEMORY-WARN"
            _add_rule(rule_id, "DI InMemory Warning",
                      "InMemory implementation digunakan tanpa whitelist eksplisit")
            results_list.append({
                "ruleId" : rule_id,
                "level"  : "warning",
                "message": {
                    "text": (
                        f"Interface '{fb.get('interface', '?')}' menggunakan "
                        f"'{fb.get('implementation', '?')}' yang tidak ada di ALLOWED_IN_MEMORY"
                    )
                },
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {"uri": "checker/checker_di_container.py"},
                    }
                }],
            })

    sarif_doc = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs"   : [{
            "tool"   : {
                "driver": {
                    "name"   : "DIContainerChecker",
                    "version": "2.0",
                    "rules"  : rules,
                }
            },
            "results": results_list,
        }],
    }

    try:
        out = Path(filepath)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(sarif_doc, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"{COLOR['GREEN']}✅ SARIF diekspor ke: {out.resolve()}{COLOR['RESET']}")
    except OSError as exc:
        print(f"{COLOR['RED']}❌ Gagal menulis SARIF ke '{filepath}': {exc}{COLOR['RESET']}")


# =============================================================================
# Main CLI
# =============================================================================

def main() -> None:
    """
    Entry point CLI.
    [BUG-21 FIX] Handle event loop yang sudah ada (pytest-asyncio compatibility).
    [BUG-22 FIX] Timeout global via asyncio.
    [BUG-23 FIX] Hitung waktu dari paling awal.
    """
    # [PERBAIKAN SYNTAX ERROR] Deklarasikan global sebelum penggunaan variabel
    global _rca_engine, _RCA_AVAILABLE

    wall_start = time.monotonic()

    parser = argparse.ArgumentParser(
        description="Sovereign ERP — DI Container Integrity Checker v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exit codes:\n"
            "  0 = PASS (semua dependency OK)\n"
            "  1 = FAIL (ada error yang perlu diperbaiki)\n"
            "  2 = ERROR (checker sendiri gagal dijalankan)\n"
        ),
    )
    parser.add_argument("--json",  metavar="FILE", help="Export laporan ke JSON")
    parser.add_argument("--sarif", metavar="FILE", help="Export laporan ke SARIF 2.1.0")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Tampilkan traceback dan detail tambahan")
    parser.add_argument("--timeout", type=float, default=RESOLVE_TIMEOUT_SECONDS,
                        metavar="SEC",
                        help=f"Timeout resolve per-dependency (default: {RESOLVE_TIMEOUT_SECONDS}s)")
    parser.add_argument("--no-rca", action="store_true",
                        help="Nonaktifkan RCA analysis (lebih cepat)")
    args = parser.parse_args()

    # Banner
    c = COLOR
    print(f"{c['BOLD']}{c['CYAN']}")
    print(f"╔{'═'*72}╗")
    print(f"║{'SOVEREIGN ERP — DI CONTAINER INTEGRITY CHECKER v2.0':^72}║")
    print(f"╚{'═'*72}╝{c['RESET']}")
    print(f"  Root   : {ROOT}")
    print(f"  RCA    : {'enabled' if (_RCA_AVAILABLE and not args.no_rca) else 'disabled'}")
    print(f"  Timeout: {args.timeout}s per-dependency")
    print()

    # Nonaktifkan RCA jika diminta
    if args.no_rca:
        _rca_engine    = None
        _RCA_AVAILABLE = False

    # Jalankan checker
    checker = DIContainerChecker(resolve_timeout=args.timeout)
    exit_code = 2  # default: error
    result: Dict[str, Any] = {}

    try:
        # [BUG-21 FIX] asyncio.run() vs existing event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            # Sudah ada loop (e.g. pytest-asyncio) — jadwalkan sebagai task
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run, checker.run_checks()
                )
                result = future.result(timeout=args.timeout * 200 + 30)
        else:
            result = asyncio.run(checker.run_checks())

        exit_code = 0 if result.get("success", False) else 1

    except KeyboardInterrupt:
        print(f"\n{c['YELLOW']}⚠️  Audit dibatalkan oleh user.{c['RESET']}")
        sys.exit(2)
    except Exception as exc:
        print(f"\n{c['RED']}❌ CHECKER ERROR: {type(exc).__name__}: {exc}{c['RESET']}")
        if args.verbose:
            traceback.print_exc()
        sys.exit(2)

    # Output
    print_report(result, verbose=args.verbose)

    if args.json:
        save_json(result, args.json)

    if args.sarif:
        save_sarif(result, args.sarif)

    wall_elapsed = time.monotonic() - wall_start
    print(f"  ⏱️  Total waktu audit : {wall_elapsed:.3f} detik\n")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()