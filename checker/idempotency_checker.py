#!/usr/bin/env python3
"""
idempotency_checker.py - Idempotency Implementation Validator
=============================================================
Memeriksa implementasi idempotensi di seluruh proyek:
1. Penggunaan Idempotency-Key (header/parameter)
2. Penyimpanan hasil operasi (cache/DB)
3. Validasi duplikasi (key existence check)
4. Response konsisten untuk operasi duplikat

Cara pakai:
  python idempotency_checker.py
  python idempotency_checker.py --verbose
  python idempotency_checker.py --json report.json
  python idempotency_checker.py --skip-runtime   # skip runtime import
"""

from __future__ import annotations

import argparse
import ast
import importlib
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

@dataclass
class Finding:
    file: str
    line: int
    severity: str       # ERROR / WARNING / INFO
    category: str       # key / storage / validation / response / missing
    message: str
    detail: str = ""

@dataclass
class RuntimeError:
    module: str
    error_type: str
    error_msg: str

@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    runtime_errors: list[RuntimeError] = field(default_factory=list)
    score: int = 100

# =============================================================================
# 1. Idempotency Key Detector
# =============================================================================
def check_idempotency_key(file_path: pathlib.Path) -> list[Finding]:
    """Cari apakah ada deklarasi atau penggunaan idempotency key."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    idempotency_patterns = ['idempotency', 'idempotent', 'idempotency_key', 'Idempotency-Key', 'idempotency_key']

    # Cari di function/class definitions
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name.lower()
            if any(p in func_name for p in idempotency_patterns):
                # Found function with idempotency in name
                findings.append(Finding(
                    file=str(file_path),
                    line=node.lineno,
                    severity="INFO",
                    category="key",
                    message=f"Fungsi '{node.name}' mengandung 'idempotency' dalam nama",
                    detail="Pastikan implementasi idempotensi lengkap."
                ))
            # Cari parameter dengan nama idempotency_key atau header
            for arg in node.args.args:
                arg_name = arg.arg.lower()
                if 'idempotency' in arg_name or ('key' in arg_name and 'idempotent' in func_name):
                    findings.append(Finding(
                        file=str(file_path),
                        line=node.lineno,
                        severity="INFO",
                        category="key",
                        message=f"Parameter '{arg.arg}' mungkin adalah idempotency key",
                        detail="Pastikan key digunakan untuk deduplikasi."
                    ))

        # Cari assignment idempotency_key = ...
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and 'idempotency' in target.id.lower():
                    findings.append(Finding(
                        file=str(file_path),
                        line=node.lineno,
                        severity="INFO",
                        category="key",
                        message=f"Variable '{target.id}' dideklarasikan untuk idempotensi",
                        detail="Periksa penggunaan untuk deduplikasi."
                    ))
    return findings

# =============================================================================
# 2. Storage Checker (Cache/DB for idempotency)
# =============================================================================
def check_idempotency_storage(file_path: pathlib.Path) -> list[Finding]:
    """Cari apakah ada penyimpanan hasil operasi berdasarkan key."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    storage_keywords = ['cache', 'redis', 'store', 'save', 'set', 'put', 'persist']
    idempotency_patterns = ['idempotency', 'idempotent']

    # Cari di function definitions
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name.lower()
            if not any(p in func_name for p in idempotency_patterns):
                continue
            # Cari operasi penyimpanan
            has_storage = False
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    if isinstance(stmt.value.func, ast.Attribute):
                        attr = stmt.value.func.attr.lower()
                        if any(k in attr for k in storage_keywords):
                            has_storage = True
                            break
                    elif isinstance(stmt.value.func, ast.Name):
                        fn = stmt.value.func.id.lower()
                        if any(k in fn for k in storage_keywords):
                            has_storage = True
                            break
            if not has_storage:
                findings.append(Finding(
                    file=str(file_path),
                    line=node.lineno,
                    severity="WARNING",
                    category="storage",
                    message=f"Fungsi '{node.name}' tidak memiliki penyimpanan hasil idempotensi",
                    detail="Simpan hasil operasi di cache/DB untuk idempotensi."
                ))
    return findings

