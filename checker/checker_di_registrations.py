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
- RCA integration (analisis root cause untuk setiap error)

Cara pakai:
  python checker/checker_di_registrations.py
  python checker/checker_di_registrations.py --json report.json
  python checker/checker_di_registrations.py --verbose
  python checker/checker_di_registrations.py --no-rca   # nonaktifkan RCA
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import importlib.util
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# =============================================================================
# [RCA] Load RCA Engine dari checker/core/rca.py menggunakan importlib.util
# =============================================================================
# =============================================================================
# [RCA] Load RCA Engine dari checker/core/rca.py
# =============================================================================
_RCA_AVAILABLE = False
_analyze_exception = None
_RCAEngine = None

def _load_rca_from_file():
    global _RCA_AVAILABLE, _analyze_exception, _RCAEngine
    rca_path = Path(__file__).resolve().parent / "core" / "rca.py"
    if not rca_path.exists():
        print(f"⚠️  RCA file not found at {rca_path}")
        return False

    # Coba import normal dengan menambahkan path
    sys.path.insert(0, str(rca_path.parent))
    try:
        import rca as rca_module
        _analyze_exception = getattr(rca_module, "analyze_exception", None)
        _RCAEngine = getattr(rca_module, "RCAEngine", None)
        if _analyze_exception is not None and _RCAEngine is not None:
            _RCA_AVAILABLE = True
            print("✅ RCA Engine loaded via normal import")
            return True
        else:
            print("⚠️  RCA module loaded but required attributes missing")
            return False
    except ImportError as e:
        print(f"⚠️  Normal import failed: {e}")
        # Fallback ke importlib.util
        try:
            spec = importlib.util.spec_from_file_location("rca", rca_path)
            if spec is None or spec.loader is None:
                print("⚠️  Failed to create spec for rca.py")
                return False
            rca_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(rca_module)
            _analyze_exception = getattr(rca_module, "analyze_exception", None)
            _RCAEngine = getattr(rca_module, "RCAEngine", None)
            if _analyze_exception is not None and _RCAEngine is not None:
                _RCA_AVAILABLE = True
                print("✅ RCA Engine loaded via importlib.util")
                return True
            else:
                print("⚠️  RCA module loaded but required attributes missing")
                return False
        except Exception as e:
            import traceback
            print(f"⚠️  RCA load error: {e}")
            traceback.print_exc()
            return False
    except Exception as e:
        import traceback
        print(f"⚠️  RCA load error: {e}")
        traceback.print_exc()
        return False

_load_rca_from_file()

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
    "DIM": "\033[2m",
    "RESET": "\033[0m"
}
if not sys.stdout.isatty():
    COLOR = dict.fromkeys(COLOR, "")

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
    implementation: str | None = None
    is_fallback: bool = False
    is_ignored: bool = False
    error: str | None = None
    rca_result: dict[str, Any] | None = None

@dataclass
class CheckResult:
    total_ports: int
    ignored_count: int
    registered_count: int
    resolvable_count: int
    fallback_count: int
    unregistered_count: int
    details: list[RegistrationStatus]
    score: float
    errors: list[str]

