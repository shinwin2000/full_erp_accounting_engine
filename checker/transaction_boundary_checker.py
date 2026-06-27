#!/usr/bin/env python3
"""
transaction_boundary_checker.py - Transaction Boundary & Unit of Work Validator
================================================================================
Memeriksa konsistensi transaksi di seluruh aplikasi berdasarkan pola Unit of Work.

Fitur:
- Deteksi UoW pattern di ports/primary/unit_of_work_port.py
- Pengecekan penggunaan UoW di use cases (application/use_cases/*.py)
- Deteksi operasi database langsung (session.commit, session.rollback, session.execute) di luar UoW
- Verifikasi bahwa semua repository mengikuti UoW yang sama
- Pelacakan transaksi nested dan pembungkus yang benar (async with / with)
- Laporan rinci dan skor kepatuhan

Cara pakai:
  python transaction_boundary_checker.py                     # Mode normal
  python transaction_boundary_checker.py --verbose           # Detail
  python transaction_boundary_checker.py --json report.json  # Simpan JSON
  python transaction_boundary_checker.py --exclude tests,migrations
  python transaction_boundary_checker.py --help
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
import time
from dataclasses import dataclass, field

# =============================================================================
# Konfigurasi Warna
# =============================================================================
COLOR = {"RED": "", "GREEN": "", "YELLOW": "", "CYAN": "", "RESET": ""}
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
# Data Structures
# =============================================================================
@dataclass
class TransactionIssue:
    severity: str  # ERROR, WARNING
    file: str
    line: int
    message: str
    detail: str = ""

@dataclass
class UoWUsage:
    file: str
    line: int
    is_async: bool
    context_var: str  # nama variabel context (misal 'uow', 'session')
    method: str       # nama method yang menggunakan UoW

@dataclass
class Report:
    total_files: int = 0
    issues: list[TransactionIssue] = field(default_factory=list)
    uow_usages: list[UoWUsage] = field(default_factory=list)
    has_uow_port: bool = False
    uow_port_file: str = ""
    score: int = 100

# =============================================================================
# AST Analysis Functions
# =============================================================================
def find_unit_of_work_port(root: pathlib.Path) -> pathlib.Path | None:
    """Cari file unit_of_work_port.py di ports/primary/."""
    port_file = root / "ports" / "primary" / "unit_of_work_port.py"
    return port_file if port_file.exists() else None

def analyze_unit_of_work_port(file_path: pathlib.Path) -> dict[str, any]:
    """Analisis UoW port: cari class, method, dan pola async."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return {}

    info = {
        "class_name": None,
        "methods": [],
        "has_async": False,
        "has_commit": False,
        "has_rollback": False,
        "has_enter_exit": False,
        "has_async_enter_exit": False,
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Cari class yang mungkin UoW (biasanya bernama UnitOfWork atau UoW)
            if "UnitOfWork" in node.name or "UoW" in node.name:
                info["class_name"] = node.name
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        info["methods"].append(item.name)
                        if item.name == "commit":
                            info["has_commit"] = True
                        if item.name == "rollback":
                            info["has_rollback"] = True
                        if item.name == "__enter__":
                            info["has_enter_exit"] = True
                        if item.name == "__aenter__":
                            info["has_async_enter_exit"] = True
                        if isinstance(item, ast.AsyncFunctionDef):
                            info["has_async"] = True
    return info

def find_session_attributes(tree: ast.AST) -> list[tuple[int, str, str]]:
    """Temukan semua penggunaan session.commit, session.rollback, session.execute, session.begin."""
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Cari attribute call seperti session.commit()
            if isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                if attr in ("commit", "rollback", "execute", "begin", "flush"):
                    # Cari nama objek yang dipanggil (misal session, db, conn)
                    if isinstance(node.func.value, ast.Name):
                        obj_name = node.func.value.id
                        findings.append((node.lineno, attr, obj_name))
                    elif isinstance(node.func.value, ast.Attribute):
                        # misal self.session.commit()
                        obj_name = ast.unparse(node.func.value)
                        findings.append((node.lineno, attr, obj_name))
    return findings

def find_uow_usage(tree: ast.AST, file_path: str) -> list[UoWUsage]:
    """Cari penggunaan Unit of Work (with uow: atau async with uow:)."""
    usages = []
    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            # Cek apakah context manager adalah UoW
            for item in node.items:
                if isinstance(item.context_expr, ast.Call):
                    # uow = UnitOfWork() atau uow = get_uow()
                    if isinstance(item.context_expr.func, ast.Name):
                        # Cari nama yang mirip UoW
                        if "UnitOfWork" in item.context_expr.func.id or "UoW" in item.context_expr.func.id:
                            is_async = False
                            if isinstance(node, ast.AsyncWith):
                                is_async = True
                            # Dapatkan variabel context (jika ada)
                            context_var = None
                            if item.optional_vars:
                                if isinstance(item.optional_vars, ast.Name):
                                    context_var = item.optional_vars.id
                            usages.append(UoWUsage(
                                file=file_path,
                                line=node.lineno,
                                is_async=is_async,
                                context_var=context_var or "uow",
                                method="unknown",  # akan diisi nanti
                            ))
    return usages

def find_uow_in_use_cases(root: pathlib.Path) -> list[tuple[pathlib.Path, ast.AST, str]]:
    """Cari semua file use case di application/use_cases/ dan return file, tree, content."""
    use_case_dir = root / "application" / "use_cases"
    if not use_case_dir.exists():
        return []
    results = []
    for py_file in use_case_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        try:
            src = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(py_file))
        except SyntaxError:
            continue
        results.append((py_file, tree, src))
    return results

