#!/usr/bin/env python3
"""
tax_checker.py - Tax Implementation Validator (Forensic)
========================================================
Memeriksa kelengkapan implementasi perpajakan dengan akurasi tinggi.
Error hanya untuk masalah fatal (calculate hilang / signature salah).
Decimal dan return type diperlakukan sebagai WARNING (best practice).

Cara pakai:
  python checker/tax_checker.py
  python checker/tax_checker.py --verbose
  python checker/tax_checker.py --json report.json
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set, Tuple

# --- Warna terminal ---
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

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

# ============================================================================
# DAFTAR CALCULATOR YANG DIHARAPKAN (hanya untuk referensi)
# ============================================================================
EXPECTED_CALCULATORS = {
    "ppn_calculator": "PPN 11%",
    "pph_21_calculator": "PPh Pasal 21 (progresif)",
    "pph_22_calculator": "PPh Pasal 22 (0.1%-7.5%)",
    "pph_23_calculator": "PPh Pasal 23 (2%-15%)",
    "pph_25_calculator": "PPh Pasal 25 (angsuran 25%)",
    "pph_26_calculator": "PPh Pasal 26 (20%)",
    "pph_4_ayat_2_calculator": "PPh Pasal 4 ayat 2 (0.5%-10%)",
    "pph_badan_calculator": "PPh Badan (22%)",
    "bea_meterai_calculator": "Bea Meterai (Rp10.000)",
    "withholding_engine": "Engine pemotongan pajak",
    "penalty_interest_engine": "Engine denda & bunga",
    "rate_registry_dynamic": "Registry tarif dinamis",
}

# ============================================================================
# KONFIGURASI CHECKER
# ============================================================================
SKIP_CLASS_PATTERNS = {
    "Registry",
    "Type",
    "State",
    "Table",
    "Config",
    "Constants",
    "Data",
    "Model",
    "Schema",
    "Exception",
    "Error",
    "Base",
    "Mixin",
}

SKIP_FILE_PATTERNS = {
    "__init__",
    "exception",
    "constant",
    "util",
    "model",
    "schema",
    "saga",
    "state",
    "table",
    "router",
    "adapter",
    "repository",
    "service",
}


# ============================================================================
# DATA CLASSES
# ============================================================================
@dataclass
class CalculatorInfo:
    file: str
    name: str
    class_name: str
    has_calculate: bool
    has_validate: bool
    has_get_rate: bool
    uses_decimal: bool
    hardcoded_rates: List[str]
    methods: List[str]
    is_calculator_class: bool
    has_correct_signature: bool
    has_decimal_return: bool


@dataclass
class Violation:
    file: str
    line: int
    message: str
    severity: str  # ERROR, WARNING, INFO


@dataclass
class Report:
    calculators: List[CalculatorInfo] = field(default_factory=list)
    violations: List[Violation] = field(default_factory=list)
    score: int = 100
    total_files_scanned: int = 0
    total_calculators_found: int = 0


# ============================================================================
# UTILITY: Pattern Matching
# ============================================================================
def is_calculator_file(filename: str) -> bool:
    name_lower = filename.lower()
    keywords = ["calculator", "withholding", "rate", "tax_", "ppn", "pph", "bea_meterai", "penalty"]
    has_keyword = any(kw in name_lower for kw in keywords)
    if not has_keyword:
        return False
    for pattern in SKIP_FILE_PATTERNS:
        if pattern in name_lower:
            return False
    return True


def is_calculator_class(cls_node: ast.ClassDef) -> bool:
    class_name = cls_node.name
    if not (class_name.endswith("Calculator") or class_name.endswith("Engine")):
        return False
    for pattern in SKIP_CLASS_PATTERNS:
        if pattern in class_name:
            return False
    for base in cls_node.bases:
        if isinstance(base, ast.Name) and base.id in ("Exception", "BaseException"):
            return False
        if isinstance(base, ast.Attribute) and base.attr in ("Exception", "BaseException"):
            return False
    return True


def find_calculator_class(tree: ast.AST) -> Optional[ast.ClassDef]:
    candidates = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and is_calculator_class(node):
            methods = [item.name for item in node.body if isinstance(item, ast.FunctionDef)]
            has_calculate = any('calculate' in m.lower() for m in methods)
            candidates.append((node, has_calculate))
    for node, has_calc in candidates:
        if has_calc:
            return node
    return candidates[0][0] if candidates else None


# ============================================================================
# PARSING FILE
# ============================================================================
def parse_calculator_file(file_path: pathlib.Path) -> Optional[CalculatorInfo]:
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return None

    cls = find_calculator_class(tree)
    if not cls:
        return None

    class_name = cls.name
    methods = [item.name for item in cls.body if isinstance(item, ast.FunctionDef)]

    has_calculate = any('calculate' in m.lower() for m in methods)
    has_validate = any('validate' in m.lower() for m in methods)
    has_get_rate = any('get_rate' in m.lower() for m in methods)

    # Cek signature
    has_correct_signature = False
    for item in cls.body:
        if isinstance(item, ast.FunctionDef) and 'calculate' in item.name.lower():
            params = [arg.arg for arg in item.args.args if arg.arg not in ('self', 'cls')]
            if len(params) >= 1:
                has_correct_signature = True
            break

    # Cek return Decimal
    has_decimal_return = False
    for node in ast.walk(cls):
        if isinstance(node, ast.FunctionDef) and 'calculate' in node.name.lower():
            for sub in ast.walk(node):
                if isinstance(sub, ast.Return) and sub.value:
                    # Cek langsung Decimal(...)
                    if isinstance(sub.value, ast.Call) and isinstance(sub.value.func, ast.Name) and sub.value.func.id == "Decimal":
                        has_decimal_return = True
                        break
                    # Cek operasi dengan Decimal
                    if isinstance(sub.value, ast.BinOp):
                        for operand in (sub.value.left, sub.value.right):
                            if isinstance(operand, ast.Call) and isinstance(operand.func, ast.Name) and operand.func.id == "Decimal":
                                has_decimal_return = True
                                break
                    # Cek return variable yang mungkin Decimal (tidak bisa dipastikan)
                    if isinstance(sub.value, ast.Name):
                        # Cek apakah variable tersebut dideklarasikan sebagai Decimal di atas
                        for assign in ast.walk(cls):
                            if isinstance(assign, ast.Assign):
                                for target in assign.targets:
                                    if isinstance(target, ast.Name) and target.id == sub.value.id:
                                        if isinstance(assign.value, ast.Call) and isinstance(assign.value.func, ast.Name) and assign.value.func.id == "Decimal":
                                            has_decimal_return = True
                                            break
                            if has_decimal_return:
                                break
                    if has_decimal_return:
                        break
            break

    # Cek penggunaan Decimal di dalam class
    uses_decimal = False
    for node in ast.walk(cls):
        if isinstance(node, ast.Name) and node.id == 'Decimal':
            uses_decimal = True
            break
        if isinstance(node, ast.ImportFrom) and node.module == 'decimal':
            for alias in node.names:
                if alias.name == 'Decimal':
                    uses_decimal = True
                    break
        if isinstance(node, ast.Attribute) and node.attr == 'Decimal':
            uses_decimal = True
            break

    # Hardcoded rates
    hardcoded_rates = []
    for node in ast.walk(cls):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and ('rate' in target.id.lower() or 'tarif' in target.id.lower()):
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, (int, float)):
                        hardcoded_rates.append(f"{target.id}={node.value.value}")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            for operand in (node.left, node.right):
                if isinstance(operand, ast.Constant) and isinstance(operand.value, (int, float)):
                    hardcoded_rates.append(f"Perkalian dengan {operand.value} di baris {node.lineno}")

    return CalculatorInfo(
        file=str(file_path),
        name=file_path.stem,
        class_name=class_name,
        has_calculate=has_calculate,
        has_validate=has_validate,
        has_get_rate=has_get_rate,
        uses_decimal=uses_decimal,
        hardcoded_rates=hardcoded_rates,
        methods=methods,
        is_calculator_class=True,
        has_correct_signature=has_correct_signature,
        has_decimal_return=has_decimal_return,
    )


# ============================================================================
# VALIDASI (dengan severity yang disesuaikan)
# ============================================================================
def validate_calculator(info: CalculatorInfo) -> List[Violation]:
    violations = []

    # ERROR: calculate WAJIB
    if not info.has_calculate:
        violations.append(Violation(
            file=info.file,
            line=0,
            message=f"Calculator {info.name} tidak memiliki method 'calculate' di kelas {info.class_name}",
            severity="ERROR"
        ))
    else:
        # ERROR: signature calculate harus punya parameter
        if not info.has_correct_signature:
            violations.append(Violation(
                file=info.file,
                line=0,
                message=f"Calculator {info.name} method 'calculate' tidak memiliki parameter yang cukup (minimal 1 parameter)",
                severity="ERROR"
            ))
        # WARNING: return Decimal (best practice)
        if not info.has_decimal_return:
            violations.append(Violation(
                file=info.file,
                line=0,
                message=f"Calculator {info.name} method 'calculate' tidak mengembalikan Decimal (sebaiknya Decimal untuk akurasi)",
                severity="WARNING"
            ))

    # WARNING: Decimal untuk uang (best practice)
    if not info.uses_decimal:
        violations.append(Violation(
            file=info.file,
            line=0,
            message=f"Calculator {info.name} tidak menggunakan Decimal untuk uang (sebaiknya Decimal)",
            severity="WARNING"
        ))

    # INFO: validate & get_rate opsional
    if not info.has_validate:
        violations.append(Violation(
            file=info.file,
            line=0,
            message=f"Calculator {info.name} tidak memiliki method 'validate' (opsional)",
            severity="INFO"
        ))
    if not info.has_get_rate:
        violations.append(Violation(
            file=info.file,
            line=0,
            message=f"Calculator {info.name} tidak memiliki method 'get_rate' (opsional)",
            severity="INFO"
        ))

    # WARNING: hardcoded rate
    if info.hardcoded_rates:
        for rate in info.hardcoded_rates[:3]:
            violations.append(Violation(
                file=info.file,
                line=0,
                message=f"Hardcoded rate ditemukan: {rate} (sebaiknya dari konfigurasi)",
                severity="WARNING"
            ))

    return violations


# ============================================================================
# SCAN UTAMA
# ============================================================================
def scan_tax_implementations() -> Report:
    report = Report()

    search_dirs = [
        PROJECT_ROOT / "policy_engine" / "tax_indonesia",
        PROJECT_ROOT / "infrastructure" / "tax",
        PROJECT_ROOT / "adapters" / "tax",
        PROJECT_ROOT / "domain" / "tax",
        PROJECT_ROOT / "application" / "service_layer" / "tax",
    ]

    candidate_files: List[pathlib.Path] = []
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for f in search_dir.glob("*.py"):
            if is_calculator_file(f.name):
                candidate_files.append(f)

    for f in PROJECT_ROOT.glob("*calculator*.py"):
        if f not in candidate_files:
            candidate_files.append(f)
    for f in PROJECT_ROOT.glob("*withholding*.py"):
        if f not in candidate_files:
            candidate_files.append(f)

    report.total_files_scanned = len(candidate_files)

    for file_path in candidate_files:
        info = parse_calculator_file(file_path)
        if info is None:
            continue
        report.calculators.append(info)
        report.total_calculators_found += 1
        report.violations.extend(validate_calculator(info))

    # Hitung skor: ERROR 15, WARNING 2, INFO 0
    error_count = sum(1 for v in report.violations if v.severity == "ERROR")
    warning_count = sum(1 for v in report.violations if v.severity == "WARNING")
    report.score = max(0, 100 - error_count * 15 - warning_count * 2)

    # Cek kelengkapan file (INFO)
    expected_files = set(EXPECTED_CALCULATORS.keys())
    found_files = {info.name for info in report.calculators}
    missing = expected_files - found_files
    for m in missing:
        report.violations.append(Violation(
            file=m,
            line=0,
            message=f"File calculator {m}.py tidak ditemukan (diharapkan: {EXPECTED_CALCULATORS.get(m, '')})",
            severity="INFO"
        ))

    return report


# ============================================================================
# OUTPUT
# ============================================================================
def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}TAX IMPLEMENTATION CHECKER REPORT (Forensic){c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"\n  Total files scanned: {report.total_files_scanned}")
    print(f"  Calculator files found: {report.total_calculators_found}")
    print(f"  Violations: {len(report.violations)}")
    error_count = sum(1 for v in report.violations if v.severity == "ERROR")
    warning_count = sum(1 for v in report.violations if v.severity == "WARNING")
    info_count = sum(1 for v in report.violations if v.severity == "INFO")
    print(f"    - ERROR: {error_count}")
    print(f"    - WARNING: {warning_count}")
    print(f"    - INFO: {info_count}")
    print(f"  Score: {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    if verbose:
        print(f"\n{c['CYAN']}Calculator details:{c['RESET']}")
        for calc in report.calculators:
            print(f"\n  {calc.name} ({calc.class_name})")
            print(f"    calculate: {'✅' if calc.has_calculate else '❌'}")
            print(f"    validate: {'✅' if calc.has_validate else '❌'}")
            print(f"    get_rate: {'✅' if calc.has_get_rate else '❌'}")
            print(f"    Decimal: {'✅' if calc.uses_decimal else '❌'}")
            print(f"    Signature: {'✅' if calc.has_correct_signature else '❌'}")
            print(f"    Decimal return: {'✅' if calc.has_decimal_return else '❌'}")
            if calc.hardcoded_rates:
                print(f"    Hardcoded: {', '.join(calc.hardcoded_rates)}")

    if report.violations:
        print(f"\n{c['RED'] if error_count > 0 else c['YELLOW']}❌ Violations:{c['RESET']}")
        for v in report.violations[:50]:
            if v.severity == "ERROR":
                color = c["RED"]
            elif v.severity == "WARNING":
                color = c["YELLOW"]
            else:
                color = c["CYAN"]
            print(f"  {color}[{v.severity}]{c['RESET']} {v.file}:{v.line}")
            print(f"     {v.message}")
        if len(report.violations) > 50:
            print(f"  ... and {len(report.violations)-50} more")


def save_json(report: Report, filepath: str):
    c = COLOR
    data = {
        "total_files_scanned": report.total_files_scanned,
        "total_calculators_found": report.total_calculators_found,
        "score": report.score,
        "calculators": [
            {
                "file": c.file,
                "name": c.name,
                "class_name": c.class_name,
                "has_calculate": c.has_calculate,
                "has_validate": c.has_validate,
                "has_get_rate": c.has_get_rate,
                "uses_decimal": c.uses_decimal,
                "hardcoded_rates": c.hardcoded_rates,
                "methods": c.methods,
                "has_correct_signature": c.has_correct_signature,
                "has_decimal_return": c.has_decimal_return,
            }
            for c in report.calculators
        ],
        "violations": [
            {"file": v.file, "line": v.line, "message": v.message, "severity": v.severity}
            for v in report.violations
        ],
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{c['CYAN']}✅ JSON saved to {filepath}{c['RESET']}")


def main():
    parser = argparse.ArgumentParser(description="Tax Implementation Checker (Forensic)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan laporan ke JSON")
    args = parser.parse_args()

    start = time.monotonic()
    report = scan_tax_implementations()
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)
    elapsed = time.monotonic() - start
    print(f"\n  ⏱️  Time: {elapsed:.2f}s")

    # Exit code 0 jika tidak ada ERROR
    sys.exit(0 if sum(1 for v in report.violations if v.severity == "ERROR") == 0 else 1)


if __name__ == "__main__":
    main()