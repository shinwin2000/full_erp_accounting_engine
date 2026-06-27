#!/usr/bin/env python3
"""
money_precision_checker.py - Monetary Precision & Decimal Usage Validator
===========================================================================
Memeriksa penggunaan tipe data untuk nilai moneter:
- WAJIB menggunakan Decimal, bukan float
- Deteksi float pada field: amount, debit, credit, price, cost, tax, total, balance, value, dll.
- Deteksi operasi aritmatika float yang tidak aman
- Deteksi pembulatan (round) tanpa Decimal context

Cara pakai:
  python money_precision_checker.py
  python money_precision_checker.py --verbose
  python money_precision_checker.py --json report.json
  python money_precision_checker.py --fix  # (opsional) rekomendasi perbaikan
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
from dataclasses import dataclass, field

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

# Daftar nama field yang seharusnya menggunakan Decimal
MONETARY_FIELDS = {
    'amount', 'debit', 'credit', 'price', 'cost', 'tax', 'total', 'balance',
    'value', 'subtotal', 'discount', 'fee', 'commission', 'interest', 'penalty',
    'payment', 'refund', 'adjustment', 'settlement', 'premium', 'deposit',
    'withdrawal', 'transfer', 'exchange', 'rate', 'currency_amount'
}

# Kata kunci untuk operasi yang melibatkan uang
MONEY_OPERATIONS = {'price', 'cost', 'tax', 'total', 'amount', 'balance', 'value'}

@dataclass
class Finding:
    file: str
    line: int
    severity: str       # ERROR / WARNING
    category: str       # float_type / float_cast / float_arithmetic / rounding
    message: str
    snippet: str = ""
    recommendation: str = ""

@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    score: int = 100

# ----------------------------------------------------------------------
# 1. Deteksi float type hint untuk field moneter
# ----------------------------------------------------------------------
def detect_float_type_hint(file_path: pathlib.Path) -> list[Finding]:
    """Cari type hint : float pada field moneter."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    for node in ast.walk(tree):
        # Cari assignment atau function definition dengan annotation
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                field_name = node.target.id.lower()
                if field_name in MONETARY_FIELDS:
                    if isinstance(node.annotation, ast.Name) and node.annotation.id == 'float':
                        findings.append(Finding(
                            file=str(file_path),
                            line=node.lineno,
                            severity="ERROR",
                            category="float_type",
                            message=f"Field '{node.target.id}' menggunakan type hint float (harus Decimal)",
                            snippet=ast.unparse(node),
                            recommendation="Ganti 'float' dengan 'Decimal' dari decimal module"
                        ))
        # Cari argumen fungsi dengan annotation float
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in node.args.args:
                if arg.annotation:
                    if isinstance(arg.annotation, ast.Name) and arg.annotation.id == 'float':
                        arg_name = arg.arg.lower()
                        if arg_name in MONETARY_FIELDS:
                            findings.append(Finding(
                                file=str(file_path),
                                line=arg.lineno,
                                severity="ERROR",
                                category="float_type",
                                message=f"Parameter '{arg.arg}' bertipe float (harus Decimal)",
                                snippet=f"def {node.name}({arg.arg}: float)",
                                recommendation="Ganti 'float' dengan 'Decimal'"
                            ))
    return findings

# ----------------------------------------------------------------------
# 2. Deteksi float() casting pada nilai moneter
# ----------------------------------------------------------------------
def detect_float_cast(file_path: pathlib.Path) -> list[Finding]:
    """Cari pemanggilan float() pada variabel yang berisi nilai moneter."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == 'float':
                # Cek apakah argumennya adalah variabel yang mungkin moneter
                if node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Name):
                        var_name = arg.id.lower()
                        if any(field in var_name for field in MONETARY_FIELDS):
                            findings.append(Finding(
                                file=str(file_path),
                                line=node.lineno,
                                severity="ERROR",
                                category="float_cast",
                                message=f"Penggunaan float() pada variabel '{arg.id}' (nilai moneter)",
                                snippet=ast.unparse(node),
                                recommendation="Gunakan Decimal() atau Decimal(str(value))"
                            ))
                    elif isinstance(arg, ast.Constant) and isinstance(arg.value, (int, float)):
                        # float literal
                        findings.append(Finding(
                            file=str(file_path),
                            line=node.lineno,
                            severity="WARNING",
                            category="float_cast",
                            message="Literal float digunakan langsung",
                            snippet=ast.unparse(node),
                            recommendation="Gunakan Decimal('...') atau Decimal(integer)"
                        ))
    return findings

# ----------------------------------------------------------------------
# 3. Deteksi operasi aritmatika float pada nilai moneter
# ----------------------------------------------------------------------
def detect_float_arithmetic(file_path: pathlib.Path) -> list[Finding]:
    """Cari operasi +, -, *, / pada variabel moneter (tanpa Decimal)."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp):
            # Cek apakah left atau right adalah variabel moneter
            left = node.left
            right = node.right
            # Coba ekstrak nama variabel
            var_names = []
            if isinstance(left, ast.Name):
                var_names.append(left.id.lower())
            if isinstance(right, ast.Name):
                var_names.append(right.id.lower())
            # Jika ada nama yang mengandung kata moneter
            if any(any(field in v for field in MONETARY_FIELDS) for v in var_names):
                # Cek apakah operasi menggunakan float literal atau int literal
                has_float_literal = False
                if isinstance(left, ast.Constant) and isinstance(left.value, float):
                    has_float_literal = True
                if isinstance(right, ast.Constant) and isinstance(right.value, float):
                    has_float_literal = True
                # Cek apakah ada pembagian (/), yang bisa menghasilkan float
                if isinstance(node.op, ast.Div):
                    findings.append(Finding(
                        file=str(file_path),
                        line=node.lineno,
                        severity="WARNING",
                        category="float_arithmetic",
                        message="Pembagian (/) pada nilai moneter dapat menghasilkan float",
                        snippet=ast.unparse(node),
                        recommendation="Gunakan Decimal division atau bulatkan dengan quantize"
                    ))
                elif has_float_literal:
                    findings.append(Finding(
                        file=str(file_path),
                        line=node.lineno,
                        severity="WARNING",
                        category="float_arithmetic",
                        message="Operasi dengan float literal pada nilai moneter",
                        snippet=ast.unparse(node),
                        recommendation="Gunakan Decimal untuk operasi moneter"
                    ))
    return findings

