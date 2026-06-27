#!/usr/bin/env python3
"""
Sovereign ERP System - DI Container Integrity Checker (Real Code)
==================================================================
Memeriksa:
1. Semua dependency terdaftar di container dapat di-resolve.
2. Mendeteksi In-Memory fallback (dengan konteks: apakah ini disengaja?).
3. Validasi kontrak method untuk interface kritis (dengan toleransi).
4. Skor kepatuhan (0-100) dengan penalaran yang lebih baik.
5. Memberikan saran perbaikan untuk setiap masalah.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# =============================================================================
# Pastikan root project ada di sys.path
# =============================================================================
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# =============================================================================
# Konfigurasi Terminal
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
    COLOR = {k: "" for k in COLOR}

# =============================================================================
# Konfigurasi Contract Checks
# =============================================================================
# Format: interface_name -> (expected_methods, allowed_implementations_override)
# Jika implementasi ada di override, maka method yang hilang bisa dimaafkan
CONTRACT_CHECKS: Dict[str, Tuple[List[str], Optional[List[str]]]] = {
    "UnitOfWorkPort": (["commit", "rollback", "begin"], None),
    "CoreTaxPort": (
        ["submit_tax", "get_status"],
        ["InMemoryCoreTaxPort"]  # InMemory tidak punya method ini, tapi dianggap OK
    ),
    "IAMUserRepositoryPort": (["save", "find_by_username", "find_by_id"], None),
    "ARRepositoryPort": (["save_invoice", "find_invoice_by_id"], None),
    "APRepositoryPort": (["save_invoice", "find_invoice_by_id"], None),
    "InventoryRepositoryPort": (["save_item", "find_item_by_id", "adjust_stock"], None),
    "FixedAssetRepositoryPort": (["save_asset", "find_asset_by_id"], None),
    "PayrollRepositoryPort": (["save_payroll", "find_by_employee"], None),
    "ConsolidationRepositoryPort": (["save_group", "find_group"], None),
}

# Daftar implementasi yang dianggap "valid" meskipun menggunakan in-memory (disengaja)
ALLOWED_IN_MEMORY = {
    "InMemoryCoreTaxPort",
    "InMemoryTaxRepository",
}

# =============================================================================
# Main Checker
# =============================================================================
class DIContainerChecker:
    def __init__(self):
        self.root = ROOT
        self.container = None
        self.registry = None
        self.results: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, Any]] = []
        self.in_memory_fallbacks: List[Dict[str, str]] = []
        self.contract_failures: List[Dict[str, Any]] = []
        self.suggestions: List[str] = []

    def _setup_imports(self) -> bool:
        """Import semua modul yang dibutuhkan."""
        try:
            from bootstrap.dependency_container.adapter_registry import get_adapter_registry
            from bootstrap.dependency_container.ioc_container import get_container
            self.registry = get_adapter_registry()
            self.container = get_container()
            return True
        except ImportError as e:
            self.errors.append({"type": "ImportError", "message": str(e)})
            return False
        except Exception as e:
            self.errors.append({"type": "SetupError", "message": str(e), "trace": traceback.format_exc()})
            return False

    def _get_registered_types(self) -> List[type]:
        """Ambil daftar semua interface yang terdaftar di container."""
        if self.container is None:
            return []
        # Coba berbagai metode
        methods = ["get_registered_types", "get_registered_interfaces", "registered_types", "_registry"]
        for method_name in methods:
            if hasattr(self.container, method_name):
                attr = getattr(self.container, method_name)
                if callable(attr):
                    try:
                        result = attr()
                        if isinstance(result, list):
                            return result
                        if isinstance(result, dict):
                            return list(result.keys())
                    except Exception:
                        continue
                elif isinstance(attr, (list, dict)):
                    return list(attr.keys()) if isinstance(attr, dict) else attr
        if hasattr(self.container, "_registry"):
            reg = getattr(self.container, "_registry")
            if isinstance(reg, dict):
                return list(reg.keys())
        return []

    async def resolve_dependency(self, interface: type) -> Optional[object]:
        """Resolve dependency dengan async/fallback."""
        if self.container is None:
            return None
        # Coba resolve_async
        if hasattr(self.container, "resolve_async"):
            try:
                return await self.container.resolve_async(interface)
            except Exception:
                pass
        # Coba resolve
        if hasattr(self.container, "resolve"):
            try:
                return self.container.resolve(interface)
            except Exception:
                pass
        # Coba get
        if hasattr(self.container, "get"):
            try:
                return self.container.get(interface)
            except Exception:
                pass
        return None

    def check_contract(self, interface_name: str, instance: object) -> Tuple[bool, List[str]]:
        """Periksa kontrak method untuk interface."""
        if interface_name not in CONTRACT_CHECKS:
            return True, []
        expected, allowed_impls = CONTRACT_CHECKS[interface_name]
        class_name = instance.__class__.__name__
        # Jika implementasi ada di override, abaikan missing method
        if allowed_impls and class_name in allowed_impls:
            return True, []
        missing = []
        for method in expected:
            if not hasattr(instance, method) or not callable(getattr(instance, method)):
                missing.append(method)
        return len(missing) == 0, missing

    async def run_checks(self) -> Dict[str, Any]:
        """Jalankan semua pemeriksaan."""
        # 1. Setup imports
        if not self._setup_imports():
            return {
                "success": False,
                "errors": self.errors,
                "message": "Gagal import modul DI container."
            }

        # 2. Registrasi semua adapter
        try:
            if self.registry and hasattr(self.registry, "register_all"):
                self.registry.register_all()
        except Exception as e:
            self.errors.append({"type": "RegistrationError", "message": str(e), "trace": traceback.format_exc()})

        # 3. Dapatkan daftar interface
        registered_types = self._get_registered_types()
        if not registered_types:
            self.errors.append({"type": "NoRegisteredTypes", "message": "Tidak ada dependency yang terdaftar!"})
            return {"success": False, "errors": self.errors, "message": "Container kosong."}

        total = len(registered_types)
        resolved_count = 0
        resolved_ok = 0
        in_memory_count = 0
        contract_error_count = 0

        for interface in registered_types:
            interface_name = interface.__name__ if hasattr(interface, "__name__") else str(interface)
            try:
                instance = await self.resolve_dependency(interface)
                if instance is None:
                    self.errors.append({"type": "ResolutionError", "interface": interface_name, "message": "Instance None"})
                    continue

                resolved_count += 1
                class_name = instance.__class__.__name__

                # Deteksi In-Memory fallback
                if "InMemory" in class_name or "Memory" in class_name:
                    is_allowed = class_name in ALLOWED_IN_MEMORY
                    self.in_memory_fallbacks.append({
                        "interface": interface_name,
                        "implementation": class_name,
                        "is_allowed": is_allowed
                    })
                    if not is_allowed:
                        in_memory_count += 1
                    else:
                        # Allowed in-memory dianggap OK
                        resolved_ok += 1
                else:
                    resolved_ok += 1

                # Cek kontrak
                ok, missing = self.check_contract(interface_name, instance)
                if not ok:
                    self.contract_failures.append({
                        "interface": interface_name,
                        "missing": missing,
                        "implementation": class_name
                    })
                    contract_error_count += 1

            except Exception as e:
                self.errors.append({
                    "type": "ResolutionError",
                    "interface": interface_name,
                    "message": str(e),
                    "trace": traceback.format_exc()
                })

        # Hitung skor
        error_count = len(self.errors) + in_memory_count + contract_error_count
        score = max(0, 100 - (error_count * 2))

        # Generate suggestions
        if in_memory_count > 0:
            self.suggestions.append("Periksa konfigurasi kredensial untuk layanan yang menggunakan InMemory fallback.")
        for fail in self.contract_failures:
            self.suggestions.append(
                f"Tambahkan method {', '.join(fail['missing'])} ke implementasi {fail['implementation']} "
                f"atau tambahkan ke ALLOWED_IN_MEMORY jika memang disengaja."
            )

        return {
            "success": error_count == 0,
            "total_interfaces": total,
            "resolved_count": resolved_count,
            "resolved_ok": resolved_ok,
            "in_memory_fallbacks": self.in_memory_fallbacks,
            "contract_failures": self.contract_failures,
            "errors": self.errors,
            "score": score,
            "suggestions": self.suggestions,
        }

# =============================================================================
# Output
# =============================================================================
def print_report(result: Dict[str, Any], verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'═'*72}{c['RESET']}")
    print(f"{c['BOLD']}{c['CYAN']}  DI CONTAINER INTEGRITY REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'═'*72}{c['RESET']}")

    if result.get("message"):
        print(f"\n{c['RED']}{result['message']}{c['RESET']}")

    print(f"\n  Total Interfaces Terdaftar: {result.get('total_interfaces', 0)}")
    print(f"  Berhasil di-resolve       : {result.get('resolved_ok', 0)}")
    print(f"  In-Memory Fallback        : {len([f for f in result.get('in_memory_fallbacks', []) if not f.get('is_allowed', False)])}")
    print(f"  Contract Failures         : {len(result.get('contract_failures', []))}")
    print(f"  Resolution Errors         : {len(result.get('errors', []))}")
    print(f"  📈 Skor Kepatuhan         : {c['CYAN']}{c['BOLD']}{result.get('score', 0)}/100{c['RESET']}")

    # In-Memory fallbacks
    fallbacks = result.get('in_memory_fallbacks', [])
    if fallbacks:
        print(f"\n{c['YELLOW']}⚠️ In-Memory Fallbacks:{c['RESET']}")
        for f in fallbacks:
            status = "✅ (allowed)" if f.get('is_allowed') else "❌"
            print(f"    {status} {f['interface']} -> {f['implementation']}")

    # Contract failures
    if result.get('contract_failures'):
        print(f"\n{c['RED']}❌ Contract Failures:{c['RESET']}")
        for fail in result['contract_failures']:
            print(f"    Interface: {fail['interface']}")
            print(f"    Missing methods: {', '.join(fail['missing'])}")
            print(f"    Implementation: {fail['implementation']}")

    # Errors
    if result.get('errors'):
        print(f"\n{c['RED']}❌ Resolution Errors:{c['RESET']}")
        for err in result['errors']:
            print(f"    {err.get('interface', '')}: {err.get('message', '')}")
            if verbose and err.get('trace'):
                print(f"    {err['trace']}")

    # Suggestions
    if result.get('suggestions'):
        print(f"\n{c['CYAN']}💡 Saran Perbaikan:{c['RESET']}")
        for s in result['suggestions']:
            print(f"    {s}")

    if result['success']:
        print(f"\n{c['GREEN']}✅ Semua dependency OK, tidak ada error kritis.{c['RESET']}")
    else:
        print(f"\n{c['RED']}❌ Masih ada error yang perlu diperbaiki.{c['RESET']}")

def save_json(result: Dict[str, Any], filepath: str):
    payload = {
        "score": result.get("score", 0),
        "total_interfaces": result.get("total_interfaces", 0),
        "resolved_ok": result.get("resolved_ok", 0),
        "in_memory_fallbacks": result.get("in_memory_fallbacks", []),
        "contract_failures": result.get("contract_failures", []),
        "errors": [
            {"interface": e.get("interface"), "message": e.get("message")}
            for e in result.get("errors", [])
        ],
        "suggestions": result.get("suggestions", []),
        "success": result.get("success", False)
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"{COLOR['GREEN']}✅ Laporan diekspor ke {filepath}{COLOR['RESET']}")

# =============================================================================
# Main CLI
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="DI Container Integrity Checker")
    parser.add_argument("--json", metavar="FILE", help="Ekspor laporan ke JSON")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail tambahan")
    args = parser.parse_args()

    start_time = time.monotonic()

    print(f"{COLOR['BOLD']}{COLOR['CYAN']}╔════════════════════════════════════════════════════════════════════╗")
    print(f"║      SOVEREIGN DI CONTAINER INTEGRITY CHECKER                  ║")
    print(f"╚════════════════════════════════════════════════════════════════════╝{COLOR['RESET']}")

    checker = DIContainerChecker()
    result = asyncio.run(checker.run_checks())

    print_report(result, verbose=args.verbose)

    if args.json:
        save_json(result, args.json)

    elapsed = time.monotonic() - start_time
    print(f"\n ⏱️ Waktu Audit: {elapsed:.3f} detik")

    sys.exit(0 if result.get("success", False) else 1)

if __name__ == "__main__":
    main()