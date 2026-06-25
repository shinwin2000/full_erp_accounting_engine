#!/usr/bin/env python3
"""
general_ledger_checker.py - General Ledger Integrity Validator
===============================================================
Memeriksa kepatuhan terhadap aturan General Ledger:
1. Double-entry balance (debit == credit)
2. Account validation (account harus ada di COA)
3. Period validation (tidak boleh posting ke period closed/locked)
4. Audit trail untuk setiap posting GL
5. Reconciliation consistency (GL vs sub-ledger)

Cara pakai:
  python general_ledger_checker.py
  python general_ledger_checker.py --verbose
  python general_ledger_checker.py --json report.json
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

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
    category: str       # balance / account_validation / period / audit / reconciliation
    message: str
    detail: str = ""

@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    score: int = 100

# ----------------------------------------------------------------------
# 1. Double-entry Balance Checker
# ----------------------------------------------------------------------
def check_balance_validation(file_path: pathlib.Path) -> List[Finding]:
    """Cari apakah ada validasi debit == credit sebelum posting GL."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    gl_keywords = {'post', 'journal', 'entry', 'gl', 'ledger', 'record'}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name.lower()
            if not any(k in func_name for k in gl_keywords):
                continue

            # Cek validasi balance
            has_balance_check = False
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.If):
                    cond = ast.unparse(stmt.test).lower()
                    if ('debit' in cond and 'credit' in cond) and ('==' in cond or '!=' in cond or '>=' in cond):
                        has_balance_check = True
                        break
                elif isinstance(stmt, ast.Assert):
                    cond = ast.unparse(stmt.test).lower()
                    if 'debit' in cond and 'credit' in cond:
                        has_balance_check = True
                        break
                elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    if isinstance(stmt.value.func, ast.Name):
                        if 'balance' in stmt.value.func.id.lower() or 'validate' in stmt.value.func.id.lower():
                            has_balance_check = True
                            break
                    elif isinstance(stmt.value.func, ast.Attribute):
                        if 'balance' in stmt.value.func.attr.lower() or 'validate' in stmt.value.func.attr.lower():
                            has_balance_check = True
                            break

            if not has_balance_check:
                findings.append(Finding(
                    file=str(file_path),
                    line=node.lineno,
                    severity="ERROR",
                    category="balance",
                    message=f"Fungsi '{node.name}' tidak memiliki validasi double-entry (debit == credit)",
                    detail="Tambahkan pemeriksaan total debit == total credit sebelum menyimpan GL."
                ))
    return findings

# ----------------------------------------------------------------------
# 2. Account Validation Checker
# ----------------------------------------------------------------------
def check_account_validation(file_path: pathlib.Path) -> List[Finding]:
    """Cari apakah account yang diposting divalidasi terhadap COA."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name.lower()
            if not any(k in func_name for k in ('post', 'journal', 'entry', 'gl', 'record')):
                continue

            # Cek validasi account
            has_account_validation = False
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.If):
                    cond = ast.unparse(stmt.test).lower()
                    if 'account' in cond and ('valid' in cond or 'exists' in cond or 'found' in cond):
                        has_account_validation = True
                        break
                elif isinstance(stmt, ast.Assert):
                    cond = ast.unparse(stmt.test).lower()
                    if 'account' in cond and ('valid' in cond or 'exists' in cond):
                        has_account_validation = True
                        break
                elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    if isinstance(stmt.value.func, ast.Name):
                        if 'validate_account' in stmt.value.func.id.lower() or 'check_account' in stmt.value.func.id.lower():
                            has_account_validation = True
                            break
                    elif isinstance(stmt.value.func, ast.Attribute):
                        if 'validate_account' in stmt.value.func.attr.lower() or 'check_account' in stmt.value.func.attr.lower():
                            has_account_validation = True
                            break

            # Cek juga apakah ada import/ref ke COA atau AccountRepository
            if not has_account_validation:
                # Cari import dari COA atau repository
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.ImportFrom):
                        if stmt.module and ('coa' in stmt.module.lower() or 'account' in stmt.module.lower()):
                            has_account_validation = True
                            break
                    if isinstance(stmt, ast.Import):
                        for alias in stmt.names:
                            if 'coa' in alias.name.lower() or 'account' in alias.name.lower():
                                has_account_validation = True
                                break

            if not has_account_validation:
                findings.append(Finding(
                    file=str(file_path),
                    line=node.lineno,
                    severity="ERROR",
                    category="account_validation",
                    message=f"Fungsi '{node.name}' tidak memvalidasi account terhadap COA",
                    detail="Pastikan account yang diposting terdaftar di Chart of Accounts."
                ))
    return findings

# ----------------------------------------------------------------------
# 3. Period Validation Checker
# ----------------------------------------------------------------------
def check_period_validation_gl(file_path: pathlib.Path) -> List[Finding]:
    """Cari apakah period dipastikan open sebelum posting GL."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name.lower()
            if not any(k in func_name for k in ('post', 'journal', 'entry', 'gl', 'record')):
                continue

            has_period_check = False
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.If):
                    cond = ast.unparse(stmt.test).lower()
                    if 'period' in cond and ('closed' in cond or 'locked' in cond or 'open' in cond):
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
                    elif isinstance(stmt.value.func, ast.Attribute):
                        if 'period' in stmt.value.func.attr.lower() and ('open' in stmt.value.func.attr.lower() or 'closed' in stmt.value.func.attr.lower()):
                            has_period_check = True
                            break

            if not has_period_check:
                findings.append(Finding(
                    file=str(file_path),
                    line=node.lineno,
                    severity="ERROR",
                    category="period",
                    message=f"Fungsi '{node.name}' tidak memeriksa status period (open/closed)",
                    detail="Tambahkan pemeriksaan period status sebelum posting GL."
                ))
    return findings

