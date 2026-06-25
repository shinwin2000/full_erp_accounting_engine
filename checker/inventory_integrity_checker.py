#!/usr/bin/env python3
"""
inventory_integrity_checker.py - Inventory Integrity & Valuation Validator
==========================================================================
Memeriksa kepatuhan terhadap aturan integritas inventaris:
1. Stock tidak boleh negatif (negative stock prevention)
2. Metode valuasi konsisten (FIFO / Weighted Average / Moving Average)
3. COGS calculation yang benar
4. Stock opname reconciliation
5. Audit trail untuk setiap movement

Cara pakai:
  python inventory_integrity_checker.py
  python inventory_integrity_checker.py --verbose
  python inventory_integrity_checker.py --json report.json
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
    category: str       # negative_stock / valuation / cogs / reconciliation / audit
    message: str
    detail: str = ""

@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    score: int = 100

# ----------------------------------------------------------------------
# 1. Negative Stock Prevention Checker
# ----------------------------------------------------------------------
def check_negative_stock_prevention(file_path: pathlib.Path) -> List[Finding]:
    """Cari validasi stock tidak boleh negatif di method movement."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    movement_keywords = {'movement', 'move', 'adjust', 'adjustment', 'transfer', 'issue', 'receive', 'consume'}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name.lower()
            if not any(k in func_name for k in movement_keywords):
                continue

            has_negative_check = False
            for stmt in ast.walk(node):
                # Cek if statement: if quantity < 0 or if stock < 0
                if isinstance(stmt, ast.If):
                    cond = ast.unparse(stmt.test).lower()
                    if ('quantity' in cond or 'stock' in cond or 'qty' in cond) and '< 0' in cond:
                        has_negative_check = True
                        break
                    # Cek raise if quantity negative
                    if 'raise' in ast.unparse(stmt).lower() and ('quantity' in cond or 'stock' in cond):
                        has_negative_check = True
                        break
                # Cek assert: assert quantity >= 0
                elif isinstance(stmt, ast.Assert):
                    cond = ast.unparse(stmt.test).lower()
                    if ('quantity' in cond or 'stock' in cond or 'qty' in cond) and '>= 0' in cond:
                        has_negative_check = True
                        break

                # Cek pemanggilan fungsi validasi seperti validate_quantity()
                elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    if isinstance(stmt.value.func, ast.Name):
                        if 'validate' in stmt.value.func.id.lower() and ('quantity' in stmt.value.func.id.lower() or 'stock' in stmt.value.func.id.lower()):
                            has_negative_check = True
                            break
                    elif isinstance(stmt.value.func, ast.Attribute):
                        if 'validate' in stmt.value.func.attr.lower() and ('quantity' in stmt.value.func.attr.lower() or 'stock' in stmt.value.func.attr.lower()):
                            has_negative_check = True
                            break

            if not has_negative_check:
                findings.append(Finding(
                    file=str(file_path),
                    line=node.lineno,
                    severity="ERROR",
                    category="negative_stock",
                    message=f"Fungsi '{node.name}' tidak memiliki validasi stock negatif",
                    detail="Tambahkan pemeriksaan untuk memastikan quantity >= 0 sebelum movement."
                ))
    return findings

# ----------------------------------------------------------------------
# 2. Valuation Method Checker
# ----------------------------------------------------------------------
def check_valuation_method(file_path: pathlib.Path) -> List[Finding]:
    """Cari implementasi metode valuasi (FIFO, Weighted Average, Moving Average)."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    valuation_classes = {'fifo', 'weighted_average', 'moving_average', 'valuation', 'costing'}

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            class_name = node.name.lower()
            # Cari class yang mengimplementasikan valuasi
            if any(k in class_name for k in valuation_classes):
                # Cek method untuk menghitung cost
                has_cost_calc = False
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        if any(k in item.name.lower() for k in ('cost', 'value', 'calculate')):
                            has_cost_calc = True
                            break
                if not has_cost_calc:
                    findings.append(Finding(
                        file=str(file_path),
                        line=node.lineno,
                        severity="WARNING",
                        category="valuation",
                        message=f"Class '{node.name}' tidak memiliki method perhitungan cost/value",
                        detail="Pastikan ada method calculate_cost() atau calculate_value()."
                    ))
            # Cari jika ada constant untuk metode valuasi
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            if 'method' in target.id.lower() or 'valuation' in target.id.lower():
                                # Cek apakah nilainya salah satu yang valid
                                if isinstance(item.value, ast.Constant):
                                    val = str(item.value.value).lower()
                                    if val not in ['fifo', 'weighted_average', 'moving_average', 'lifo']:
                                        findings.append(Finding(
                                            file=str(file_path),
                                            line=item.lineno,
                                            severity="ERROR",
                                            category="valuation",
                                            message=f"Metode valuasi tidak valid: {val}",
                                            detail="Gunakan FIFO, Weighted Average, atau Moving Average."
                                        ))

    # Cek di fungsi-fungsi terkait inventory
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name.lower()
            if 'valuation' in func_name or 'cost' in func_name:
                # Cek apakah ada logika perhitungan
                has_logic = False
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.BinOp) and isinstance(stmt.op, (ast.Mult, ast.Div, ast.Add, ast.Sub)):
                        # Ada operasi aritmatika, mungkin perhitungan
                        has_logic = True
                        break
                if not has_logic:
                    findings.append(Finding(
                        file=str(file_path),
                        line=node.lineno,
                        severity="WARNING",
                        category="valuation",
                        message=f"Fungsi '{node.name}' tidak memiliki logika perhitungan cost",
                        detail="Implementasikan perhitungan sesuai metode valuasi yang dipilih."
                    ))
    return findings

# ----------------------------------------------------------------------
# 3. COGS Calculation Checker
# ----------------------------------------------------------------------
def check_cogs_calculation(file_path: pathlib.Path) -> List[Finding]:
    """Cari implementasi COGS (Cost of Goods Sold) calculation."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    cogs_keywords = {'cogs', 'cost_of_goods_sold', 'hpp'}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name.lower()
            if not any(k in func_name for k in cogs_keywords):
                continue

            # Cek apakah ada formula COGS: beginning + purchases - ending
            has_formula = False
            body_str = ast.unparse(node)
            if 'beginning' in body_str.lower() and 'purchase' in body_str.lower() and 'ending' in body_str.lower():
                has_formula = True
            # Cek operasi aritmatika
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.BinOp) and isinstance(stmt.op, (ast.Add, ast.Sub)):
                    if has_formula:
                        break
                    op_str = ast.unparse(stmt)
                    if any(k in op_str.lower() for k in ['beginning', 'purchase', 'ending', 'inventory']):
                        has_formula = True
                        break

            if not has_formula:
                findings.append(Finding(
                    file=str(file_path),
                    line=node.lineno,
                    severity="WARNING",
                    category="cogs",
                    message=f"Fungsi '{node.name}' tidak memiliki formula COGS yang jelas",
                    detail="Pastikan COGS = Beginning Inventory + Purchases - Ending Inventory."
                ))

    return findings

