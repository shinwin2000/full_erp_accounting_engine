#!/usr/bin/env python3
"""
Sovereign ERP System - Aggregate Event Contract Checker (Akurat Runtime)
=========================================================================
Memeriksa konsistensi event contract pada aggregate root dengan runtime inspection,
terintegrasi penuh dengan RCA Engine v3.0.0 (checker/core/rca.py) untuk analisis
akar masalah forensik.

Standar Event Contract:
    - _events: list[DomainEvent]
    - register_event(event) -> None
    - get_events() -> list[DomainEvent]
    - pull_events() -> list[DomainEvent]
    - clear_events() -> None
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import pathlib
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

# =============================================================================
# Path & RCA Integration
# =============================================================================
ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- RCA Engine (v3.0.0) ---
_RCA_AVAILABLE = False
_rca_engine = None
_analyze_exception = None

# Coba import dari checker/core/rca.py
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
    _analyze_exception = analyze_exception
    _RCA_AVAILABLE = True
    print(f"[RCA] Engine v{RCAEngine.VERSION} loaded from {_checker_core}")
except ImportError:
    # Fallback: coba dari direktori yang sama dengan checker ini
    try:
        _this_dir = pathlib.Path(__file__).resolve().parent
        if str(_this_dir) not in sys.path:
            sys.path.insert(0, str(_this_dir))
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
        _analyze_exception = analyze_exception
        _RCA_AVAILABLE = True
        print(f"[RCA] Engine v{RCAEngine.VERSION} loaded from {_this_dir}")
    except ImportError:
        print("[RCA] ⚠️  RCA Engine not available – using fallback analysis")
        _RCA_AVAILABLE = False

# =============================================================================
# Color Support
# =============================================================================
COLOR = {
    "RED": "\033[91m",
    "GREEN": "\033[92m",
    "YELLOW": "\033[93m",
    "BLUE": "\033[94m",
    "CYAN": "\033[96m",
    "BOLD": "\033[1m",
    "RESET": "\033[0m"
}
if not sys.stdout.isatty():
    COLOR = dict.fromkeys(COLOR, "")

# =============================================================================
# Configuration
# =============================================================================
EXCLUDED_DIRS = {
    "checker", "tests", "migrations", "__pycache__", ".git",
    "docs", "scripts", "deployment", "monitoring", "reports", "alembic",
    "shared_value_objects", "value_objects"
}

NON_AGGREGATE_KEYWORDS = {
    "Repository", "Error", "Exception", "Table", "Store", "Adapter",
    "Service", "Factory", "Risk", "Enum", "Signature"
}

# =============================================================================
# Data Structures
# =============================================================================
@dataclass
class AggregateInfo:
    file_path: str
    class_name: str
    base_classes: List[str]
    has_events_attr: bool
    has_register_event: bool
    has_get_events: bool
    has_pull_events: bool
    has_clear_events: bool
    violations: List[str] = field(default_factory=list)
    # RCA results per violation
    rca_results: List[Dict[str, Any]] = field(default_factory=list)
    import_error: Optional[str] = None  # Jika ada error saat import module

# =============================================================================
# Checker Class
# =============================================================================
class AggregateEventContractChecker:
    def __init__(self, root_dir: pathlib.Path, enable_rca: bool = True):
        self.root_dir = root_dir
        self.enable_rca = enable_rca and _RCA_AVAILABLE
        self.aggregates: List[AggregateInfo] = []

    def _get_python_files(self) -> List[pathlib.Path]:
        py_files = []
        domain_dir = self.root_dir / "domain"
        if not domain_dir.exists():
            return py_files
        for p in domain_dir.rglob("*.py"):
            if any(part in EXCLUDED_DIRS for part in p.parts):
                continue
            if p.name.startswith(("test_", "conftest")):
                continue
            py_files.append(p)
        return py_files

    def _is_aggregate_class(self, cls: type) -> bool:
        name = cls.__name__
        for kw in NON_AGGREGATE_KEYWORDS:
            if kw in name:
                return False
        if "Aggregate" in name:
            return True
        if "Collection" in name:
            return hasattr(cls, "register_event") or hasattr(cls, "pull_events")
        if hasattr(cls, "register_event") or hasattr(cls, "pull_events"):
            return True
        return False

    def _check_contract(self, cls: type) -> tuple[
        bool, bool, bool, bool, bool, List[str], List[Dict[str, Any]]
    ]:
        """
        Periksa kontrak event aggregate.
        Return: (has_events_attr, has_reg, has_get, has_pull, has_clear, violations, rca_list)
        """
        has_reg = hasattr(cls, "register_event") and inspect.isfunction(cls.register_event)
        has_get = hasattr(cls, "get_events") and inspect.isfunction(cls.get_events)
        has_pull = hasattr(cls, "pull_events") and inspect.isfunction(cls.pull_events)
        has_clear = hasattr(cls, "clear_events") and inspect.isfunction(cls.clear_events)
        has_events = hasattr(cls, "_events") or (has_reg and has_get and has_pull and has_clear)

        violations = []
        rca_list = []

        # Membuat synthetic exception untuk setiap pelanggaran
        if not has_events:
            violations.append("Tidak memiliki attribute _events")
            if self.enable_rca and _analyze_exception is not None:
                exc = AttributeError(
                    f"Aggregate '{cls.__name__}' tidak memiliki attribute '_events' "
                    "untuk menyimpan daftar event."
                )
                rca = _analyze_exception(exc)
                rca_list.append({
                    "violation": "Tidak memiliki attribute _events",
                    "rca": rca.to_dict() if rca else {}
                })

        if not has_reg:
            violations.append("Tidak memiliki method register_event()")
            if self.enable_rca and _analyze_exception is not None:
                exc = AttributeError(
                    f"Aggregate '{cls.__name__}' tidak memiliki method 'register_event(event)'."
                )
                rca = _analyze_exception(exc)
                rca_list.append({
                    "violation": "Tidak memiliki method register_event()",
                    "rca": rca.to_dict() if rca else {}
                })

        if not has_get:
            violations.append("Tidak memiliki method get_events()")
            if self.enable_rca and _analyze_exception is not None:
                exc = AttributeError(
                    f"Aggregate '{cls.__name__}' tidak memiliki method 'get_events()'."
                )
                rca = _analyze_exception(exc)
                rca_list.append({
                    "violation": "Tidak memiliki method get_events()",
                    "rca": rca.to_dict() if rca else {}
                })

        if not has_pull:
            violations.append("Tidak memiliki method pull_events()")
            if self.enable_rca and _analyze_exception is not None:
                exc = AttributeError(
                    f"Aggregate '{cls.__name__}' tidak memiliki method 'pull_events()'."
                )
                rca = _analyze_exception(exc)
                rca_list.append({
                    "violation": "Tidak memiliki method pull_events()",
                    "rca": rca.to_dict() if rca else {}
                })

        if not has_clear:
            violations.append("Tidak memiliki method clear_events()")
            if self.enable_rca and _analyze_exception is not None:
                exc = AttributeError(
                    f"Aggregate '{cls.__name__}' tidak memiliki method 'clear_events()'."
                )
                rca = _analyze_exception(exc)
                rca_list.append({
                    "violation": "Tidak memiliki method clear_events()",
                    "rca": rca.to_dict() if rca else {}
                })

        return has_events, has_reg, has_get, has_pull, has_clear, violations, rca_list

    def _get_base_class_names(self, cls: type) -> List[str]:
        return [base.__name__ for base in cls.__bases__ if base.__name__ not in ("object",)]

    def _analyze_import_error(self, module_name: str, exc: Exception) -> Dict[str, Any]:
        """Analisis ImportError dengan RCA engine (v3.0.0)."""
        if not self.enable_rca or _analyze_exception is None:
            return {"root_cause": str(exc), "suggested_fix": "Periksa dependensi modul."}
        try:
            rca = _analyze_exception(exc)
            return rca.to_dict() if rca else {"root_cause": str(exc)}
        except Exception:
            return {"root_cause": str(exc)}

    def scan_file(self, module_name: str, file_path: pathlib.Path) -> List[AggregateInfo]:
        infos = []
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            # Gagal import -> catat error untuk RCA
            rca_info = self._analyze_import_error(module_name, e)
            dummy = AggregateInfo(
                file_path=str(file_path.relative_to(self.root_dir)),
                class_name="<IMPORT_ERROR>",
                base_classes=[],
                has_events_attr=False,
                has_register_event=False,
                has_get_events=False,
                has_pull_events=False,
                has_clear_events=False,
                violations=[f"Gagal import module: {e}"],
                rca_results=[{"violation": "ImportError", "rca": rca_info}],
                import_error=str(e)
            )
            infos.append(dummy)
            return infos

        for name, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != module.__name__:
                continue
            if not self._is_aggregate_class(obj):
                continue

            base_names = self._get_base_class_names(obj)
            has_events, has_reg, has_get, has_pull, has_clear, violations, rca_list = self._check_contract(obj)

            infos.append(AggregateInfo(
                file_path=str(file_path.relative_to(self.root_dir)),
                class_name=name,
                base_classes=base_names,
                has_events_attr=has_events,
                has_register_event=has_reg,
                has_get_events=has_get,
                has_pull_events=has_pull,
                has_clear_events=has_clear,
                violations=violations,
                rca_results=rca_list
            ))
        return infos

    def scan(self) -> List[AggregateInfo]:
        self.aggregates = []
        for f in self._get_python_files():
            rel_path = str(f.relative_to(self.root_dir)).replace("/", ".").replace("\\", ".")
            module_name = rel_path[:-3]  # hapus .py
            infos = self.scan_file(module_name, f)
            self.aggregates.extend(infos)
        return self.aggregates

# =============================================================================
# Helper Functions for Reporting
# =============================================================================
def generate_fix_suggestions(info: AggregateInfo) -> str:
    """Generate template kode perbaikan (fallback jika RCA tidak memberikan saran)."""
    suggestions = []
    if not info.has_events_attr:
        suggestions.append("_events: list[DomainEvent] = []")
    if not info.has_register_event:
        suggestions.append("def register_event(self, event: DomainEvent) -> None: self._events.append(event)")
    if not info.has_get_events:
        suggestions.append("def get_events(self) -> list[DomainEvent]: return self._events.copy()")
    if not info.has_pull_events:
        suggestions.append("def pull_events(self) -> list[DomainEvent]: events = self._events.copy(); self._events.clear(); return events")
    if not info.has_clear_events:
        suggestions.append("def clear_events(self) -> None: self._events.clear()")
    return "\n    ".join(suggestions)

def get_suggested_fix_from_rca(rca_dict: Dict[str, Any]) -> str:
    """Ekstrak suggested_fix dari RCA result."""
    if not rca_dict:
        return ""
    return rca_dict.get("suggested_fix", "") or ""

def print_report(aggregates: List[AggregateInfo], verbose: bool = False, json_output: Optional[str] = None) -> None:
    total = len(aggregates)
    # Filter aggregate yang memiliki violations (kecuali yang import error)
    violations_list = [a for a in aggregates if a.violations and a.class_name != "<IMPORT_ERROR>"]
    import_errors = [a for a in aggregates if a.class_name == "<IMPORT_ERROR>"]
    error_count = sum(len(a.violations) for a in violations_list)
    compliant = [a for a in aggregates if not a.violations and a.class_name != "<IMPORT_ERROR>"]
    score = (len(compliant) / total * 100) if total else 100.0

    # Cetak header
    print(f"{COLOR['BOLD']}{COLOR['CYAN']}╔════════════════════════════════════════════════════════════════════╗")
    print("║      SOVEREIGN AGGREGATE EVENT CONTRACT CHECKER (RUNTIME)      ║")
    print(f"╚════════════════════════════════════════════════════════════════════╝{COLOR['RESET']}")
    print("  Standar Event Contract:")
    print("    ✅ _events: list[DomainEvent]")
    print("    ✅ register_event(event) -> None")
    print("    ✅ get_events() -> list[DomainEvent]")
    print("    ✅ pull_events() -> list[DomainEvent]")
    print("    ✅ clear_events() -> None")
    print(f"  Total Aggregate Ditemukan: {total}")
    print(f"  Total Violations: {error_count}")
    print(f"  Import Errors: {len(import_errors)}")
    print(f"  RCA Engine: {'✅ aktif (v3.0.0)' if _RCA_AVAILABLE else '⚠️ tidak tersedia'}")

    if import_errors:
        print(f"\n{COLOR['RED']}─── IMPORT ERRORS ───{COLOR['RESET']}")
        for info in import_errors:
            print(f"  [ERROR] {info.file_path}: {info.import_error}")
            if info.rca_results:
                rca = info.rca_results[0].get("rca", {})
                if rca.get("root_cause"):
                    print(f"    Root Cause: {rca['root_cause']}")
                if rca.get("suggested_fix"):
                    print(f"    Saran RCA: {rca['suggested_fix']}")
                if verbose and rca.get("confidence") is not None:
                    print(f"    Confidence: {rca['confidence']:.0%}")
            if verbose and info.import_error:
                print(f"    Detail: {info.import_error}")

    if violations_list:
        print(f"\n{COLOR['RED']}─── VIOLATIONS (harus diperbaiki) ───{COLOR['RESET']}")
        for info in violations_list:
            base_info = f" (inherits: {', '.join(info.base_classes)})" if info.base_classes else ""
            print(f"  [ERROR] {info.file_path}: {info.class_name}{base_info}")
            for idx, v in enumerate(info.violations):
                print(f"    {v}")
                # Tampilkan RCA jika ada
                if idx < len(info.rca_results):
                    rca_dict = info.rca_results[idx].get("rca", {})
                    if rca_dict:
                        if rca_dict.get("root_cause"):
                            print(f"      → Root Cause: {rca_dict['root_cause']}")
                        if rca_dict.get("suggested_fix"):
                            print(f"      → Saran RCA: {rca_dict['suggested_fix']}")
                        if verbose and rca_dict.get("confidence") is not None:
                            print(f"      → Confidence: {rca_dict['confidence']:.0%}")
            if verbose:
                fallback = generate_fix_suggestions(info)
                if fallback:
                    print(f"    → Template kode (fallback):\n    {fallback}")
            print()

    if not violations_list and not import_errors:
        print(f"\n{COLOR['GREEN']}✅ Semua aggregate root memiliki event contract yang konsisten.{COLOR['RESET']}")

    print(f"  📈 Skor Kepatuhan Event Contract: {COLOR['CYAN']}{COLOR['BOLD']}{score:.1f}/100{COLOR['RESET']}")
    print(f"  RCA Engine: {'✅ aktif (v3.0.0)' if _RCA_AVAILABLE else '⚠️ tidak tersedia'}")

    # JSON export
    if json_output:
        payload = {
            "total_aggregates": total,
            "compliant": len(compliant),
            "violations_count": error_count,
            "import_errors": len(import_errors),
            "score": round(score, 1),
            "rca_available": _RCA_AVAILABLE,
            "violations": [
                {
                    "file": info.file_path,
                    "class": info.class_name,
                    "base_classes": info.base_classes,
                    "issues": info.violations,
                    "rca": [r.get("rca", {}) for r in info.rca_results]
                } for info in violations_list
            ],
            "import_errors": [
                {
                    "file": info.file_path,
                    "error": info.import_error,
                    "rca": info.rca_results[0].get("rca", {}) if info.rca_results else {}
                } for info in import_errors
            ]
        }
        try:
            with open(json_output, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            print(f"{COLOR['GREEN']}✅ Laporan JSON diekspor ke {json_output}{COLOR['RESET']}")
        except Exception as e:
            print(f"{COLOR['RED']}❌ Gagal menulis JSON: {e}{COLOR['RESET']}")

# =============================================================================
# Main CLI
# =============================================================================
def main() -> None:
    global _rca_engine, _RCA_AVAILABLE, _analyze_exception

    parser = argparse.ArgumentParser(
        description="Aggregate Event Contract Checker with RCA Integration v3.0.0"
    )
    parser.add_argument("--json", metavar="FILE", help="Ekspor laporan ke JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan detail tambahan")
    parser.add_argument("--no-rca", action="store_true", help="Nonaktifkan RCA analysis (lebih cepat)")
    args = parser.parse_args()

    # Nonaktifkan RCA jika diminta
    if args.no_rca:
        _rca_engine = None
        _analyze_exception = None
        _RCA_AVAILABLE = False

    start = time.monotonic()
    checker = AggregateEventContractChecker(ROOT, enable_rca=not args.no_rca)
    aggregates = checker.scan()
    elapsed = time.monotonic() - start

    print_report(aggregates, verbose=args.verbose, json_output=args.json)
    print(f"\n ⏱️ Waktu Audit: {elapsed:.3f} detik")

    # Exit code: 0 jika tidak ada error, 1 jika ada violations atau import errors
    has_error = any(
        a.violations or a.class_name == "<IMPORT_ERROR>"
        for a in aggregates
    )
    sys.exit(1 if has_error else 0)

if __name__ == "__main__":
    main()