# ----------------------------------------------------------------------
# 4. Audit Trail Checker for GL
# ----------------------------------------------------------------------
def check_audit_trail_gl(file_path: pathlib.Path) -> List[Finding]:
    """Cari apakah setiap posting GL mencatat audit trail."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name.lower()
            if not any(k in func_name for k in ('post', 'journal', 'entry', 'gl', 'record')):
                continue

            has_audit = False
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    if isinstance(stmt.value.func, ast.Name):
                        fn = stmt.value.func.id.lower()
                        if any(k in fn for k in ('event', 'audit', 'log', 'record')):
                            has_audit = True
                            break
                    elif isinstance(stmt.value.func, ast.Attribute):
                        attr = stmt.value.func.attr.lower()
                        if any(k in attr for k in ('event', 'audit', 'log', 'record')):
                            has_audit = True
                            break
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            if any(k in target.id.lower() for k in ('audit', 'event', 'log')):
                                has_audit = True
                                break

            if not has_audit:
                findings.append(Finding(
                    file=str(file_path),
                    line=node.lineno,
                    severity="WARNING",
                    category="audit",
                    message=f"Fungsi '{node.name}' tidak mencatat audit trail untuk posting GL",
                    detail="Tambahkan logging/event publishing untuk setiap transaksi GL."
                ))
    return findings

# ----------------------------------------------------------------------
# 5. Reconciliation Consistency Check
# ----------------------------------------------------------------------
def check_reconciliation_gl(file_path: pathlib.Path) -> List[Finding]:
    """Cari apakah ada proses rekonsiliasi antara GL dan sub-ledger."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    reconcile_keywords = {'reconcile', 'reconciliation', 'match', 'compare'}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name.lower()
            if not any(k in func_name for k in reconcile_keywords):
                continue

            # Cek apakah ada perbandingan GL vs sub-ledger
            has_comparison = False
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Compare):
                    comp_str = ast.unparse(stmt)
                    if ('gl' in comp_str.lower() or 'general_ledger' in comp_str.lower()) and ('subledger' in comp_str.lower() or 'sub_ledger' in comp_str.lower()):
                        has_comparison = True
                        break
                if isinstance(stmt, ast.Assign):
                    if isinstance(stmt.value, ast.BinOp) and isinstance(stmt.value.op, (ast.Sub, ast.Eq)):
                        val_str = ast.unparse(stmt.value)
                        if ('gl' in val_str.lower() or 'general_ledger' in val_str.lower()) and ('subledger' in val_str.lower() or 'sub_ledger' in val_str.lower()):
                            has_comparison = True
                            break

            if not has_comparison:
                findings.append(Finding(
                    file=str(file_path),
                    line=node.lineno,
                    severity="WARNING",
                    category="reconciliation",
                    message=f"Fungsi '{node.name}' tidak melakukan rekonsiliasi GL vs sub-ledger",
                    detail="Implementasikan proses rekonsiliasi untuk memastikan konsistensi GL."
                ))

    return findings