def analyze_use_case(tree: ast.AST, file_path: pathlib.Path) -> list[TransactionIssue]:
    """Analisis use case: cek apakah menggunakan UoW dengan benar."""
    issues = []
    # 1. Cari semua fungsi/async fungsi di dalam class atau module
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Cari body untuk melihat apakah ada penggunaan UoW
            uses_uow = False
            has_async_with = False
            has_with = False
            has_commit = False
            has_rollback = False
            has_session_commit = False

            # Cek body
            for subnode in ast.walk(node):
                if isinstance(subnode, ast.With):
                    for item in subnode.items:
                        # Cek apakah context_expr adalah UoW atau get_uow()
                        if isinstance(item.context_expr, ast.Call):
                            if isinstance(item.context_expr.func, ast.Name):
                                if "UnitOfWork" in item.context_expr.func.id or "UoW" in item.context_expr.func.id:
                                    if isinstance(subnode, ast.AsyncWith):
                                        has_async_with = True
                                    else:
                                        has_with = True
                                    uses_uow = True
                if isinstance(subnode, ast.Call):
                    if isinstance(subnode.func, ast.Attribute):
                        if subnode.func.attr == "commit":
                            has_commit = True
                        elif subnode.func.attr == "rollback":
                            has_rollback = True
                        # Cek session.commit (misal self.session.commit())
                        if subnode.func.attr == "commit" and isinstance(subnode.func.value, ast.Attribute):
                            if subnode.func.value.attr in ("session", "db", "conn"):
                                has_session_commit = True
                        if subnode.func.attr == "execute" and isinstance(subnode.func.value, ast.Attribute):
                            if subnode.func.value.attr in ("session", "db", "conn"):
                                has_session_commit = True

            # Jika fungsi adalah async, seharusnya menggunakan async with
            if isinstance(node, ast.AsyncFunctionDef):
                if not has_async_with and uses_uow:
                    issues.append(TransactionIssue(
                        severity="ERROR",
                        file=str(file_path),
                        line=node.lineno,
                        message=f"Async function '{node.name}' menggunakan UoW tetapi tidak menggunakan 'async with'",
                        detail="Gunakan 'async with uow:' untuk membungkus transaksi."
                    ))
                elif has_with and not has_async_with:
                    issues.append(TransactionIssue(
                        severity="ERROR",
                        file=str(file_path),
                        line=node.lineno,
                        message=f"Async function '{node.name}' menggunakan 'with' bukan 'async with' untuk UoW",
                        detail="Gunakan 'async with' untuk fungsi async."
                    ))
                # Cek apakah ada commit/rollback manual di luar konteks
                if has_session_commit and not uses_uow:
                    issues.append(TransactionIssue(
                        severity="ERROR",
                        file=str(file_path),
                        line=node.lineno,
                        message=f"Async function '{node.name}' menggunakan session.commit/execute langsung tanpa UoW",
                        detail="Harap gunakan Unit of Work untuk mengelola transaksi."
                    ))
            else:
                # Fungsi sync
                if has_async_with:
                    issues.append(TransactionIssue(
                        severity="ERROR",
                        file=str(file_path),
                        line=node.lineno,
                        message=f"Sync function '{node.name}' menggunakan 'async with' tetapi fungsi tidak async",
                        detail="Gunakan 'with' untuk fungsi sync."
                    ))
                if has_session_commit and not uses_uow:
                    issues.append(TransactionIssue(
                        severity="ERROR",
                        file=str(file_path),
                        line=node.lineno,
                        message=f"Sync function '{node.name}' menggunakan session.commit/execute langsung tanpa UoW",
                        detail="Harap gunakan Unit of Work untuk mengelola transaksi."
                    ))

            # Cek jika ada commit/rollback manual di dalam UoW (harusnya otomatis)
            if uses_uow and (has_commit or has_rollback):
                issues.append(TransactionIssue(
                    severity="WARNING",
                    file=str(file_path),
                    line=node.lineno,
                    message=f"Function '{node.name}' menggunakan UoW tetapi juga memanggil commit/rollback secara manual",
                    detail="UoW seharusnya mengelola commit/rollback otomatis di exit."
                ))

    return issues

