#!/usr/bin/env python3
"""
fiscal_period_checker.py - Fiscal Period Rules & Lifecycle Validator
===================================================================
Memeriksa kepatuhan terhadap aturan fiscal period (periode fiskal):
1. Period Status Lifecycle (DRAFT → OPEN → CLOSED → LOCKED)
2. Period Open/Close Logic (validasi sebelum posting)
3. Fiscal Year Consistency
4. Period Closure Constraints (tidak bisa reopen)
5. Year-End Closing Procedure

Cara pakai:
  python fiscal_period_checker.py
  python fiscal_period_checker.py --verbose
  python fiscal_period_checker.py --json report.json
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Set, Dict

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
    severity: str       # ERROR / WARNING / INFO
    category: str       # status_lifecycle / period_validation / fiscal_year / closure_constraint / year_end
    message: str
    detail: str = ""

@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    score: int = 100

# =============================================================================
# 1. Period Status Lifecycle Checker
# =============================================================================
def check_period_status_lifecycle(file_path: pathlib.Path) -> List[Finding]:
    """
    Cari apakah ada definisi status period: DRAFT, OPEN, CLOSED, LOCKED.
    Status harus ada di enum atau class constants.
    """
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    expected_statuses = {'DRAFT', 'OPEN', 'CLOSED', 'LOCKED'}
    found_statuses = set()

    for node in ast.walk(tree):
        # Cari enum atau class yang berisi status
        if isinstance(node, ast.ClassDef):
            # Cek apakah class ini mendefinisikan status period
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            # Cek assignment ke constant seperti DRAFT = "DRAFT" atau DRAFT = 1
                            if target.id.upper() in expected_statuses:
                                found_statuses.add(target.id.upper())
                elif isinstance(item, ast.AnnAssign):
                    if isinstance(item.target, ast.Name):
                        if item.target.id.upper() in expected_statuses:
                            found_statuses.add(item.target.id.upper())

        # Cari juga definisi enum di luar class (misal di module level)
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if target.id.upper() in expected_statuses:
                        found_statuses.add(target.id.upper())

        # Cari dekorator @enum.unique atau inheritance dari Enum
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if isinstance(base, ast.Name) and base.id == 'Enum':
                    # Ini adalah enum class, cek semua atribut
                    for item in node.body:
                        if isinstance(item, ast.Assign):
                            for target in item.targets:
                                if isinstance(target, ast.Name):
                                    if target.id.upper() in expected_statuses:
                                        found_statuses.add(target.id.upper())

    missing = expected_statuses - found_statuses
    if missing:
        findings.append(Finding(
            file=str(file_path),
            line=1,
            severity="ERROR",
            category="status_lifecycle",
            message=f"Status period tidak lengkap: {', '.join(missing)}",
            detail="Pastikan ada status DRAFT, OPEN, CLOSED, LOCKED di enum atau constants."
        ))
    else:
        # Cek apakah ada transisi status yang valid
        has_transition = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if 'transition' in node.name.lower() or 'change_status' in node.name.lower():
                    has_transition = True
                    break
                # Cek juga method yang mengubah status
                if 'open' in node.name.lower() or 'close' in node.name.lower() or 'lock' in node.name.lower():
                    has_transition = True
                    break

        if not has_transition:
            findings.append(Finding(
                file=str(file_path),
                line=1,
                severity="WARNING",
                category="status_lifecycle",
                message="Tidak ditemukan fungsi transisi status period",
                detail="Tambahkan fungsi untuk mengubah status period (open, close, lock)."
            ))

    return findings

# =============================================================================
# 2. Period Validation Checker
# =============================================================================
def check_period_validation(file_path: pathlib.Path) -> List[Finding]:
    """
    Cari apakah ada validasi period status sebelum posting jurnal.
    """
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    posting_keywords = {'post', 'journal', 'entry', 'record', 'transaction'}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name.lower()
            if not any(k in func_name for k in posting_keywords):
                continue

            has_period_check = False
            # Cek apakah ada pemeriksaan period status
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.If):
                    cond = ast.unparse(stmt.test).lower()
                    if 'period' in cond and ('closed' in cond or 'locked' in cond or 'open' in cond):
                        has_period_check = True
                        break
                    if 'status' in cond and 'period' in cond:
                        has_period_check = True
                        break
                elif isinstance(stmt, ast.Assert):
                    cond = ast.unparse(stmt.test).lower()
                    if 'period' in cond and ('closed' in cond or 'locked' in cond or 'open' in cond):
                        has_period_check = True
                        break
                elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    if isinstance(stmt.value.func, ast.Name):
                        if 'period' in stmt.value.func.id.lower() and ('open' in stmt.value.func.id.lower() or 'closed' in stmt.value.func.id.lower()):
                            has_period_check = True
                            break
                        if 'validate' in stmt.value.func.id.lower() and 'period' in stmt.value.func.id.lower():
                            has_period_check = True
                            break
                    elif isinstance(stmt.value.func, ast.Attribute):
                        if 'period' in stmt.value.func.attr.lower() and ('open' in stmt.value.func.attr.lower() or 'closed' in stmt.value.func.attr.lower()):
                            has_period_check = True
                            break
                        if 'validate' in stmt.value.func.attr.lower() and 'period' in stmt.value.func.attr.lower():
                            has_period_check = True
                            break

            if not has_period_check:
                findings.append(Finding(
                    file=str(file_path),
                    line=node.lineno,
                    severity="ERROR",
                    category="period_validation",
                    message=f"Fungsi '{node.name}' tidak memvalidasi status period sebelum posting",
                    detail="Pastikan period masih OPEN sebelum melakukan posting jurnal."
                ))

    return findings

# =============================================================================
# 3. Fiscal Year Consistency Checker
# =============================================================================
def check_fiscal_year_consistency(file_path: pathlib.Path) -> List[Finding]:
    """
    Cari apakah ada definisi fiscal year yang konsisten.
    """
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    fiscal_year_keywords = {'fiscal_year', 'fiscal_period', 'accounting_period', 'financial_year'}

    for node in ast.walk(tree):
        # Cari class atau fungsi yang terkait fiscal year
        if isinstance(node, ast.ClassDef):
            class_name = node.name.lower()
            if any(k in class_name for k in fiscal_year_keywords):
                # Cek apakah ada atribut untuk start_date dan end_date
                has_start = False
                has_end = False
                for item in node.body:
                    if isinstance(item, ast.Assign) or isinstance(item, ast.AnnAssign):
                        if isinstance(item, ast.Assign):
                            for target in item.targets:
                                if isinstance(target, ast.Name):
                                    if 'start' in target.id.lower() and 'date' in target.id.lower():
                                        has_start = True
                                    if 'end' in target.id.lower() and 'date' in target.id.lower():
                                        has_end = True
                        elif isinstance(item, ast.AnnAssign):
                            if isinstance(item.target, ast.Name):
                                if 'start' in item.target.id.lower() and 'date' in item.target.id.lower():
                                    has_start = True
                                if 'end' in item.target.id.lower() and 'date' in item.target.id.lower():
                                    has_end = True
                if not has_start or not has_end:
                    findings.append(Finding(
                        file=str(file_path),
                        line=node.lineno,
                        severity="WARNING",
                        category="fiscal_year",
                        message=f"Class '{node.name}' tidak memiliki start_date dan end_date untuk fiscal year",
                        detail="Tambahkan atribut start_date dan end_date untuk fiscal period."
                    ))

        # Cari fungsi untuk mendapatkan fiscal year
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name.lower()
            if any(k in func_name for k in fiscal_year_keywords):
                # Cek apakah fungsi mengembalikan fiscal year atau period
                has_return = False
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.Return):
                        has_return = True
                        break
                if not has_return:
                    findings.append(Finding(
                        file=str(file_path),
                        line=node.lineno,
                        severity="WARNING",
                        category="fiscal_year",
                        message=f"Fungsi '{node.name}' tidak mengembalikan fiscal year/period",
                        detail="Pastikan fungsi mengembalikan objek fiscal period yang valid."
                    ))

    return findings

# =============================================================================
# 4. Period Closure Constraints Checker
# =============================================================================
def check_period_closure_constraints(file_path: pathlib.Path) -> List[Finding]:
    """
    Cari apakah ada aturan bahwa period yang sudah CLOSED tidak bisa dibuka kembali.
    """
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    closure_keywords = {'close', 'reopen', 'lock', 'unlock', 'period'}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name.lower()
            # Cari fungsi yang mencoba membuka kembali period
            if 'reopen' in func_name or 'unlock' in func_name:
                # Cek apakah ada validasi bahwa period sudah CLOSED
                has_validation = False
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.If):
                        cond = ast.unparse(stmt.test).lower()
                        if 'closed' in cond or 'locked' in cond:
                            has_validation = True
                            break
                if not has_validation:
                    findings.append(Finding(
                        file=str(file_path),
                        line=node.lineno,
                        severity="ERROR",
                        category="closure_constraint",
                        message=f"Fungsi '{node.name}' tidak memvalidasi period yang sudah CLOSED",
                        detail="Pastikan period yang sudah CLOSED tidak bisa di-reopen."
                    ))

            # Cari fungsi close period
            if 'close' in func_name:
                # Cek apakah ada validasi status sebelum close
                has_status_check = False
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.If):
                        cond = ast.unparse(stmt.test).lower()
                        if 'status' in cond and ('open' in cond or 'draft' in cond):
                            has_status_check = True
                            break
                if not has_status_check:
                    findings.append(Finding(
                        file=str(file_path),
                        line=node.lineno,
                        severity="WARNING",
                        category="closure_constraint",
                        message=f"Fungsi '{node.name}' tidak memeriksa status sebelum close",
                        detail="Pastikan period dalam status OPEN sebelum ditutup."
                    ))

    return findings

# =============================================================================
# 5. Year-End Closing Procedure Checker
# =============================================================================
def check_year_end_closing(file_path: pathlib.Path) -> List[Finding]:
    """
    Cari apakah ada prosedur year-end closing.
    """
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    year_end_keywords = {'year_end', 'year_close', 'closing', 'retained_earnings'}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name.lower()
            if not any(k in func_name for k in year_end_keywords):
                continue

            # Cek apakah ada operasi untuk retained earnings
            has_retained = False
            has_journal = False

            body_str = ast.unparse(node)
            if 'retained' in body_str.lower() and 'earnings' in body_str.lower():
                has_retained = True
            if 'journal' in body_str.lower() or 'entry' in body_str.lower():
                has_journal = True

            # Cek juga apakah ada pemanggilan fungsi untuk closing
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    if isinstance(stmt.value.func, ast.Name):
                        if 'close' in stmt.value.func.id.lower() or 'retained' in stmt.value.func.id.lower():
                            has_retained = True
                    elif isinstance(stmt.value.func, ast.Attribute):
                        if 'close' in stmt.value.func.attr.lower() or 'retained' in stmt.value.func.attr.lower():
                            has_retained = True

            if not has_retained or not has_journal:
                findings.append(Finding(
                    file=str(file_path),
                    line=node.lineno,
                    severity="WARNING",
                    category="year_end",
                    message=f"Fungsi '{node.name}' tidak memiliki prosedur year-end closing lengkap",
                    detail="Pastikan year-end closing mencakup retained earnings adjustment dan closing journal entries."
                ))

    return findings

# =============================================================================
# Main Scanner
# =============================================================================
def scan_project() -> Report:
    report = Report()
    target_dirs = [
        PROJECT_ROOT / "domain" / "fiscal_period",
        PROJECT_ROOT / "domain" / "accounting_period",
        PROJECT_ROOT / "application" / "use_cases",
        PROJECT_ROOT / "application" / "service_layer",
        PROJECT_ROOT / "kernel" / "guards",
    ]

    # Cari juga di domain/shared_value_objects (accounting_period_vo)
    shared_dir = PROJECT_ROOT / "domain" / "shared_value_objects"
    if shared_dir.exists():
        target_dirs.append(shared_dir)

    exclude = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', 'dist', 'build', 'migrations', 'deployment', 'docs', 'tests'}

    for dir_path in target_dirs:
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if any(part in exclude for part in py_file.parts):
                continue
            if py_file.name.startswith("__") or py_file.name.startswith("fiscal_period_checker"):
                continue

            # Cek setiap aspek
            report.findings.extend(check_period_status_lifecycle(py_file))
            report.findings.extend(check_period_validation(py_file))
            report.findings.extend(check_fiscal_year_consistency(py_file))
            report.findings.extend(check_period_closure_constraints(py_file))
            report.findings.extend(check_year_end_closing(py_file))

    # Score: ERROR -10, WARNING -3, INFO 0
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
    print(f"{c['CYAN']}FISCAL PERIOD CHECKER REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"\n  Total findings: {len(report.findings)}")
    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")
    print(f"  Errors: {c['RED']}{errors}{c['RESET']}, Warnings: {c['YELLOW']}{warnings}{c['RESET']}")
    print(f"  Score: {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    if report.findings:
        # Group by category
        categories: Dict[str, List[Finding]] = {}
        for f in report.findings:
            categories.setdefault(f.category, []).append(f)

        print(f"\n{c['CYAN']}By Category:{c['RESET']}")
        for cat, items in categories.items():
            cat_label = {
                'status_lifecycle': 'Period Status Lifecycle',
                'period_validation': 'Period Validation',
                'fiscal_year': 'Fiscal Year Consistency',
                'closure_constraint': 'Period Closure Constraints',
                'year_end': 'Year-End Closing Procedure',
            }.get(cat, cat)
            err_cnt = sum(1 for i in items if i.severity == "ERROR")
            warn_cnt = sum(1 for i in items if i.severity == "WARNING")
            color = c["RED"] if err_cnt > 0 else c["YELLOW"] if warn_cnt > 0 else c["GREEN"]
            print(f"  {cat_label}: {color}{err_cnt} errors, {warn_cnt} warnings{c['RESET']}")

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
    parser = argparse.ArgumentParser(description="Fiscal Period Rules Checker")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    args = parser.parse_args()

    report = scan_project()
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)

    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    sys.exit(0 if errors == 0 else 1)

if __name__ == "__main__":
    main()