#!/usr/bin/env python3
"""
uow_checker.py - Unit of Work Pattern Validator
================================================
Memeriksa kepatuhan terhadap Unit of Work (UoW) pattern:
- Port UoW didefinisikan dengan benar (commit, rollback, begin/__enter__/__exit__)
- Implementasi UoW di adapter mengimplementasikan semua method
- Setiap operasi write di use cases menggunakan UoW (dekorator @transactional atau with uow:)
- Tidak ada write operation yang bypass UoW

Cara pakai:
  python uow_checker.py
  python uow_checker.py --verbose
  python uow_checker.py --json report.json
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Set

# Warna
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

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent

@dataclass
class Finding:
    file: str
    line: int
    severity: str       # ERROR / WARNING
    category: str       # port / implementation / usage / bypass
    message: str
    detail: str = ""

@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    score: int = 100

# =============================================================================
# 1. Port Checker – memeriksa UoW port
# =============================================================================
def check_uow_port() -> List[Finding]:
    """Cek file ports/primary/unit_of_work_port.py, pastikan ada class dengan metode commit, rollback, begin."""
    findings = []
    port_file = PROJECT_ROOT / "ports" / "primary" / "unit_of_work_port.py"
    if not port_file.exists():
        findings.append(Finding(
            file=str(port_file),
            line=0,
            severity="ERROR",
            category="port",
            message="File unit_of_work_port.py tidak ditemukan di ports/primary/",
            detail="Buat file ports/primary/unit_of_work_port.py dengan interface UoW."
        ))
        return findings

    try:
        src = port_file.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(port_file))
    except SyntaxError as e:
        findings.append(Finding(
            file=str(port_file),
            line=e.lineno or 0,
            severity="ERROR",
            category="port",
            message=f"Syntax error di port file: {e.msg}",
            detail="Perbaiki syntax error."
        ))
        return findings

    # Cari class yang mungkin UoW (bisa bernama UnitOfWork, UnitOfWorkPort, dll.)
    uow_classes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if 'unit' in node.name.lower() and 'work' in node.name.lower():
                uow_classes.append(node)

    if not uow_classes:
        findings.append(Finding(
            file=str(port_file),
            line=0,
            severity="ERROR",
            category="port",
            message="Tidak ditemukan class UnitOfWork di port file",
            detail="Tambahkan class UnitOfWork (atau UnitOfWorkPort) dengan method commit, rollback, begin."
        ))
        return findings

    # Periksa setiap class UoW
    for cls in uow_classes:
        methods = [item.name for item in cls.body if isinstance(item, ast.FunctionDef)]
        required = {'commit', 'rollback', 'begin'}
        # Beberapa implementasi menggunakan __enter__ dan __exit__ sebagai pengganti begin
        if '__enter__' in methods and '__exit__' in methods:
            required.discard('begin')  # begin tidak wajib jika pakai context manager

        missing = required - set(methods)
        if missing:
            findings.append(Finding(
                file=str(port_file),
                line=cls.lineno,
                severity="ERROR",
                category="port",
                message=f"Class '{cls.name}' kekurangan method: {', '.join(missing)}",
                detail=f"Implementasikan method {', '.join(missing)}."
            ))
        else:
            # Tambahkan informasi bahwa port OK
            findings.append(Finding(
                file=str(port_file),
                line=cls.lineno,
                severity="INFO",
                category="port",
                message=f"✅ Port UoW '{cls.name}' lengkap (commit, rollback, begin/context manager)",
                detail=""
            ))

    return findings

# =============================================================================
# 2. Implementation Checker – cek adapter UoW
# =============================================================================
def check_uow_implementation() -> List[Finding]:
    """Cari implementasi UoW di adapters/secondary_impl/, cek apakah mengimplementasikan semua method port."""
    findings = []
    impl_dir = PROJECT_ROOT / "adapters" / "secondary_impl"
    if not impl_dir.exists():
        findings.append(Finding(
            file=str(impl_dir),
            line=0,
            severity="ERROR",
            category="implementation",
            message="Direktori adapters/secondary_impl/ tidak ditemukan",
            detail="Buat direktori adapters/secondary_impl/ untuk implementasi UoW."
        ))
        return findings

    # Cari file yang mengandung 'unit_of_work' atau 'uow' di namanya
    impl_files = list(impl_dir.glob("*unit_of_work*.py")) + list(impl_dir.glob("*uow*.py"))
    if not impl_files:
        findings.append(Finding(
            file=str(impl_dir),
            line=0,
            severity="ERROR",
            category="implementation",
            message="Tidak ditemukan implementasi UoW di adapters/secondary_impl/",
            detail="Buat file misalnya sqlalchemy_unit_of_work_impl.py"
        ))
        return findings

    for impl_file in impl_files:
        try:
            src = impl_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(impl_file))
        except SyntaxError as e:
            findings.append(Finding(
                file=str(impl_file),
                line=e.lineno or 0,
                severity="ERROR",
                category="implementation",
                message=f"Syntax error di {impl_file.name}: {e.msg}",
                detail="Perbaiki syntax error."
            ))
            continue

        # Cari class yang mungkin implementasi UoW
        impl_classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if 'unit' in node.name.lower() and 'work' in node.name.lower():
                    impl_classes.append(node)
        if not impl_classes:
            findings.append(Finding(
                file=str(impl_file),
                line=0,
                severity="WARNING",
                category="implementation",
                message=f"File {impl_file.name} tidak memiliki class UoW",
                detail="Pastikan file berisi class implementasi UoW."
            ))
            continue

        for cls in impl_classes:
            methods = [item.name for item in cls.body if isinstance(item, ast.FunctionDef)]
            required = {'commit', 'rollback', 'begin'}
            if '__enter__' in methods and '__exit__' in methods:
                required.discard('begin')
            missing = required - set(methods)
            if missing:
                findings.append(Finding(
                    file=str(impl_file),
                    line=cls.lineno,
                    severity="ERROR",
                    category="implementation",
                    message=f"Implementasi '{cls.name}' kekurangan method: {', '.join(missing)}",
                    detail=f"Implementasikan method {', '.join(missing)} sesuai port."
                ))
            else:
                findings.append(Finding(
                    file=str(impl_file),
                    line=cls.lineno,
                    severity="INFO",
                    category="implementation",
                    message=f"✅ Implementasi UoW '{cls.name}' lengkap",
                    detail=""
                ))

    return findings

# =============================================================================
# 3. Usage Checker – cek apakah use cases menggunakan UoW dengan benar
# =============================================================================
def check_uow_usage() -> List[Finding]:
    """Cek setiap use case atau service yang melakukan write, pastikan menggunakan @transactional atau with uow:."""
    findings = []
    target_dirs = [
        PROJECT_ROOT / "application" / "use_cases",
        PROJECT_ROOT / "application" / "service_layer",
    ]
    # Cari juga di subfolder application lainnya
    app_dir = PROJECT_ROOT / "application"
    if app_dir.exists():
        for sub in app_dir.iterdir():
            if sub.is_dir() and sub.name not in ['use_cases', 'service_layer', '__pycache__']:
                # Skip folder yang tidak relevan
                if sub.name in ['commands_cqrs', 'sagas', 'outbox', 'mappers', 'events']:
                    continue
                target_dirs.append(sub)

    write_keywords = {'post', 'create', 'update', 'delete', 'save', 'persist', 'remove', 'add', 'modify', 'change', 'register'}

    for dir_path in target_dirs:
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if py_file.name.startswith("__") or py_file.name.startswith("uow_checker"):
                continue
            try:
                src = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=str(py_file))
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_name = node.name.lower()
                    # Cek apakah fungsi ini menulis data?
                    if not any(k in func_name for k in write_keywords):
                        continue

                    # Cek dekorator @transactional
                    has_transactional = False
                    for dec in node.decorator_list:
                        if isinstance(dec, ast.Name) and dec.id == 'transactional':
                            has_transactional = True
                            break
                        elif isinstance(dec, ast.Attribute) and dec.attr == 'transactional':
                            has_transactional = True
                            break
                        elif isinstance(dec, ast.Call):
                            if isinstance(dec.func, ast.Name) and dec.func.id == 'transactional':
                                has_transactional = True
                                break
                            elif isinstance(dec.func, ast.Attribute) and dec.func.attr == 'transactional':
                                has_transactional = True
                                break

                    # Cek apakah ada dengan uow: atau unit_of_work:
                    has_uow_context = False
                    for stmt in ast.walk(node):
                        if isinstance(stmt, ast.With):
                            for item in stmt.items:
                                context_expr = ast.unparse(item.context_expr)
                                if 'uow' in context_expr.lower() or 'unit_of_work' in context_expr.lower():
                                    has_uow_context = True
                                    break
                        # Cek juga assignment seperti uow = get_uow()
                        if isinstance(stmt, ast.Assign):
                            for target in stmt.targets:
                                if isinstance(target, ast.Name) and target.id in ('uow', 'unit_of_work'):
                                    # Cek apakah ada pemanggilan commit/rollback nanti
                                    has_uow_context = True
                                    break

                    # Cek apakah ada pemanggilan commit/rollback langsung
                    has_commit = False
                    for stmt in ast.walk(node):
                        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                            if isinstance(stmt.value.func, ast.Attribute):
                                if stmt.value.func.attr in ('commit', 'rollback'):
                                    # Cek apakah objeknya adalah uow
                                    if isinstance(stmt.value.func.value, ast.Name) and stmt.value.func.value.id in ('uow', 'unit_of_work'):
                                        has_commit = True
                                        break

                    if not has_transactional and not has_uow_context and not has_commit:
                        findings.append(Finding(
                            file=str(py_file),
                            line=node.lineno,
                            severity="ERROR",
                            category="usage",
                            message=f"Fungsi '{node.name}' melakukan write tanpa UoW",
                            detail="Tambahkan dekorator @transactional atau gunakan 'with uow:' untuk membungkus operasi."
                        ))
    return findings

# =============================================================================
# 4. Bypass Checker – cek apakah ada repository.save() tanpa UoW
# =============================================================================
def check_bypass_uow() -> List[Finding]:
    """Cek kode yang memanggil repository.save() atau .add() tanpa UoW."""
    findings = []
    target_dirs = [
        PROJECT_ROOT / "application",
        PROJECT_ROOT / "adapters",
        PROJECT_ROOT / "domain",
        PROJECT_ROOT / "infrastructure",
    ]
    exclude = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', 'dist', 'build', 'migrations', 'deployment', 'docs', 'tests'}

    for dir_path in target_dirs:
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if any(part in exclude for part in py_file.parts):
                continue
            if py_file.name.startswith("__") or py_file.name.startswith("uow_checker"):
                continue
            try:
                src = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=str(py_file))
            except SyntaxError:
                continue

            # Cari pemanggilan repository.save(), .add(), .update(), .delete() tanpa UoW
            for node in ast.walk(tree):
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                    call = node.value
                    if isinstance(call.func, ast.Attribute):
                        attr = call.func.attr.lower()
                        if attr in ('save', 'add', 'update', 'delete', 'persist', 'remove'):
                            # Cek apakah objeknya adalah repository
                            if isinstance(call.func.value, ast.Name):
                                obj_name = call.func.value.id.lower()
                                if 'repo' in obj_name or 'repository' in obj_name:
                                    # Cek apakah pemanggilan ini berada di dalam fungsi yang sudah menggunakan UoW?
                                    # Kita akan cek parent function apakah sudah ada UoW
                                    parent_func = None
                                    for parent in ast.walk(tree):
                                        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                            if node in ast.walk(parent):
                                                parent_func = parent
                                                break
                                    if parent_func:
                                        # Cek apakah parent_func menggunakan UoW (dengan cara yang sama seperti di usage)
                                        has_uow = False
                                        for stmt in ast.walk(parent_func):
                                            if isinstance(stmt, ast.With):
                                                for item in stmt.items:
                                                    if 'uow' in ast.unparse(item.context_expr).lower():
                                                        has_uow = True
                                                        break
                                            if isinstance(stmt, ast.Assign):
                                                for target in stmt.targets:
                                                    if isinstance(target, ast.Name) and target.id in ('uow', 'unit_of_work'):
                                                        has_uow = True
                                                        break
                                            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                                                if isinstance(stmt.value.func, ast.Attribute) and stmt.value.func.attr in ('commit', 'rollback'):
                                                    if isinstance(stmt.value.func.value, ast.Name) and stmt.value.func.value.id in ('uow', 'unit_of_work'):
                                                        has_uow = True
                                                        break
                                        if not has_uow:
                                            findings.append(Finding(
                                                file=str(py_file),
                                                line=node.lineno,
                                                severity="WARNING",
                                                category="bypass",
                                                message=f"Pemanggilan {call.func.attr}() tanpa UoW di {parent_func.name}",
                                                detail="Gunakan UoW untuk operasi write ke repository."
                                            ))
    return findings

# =============================================================================
# Main
# =============================================================================
def scan_uow() -> Report:
    report = Report()
    report.findings.extend(check_uow_port())
    report.findings.extend(check_uow_implementation())
    report.findings.extend(check_uow_usage())
    report.findings.extend(check_bypass_uow())

    # Hitung skor
    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")
    report.score = max(0, 100 - errors * 10 - warnings * 3)
    return report

# =============================================================================
# Output
# =============================================================================
def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}UNIT OF WORK (UoW) CHECKER REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"\n  Total findings: {len(report.findings)}")
    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")
    print(f"  Errors: {c['RED']}{errors}{c['RESET']}, Warnings: {c['YELLOW']}{warnings}{c['RESET']}")
    print(f"  Score: {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    if report.findings:
        categories = {}
        for f in report.findings:
            categories.setdefault(f.category, []).append(f)

        print(f"\n{c['CYAN']}By Category:{c['RESET']}")
        cat_labels = {
            'port': 'UoW Port Definition',
            'implementation': 'UoW Implementation',
            'usage': 'UoW Usage in Use Cases',
            'bypass': 'Bypass Detection',
        }
        for cat, items in categories.items():
            label = cat_labels.get(cat, cat)
            err_cnt = sum(1 for i in items if i.severity == "ERROR")
            warn_cnt = sum(1 for i in items if i.severity == "WARNING")
            color = c["RED"] if err_cnt > 0 else c["YELLOW"] if warn_cnt > 0 else c["GREEN"]
            print(f"  {label}: {color}{err_cnt} errors, {warn_cnt} warnings{c['RESET']}")

        print(f"\n{c['RED'] if errors else c['YELLOW']}Details:{c['RESET']}")
        for f in report.findings[:30]:
            color = c["RED"] if f.severity == "ERROR" else c["YELLOW"]
            print(f"  {color}[{f.severity}]{c['RESET']} [{f.category}] {f.file}:{f.line}")
            print(f"     {f.message}")
            if verbose and f.detail:
                print(f"     {c['CYAN']}→ {f.detail}{c['RESET']}")
        if len(report.findings) > 30:
            print(f"  ... and {len(report.findings)-30} more findings")

def save_json(report: Report, filepath: str):
    data = {
        "findings": [
            {"file": f.file, "line": f.line, "severity": f.severity,
             "category": f.category, "message": f.message, "detail": f.detail}
            for f in report.findings
        ],
        "score": report.score,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{c['CYAN']}JSON saved to {filepath}{c['RESET']}")

# =============================================================================
# CLI
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="Unit of Work (UoW) Pattern Checker")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    args = parser.parse_args()

    report = scan_uow()
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)

    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    sys.exit(0 if errors == 0 else 1)

if __name__ == "__main__":
    main()