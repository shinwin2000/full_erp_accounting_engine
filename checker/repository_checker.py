#!/usr/bin/env python3
"""
Sovereign ERP System - Repository Contract Checker (Akurat)
============================================================
- Scan interface di ports/primary (class berakhiran Port/Protocol dan mengandung repository/store/cache)
- Scan implementasi di adapters/secondary_impl (class berakhiran Adapter/Impl/Repository/Store/Cache)
- Normalisasi nama: hilangkan prefix/suffix umum
- Pencocokan: exact match base_name, lalu partial match
- Periksa method public yang hilang di implementasi
- Periksa signature (parameter wajib, async) hanya sebagai warning
- Skor: proporsi interface yang match & bebas error
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import pathlib
import sys
import time
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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

EXCLUDED_DIRS = {"checker", "tests", "migrations", "__pycache__", ".git", "docs", "scripts",
                 "deployment", "monitoring", "reports"}

INFRASTRUCTURE_KEYWORDS = {
    "s3", "file", "storage", "kafka", "email", "smtp", "slack", "whatsapp",
    "notification", "pagerduty", "glacier", "cold", "backup", "event", "publisher",
    "consumer", "dead", "letter", "broker", "message", "cache", "redis", "memcached",
    "audit", "append", "snapshot", "mt940", "parser", "encryption", "keyvault",
    "hashicorp", "hsm", "minio", "coretax", "authority", "bank_api", "timestamp",
    "notary", "hashchain", "saga", "cqrs", "analytics", "read_model", "projection",
    "connection_pool", "replica", "router", "fiscal", "report", "approval",
    "goods_receipt", "sales", "customer_category", "event_status", "file_storage_status",
    "notification_channel", "sales_repository_adapter", "iam_repository_adapter",
    "unit_of_work", "cohort", "export", "import", "adapter"
}

@dataclass
class MethodInfo:
    name: str
    required_count: int   # jumlah parameter wajib (tanpa default)
    kwonly_count: int     # jumlah keyword-only parameters
    total_count: int      # total parameter (untuk display)
    is_async: bool
    lineno: int

@dataclass
class InterfaceInfo:
    name: str
    file_path: str
    module: str
    methods: dict[str, MethodInfo]
    base_name: str

@dataclass
class ImplementationInfo:
    name: str
    file_path: str
    module: str
    methods: dict[str, MethodInfo]
    is_infrastructure: bool = False
    base_name: str = ""

@dataclass
class Violation:
    severity: str  # "ERROR" atau "WARNING"
    interface: str
    implementation: str
    message: str
    detail: str = ""

# -----------------------------------------------------------------------------
# Utility
# -----------------------------------------------------------------------------

def is_infrastructure(name: str, file_path: str) -> bool:
    name_lower = name.lower()
    file_lower = str(file_path).lower()
    if "repository" in name_lower:
        return False
    for kw in INFRASTRUCTURE_KEYWORDS:
        if kw in name_lower or kw in file_lower:
            return True
    return True

def normalize_interface(name: str) -> str:
    for suffix in ["Port", "Protocol", "Repository", "Store", "Cache"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    if name.endswith("Repository"):
        name = name[:-len("Repository")]
    return name.lower().strip()

def normalize_impl(name: str) -> str:
    for prefix in ["SQLAlchemy", "Postgres", "AsyncPG", "InMemory", "Hashicorp",
                   "Customer", "Supplier", "Coretax", "Tax", "S3", "Redis",
                   "Kafka", "Email", "Slack", "WhatsApp", "PagerDuty", "MinIO",
                   "Glacier", "HSM", "Timestamp"]:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    for suffix in ["Adapter", "Impl", "Repository", "Store", "Cache"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break
    return name.lower().strip()

def extract_methods_from_class(tree: ast.AST, class_name: str) -> dict[str, MethodInfo]:
    """Extract public methods, hitung parameter wajib dan keyword-only."""
    methods = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name.startswith("_") and item.name != "__init__":
                        continue
                    if item.name == "__init__":
                        continue

                    # Hitung parameter
                    total_pos = len(item.args.args)
                    num_defaults = len(item.args.defaults)
                    offset = 1 if total_pos > 0 and item.args.args[0].arg in ("self", "cls") else 0
                    required = total_pos - num_defaults - offset
                    if required < 0:
                        required = 0
                    kwonly_count = len(item.args.kwonlyargs)

                    is_async = isinstance(item, ast.AsyncFunctionDef)
                    methods[item.name] = MethodInfo(
                        name=item.name,
                        required_count=required,
                        kwonly_count=kwonly_count,
                        total_count=total_pos - offset,
                        is_async=is_async,
                        lineno=item.lineno,
                    )
            break
    return methods

# -----------------------------------------------------------------------------
# Scanner
# -----------------------------------------------------------------------------

def scan_interfaces() -> list[InterfaceInfo]:
    interfaces = []
    ports_dir = ROOT / "ports" / "primary"
    if not ports_dir.exists():
        return interfaces

    seen = set()
    for py_file in ports_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        try:
            src = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(py_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                name = node.name
                if name in seen:
                    continue
                is_repo_port = (
                    (name.endswith("Port") or name.endswith("Protocol")) and
                    ("repository" in name.lower() or "store" in name.lower() or "cache" in name.lower())
                )
                if is_repo_port:
                    methods = extract_methods_from_class(tree, name)
                    if methods:
                        rel_path = py_file.relative_to(ROOT)
                        module = str(rel_path.with_suffix("")).replace(os.sep, ".")
                        base_name = normalize_interface(name)
                        interfaces.append(InterfaceInfo(
                            name=name,
                            file_path=str(py_file),
                            module=module,
                            methods=methods,
                            base_name=base_name,
                        ))
                        seen.add(name)
    return interfaces

def scan_implementations() -> list[ImplementationInfo]:
    impls = []
    adapters_dir = ROOT / "adapters" / "secondary_impl"
    if not adapters_dir.exists():
        return impls

    seen = set()
    for py_file in adapters_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        try:
            src = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(py_file))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                name = node.name
                if name in seen:
                    continue
                if name.endswith(("Adapter", "Impl", "Repository", "Store", "Cache")):
                    methods = extract_methods_from_class(tree, name)
                    if methods:
                        rel_path = py_file.relative_to(ROOT)
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
                        ))
                        seen.add(name)
    return impls

# -----------------------------------------------------------------------------
# Matching
# -----------------------------------------------------------------------------

def match_interface_to_impl(interface: InterfaceInfo, impls: list[ImplementationInfo]) -> ImplementationInfo | None:
    base_iface = interface.base_name
    exact_matches = []
    partial_matches = []

    for impl in impls:
        if impl.is_infrastructure:
            continue
        base_impl = impl.base_name
        if base_iface == base_impl:
            exact_matches.append(impl)
        elif len(base_iface) >= 3 and (base_iface in base_impl or base_impl in base_iface):
            partial_matches.append(impl)

    if exact_matches:
        for impl in exact_matches:
            if "sqlalchemy" in impl.name.lower():
                return impl
        return exact_matches[0]
    if partial_matches:
        for impl in partial_matches:
            if "sqlalchemy" in impl.name.lower():
                return impl
        return partial_matches[0]
    return None

# -----------------------------------------------------------------------------
# Compare
# -----------------------------------------------------------------------------

def compare_methods(interface: InterfaceInfo, impl: ImplementationInfo) -> list[Violation]:
    violations = []
    # 1. Cek method yang hilang (ERROR)
    for mname, mdef in interface.methods.items():
        if mname not in impl.methods:
            violations.append(Violation(
                severity="ERROR",
                interface=interface.name,
                implementation=impl.name,
                message=f"Method '{mname}' missing in implementation",
                detail=f"Defined at {interface.file_path}:{mdef.lineno}"
            ))
        else:
            impl_method = impl.methods[mname]
            # 2. Cek parameter wajib (WARNING)
            if mdef.required_count != impl_method.required_count:
                violations.append(Violation(
                    severity="WARNING",
                    interface=interface.name,
                    implementation=impl.name,
                    message=f"Required parameter count mismatch for '{mname}'",
                    detail=f"Interface: {mdef.required_count} required, Impl: {impl_method.required_count} required"
                ))
            # 3. Cek keyword-only (WARNING)
            if mdef.kwonly_count != impl_method.kwonly_count:
                violations.append(Violation(
                    severity="WARNING",
                    interface=interface.name,
                    implementation=impl.name,
                    message=f"Keyword-only parameter count mismatch for '{mname}'",
                    detail=f"Interface: {mdef.kwonly_count}, Impl: {impl_method.kwonly_count}"
                ))
            # 4. Cek async (WARNING)
            if mdef.is_async != impl_method.is_async:
                violations.append(Violation(
                    severity="WARNING",
                    interface=interface.name,
                    implementation=impl.name,
                    message=f"Async mismatch for '{mname}'",
                    detail=f"Interface: {'async' if mdef.is_async else 'sync'}, Impl: {'async' if impl_method.is_async else 'sync'}"
                ))
    return violations

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def scan_repositories() -> dict:
    interfaces = scan_interfaces()
    all_implementations = scan_implementations()

    repo_impls = [i for i in all_implementations if not i.is_infrastructure]
    infra_impls = [i.name for i in all_implementations if i.is_infrastructure]

    matched_pairs = []
    used_impls = set()
    matched_interfaces = set()
    unmatched_interfaces = []
    all_violations = []
    total_errors = 0
    total_warnings = 0

    for iface in interfaces:
        if iface.name in matched_interfaces:
            continue
        impl = match_interface_to_impl(iface, repo_impls)
        if impl:
            matched_pairs.append((iface.name, impl.name))
            used_impls.add(impl.name)
            matched_interfaces.add(iface.name)
            violations = compare_methods(iface, impl)
            all_violations.extend(violations)
            total_errors += sum(1 for v in violations if v.severity == "ERROR")
            total_warnings += sum(1 for v in violations if v.severity == "WARNING")
        else:
            unmatched_interfaces.append(iface.name)

    unmatched_impls = [i.name for i in repo_impls if i.name not in used_impls]

    total_interfaces = len(interfaces)
    error_free_matches = 0
    for iface in interfaces:
        if iface.name in matched_interfaces:
            has_error = any(v.interface == iface.name and v.severity == "ERROR" for v in all_violations)
            if not has_error:
                error_free_matches += 1

    score = (error_free_matches / total_interfaces * 100) if total_interfaces > 0 else 100.0

    return {
        "interfaces": interfaces,
        "implementations": repo_impls,
        "infrastructure_impls": infra_impls,
        "matched": matched_pairs,
        "unmatched_interfaces": unmatched_interfaces,
        "unmatched_impls": unmatched_impls,
        "violations": all_violations,
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "score": round(score, 1),
    }

# -----------------------------------------------------------------------------
# Report
# -----------------------------------------------------------------------------

def print_report(data: dict, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*72}{c['RESET']}")
    print(f"{c['BOLD']}{c['CYAN']}  REPOSITORY CONTRACT CHECKER REPORT (AKURAT){c['RESET']}")
    print(f"{c['CYAN']}{'='*72}{c['RESET']}")

    print(f"\n  Interfaces found          : {len(data['interfaces'])}")
    print(f"  Repository implementations : {len(data['implementations'])}")
    print(f"  Infrastructure impls (skip): {len(data['infrastructure_impls'])}")
    print(f"  Matched pairs             : {len(data['matched'])}")
    print(f"  Unmatched interfaces      : {len(data['unmatched_interfaces'])}")
    print(f"  Unmatched impls           : {len(data['unmatched_impls'])}")
    print(f"  Contract Errors (missing) : {len([v for v in data['violations'] if v.severity == 'ERROR'])}")
    print(f"  Contract Warnings (sig)   : {len([v for v in data['violations'] if v.severity == 'WARNING'])}")
    print(f"  📈 Skor Kepatuhan         : {c['CYAN']}{c['BOLD']}{data['score']}/100{c['RESET']}")

    if data['matched']:
        print(f"\n{c['GREEN']}✅ Matched pairs:{c['RESET']}")
        for iface, impl in data['matched'][:30]:
            print(f"    {iface}  ↔  {impl}")
        if len(data['matched']) > 30:
            print(f"    ... dan {len(data['matched'])-30} lainnya.")

    if data['unmatched_interfaces']:
        print(f"\n{c['YELLOW']}⚠ Unmatched interfaces ({len(data['unmatched_interfaces'])}):{c['RESET']}")
        for name in data['unmatched_interfaces'][:20]:
            print(f"    {name}")
        if len(data['unmatched_interfaces']) > 20:
            print(f"    ... dan {len(data['unmatched_interfaces'])-20} lainnya.")

    if data['unmatched_impls']:
        print(f"\n{c['YELLOW']}⚠ Unmatched implementations ({len(data['unmatched_impls'])}):{c['RESET']}")
        for name in data['unmatched_impls'][:20]:
            print(f"    {name}")
        if len(data['unmatched_impls']) > 20:
            print(f"    ... dan {len(data['unmatched_impls'])-20} lainnya.")

    # Tampilkan violations
    errors = [v for v in data['violations'] if v.severity == "ERROR"]
    warnings = [v for v in data['violations'] if v.severity == "WARNING"]

    if errors:
        print(f"\n{c['RED']}❌ Contract ERRORS ({len(errors)}):{c['RESET']}")
        for v in errors[:30]:
            print(f"  {c['RED']}[ERROR]{c['RESET']} {v.message}")
            print(f"       Interface: {v.interface}, Implementation: {v.implementation}")
            if v.detail:
                print(f"       Detail: {v.detail}")
        if len(errors) > 30:
            print(f"  ... dan {len(errors)-30} errors lainnya.")

    if warnings and verbose:
        print(f"\n{c['YELLOW']}⚠ Contract WARNINGS ({len(warnings)}):{c['RESET']}")
        for v in warnings[:30]:
            print(f"  {c['YELLOW']}[WARNING]{c['RESET']} {v.message}")
            print(f"       Interface: {v.interface}, Implementation: {v.implementation}")
            if v.detail:
                print(f"       Detail: {v.detail}")
        if len(warnings) > 30:
            print(f"  ... dan {len(warnings)-30} warnings lainnya.")
    elif warnings and not verbose:
        print(f"\n{c['YELLOW']}⚠ {len(warnings)} warnings (gunakan --verbose untuk melihat detail).{c['RESET']}")

    print(f"\n{c['CYAN']}{'─'*72}{c['RESET']}")
    print(f"  Errors  : {c['RED']}{data['total_errors']}{c['RESET']}")
    print(f"  Warnings: {c['YELLOW']}{data['total_warnings']}{c['RESET']}")

    if data['total_errors'] == 0:
        print(f"  {c['GREEN']}✅ All repository contracts are satisfied (no missing methods).{c['RESET']}")
    else:
        print(f"  {c['RED']}❌ Fix the errors above before proceeding.{c['RESET']}")

def save_json(data: dict, filepath: str):
    payload = {
        "score": data["score"],
        "total_interfaces": len(data["interfaces"]),
        "total_repo_impls": len(data["implementations"]),
        "infrastructure_impls": data["infrastructure_impls"],
        "matched_pairs": data["matched"],
        "unmatched_interfaces": data["unmatched_interfaces"],
        "unmatched_impls": data["unmatched_impls"],
        "errors": [
            {"interface": v.interface, "implementation": v.implementation, "message": v.message, "detail": v.detail}
            for v in data["violations"] if v.severity == "ERROR"
        ],
        "warnings": [
            {"interface": v.interface, "implementation": v.implementation, "message": v.message, "detail": v.detail}
            for v in data["violations"] if v.severity == "WARNING"
        ],
        "total_errors": data["total_errors"],
        "total_warnings": data["total_warnings"],
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"{COLOR['GREEN']}✅ Laporan diekspor ke {filepath}{COLOR['RESET']}")

# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Repository Contract Checker (Akurat)")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail tambahan (termasuk warnings)")
    parser.add_argument("--json", metavar="FILE", help="Ekspor laporan ke JSON")
    args = parser.parse_args()

    start_time = time.monotonic()

    print(f"{COLOR['BOLD']}{COLOR['CYAN']}╔════════════════════════════════════════════════════════════════════╗")
    print("║      SOVEREIGN REPOSITORY CONTRACT CHECKER (AKURAT)          ║")
    print(f"╚════════════════════════════════════════════════════════════════════╝{COLOR['RESET']}")
    print(f"  Interface dir      : {ROOT / 'ports' / 'primary'}")
    print(f"  Implementation dir : {ROOT / 'adapters' / 'secondary_impl'}")

    data = scan_repositories()
    print_report(data, verbose=args.verbose)

    if args.json:
        save_json(data, args.json)

    elapsed = time.monotonic() - start_time
    print(f"\n ⏱️ Waktu Audit: {elapsed:.3f} detik")

    sys.exit(0 if data["total_errors"] == 0 else 1)

if __name__ == "__main__":
    main()
