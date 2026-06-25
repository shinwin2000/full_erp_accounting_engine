#!/usr/bin/env python3
"""
repository_checker.py - Repository Contract & Implementation Validator
========================================================================
Memeriksa kesesuaian antara repository interfaces (ports) dan implementasi
(adapters) pada proyek ERP Accounting Engine.

Fitur:
- Scan statis: daftar method di interface dan implementasi
- Pencocokan otomatis berdasarkan konvensi penamaan
- Cek method yang hilang atau ekstra (warning)
- Runtime import & instansiasi untuk deteksi error nyata
- Dukungan async (jika method bertanda async)

Cara pakai:
  python repository_checker.py                     # Jalankan semua pemeriksaan
  python repository_checker.py --verbose           # Tampilkan detail
  python repository_checker.py --check-runtime     # Aktifkan runtime check (default: on)
  python repository_checker.py --skip-runtime      # Hanya statis
  python repository_checker.py --json report.json  # Simpan hasil JSON
  python repository_checker.py --help              # Bantuan
"""

from __future__ import annotations

import argparse
import ast
import importlib
import json
import pathlib
import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

# =============================================================================
# Konfigurasi & Path
# =============================================================================
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
PORTS_DIR = PROJECT_ROOT / "ports" / "primary"
ADAPTERS_DIR = PROJECT_ROOT / "adapters" / "secondary_impl"

# Warna (jika colorama tersedia)
COLOR = {
    "RED": "",
    "GREEN": "",
    "YELLOW": "",
    "CYAN": "",
    "RESET": "",
}
try:
    import colorama
    colorama.init(autoreset=True)
    COLOR["RED"] = colorama.Fore.RED
    COLOR["GREEN"] = colorama.Fore.GREEN
    COLOR["YELLOW"] = colorama.Fore.YELLOW
    COLOR["CYAN"] = colorama.Fore.CYAN
    COLOR["RESET"] = colorama.Style.RESET_ALL
except ImportError:
    pass

# =============================================================================
# Data structures
# =============================================================================
@dataclass
class MethodInfo:
    name: str
    params: List[str]          # Nama parameter (tanpa self/cls)
    is_async: bool
    lineno: int
    decorators: List[str]      # Nama decorator (misal abstractmethod)
    docstring: Optional[str] = None

@dataclass
class InterfaceInfo:
    module: str                # Nama modul (misal ports.primary.journal_repository_port)
    class_name: str
    file_path: str
    methods: Dict[str, MethodInfo]

@dataclass
class ImplementationInfo:
    module: str
    class_name: str
    file_path: str
    methods: Dict[str, MethodInfo]

@dataclass
class ContractViolation:
    severity: str              # "ERROR" atau "WARNING"
    interface: str
    implementation: str
    message: str
    detail: str = ""

@dataclass
class RuntimeError:
    module: str
    error_type: str
    error_msg: str
    traceback: str = ""

@dataclass
class CheckResult:
    interfaces: List[InterfaceInfo]
    implementations: List[ImplementationInfo]
    violations: List[ContractViolation]
    runtime_errors: List[RuntimeError]
    matched_pairs: List[Tuple[str, str]]   # (interface_class, impl_class)
    unmatched_interfaces: List[str]
    unmatched_impls: List[str]

# =============================================================================
# Utilitas AST
# =============================================================================
def get_methods_from_class(tree: ast.AST, class_name: str) -> Dict[str, MethodInfo]:
    """Ekstrak semua method dari class dengan nama tertentu."""
    methods = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    # Skip magic methods? (opsional)
                    if item.name.startswith("__") and item.name != "__init__":
                        continue
                    params = []
                    for arg in item.args.args:
                        # Skip self/cls
                        if arg.arg in ("self", "cls"):
                            continue
                        params.append(arg.arg)
                    is_async = isinstance(item, ast.AsyncFunctionDef)
                    decorators = []
                    for dec in item.decorator_list:
                        if isinstance(dec, ast.Name):
                            decorators.append(dec.id)
                        elif isinstance(dec, ast.Attribute):
                            decorators.append(dec.attr)
                        elif isinstance(dec, ast.Call):
                            if isinstance(dec.func, ast.Name):
                                decorators.append(dec.func.id)
                            elif isinstance(dec.func, ast.Attribute):
                                decorators.append(dec.func.attr)
                    docstring = ast.get_docstring(item)
                    methods[item.name] = MethodInfo(
                        name=item.name,
                        params=params,
                        is_async=is_async,
                        lineno=item.lineno,
                        decorators=decorators,
                        docstring=docstring,
                    )
            break
    return methods

