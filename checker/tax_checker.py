#!/usr/bin/env python3
"""
tax_checker.py - Tax Implementation Validator
==============================================
Memeriksa kelengkapan dan kebenaran implementasi perpajakan (PPN, PPh, dll.)

Fitur:
- Cek keberadaan file kalkulator utama
- Cek metode calculate, validate, get_rate
- Cek penggunaan Decimal untuk uang
- Deteksi hardcoded tarif
- Cek konsistensi tarif dengan ketentuan

Cara pakai:
  python tax_checker.py
  python tax_checker.py --verbose
  python tax_checker.py --json report.json
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

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

# -----------------------------------------------------------------------------
# Data Structures
# -----------------------------------------------------------------------------
@dataclass
class TaxCalculatorInfo:
    file: str
    name: str
    class_name: str
    has_calculate: bool
    has_validate: bool
    has_get_rate: bool
    has_rate_constant: bool
    uses_decimal: bool
    hardcoded_rates: List[str]
    methods: List[str]

@dataclass
class Violation:
    file: str
    line: int
    message: str
    severity: str  # ERROR or WARNING

@dataclass
class Report:
    calculators: List[TaxCalculatorInfo] = field(default_factory=list)
    violations: List[Violation] = field(default_factory=list)
    score: int = 100

# -----------------------------------------------------------------------------
# Tax Calculator File Detection
# -----------------------------------------------------------------------------
EXPECTED_CALCULATORS = [
    "ppn_calculator",
    "pph_21_calculator",
    "pph_22_calculator",
    "pph_23_calculator",
    "pph_25_calculator",
    "pph_26_calculator",
    "pph_4_ayat_2_calculator",
    "pph_badan_calculator",
    "bea_meterai_calculator",
    "withholding_engine",
    "rate_registry_dynamic",
    "penalty_interest_engine",
]

TAX_DIR = PROJECT_ROOT / "policy_engine" / "tax_indonesia"

# -----------------------------------------------------------------------------
# AST Analysis
# -----------------------------------------------------------------------------
def parse_tax_file(file_path: pathlib.Path) -> Optional[TaxCalculatorInfo]:
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return None

    # Cari class yang mungkin calculator (biasanya satu class utama)
    classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    if not classes:
        return None

    cls = classes[0]
    methods = [item.name for item in cls.body if isinstance(item, ast.FunctionDef)]

    has_calculate = any('calculate' in m.lower() for m in methods)
    has_validate = any('validate' in m.lower() for m in methods)
    has_get_rate = any('get_rate' in m.lower() for m in methods)

    # Cek adanya konstanta tarif (misal PPN = 0.11 atau RATE = 0.11)
    has_rate_constant = False
    hardcoded_rates = []
    for item in cls.body:
        if isinstance(item, ast.Assign):
            for target in item.targets:
                if isinstance(target, ast.Name) and 'rate' in target.id.lower():
                    has_rate_constant = True
                    # Cek apakah nilai adalah angka literal
                    if isinstance(item.value, ast.Constant) and isinstance(item.value.value, (int, float)):
                        hardcoded_rates.append(f"{target.id}={item.value.value}")
                    break

    # Cek penggunaan Decimal
    uses_decimal = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == 'Decimal':
            uses_decimal = True
            break
        if isinstance(node, ast.Attribute) and node.attr == 'Decimal':
            uses_decimal = True
            break
        # Import from decimal import Decimal
        if isinstance(node, ast.ImportFrom) and node.module == 'decimal':
            for alias in node.names:
                if alias.name == 'Decimal':
                    uses_decimal = True
                    break

    # Ekstrak hardcoded rates dari body (nilai literal)
    # Kami sudah menangani di atas

    return TaxCalculatorInfo(
        file=str(file_path),
        name=file_path.stem,
        class_name=cls.name,
        has_calculate=has_calculate,
        has_validate=has_validate,
        has_get_rate=has_get_rate,
        has_rate_constant=has_rate_constant,
        uses_decimal=uses_decimal,
        hardcoded_rates=hardcoded_rates,
        methods=methods,
    )

# -----------------------------------------------------------------------------
# Validation Rules
# -----------------------------------------------------------------------------
def validate_calculator(info: TaxCalculatorInfo) -> List[Violation]:
    violations = []
    # ERROR: Missing calculate method
    if not info.has_calculate:
        violations.append(Violation(
            file=info.file,
            line=0,
            message=f"Calculator {info.name} tidak memiliki method 'calculate'",
            severity="ERROR"
        ))
    # WARNING: Missing validate
    if not info.has_validate:
        violations.append(Violation(
            file=info.file,
            line=0,
            message=f"Calculator {info.name} tidak memiliki method 'validate'",
            severity="WARNING"
        ))
    # WARNING: Missing get_rate
    if not info.has_get_rate:
        violations.append(Violation(
            file=info.file,
            line=0,
            message=f"Calculator {info.name} tidak memiliki method 'get_rate'",
            severity="WARNING"
        ))
    # WARNING: Hardcoded rates
    if info.hardcoded_rates:
        for rate in info.hardcoded_rates:
            violations.append(Violation(
                file=info.file,
                line=0,
                message=f"Hardcoded rate ditemukan: {rate}. Sebaiknya dari konfigurasi.",
                severity="WARNING"
            ))
    # ERROR: Not using Decimal
    if not info.uses_decimal:
        violations.append(Violation(
            file=info.file,
            line=0,
            message=f"Calculator {info.name} tidak menggunakan Decimal. Gunakan Decimal untuk akurasi uang.",
            severity="ERROR"
        ))
    return violations

# -----------------------------------------------------------------------------
# Additional Checks (Rate Consistency)
# -----------------------------------------------------------------------------
def check_rate_consistency() -> List[Violation]:
    # Tarif standar berdasarkan ketentuan (hanya contoh)
    expected_rates = {
        "ppn_calculator": 0.11,  # 11% mulai 2022
        "pph_21_calculator": "progressive",
        "pph_22_calculator": "0.1% - 7.5%",
        "pph_23_calculator": "2% - 15%",
        "pph_25_calculator": "25%",
        "pph_26_calculator": "20%",
        "pph_4_ayat_2_calculator": "0.5% - 10%",
        "pph_badan_calculator": "22%",
        "bea_meterai_calculator": 10000,  # 2022
    }
    violations = []
    # Kita scan file untuk melihat apakah ada komentar atau docstring yang menyebutkan tarif
    for calc_name, expected in expected_rates.items():
        file_path = TAX_DIR / f"{calc_name}.py"
        if not file_path.exists():
            continue
        try:
            src = file_path.read_text(encoding="utf-8", errors="replace")
            # Cari docstring atau komentar yang menyebutkan tarif
            if isinstance(expected, str) and expected not in src:
                violations.append(Violation(
                    file=str(file_path),
                    line=0,
                    message=f"Tarif standar {calc_name} tidak ditemukan dalam komentar/docstring. Diharapkan: {expected}",
                    severity="WARNING"
                ))
            elif isinstance(expected, (int, float)) and str(expected) not in src:
                violations.append(Violation(
                    file=str(file_path),
                    line=0,
                    message=f"Tarif standar {calc_name} tidak ditemukan dalam komentar/docstring. Diharapkan: {expected}",
                    severity="WARNING"
                ))
        except Exception:
            pass
    return violations

# -----------------------------------------------------------------------------
# Main Scan
# -----------------------------------------------------------------------------
def scan_tax_implementations() -> Report:
    report = Report()
    if not TAX_DIR.exists():
        report.violations.append(Violation(
            file=str(TAX_DIR),
            line=0,
            message="Direktori policy_engine/tax_indonesia tidak ditemukan",
            severity="ERROR"
        ))
        return report

    # 1. Cek keberadaan file calculator yang diharapkan
    for expected in EXPECTED_CALCULATORS:
        file_path = TAX_DIR / f"{expected}.py"
        if not file_path.exists():
            report.violations.append(Violation(
                file=str(file_path),
                line=0,
                message=f"File calculator {expected}.py tidak ditemukan",
                severity="ERROR"
            ))
            continue
        info = parse_tax_file(file_path)
        if info is None:
            report.violations.append(Violation(
                file=str(file_path),
                line=0,
                message=f"Gagal parse file {expected}.py (syntax error?)",
                severity="ERROR"
            ))
            continue
        report.calculators.append(info)
        report.violations.extend(validate_calculator(info))

    # 2. Cek konsistensi tarif di komentar
    report.violations.extend(check_rate_consistency())

    # 3. Cek penggunaan Decimal di seluruh file tax (sudah di atas)
    # Skor: setiap ERROR -15, WARNING -5
    error_count = sum(1 for v in report.violations if v.severity == "ERROR")
    warning_count = sum(1 for v in report.violations if v.severity == "WARNING")
    report.score = max(0, 100 - error_count * 15 - warning_count * 5)
    return report

# -----------------------------------------------------------------------------
# Output
# -----------------------------------------------------------------------------
def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}TAX IMPLEMENTATION CHECKER REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"\n  Calculators found: {len(report.calculators)}")
    print(f"  Violations: {len(report.violations)}")
    print(f"  Score: {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    if verbose:
        for calc in report.calculators:
            print(f"\n  {calc.name} ({calc.class_name})")
            print(f"    calculate: {'✅' if calc.has_calculate else '❌'}")
            print(f"    validate: {'✅' if calc.has_validate else '❌'}")
            print(f"    get_rate: {'✅' if calc.has_get_rate else '❌'}")
            print(f"    rate_constant: {'✅' if calc.has_rate_constant else '❌'}")
            print(f"    uses Decimal: {'✅' if calc.uses_decimal else '❌'}")
            if calc.hardcoded_rates:
                print(f"    Hardcoded rates: {', '.join(calc.hardcoded_rates)}")

    if report.violations:
        print(f"\n{c['RED']}❌ Violations:{c['RESET']}")
        for v in report.violations[:30]:
            color = c["RED"] if v.severity == "ERROR" else c["YELLOW"]
            print(f"  {color}[{v.severity}]{c['RESET']} {v.file}:{v.line}")
            print(f"     {v.message}")
        if len(report.violations) > 30:
            print(f"  ... and {len(report.violations)-30} more")

def save_json(report: Report, filepath: str):
    data = {
        "calculators": [
            {
                "file": c.file,
                "name": c.name,
                "class_name": c.class_name,
                "has_calculate": c.has_calculate,
                "has_validate": c.has_validate,
                "has_get_rate": c.has_get_rate,
                "has_rate_constant": c.has_rate_constant,
                "uses_decimal": c.uses_decimal,
                "hardcoded_rates": c.hardcoded_rates,
            }
            for c in report.calculators
        ],
        "violations": [
            {"file": v.file, "line": v.line, "message": v.message, "severity": v.severity}
            for v in report.violations
        ],
        "score": report.score,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{c['CYAN']}JSON saved to {filepath}{c['RESET']}")

def main():
    parser = argparse.ArgumentParser(description="Tax Implementation Checker")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    args = parser.parse_args()

    start = time.monotonic()
    report = scan_tax_implementations()
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)
    elapsed = time.monotonic() - start
    print(f"\n  Time: {elapsed:.2f}s")

    sys.exit(0 if len([v for v in report.violations if v.severity == "ERROR"]) == 0 else 1)

if __name__ == "__main__":
    main()