# =============================================================================
# 3. Validation Checker (Check if key exists)
# =============================================================================
def check_idempotency_validation(file_path: pathlib.Path) -> list[Finding]:
    """Cari apakah ada pengecekan key existence sebelum eksekusi."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name.lower()
            if 'idempotent' not in func_name and 'idempotency' not in func_name:
                continue
            # Cari if/assert untuk memeriksa apakah key sudah ada
            has_check = False
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.If):
                    cond = ast.unparse(stmt.test).lower()
                    if 'exists' in cond or 'has' in cond or 'already' in cond:
                        has_check = True
                        break
                elif isinstance(stmt, ast.Assert):
                    cond = ast.unparse(stmt.test).lower()
                    if 'exists' in cond or 'has' in cond:
                        has_check = True
                        break
                elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    if isinstance(stmt.value.func, ast.Name):
                        if 'exists' in stmt.value.func.id.lower():
                            has_check = True
                            break
                    elif isinstance(stmt.value.func, ast.Attribute):
                        if 'exists' in stmt.value.func.attr.lower():
                            has_check = True
                            break
            if not has_check:
                findings.append(Finding(
                    file=str(file_path),
                    line=node.lineno,
                    severity="ERROR",
                    category="validation",
                    message=f"Fungsi '{node.name}' tidak memeriksa apakah key sudah ada",
                    detail="Tambahkan pengecekan key existence sebelum eksekusi operasi."
                ))
    return findings

# =============================================================================
# 4. Response Consistency Checker
# =============================================================================
def check_response_consistency(file_path: pathlib.Path) -> list[Finding]:
    """Cari apakah response sama untuk operasi duplikat."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name.lower()
            if 'idempotent' not in func_name and 'idempotency' not in func_name:
                continue
            # Cari return value untuk key yang sudah ada vs eksekusi baru
            # Sederhana: cari return statement dengan variable atau literal
            returns = []
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Return):
                    returns.append(stmt)
            if len(returns) >= 2:
                # Ada multiple return, kemungkinan ada conditional
                findings.append(Finding(
                    file=str(file_path),
                    line=node.lineno,
                    severity="INFO",
                    category="response",
                    message=f"Fungsi '{node.name}' memiliki multiple returns, mungkin untuk idempotensi",
                    detail="Pastikan response untuk key existing dan new operation konsisten."
                ))
    return findings