def parse_interface_file(file_path: pathlib.Path) -> Optional[InterfaceInfo]:
    """Parse file port dan ekstrak informasi interface (satu class per file)."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return None
    # Cari class yang mungkin interface (biasanya satu class per file)
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    if not classes:
        return None
    # Ambil class pertama (asumsi hanya satu class utama)
    cls = classes[0]
    methods = get_methods_from_class(tree, cls.name)
    # Tentukan modul name
    rel_path = file_path.relative_to(PROJECT_ROOT)
    module = str(rel_path.with_suffix("")).replace("/", ".")
    return InterfaceInfo(
        module=module,
        class_name=cls.name,
        file_path=str(file_path),
        methods=methods,
    )

def parse_impl_file(file_path: pathlib.Path) -> Optional[ImplementationInfo]:
    """Parse file implementasi dan ekstrak class implementasi."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return None
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    if not classes:
        return None
    # Ambil class pertama (asumsi satu class implementasi utama)
    cls = classes[0]
    methods = get_methods_from_class(tree, cls.name)
    rel_path = file_path.relative_to(PROJECT_ROOT)
    module = str(rel_path.with_suffix("")).replace("/", ".")
    return ImplementationInfo(
        module=module,
        class_name=cls.name,
        file_path=str(file_path),
        methods=methods,
    )

# =============================================================================
# Pencocokan interface ↔ implementasi
# =============================================================================
def match_interface_to_impl(interface: InterfaceInfo, impls: List[ImplementationInfo]) -> Optional[ImplementationInfo]:
    """
    Cari implementasi yang cocok untuk interface berdasarkan konvensi penamaan.
    Misal:
      - Interface: journal_repository_port   → Implementasi: sqlalchemy_journal_repository_impl
      - Atau: JournalRepositoryPort → SqlAlchemyJournalRepositoryImpl
    """
    base_name = interface.class_name
    # Hilangkan suffix "Port" atau "Repository" atau "_port"
    base = re.sub(r'(Port|Repository|_port|_repository)$', '', base_name, flags=re.IGNORECASE)
    # Coba berbagai pola
    candidates = []
    for impl in impls:
        impl_name = impl.class_name
        # Cocokkan jika nama impl mengandung base (case insensitive)
        if base.lower() in impl_name.lower():
            candidates.append(impl)
        # Cocokkan jika modul impl mengandung base
        elif base.lower() in impl.module.lower():
            candidates.append(impl)
    if len(candidates) == 1:
        return candidates[0]
    # Jika lebih dari satu, pilih yang paling mirip (misal yang diawali sqlalchemy_)
    for impl in candidates:
        if "sqlalchemy" in impl.module.lower():
            return impl
    # Jika tidak ada, kembalikan None
    return None

# =============================================================================
# Runtime checker (import & instantiate)
# =============================================================================
def try_import_and_instantiate(module_name: str, class_name: str) -> Optional[RuntimeError]:
    """
    Coba import modul dan instansiasi class.
    Mengembalikan RuntimeError jika terjadi error, None jika berhasil.
    """
    try:
        mod = importlib.import_module(module_name)
        cls = getattr(mod, class_name, None)
        if cls is None:
            return RuntimeError(
                module=module_name,
                error_type="AttributeError",
                error_msg=f"Class '{class_name}' not found in module '{module_name}'"
            )
        # Coba instansiasi (tanpa argumen)
        try:
            instance = cls()
            # Jika berhasil, kita tidak perlu apa-apa lagi
        except TypeError as e:
            # Mungkin konstruktor membutuhkan argumen; coba cek __init__ signature
            # Kita hanya catat sebagai warning, bukan error berat
            return RuntimeError(
                module=module_name,
                error_type="TypeError",
                error_msg=f"Failed to instantiate '{class_name}': {e}"
            )
        except Exception as e:
            return RuntimeError(
                module=module_name,
                error_type=type(e).__name__,
                error_msg=str(e),
                traceback=traceback.format_exc(),
            )
        return None
    except Exception as e:
        return RuntimeError(
            module=module_name,
            error_type=type(e).__name__,
            error_msg=str(e),
            traceback=traceback.format_exc(),
        )