# ----------------------------------------------------------------------
# 6. GL Posting Integrity Check
# ----------------------------------------------------------------------
def check_posting_integrity(file_path: pathlib.Path) -> List[Finding]:
    """Cari apakah ada atomicity dalam posting (semua atau tidak sama sekali)."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name.lower()
            if not any(k in func_name for k in ('post', 'journal', 'entry', 'gl')):
                continue

            # Cek apakah ada transaksi/Unit of Work
            has_transaction = False
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.With):
                    # Cek context manager seperti with transaction: atau with unit_of_work:
                    for item in stmt.items:
                        if isinstance(item.context_expr, ast.Call):
                            if isinstance(item.context_expr.func, ast.Name):
                                if 'transaction' in item.context_expr.func.id.lower() or 'unit_of_work' in item.context_expr.func.id.lower():
                                    has_transaction = True
                                    break
                            elif isinstance(item.context_expr.func, ast.Attribute):
                                if 'transaction' in item.context_expr.func.attr.lower() or 'unit_of_work' in item.context_expr.func.attr.lower():
                                    has_transaction = True
                                    break
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    if isinstance(stmt.value.func, ast.Name):
                        if 'begin_transaction' in stmt.value.func.id.lower():
                            has_transaction = True
                            break
                    elif isinstance(stmt.value.func, ast.Attribute):
                        if 'begin_transaction' in stmt.value.func.attr.lower():
                            has_transaction = True
                            break

            if not has_transaction:
                findings.append(Finding(
                    file=str(file_path),
                    line=node.lineno,
                    severity="WARNING",
                    category="integrity",
                    message=f"Fungsi '{node.name}' tidak menggunakan transaksi/Unit of Work",
                    detail="Gunakan transaksi database untuk memastikan atomicity posting GL."
                ))
    return findings

# ----------------------------------------------------------------------
# Main Scanner
# ----------------------------------------------------------------------
def scan_gl() -> Report:
    report = Report()
    target_dirs = [
        PROJECT_ROOT / "domain" / "journal",
        PROJECT_ROOT / "application" / "use_cases",
        PROJECT_ROOT / "application" / "service_layer",
        PROJECT_ROOT / "projections" / "ledger",
    ]
    # Tambahkan semua folder domain yang mengandung 'gl' atau 'ledger'
    domain_dir = PROJECT_ROOT / "domain"
    if domain_dir.exists():
        for sub in domain_dir.iterdir():
            if sub.is_dir() and any(k in sub.name.lower() for k in ('gl', 'ledger', 'journal')):
                target_dirs.append(sub)

    exclude = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', 'dist', 'build', 'migrations', 'deployment', 'docs', 'tests'}

    for dir_path in target_dirs:
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if any(part in exclude for part in py_file.parts):
                continue
            if py_file.name.startswith("__") or py_file.name.startswith("general_ledger_checker"):
                continue

            report.findings.extend(check_balance_validation(py_file))
            report.findings.extend(check_account_validation(py_file))
            report.findings.extend(check_period_validation_gl(py_file))
            report.findings.extend(check_audit_trail_gl(py_file))
            report.findings.extend(check_reconciliation_gl(py_file))
            report.findings.extend(check_posting_integrity(py_file))

    # Score: ERROR -10, WARNING -3
    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")
    report.score = max(0, 100 - errors * 10 - warnings * 3)
    return report

# ----------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------
def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}GENERAL LEDGER INTEGRITY CHECKER REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"\n  Total findings: {len(report.findings)}")
    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")
    print(f"  Errors: {c['RED']}{errors}{c['RESET']}, Warnings: {c['YELLOW']}{warnings}{c['RESET']}")
    print(f"  Score: {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    if report.findings:
        # Group by category
        categories = {}
        for f in report.findings:
            categories.setdefault(f.category, []).append(f)

        print(f"\n{c['CYAN']}By Category:{c['RESET']}")
        cat_labels = {
            'balance': 'Double-entry Balance',
            'account_validation': 'Account Validation',
            'period': 'Period Validation',
            'audit': 'Audit Trail',
            'reconciliation': 'Reconciliation',
            'integrity': 'Posting Integrity (Atomicity)',
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

# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="General Ledger Integrity Checker")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    args = parser.parse_args()

    report = scan_gl()
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)

    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    sys.exit(0 if errors == 0 else 1)

if __name__ == "__main__":
    main()