# ----------------------------------------------------------------------
# 4. Reconciliation Checker (Stock Opname)
# ----------------------------------------------------------------------
def check_reconciliation(file_path: pathlib.Path) -> List[Finding]:
    """Cari apakah ada stock opname reconciliation."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    reconcile_keywords = {'reconcile', 'opname', 'physical', 'adjust', 'adjustment', 'count'}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name.lower()
            if not any(k in func_name for k in reconcile_keywords):
                continue

            # Cek apakah ada perbandingan system vs physical
            has_comparison = False
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Compare):
                    comp_str = ast.unparse(stmt)
                    if 'system' in comp_str.lower() and 'physical' in comp_str.lower():
                        has_comparison = True
                        break
                    if 'actual' in comp_str.lower() and 'expected' in comp_str.lower():
                        has_comparison = True
                        break
                if isinstance(stmt, ast.Assign):
                    # Cek assignment variabel seperti difference = system - physical
                    if isinstance(stmt.value, ast.BinOp) and isinstance(stmt.value.op, ast.Sub):
                        val_str = ast.unparse(stmt.value)
                        if 'system' in val_str.lower() or 'physical' in val_str.lower():
                            has_comparison = True
                            break

            if not has_comparison:
                findings.append(Finding(
                    file=str(file_path),
                    line=node.lineno,
                    severity="WARNING",
                    category="reconciliation",
                    message=f"Fungsi '{node.name}' tidak membandingkan system vs physical stock",
                    detail="Tambahkan logika untuk menghitung selisih antara system dan stock opname."
                ))

    return findings

# ----------------------------------------------------------------------
# 5. Audit Trail for Inventory Movements
# ----------------------------------------------------------------------
def check_audit_trail_inventory(file_path: pathlib.Path) -> List[Finding]:
    """Cari apakah setiap movement mencatat audit trail."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    movement_keywords = {'movement', 'move', 'adjust', 'transfer', 'issue', 'receive'}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name.lower()
            if not any(k in func_name for k in movement_keywords):
                continue

            has_audit = False
            for stmt in ast.walk(node):
                # Cek pemanggilan log/event/audit
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
                # Cek assignment ke field audit
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
                    message=f"Fungsi '{node.name}' tidak mencatat audit trail untuk movement",
                    detail="Tambahkan logging/event publishing untuk setiap movement inventaris."
                ))

    return findings

# ----------------------------------------------------------------------
# Main Scanner
# ----------------------------------------------------------------------
def scan_inventory() -> Report:
    report = Report()
    target_dirs = [
        PROJECT_ROOT / "domain" / "inventory",
        PROJECT_ROOT / "application" / "use_cases",
        PROJECT_ROOT / "application" / "service_layer",
    ]
    # Cari juga di domain/subledger_inventory jika ada
    domain_dir = PROJECT_ROOT / "domain"
    if domain_dir.exists():
        for sub in domain_dir.iterdir():
            if sub.is_dir() and 'inventory' in sub.name.lower():
                target_dirs.append(sub)

    exclude = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', 'dist', 'build', 'migrations', 'deployment', 'docs', 'tests'}

    for dir_path in target_dirs:
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if any(part in exclude for part in py_file.parts):
                continue
            if py_file.name.startswith("__") or py_file.name.startswith("inventory_integrity_checker"):
                continue

            report.findings.extend(check_negative_stock_prevention(py_file))
            report.findings.extend(check_valuation_method(py_file))
            report.findings.extend(check_cogs_calculation(py_file))
            report.findings.extend(check_reconciliation(py_file))
            report.findings.extend(check_audit_trail_inventory(py_file))

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
    print(f"{c['CYAN']}INVENTORY INTEGRITY CHECKER REPORT{c['RESET']}")
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
        for cat, items in categories.items():
            cat_label = {
                'negative_stock': 'Negative Stock Prevention',
                'valuation': 'Valuation Method',
                'cogs': 'COGS Calculation',
                'reconciliation': 'Stock Opname Reconciliation',
                'audit': 'Audit Trail',
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

# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Inventory Integrity Checker")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    args = parser.parse_args()

    report = scan_inventory()
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)

    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    sys.exit(0 if errors == 0 else 1)

if __name__ == "__main__":
    main()