# =============================================================================
# Analisis kontrak
# =============================================================================
def compare_methods(interface: InterfaceInfo, impl: ImplementationInfo) -> List[ContractViolation]:
    violations = []
    # Method di interface harus ada di implementasi
    for mname, mdef in interface.methods.items():
        if mname not in impl.methods:
            violations.append(ContractViolation(
                severity="ERROR",
                interface=interface.class_name,
                implementation=impl.class_name,
                message=f"Method '{mname}' missing in implementation",
                detail=f"Defined at {interface.file_path}:{mdef.lineno}"
            ))
        else:
            # Opsional: periksa parameter (kecuali *args, **kwargs)
            impl_method = impl.methods[mname]
            if len(mdef.params) != len(impl_method.params):
                violations.append(ContractViolation(
                    severity="WARNING",
                    interface=interface.class_name,
                    implementation=impl.class_name,
                    message=f"Parameter count mismatch for '{mname}'",
                    detail=f"Interface: {len(mdef.params)} params, Impl: {len(impl_method.params)} params"
                ))
            # Periksa async/await kesesuaian
            if mdef.is_async != impl_method.is_async:
                violations.append(ContractViolation(
                    severity="WARNING",
                    interface=interface.class_name,
                    implementation=impl.class_name,
                    message=f"Async mismatch for '{mname}'",
                    detail=f"Interface: {'async' if mdef.is_async else 'sync'}, Impl: {'async' if impl_method.is_async else 'sync'}"
                ))
    # Method tambahan di implementasi (opsional, hanya warning)
    for mname in impl.methods:
        if mname not in interface.methods:
            violations.append(ContractViolation(
                severity="WARNING",
                interface=interface.class_name,
                implementation=impl.class_name,
                message=f"Extra method '{mname}' in implementation",
                detail="Not defined in interface"
            ))
    return violations

# =============================================================================
# Main checker
# =============================================================================
def scan_repositories(check_runtime: bool = True) -> CheckResult:
    # 1. Kumpulkan semua interface
    interfaces = []
    if PORTS_DIR.exists():
        for py_file in PORTS_DIR.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
            info = parse_interface_file(py_file)
            if info and info.methods:
                interfaces.append(info)

    # 2. Kumpulkan semua implementasi
    implementations = []
    if ADAPTERS_DIR.exists():
        for py_file in ADAPTERS_DIR.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
            info = parse_impl_file(py_file)
            if info and info.methods:
                implementations.append(info)

    # 3. Match
    matched_pairs = []
    unmatched_interfaces = []
    unmatched_impls = set(impl.class_name for impl in implementations)
    violations = []
    runtime_errors = []

    for iface in interfaces:
        impl = match_interface_to_impl(iface, implementations)
        if impl:
            matched_pairs.append((iface.class_name, impl.class_name))
            unmatched_impls.discard(impl.class_name)
            # Check kontrak
            violations.extend(compare_methods(iface, impl))
            # Runtime check (jika diaktifkan)
            if check_runtime:
                err = try_import_and_instantiate(iface.module, iface.class_name)
                if err:
                    runtime_errors.append(err)
                err_impl = try_import_and_instantiate(impl.module, impl.class_name)
                if err_impl:
                    runtime_errors.append(err_impl)
        else:
            unmatched_interfaces.append(iface.class_name)

    # Implementasi tanpa pasangan
    unmatched_impls = list(unmatched_impls)

    return CheckResult(
        interfaces=interfaces,
        implementations=implementations,
        violations=violations,
        runtime_errors=runtime_errors,
        matched_pairs=matched_pairs,
        unmatched_interfaces=unmatched_interfaces,
        unmatched_impls=unmatched_impls,
    )