# =============================================================================
# 5. Missing Idempotency Implementation
# =============================================================================
def check_missing_idempotency(file_path: pathlib.Path) -> list[Finding]:
    """Cari operasi write yang tidak memiliki idempotensi."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    write_keywords = ['post', 'create', 'update', 'delete', 'save', 'persist', 'submit']
    idempotency_patterns = ['idempotent', 'idempotency']

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name.lower()
            # Skip if function is already idempotent
            if any(p in func_name for p in idempotency_patterns):
                continue
            # Check if function is a write operation
            if not any(k in func_name for k in write_keywords):
                continue
            # Check if function has idempotency parameter or uses key
            has_idempotency_key = False
            for arg in node.args.args:
                if 'idempotency' in arg.arg.lower():
                    has_idempotency_key = True
                    break
            if not has_idempotency_key:
                findings.append(Finding(
                    file=str(file_path),
                    line=node.lineno,
                    severity="WARNING",
                    category="missing",
                    message=f"Fungsi '{node.name}' adalah operasi write tanpa idempotensi",
                    detail="Tambahkan idempotency key untuk mencegah duplikasi."
                ))
    return findings

# =============================================================================
# Runtime Import Check (Opsional)
# =============================================================================
def try_import_module(module_name: str) -> RuntimeError | None:
    try:
        importlib.import_module(module_name)
        return None
    except Exception as e:
        return RuntimeError(
            module=module_name,
            error_type=type(e).__name__,
            error_msg=str(e)[:100]
        )

def check_runtime_imports(target_dirs: list[pathlib.Path]) -> list[RuntimeError]:
    errors = []
    for dir_path in target_dirs:
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if py_file.name.startswith("__") or py_file.name.startswith("idempotency_checker"):
                continue
            rel = py_file.relative_to(PROJECT_ROOT)
            module = str(rel.with_suffix("")).replace("/", ".")
            err = try_import_module(module)
            if err:
                errors.append(err)
    return errors

# =============================================================================
# Main Scanner
# =============================================================================
def scan_project(skip_runtime: bool = False) -> Report:
    report = Report()
    target_dirs = [
        PROJECT_ROOT / "adapters" / "primary_api",
        PROJECT_ROOT / "application" / "use_cases",
        PROJECT_ROOT / "application" / "commands_cqrs",
        PROJECT_ROOT / "infrastructure" / "caching",
        PROJECT_ROOT / "domain" / "shared_value_objects",
    ]

    exclude = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', 'dist', 'build', 'migrations', 'deployment', 'docs', 'tests'}

    for dir_path in target_dirs:
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if any(part in exclude for part in py_file.parts):
                continue
            if py_file.name.startswith("__") or py_file.name.startswith("idempotency_checker"):
                continue

            report.findings.extend(check_idempotency_key(py_file))
            report.findings.extend(check_idempotency_storage(py_file))
            report.findings.extend(check_idempotency_validation(py_file))
            report.findings.extend(check_response_consistency(py_file))
            report.findings.extend(check_missing_idempotency(py_file))

    # Runtime import check
    if not skip_runtime:
        report.runtime_errors = check_runtime_imports(target_dirs)

    # Score: ERROR -15, WARNING -5, INFO tidak mengurangi
    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")
    runtime_err_count = len(report.runtime_errors)
    report.score = max(0, 100 - errors * 15 - warnings * 5 - runtime_err_count * 5)
    return report

# =============================================================================
# Output
# =============================================================================
def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}IDEMPOTENCY CHECKER REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"\n  Total findings: {len(report.findings)}")
    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")
    infos = sum(1 for f in report.findings if f.severity == "INFO")
    print(f"  Errors: {c['RED']}{errors}{c['RESET']}, Warnings: {c['YELLOW']}{warnings}{c['RESET']}, Info: {c['CYAN']}{infos}{c['RESET']}")
    if report.runtime_errors:
        print(f"  Runtime errors: {c['RED']}{len(report.runtime_errors)}{c['RESET']}")
    print(f"  Score: {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    if report.findings:
        # Group by category
        categories = {}
        for f in report.findings:
            categories.setdefault(f.category, []).append(f)

        print(f"\n{c['CYAN']}By Category:{c['RESET']}")
        cat_labels = {
            'key': 'Idempotency Key',
            'storage': 'Storage/Cache',
            'validation': 'Validation (Key Exists)',
            'response': 'Response Consistency',
            'missing': 'Missing Idempotency',
        }
        for cat, items in categories.items():
            label = cat_labels.get(cat, cat)
            err_cnt = sum(1 for i in items if i.severity == "ERROR")
            warn_cnt = sum(1 for i in items if i.severity == "WARNING")
            color = c["RED"] if err_cnt > 0 else c["YELLOW"] if warn_cnt > 0 else c["GREEN"]
            print(f"  {label}: {color}{err_cnt} errors, {warn_cnt} warnings{c['RESET']}")

        print(f"\n{c['RED'] if errors else c['YELLOW']}Details:{c['RESET']}")
        for f in report.findings[:30]:
            color = c["RED"] if f.severity == "ERROR" else c["YELLOW"] if f.severity == "WARNING" else c["CYAN"]
            print(f"  {color}[{f.severity}]{c['RESET']} [{f.category}] {f.file}:{f.line}")
            print(f"     {f.message}")
            if verbose and f.detail:
                print(f"     {c['CYAN']}→ {f.detail}{c['RESET']}")
        if len(report.findings) > 30:
            print(f"  ... and {len(report.findings)-30} more findings")

    if report.runtime_errors:
        print(f"\n{c['RED']}Runtime Errors:{c['RESET']}")
        for err in report.runtime_errors[:10]:
            print(f"  {err.module}: {err.error_type} - {err.error_msg}")
        if len(report.runtime_errors) > 10:
            print(f"  ... and {len(report.runtime_errors)-10} more")

def save_json(report: Report, filepath: str):
    data = {
        "findings": [
            {"file": f.file, "line": f.line, "severity": f.severity,
             "category": f.category, "message": f.message, "detail": f.detail}
            for f in report.findings
        ],
        "runtime_errors": [
            {"module": e.module, "type": e.error_type, "message": e.error_msg}
            for e in report.runtime_errors
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
    parser = argparse.ArgumentParser(description="Idempotency Implementation Checker")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    parser.add_argument("--skip-runtime", action="store_true", help="Lewati runtime import check")
    args = parser.parse_args()

    report = scan_project(skip_runtime=args.skip_runtime)
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)

    errors = sum(1 for f in report.findings if f.severity == "ERROR") + len(report.runtime_errors)
    sys.exit(0 if errors == 0 else 1)

if __name__ == "__main__":
    main()