# =============================================================================
# Scanner
# =============================================================================
class PortScanner:
    def __init__(self, root: Path):
        self.root = root
        self.exclude_names = {"BasePort", "BaseRepository", "BaseProtocol"}
        self.ignore_keywords = {"InMemory", "Fallback", "Stub", "Mock"}

    def scan(self) -> list[PortInfo]:
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
                            if name.endswith(("Port", "Protocol", "Repository")):
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
        self._registered_names: set[str] | None = None

    def setup(self) -> bool:
        try:
            from bootstrap.dependency_container.adapter_registry import get_adapter_registry
            from bootstrap.dependency_container.ioc_container import get_container
            self.container = get_container()
            self.registry = get_adapter_registry()
            return True
        except Exception as e:
            print(f"{COLOR['YELLOW']}⚠️ Gagal setup container: {e}{COLOR['RESET']}")
            return False

    def get_registered_types(self) -> set[str]:
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
                if isinstance(types, list) or isinstance(types, set):
                    for t in types:
                        names.add(t.__name__ if hasattr(t, "__name__") else str(t))
            except Exception:
                pass
        self._registered_names = names
        return names

    async def resolve_interface(self, port_name: str, port_module: str, rca_engine=None) -> tuple[bool, str | None, str | None, dict | None]:
        if self.container is None:
            return False, None, "Container not initialized", None

        try:
            mod = __import__(port_module, fromlist=[port_name])
            interface = getattr(mod, port_name, None)
            if interface is None:
                return False, None, f"Class {port_name} not found", None
        except Exception as e:
            rca = None
            if rca_engine is not None and _RCA_AVAILABLE and callable(getattr(rca_engine, "analyze", None)):
                try:
                    rca_result = rca_engine.analyze(e, {"port_name": port_name, "module": port_module})
                    rca = rca_result.to_dict() if hasattr(rca_result, "to_dict") else None
                except Exception:
                    pass
            return False, None, f"Import error: {e}", rca

        instance = None
        error_msg = None
        rca_data = None

        if hasattr(self.container, "resolve_async"):
            try:
                instance = await self.container.resolve_async(interface)
            except Exception as e:
                error_msg = f"resolve_async failed: {e}"
                if rca_engine is not None and _RCA_AVAILABLE and callable(getattr(rca_engine, "analyze", None)):
                    try:
                        rca_result = rca_engine.analyze(e, {"port_name": port_name, "module": port_module, "method": "resolve_async"})
                        rca_data = rca_result.to_dict() if hasattr(rca_result, "to_dict") else None
                    except Exception:
                        pass
        else:
            if hasattr(self.container, "resolve"):
                try:
                    instance = self.container.resolve(interface)
                except Exception as e:
                    error_msg = f"resolve failed: {e}"
                    if rca_engine is not None and _RCA_AVAILABLE and callable(getattr(rca_engine, "analyze", None)):
                        try:
                            rca_result = rca_engine.analyze(e, {"port_name": port_name, "module": port_module, "method": "resolve"})
                            rca_data = rca_result.to_dict() if hasattr(rca_result, "to_dict") else None
                        except Exception:
                            pass
            elif hasattr(self.container, "get"):
                try:
                    instance = self.container.get(interface)
                except Exception as e:
                    error_msg = f"get failed: {e}"
                    if rca_engine is not None and _RCA_AVAILABLE and callable(getattr(rca_engine, "analyze", None)):
                        try:
                            rca_result = rca_engine.analyze(e, {"port_name": port_name, "module": port_module, "method": "get"})
                            rca_data = rca_result.to_dict() if hasattr(rca_result, "to_dict") else None
                        except Exception:
                            pass

        if instance is not None:
            return True, instance.__class__.__name__, None, None
        return False, None, error_msg or "Could not resolve", rca_data