# =============================================================================
# Output & Report
# =============================================================================
def print_result(result: CheckResult, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*60}{c['RESET']}")
    print(f"{c['CYAN']}REPOSITORY CONTRACT CHECKER REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*60}{c['RESET']}")

    print(f"\n  Interfaces found    : {len(result.interfaces)}")
    print(f"  Implementations found: {len(result.implementations)}")
    print(f"  Matched pairs       : {len(result.matched_pairs)}")
    print(f"  Unmatched interfaces: {len(result.unmatched_interfaces)}")
    print(f"  Unmatched impls     : {len(result.unmatched_impls)}")

    if result.matched_pairs:
        print(f"\n{c['GREEN']}✓ Matched pairs:{c['RESET']}")
        for iface, impl in result.matched_pairs:
            print(f"    {iface}  ↔  {impl}")

    if result.unmatched_interfaces:
        print(f"\n{c['YELLOW']}⚠ Unmatched interfaces:{c['RESET']}")
        for name in result.unmatched_interfaces:
            print(f"    {name}")

    if result.unmatched_impls:
        print(f"\n{c['YELLOW']}⚠ Unmatched implementations:{c['RESET']}")
        for name in result.unmatched_impls:
            print(f"    {name}")

    # Violations
    if result.violations:
        print(f"\n{c['RED']}❌ Contract Violations ({len(result.violations)}):{c['RESET']}")
        for v in result.violations:
            color = c["RED"] if v.severity == "ERROR" else c["YELLOW"]
            print(f"  {color}[{v.severity}]{c['RESET']} {v.message}")
            print(f"       Interface: {v.interface}, Implementation: {v.implementation}")
            if v.detail:
                print(f"       Detail: {v.detail}")
            if verbose:
                # Tampilkan lokasi method
                pass
    else:
        print(f"\n{c['GREEN']}✓ No contract violations.{c['RESET']}")

    # Runtime errors
    if result.runtime_errors:
        print(f"\n{c['RED']}❌ Runtime Errors ({len(result.runtime_errors)}):{c['RESET']}")
        for err in result.runtime_errors:
            print(f"  {c['RED']}✖ {err.module}{c['RESET']}")
            print(f"     {err.error_type}: {err.error_msg}")
            if verbose and err.traceback:
                print(f"     {err.traceback}")
    else:
        print(f"\n{c['GREEN']}✓ No runtime errors.{c['RESET']}")

    # Summary
    total_errors = len([v for v in result.violations if v.severity == "ERROR"]) + len(result.runtime_errors)
    total_warnings = len([v for v in result.violations if v.severity == "WARNING"])

    print(f"\n{c['CYAN']}{'─'*60}{c['RESET']}")
    print(f"  Errors  : {c['RED']}{total_errors}{c['RESET']}")
    print(f"  Warnings: {c['YELLOW']}{total_warnings}{c['RESET']}")
    if total_errors == 0:
        print(f"  {c['GREEN']}✅ All repository contracts are satisfied.{c['RESET']}")
    else:
        print(f"  {c['RED']}❌ Fix the errors above before proceeding.{c['RESET']}")

def save_json(result: CheckResult, filepath: str):
    data = {
        "interfaces": [{"module": i.module, "class": i.class_name, "methods": list(i.methods.keys())} for i in result.interfaces],
        "implementations": [{"module": i.module, "class": i.class_name, "methods": list(i.methods.keys())} for i in result.implementations],
        "matched_pairs": result.matched_pairs,
        "unmatched_interfaces": result.unmatched_interfaces,
        "unmatched_impls": result.unmatched_impls,
        "violations": [
            {"severity": v.severity, "interface": v.interface, "implementation": v.implementation,
             "message": v.message, "detail": v.detail}
            for v in result.violations
        ],
        "runtime_errors": [
            {"module": e.module, "type": e.error_type, "message": e.error_msg}
            for e in result.runtime_errors
        ],
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{c['CYAN']}JSON report saved to {filepath}{c['RESET']}")

# =============================================================================
# Main CLI
# =============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Repository Contract Checker for ERP Accounting Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail tambahan")
    parser.add_argument("--skip-runtime", action="store_true", help="Lewati runtime import/instantiation check")
    parser.add_argument("--json", metavar="FILE", help="Simpan hasil dalam format JSON")
    parser.add_argument("--quiet", action="store_true", help="Minimal output (hanya error)")
    args = parser.parse_args()

    if args.quiet:
        # Redirect output? Kita tetap print tapi kita kontrol
        pass

    check_runtime = not args.skip_runtime
    start_time = time.monotonic()

    result = scan_repositories(check_runtime)

    if not args.quiet:
        print_result(result, verbose=args.verbose)

    if args.json:
        save_json(result, args.json)

    elapsed = time.monotonic() - start_time
    if not args.quiet:
        print(f"\n  Time: {elapsed:.2f}s")

    # Exit code: 0 if no errors, else 1
    errors = len([v for v in result.violations if v.severity == "ERROR"]) + len(result.runtime_errors)
    sys.exit(0 if errors == 0 else 1)

if __name__ == "__main__":
    main()