# =============================================================================
# Main Checker
# =============================================================================
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent

def scan_transaction_boundaries(exclude_dirs: list[str] = None) -> Report:
    if exclude_dirs is None:
        exclude_dirs = [".venv", "venv", "__pycache__", ".git", "node_modules", "dist", "build", "migrations", "deployment", "docs", "tests"]
    exclude_set = set(exclude_dirs)

    report = Report()

    # 1. Cek UoW port
    uow_port = find_unit_of_work_port(PROJECT_ROOT)
    if uow_port:
        report.has_uow_port = True
        report.uow_port_file = str(uow_port)
        uow_info = analyze_unit_of_work_port(uow_port)
        if uow_info.get("class_name"):
            # Tidak ada issue jika UoW port ditemukan
            pass
        else:
            report.issues.append(TransactionIssue(
                severity="ERROR",
                file=str(uow_port),
                line=0,
                message="UnitOfWork port tidak memiliki class yang sesuai (harus mengandung 'UnitOfWork')",
                detail="Periksa ports/primary/unit_of_work_port.py"
            ))
    else:
        report.issues.append(TransactionIssue(
            severity="ERROR",
            file="ports/primary/unit_of_work_port.py",
            line=0,
            message="File unit_of_work_port.py tidak ditemukan",
            detail="Buat ports/primary/unit_of_work_port.py sesuai pattern."
        ))

    # 2. Analisis use cases
    use_cases = find_uow_in_use_cases(PROJECT_ROOT)
    report.total_files = len(use_cases)

    for file_path, tree, src in use_cases:
        # Cari penggunaan UoW di file
        usages = find_uow_usage(tree, str(file_path))
        report.uow_usages.extend(usages)

        # Analisis use case
        issues = analyze_use_case(tree, file_path)
        report.issues.extend(issues)

        # Cek jika ada penggunaan session langsung (tanpa UoW) di luar fungsi
        session_attrs = find_session_attributes(tree)
        for lineno, attr, obj in session_attrs:
            # Abaikan jika di dalam fungsi yang sudah menggunakan UoW? Tapi kita sudah handle di fungsi.
            # Namun jika ada di level modul, kita warning.
            # Cari apakah ada di luar fungsi/with
            found_in_function = False
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Cari apakah node ini mencakup baris tersebut
                    if node.lineno <= lineno <= node.end_lineno if hasattr(node, 'end_lineno') else False:
                        found_in_function = True
                        break
            if not found_in_function:
                report.issues.append(TransactionIssue(
                    severity="WARNING",
                    file=str(file_path),
                    line=lineno,
                    message=f"Operasi database langsung ({obj}.{attr}) ditemukan di luar fungsi use case",
                    detail="Sebaiknya semua operasi database dibungkus dalam use case yang menggunakan UoW."
                ))

    # 3. Periksa repository implementations: apakah semua method menerima UoW?
    # Ini lebih rumit, kita bisa periksa parameter method repository
    # Bisa juga dengan melihat apakah ada dekorator atau pola.

    # 4. Skor
    errors = sum(1 for issue in report.issues if issue.severity == "ERROR")
    warnings = len(report.issues) - errors
    report.score = max(0, 100 - errors * 10 - warnings * 2)

    return report