# =============================================================================
# Main Checker
# =============================================================================
class PortRegistrationChecker:
    def __init__(self, enable_rca: bool = True):
        self.scanner = PortScanner(ROOT)
        self.container_checker = ContainerChecker()
        self.result: CheckResult | None = None
        self.enable_rca = enable_rca and _RCA_AVAILABLE and _RCAEngine is not None
        self.rca_engine = _RCAEngine() if self.enable_rca else None

    async def run_checks(self) -> CheckResult:
        if not self.container_checker.setup():
            return CheckResult(0, 0, 0, 0, 0, 0, [], 0, ["Failed to setup container"])

        ports = self.scanner.scan()
        total = len(ports)
        registered_names = self.container_checker.get_registered_types()

        details: list[RegistrationStatus] = []
        ignored_count = 0
        registered_count = 0
        resolvable_count = 0
        fallback_count = 0
        unregistered_count = 0

        for port in ports:
            is_ignored = False
            is_registered = port.name in registered_names
            resolvable = False
            impl = None
            is_fallback = False
            error = None
            rca_data = None

            if is_registered:
                registered_count += 1
                success, impl_class, err, rca = await self.container_checker.resolve_interface(
                    port.name, port.module, self.rca_engine
                )
                if success:
                    resolvable = True
                    resolvable_count += 1
                    impl = impl_class
                    if "InMemory" in impl or "Fallback" in impl or "Stub" in impl:
                        is_fallback = True
                        fallback_count += 1
                else:
                    error = err or "Resolve failed"
                    rca_data = rca
            else:
                # Coba implicit resolve
                success, impl_class, err, rca = await self.container_checker.resolve_interface(
                    port.name, port.module, self.rca_engine
                )
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
                    rca_data = rca

            details.append(RegistrationStatus(
                port=port,
                registered=is_registered,
                resolvable=resolvable,
                implementation=impl,
                is_fallback=is_fallback,
                is_ignored=is_ignored,
                error=error,
                rca_result=rca_data
            ))

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
    print(f"  RCA Engine          : {'✅ Aktif' if _RCA_AVAILABLE else '⚠️  Tidak tersedia'}")

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
                if status.rca_result and isinstance(status.rca_result, dict):
                    root_cause = status.rca_result.get("root_cause", "")
                    fix = status.rca_result.get("suggested_fix", "")
                    conf = status.rca_result.get("confidence", 0)
                    if root_cause:
                        print(f"      {c['CYAN']}RCA:{c['RESET']} {root_cause[:200]}")
                    if fix:
                        print(f"      {c['YELLOW']}Fix:{c['RESET']} {fix[:200]}")
                    if conf:
                        # Gunakan .get() untuk menghindari KeyError
                        dim_color = c.get('DIM', '')
                        print(f"      {dim_color}Confidence: {conf:.0%}{c['RESET']}")
            else:
                print(f"  {c['RED']}❌{c['RESET']} {status.port.name} ({status.port.file_path}) -> TIDAK TERDAFTAR")
                if status.error:
                    print(f"      Error: {status.error}")
                if status.rca_result and isinstance(status.rca_result, dict):
                    root_cause = status.rca_result.get("root_cause", "")
                    fix = status.rca_result.get("suggested_fix", "")
                    conf = status.rca_result.get("confidence", 0)
                    if root_cause:
                        print(f"      {c['CYAN']}RCA:{c['RESET']} {root_cause[:200]}")
                    if fix:
                        print(f"      {c['YELLOW']}Fix:{c['RESET']} {fix[:200]}")
                    if conf:
                        dim_color = c.get('DIM', '')
                        print(f"      {dim_color}Confidence: {conf:.0%}{c['RESET']}")

    # Deteksi duplikasi port
    port_names = {}
    duplicate_suggestions = []
    for status in result.details:
        name = status.port.name
        if name not in port_names:
            port_names[name] = []
        port_names[name].append(status.port.file_path)
    for name, files in port_names.items():
        if len(files) > 1:
            duplicate_suggestions.append(
                f"⚠️  Port '{name}' didefinisikan di {len(files)} file: {', '.join(files)}. "
                f"Hapus atau rename salah satu untuk menghindari konflik."
            )

    if duplicate_suggestions:
        print(f"\n{c['YELLOW']}─── Saran Perbaikan ───{c['RESET']}")
        for sug in duplicate_suggestions:
            print(f"  {c['YELLOW']}{sug}{c['RESET']}")

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
        "rca_available": _RCA_AVAILABLE,
        "details": [
            {
                "port": s.port.name,
                "file": s.port.file_path,
                "registered": s.registered,
                "resolvable": s.resolvable,
                "implementation": s.implementation,
                "is_fallback": s.is_fallback,
                "is_ignored": s.is_ignored,
                "error": s.error,
                "rca": s.rca_result,
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
    checker = PortRegistrationChecker(enable_rca=not args.no_rca)
    result = await checker.run_checks()
    print_report(result, verbose=args.verbose)
    if args.json:
        save_json(result, args.json)
    sys.exit(0 if result.unregistered_count == 0 and result.fallback_count == 0 and result.resolvable_count == (result.total_ports - result.ignored_count) else 1)

def main():
    parser = argparse.ArgumentParser(description="Port Registration Checker with RCA")
    parser.add_argument("--json", metavar="FILE", help="Ekspor laporan ke JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan detail tambahan")
    parser.add_argument("--no-rca", action="store_true", help="Nonaktifkan RCA analysis")
    args = parser.parse_args()

    start_time = time.monotonic()

    print(f"{COLOR['BOLD']}{COLOR['CYAN']}╔════════════════════════════════════════════════════════════════════╗")
    print("║      SOVEREIGN PORT REGISTRATION CHECKER with RCA              ║")
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
