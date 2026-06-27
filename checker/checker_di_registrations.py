#!/usr/bin/env python3
"""
Sovereign ERP System - Port Registration Checker (Final - 100% Akurat)
=======================================================================
Memeriksa apakah semua port (interface) di ports/primary dan ports/secondary
terdaftar di IoC container dan bisa di-resolve menjadi implementasi.

Fitur:
- Scan semua port dari filesystem (AST parsing)
- Filter port yang tidak perlu didaftarkan (InMemory, Fallback, Stub)
- Cek registrasi di container
- Resolve menggunakan async/await dengan benar
- Deteksi implementasi real vs fallback/in-memory
- Skor kepatuhan (0-100)
- Ekspor JSON

Cara pakai:
  python checker/checker_di_registrations.py
  python checker/checker_di_registrations.py --json report.json
  python checker/checker_di_registrations.py --verbose
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# =============================================================================
# Konfigurasi Root Project
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
# Data Classes
# =============================================================================
@dataclass
class PortInfo:
    name: str
    module: str
    file_path: str
    is_primary: bool

@dataclass
class RegistrationStatus:
    port: PortInfo
    registered: bool
    resolvable: bool
    implementation: Optional[str] = None
    is_fallback: bool = False
    is_ignored: bool = False  # Port yang diabaikan (InMemory, Fallback, Stub)
    error: Optional[str] = None

@dataclass
class CheckResult:
    total_ports: int
    ignored_count: int
    registered_count: int
    resolvable_count: int
    fallback_count: int
    unregistered_count: int
    details: List[RegistrationStatus]
    score: float
    errors: List[str]

# =============================================================================
# Scanner
# =============================================================================
class PortScanner:
    def __init__(self, root: Path):
        self.root = root
        self.exclude_names = {"BasePort", "BaseRepository", "BaseProtocol"}
        # Kata kunci yang menandakan ini bukan port yang harus didaftarkan
        self.ignore_keywords = {"InMemory", "Fallback", "Stub", "Mock"}

    def scan(self) -> List[PortInfo]:
        ports = []
        for base_dir, is_primary in [
            (self.root / "ports" / "primary", True),
            (self.root / "ports" / "secondary", False),
        ]:
            if not base_dir.exists():
                continue
            for file_path in base_dir.glob("*.py"):
                if file_path.name == "__init__.py":
                    continue
                try:
                    src = file_path.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(src, filename=str(file_path))
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef):
                            name = node.name
                            if name in self.exclude_names:
                                continue
                            # Hanya class yang berakhiran Port/Protocol/Repository
                            if name.endswith(("Port", "Protocol", "Repository")):
                                # Abaikan yang mengandung kata kunci ignore
                                if any(kw in name for kw in self.ignore_keywords):
                                    continue
                                module = str(file_path.relative_to(self.root).with_suffix("")).replace("\\", ".").replace("/", ".")
                                ports.append(PortInfo(
                                    name=name,
                                    module=module,
                                    file_path=str(file_path.relative_to(self.root)),
                                    is_primary=is_primary
                                ))
                except Exception:
                    continue
        return ports

# =============================================================================
# Container Checker
# =============================================================================
class ContainerChecker:
    def __init__(self):
        self.container = None
        self.registry = None
        self._registered_names: Optional[Set[str]] = None

    def setup(self) -> bool:
        try:
            from bootstrap.dependency_container.ioc_container import get_container
            from bootstrap.dependency_container.adapter_registry import get_adapter_registry
            self.container = get_container()
            self.registry = get_adapter_registry()
            return True
        except Exception as e:
            print(f"{COLOR['YELLOW']}⚠️ Gagal setup container: {e}{COLOR['RESET']}")
            return False

    def get_registered_types(self) -> Set[str]:
        if self._registered_names is not None:
            return self._registered_names
        if self.container is None:
            return set()
        names = set()
        for attr in ["_registry", "registry", "_services", "_instances", "_singletons"]:
            if hasattr(self.container, attr):
                reg = getattr(self.container, attr)
                if isinstance(reg, dict):
                    for key in reg.keys():
                        if hasattr(key, "__name__"):
                            names.add(key.__name__)
                        else:
                            names.add(str(key))
                elif isinstance(reg, (set, list)):
                    for item in reg:
                        if hasattr(item, "__name__"):
                            names.add(item.__name__)
                        else:
                            names.add(str(item))
        if hasattr(self.container, "get_registered_types"):
            try:
                types = self.container.get_registered_types()
                if isinstance(types, list):
                    for t in types:
                        names.add(t.__name__ if hasattr(t, "__name__") else str(t))
                elif isinstance(types, set):
                    for t in types:
                        names.add(t.__name__ if hasattr(t, "__name__") else str(t))
            except Exception:
                pass
        self._registered_names = names
        return names

    async def resolve_interface(self, port_name: str, port_module: str) -> Tuple[bool, Optional[str], Optional[str]]:
        if self.container is None:
            return False, None, "Container not initialized"
        try:
            mod = __import__(port_module, fromlist=[port_name])
            interface = getattr(mod, port_name, None)
            if interface is None:
                return False, None, f"Class {port_name} not found"
        except Exception as e:
            return False, None, f"Import error: {e}"

        instance = None
        error_msg = None

        if hasattr(self.container, "resolve_async"):
            try:
                instance = await self.container.resolve_async(interface)
            except Exception as e:
                error_msg = f"resolve_async failed: {e}"

        if instance is None and hasattr(self.container, "resolve"):
            try:
                instance = self.container.resolve(interface)
                error_msg = None
            except Exception as e:
                error_msg = f"resolve failed: {e}"

        if instance is None and hasattr(self.container, "get"):
            try:
                instance = self.container.get(interface)
                error_msg = None
            except Exception as e:
                error_msg = f"get failed: {e}"

        if instance is not None:
            return True, instance.__class__.__name__, None
        return False, None, error_msg or "Could not resolve"

# =============================================================================
# Main Checker
# =============================================================================
class PortRegistrationChecker:
    def __init__(self):
        self.scanner = PortScanner(ROOT)
        self.container_checker = ContainerChecker()
        self.result: Optional[CheckResult] = None

    async def run_checks(self) -> CheckResult:
        if not self.container_checker.setup():
            return CheckResult(0, 0, 0, 0, 0, 0, [], 0, ["Failed to setup container"])

        ports = self.scanner.scan()
        total = len(ports)
        registered_names = self.container_checker.get_registered_types()

        details: List[RegistrationStatus] = []
        ignored_count = 0
        registered_count = 0
        resolvable_count = 0
        fallback_count = 0
        unregistered_count = 0

        for port in ports:
            # Cek apakah port ini harus diabaikan (sudah difilter di scanner, tapi safety)
            is_ignored = False

            is_registered = port.name in registered_names
            resolvable = False
            impl = None
            is_fallback = False
            error = None

            if is_registered:
                registered_count += 1
                success, impl_class, err = await self.container_checker.resolve_interface(port.name, port.module)
                if success:
                    resolvable = True
                    resolvable_count += 1
                    impl = impl_class
                    if "InMemory" in impl or "Fallback" in impl or "Stub" in impl:
                        is_fallback = True
                        fallback_count += 1
                else:
                    error = err or "Resolve failed"
            else:
                # Coba implicit resolve
                success, impl_class, err = await self.container_checker.resolve_interface(port.name, port.module)
                if success:
                    is_registered = True
                    registered_count += 1
                    resolvable = True
                    resolvable_count += 1
                    impl = impl_class
                    if "InMemory" in impl or "Fallback" in impl or "Stub" in impl:
                        is_fallback = True
                        fallback_count += 1
                else:
                    unregistered_count += 1
                    error = err or "Not registered"

            details.append(RegistrationStatus(
                port=port,
                registered=is_registered,
                resolvable=resolvable,
                implementation=impl,
                is_fallback=is_fallback,
                is_ignored=is_ignored,
                error=error
            ))

        # Skor: berdasarkan resolvable_count - fallback_count, dibagi total_ports_aktual (total - ignored)
        actual_total = total - ignored_count
        score = ((resolvable_count - fallback_count) / actual_total * 100) if actual_total > 0 else 100.0

        self.result = CheckResult(
            total_ports=total,
            ignored_count=ignored_count,
            registered_count=registered_count,
            resolvable_count=resolvable_count,
            fallback_count=fallback_count,
            unregistered_count=unregistered_count,
            details=details,
            score=round(score, 1),
            errors=[]
        )
        return self.result

# =============================================================================
# Output
# =============================================================================
def print_report(result: CheckResult, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'═'*72}{c['RESET']}")
    print(f"{c['BOLD']}{c['CYAN']}  PORT REGISTRATION CHECKER REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'═'*72}{c['RESET']}")

    print(f"\n  Total Ports ditemukan   : {result.total_ports}")
    print(f"  Port diabaikan (InMemory, dll): {result.ignored_count}")
    print(f"  Terdaftar di container  : {result.registered_count}")
    print(f"  Bisa di-resolve         : {result.resolvable_count}")
    print(f"  Fallback (InMemory)     : {result.fallback_count}")
    print(f"  Tidak terdaftar         : {result.unregistered_count}")
    print(f"  📈 Skor Kepatuhan       : {c['CYAN']}{c['BOLD']}{result.score}/100{c['RESET']}")

    if result.errors:
        print(f"\n{c['RED']}❌ Errors:{c['RESET']}")
        for err in result.errors:
            print(f"    {err}")

    if verbose and result.details:
        print(f"\n{c['BOLD']}─── Detail per Port ───{c['RESET']}")
        for status in result.details:
            if status.is_ignored:
                print(f"  {c['BLUE']}⏭️ {status.port.name} ({status.port.file_path}) -> IGNORED{c['RESET']}")
                continue
            if status.registered and status.resolvable:
                if status.is_fallback:
                    icon = c['YELLOW'] + "⚠️" + c['RESET']
                    label = "fallback"
                else:
                    icon = c['GREEN'] + "✅" + c['RESET']
                    label = "real"
                print(f"  {icon} {status.port.name} ({status.port.file_path}) -> {label}")
                if status.implementation:
                    print(f"      Impl: {status.implementation}")
            elif status.registered and not status.resolvable:
                print(f"  {c['RED']}❌{c['RESET']} {status.port.name} ({status.port.file_path}) -> GAGAL RESOLVE")
                if status.error:
                    print(f"      Error: {status.error}")
            else:
                print(f"  {c['RED']}❌{c['RESET']} {status.port.name} ({status.port.file_path}) -> TIDAK TERDAFTAR")
                if status.error:
                    print(f"      Error: {status.error}")

    if result.unregistered_count == 0 and result.fallback_count == 0 and result.resolvable_count == (result.total_ports - result.ignored_count):
        print(f"\n{c['GREEN']}✅ Semua port terdaftar dengan implementasi nyata dan bisa di-resolve.{c['RESET']}")
    elif result.unregistered_count == 0 and result.fallback_count > 0:
        print(f"\n{c['YELLOW']}⚠️ Semua port terdaftar, tetapi {result.fallback_count} menggunakan fallback in-memory.{c['RESET']}")
    elif result.resolvable_count < result.registered_count:
        print(f"\n{c['RED']}❌ Ada {result.registered_count - result.resolvable_count} port terdaftar tapi gagal di-resolve.{c['RESET']}")
    else:
        print(f"\n{c['RED']}❌ Ada {result.unregistered_count} port tidak terdaftar dan {result.fallback_count} menggunakan fallback.{c['RESET']}")

def save_json(result: CheckResult, filepath: str):
    payload = {
        "score": result.score,
        "total_ports": result.total_ports,
        "ignored_count": result.ignored_count,
        "registered_count": result.registered_count,
        "resolvable_count": result.resolvable_count,
        "fallback_count": result.fallback_count,
        "unregistered_count": result.unregistered_count,
        "details": [
            {
                "port": s.port.name,
                "file": s.port.file_path,
                "registered": s.registered,
                "resolvable": s.resolvable,
                "implementation": s.implementation,
                "is_fallback": s.is_fallback,
                "is_ignored": s.is_ignored,
                "error": s.error
            }
            for s in result.details
        ],
        "errors": result.errors
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"{COLOR['GREEN']}✅ Laporan diekspor ke {filepath}{COLOR['RESET']}")

# =============================================================================
# Main CLI
# =============================================================================
async def async_main(args):
    checker = PortRegistrationChecker()
    result = await checker.run_checks()
    print_report(result, verbose=args.verbose)
    if args.json:
        save_json(result, args.json)
    # Exit code 0 jika tidak ada unregistered port atau fallback yang tidak diinginkan
    sys.exit(0 if result.unregistered_count == 0 and result.fallback_count == 0 and result.resolvable_count == (result.total_ports - result.ignored_count) else 1)

def main():
    parser = argparse.ArgumentParser(description="Port Registration Checker")
    parser.add_argument("--json", metavar="FILE", help="Ekspor laporan ke JSON")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail tambahan")
    args = parser.parse_args()

    start_time = time.monotonic()

    print(f"{COLOR['BOLD']}{COLOR['CYAN']}╔════════════════════════════════════════════════════════════════════╗")
    print(f"║      SOVEREIGN PORT REGISTRATION CHECKER                      ║")
    print(f"╚════════════════════════════════════════════════════════════════════╝{COLOR['RESET']}")

    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(1)

    elapsed = time.monotonic() - start_time
    print(f"\n ⏱️ Waktu Audit: {elapsed:.3f} detik")

if __name__ == "__main__":
    main()