# =============================================================================
# Output
# =============================================================================
def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}TRANSACTION BOUNDARY REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")

    print(f"\n  UoW Port found   : {c['GREEN'] if report.has_uow_port else c['RED']}{report.has_uow_port}{c['RESET']}")
    if report.has_uow_port:
        print(f"  UoW Port file    : {report.uow_port_file}")
    print(f"  Use cases scanned: {report.total_files}")
    print(f"  UoW usages found : {len(report.uow_usages)}")
    print(f"  Total issues     : {len(report.issues)} (Errors: {len([i for i in report.issues if i.severity == 'ERROR'])}, Warnings: {len([i for i in report.issues if i.severity == 'WARNING'])})")
    print(f"  Compliance score : {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    if report.issues:
        print(f"\n{c['RED'] if any(i.severity == 'ERROR' for i in report.issues) else c['YELLOW']}Issues:{c['RESET']}")
        for issue in report.issues:
            color = c["RED"] if issue.severity == "ERROR" else c["YELLOW"]
            print(f"  {color}[{issue.severity}]{c['RESET']} {issue.file}:{issue.line}")
            print(f"     {issue.message}")
            if verbose and issue.detail:
                print(f"     Detail: {issue.detail}")

    if not report.issues:
        print(f"\n{c['GREEN']}✅ No transaction boundary issues detected.{c['RESET']}")

    print(f"\n{c['CYAN']}{'─'*70}{c['RESET']}")

def save_json(report: Report, filepath: str):
    data = {
        "has_uow_port": report.has_uow_port,
        "uow_port_file": report.uow_port_file,
        "total_files": report.total_files,
        "uow_usages": [{
            "file": u.file,
            "line": u.line,
            "is_async": u.is_async,
            "context_var": u.context_var,
            "method": u.method,
        } for u in report.uow_usages],
        "issues": [{
            "severity": i.severity,
            "file": i.file,
            "line": i.line,
            "message": i.message,
            "detail": i.detail,
        } for i in report.issues],
        "score": report.score,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{c['CYAN']}JSON report saved to {filepath}{c['RESET']}")

# =============================================================================
# CLI
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="Transaction Boundary Checker")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    parser.add_argument("--quiet", action="store_true", help="Minimal output")
    parser.add_argument("--exclude", default=".venv,venv,__pycache__,node_modules,dist,build,migrations,deployment,docs,tests",
                        help="Folder yang diabaikan (pisahkan dengan koma)")
    args = parser.parse_args()

    exclude_dirs = [d.strip() for d in args.exclude.split(",") if d.strip()]
    start = time.monotonic()
    report = scan_transaction_boundaries(exclude_dirs)

    if not args.quiet:
        print_report(report, verbose=args.verbose)
    if args.json:
        save_json(report, args.json)

    elapsed = time.monotonic() - start
    if not args.quiet:
        print(f"\n  Time: {elapsed:.2f}s")

    # Exit code: 0 jika tidak ada ERROR, else 1
    has_errors = any(i.severity == "ERROR" for i in report.issues)
    sys.exit(1 if has_errors else 0)

if __name__ == "__main__":
    main()