# ----------------------------------------------------------------------
# 4. Deteksi penggunaan round() pada nilai moneter
# ----------------------------------------------------------------------
def detect_rounding(file_path: pathlib.Path) -> list[Finding]:
    """Cari penggunaan round() pada nilai moneter."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == 'round':
                if node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Name):
                        var_name = arg.id.lower()
                        if any(field in var_name for field in MONETARY_FIELDS):
                            findings.append(Finding(
                                file=str(file_path),
                                line=node.lineno,
                                severity="WARNING",
                                category="rounding",
                                message=f"Penggunaan round() pada '{arg.id}' (nilai moneter)",
                                snippet=ast.unparse(node),
                                recommendation="Gunakan Decimal.quantize() untuk pembulatan yang aman"
                            ))
    return findings

# ----------------------------------------------------------------------
# 5. Deteksi field assignment langsung dengan float
# ----------------------------------------------------------------------
def detect_float_assignment(file_path: pathlib.Path) -> list[Finding]:
    """Cari assignment nilai float ke field moneter."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    field_name = target.id.lower()
                    if field_name in MONETARY_FIELDS:
                        # Cek apakah value adalah float literal
                        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, float):
                            findings.append(Finding(
                                file=str(file_path),
                                line=node.lineno,
                                severity="ERROR",
                                category="float_assignment",
                                message=f"Assign float literal ke field '{target.id}' (moneter)",
                                snippet=ast.unparse(node),
                                recommendation="Gunakan Decimal('...') untuk literal"
                            ))
                        # Cek apakah value adalah operasi yang menghasilkan float
                        if isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Div):
                            findings.append(Finding(
                                file=str(file_path),
                                line=node.lineno,
                                severity="WARNING",
                                category="float_assignment",
                                message=f"Assign hasil pembagian ke field '{target.id}' (moneter)",
                                snippet=ast.unparse(node),
                                recommendation="Gunakan Decimal division"
                            ))
    return findings

# ----------------------------------------------------------------------
# Main Scanner
# ----------------------------------------------------------------------
def scan_money_precision() -> Report:
    report = Report()
    exclude = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', 'dist', 'build', 'migrations', 'deployment', 'docs', 'tests'}

    for py_file in PROJECT_ROOT.rglob("*.py"):
        if any(part in exclude for part in py_file.parts):
            continue
        if py_file.name.startswith("money_precision_checker"):
            continue

        report.findings.extend(detect_float_type_hint(py_file))
        report.findings.extend(detect_float_cast(py_file))
        report.findings.extend(detect_float_arithmetic(py_file))
        report.findings.extend(detect_rounding(py_file))
        report.findings.extend(detect_float_assignment(py_file))

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
    print(f"{c['CYAN']}MONEY PRECISION CHECKER REPORT{c['RESET']}")
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
            'float_type': 'Float Type Hint',
            'float_cast': 'Float Casting',
            'float_arithmetic': 'Float Arithmetic',
            'rounding': 'Rounding',
            'float_assignment': 'Float Assignment',
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
            if verbose:
                print(f"     Snippet: {f.snippet}")
                if f.recommendation:
                    print(f"     {c['CYAN']}💡 {f.recommendation}{c['RESET']}")
        if len(report.findings) > 30:
            print(f"  ... and {len(report.findings)-30} more findings")

def save_json(report: Report, filepath: str):
    data = {
        "findings": [
            {"file": f.file, "line": f.line, "severity": f.severity,
             "category": f.category, "message": f.message,
             "snippet": f.snippet, "recommendation": f.recommendation}
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
    parser = argparse.ArgumentParser(description="Money Precision Checker")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    args = parser.parse_args()

    report = scan_money_precision()
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)

    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    sys.exit(0 if errors == 0 else 1)

if __name__ == "__main__":
    main()
