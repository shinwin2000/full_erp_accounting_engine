#!/usr/bin/env python3
"""
general_ledger_checker.py - General Ledger Integrity Validator (v5.6.0)
=======================================================================
Perbaikan v5.6.0:
- Tampilkan daftar fungsi GL yang ditemukan (dengan file) di summary
- Opsi --show-functions untuk selalu menampilkan daftar fungsi GL
- Perbaikan logika ignore-functions: sekarang lebih jelas di output
- Tambahan deteksi validasi melalui dekorator @validates dan panggilan ke _validate
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
from collections import defaultdict
from typing import List, Set, Dict, Optional, Tuple

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE_PATH = PROJECT_ROOT / "checker" / "core"
if CORE_PATH.exists():
    sys.path.insert(0, str(CORE_PATH))

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

# RCA
RCA_AVAILABLE = False
try:
    from rca import analyze_exception
    RCA_AVAILABLE = True
except ImportError:
    pass

# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class Finding:
    file: str
    line: int
    severity: str       # ERROR / WARNING / INFO
    category: str
    message: str
    detail: str = ""
    rca_summary: str = ""

@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    gl_functions_found: int = 0
    gl_functions_checked: int = 0
    gl_functions_list: List[Tuple[str, str]] = field(default_factory=list)  # (file, function_name)
    files_scanned: int = 0
    score: int = 100
    scan_time: float = 0.0

# ============================================================================
# DETEKSI FUNGSI GL YANG PRESISI (v5.6)
# ============================================================================

GL_REPOSITORY_NAMES = {'journalrepository', 'ledgerrepository', 'glrepository', 'journal_repository', 'ledger_repository'}
GL_ENTITY_NAMES = {'journal', 'journalentry', 'ledgerentry', 'glentry', 'generalledger', 'journal_entity', 'ledger_entity'}
GL_SERVICE_NAMES = {'journalservice', 'ledgerservice', 'glservice'}

def is_gl_function(func_node: ast.FunctionDef, file_path: pathlib.Path) -> bool:
    """
    Menentukan apakah fungsi adalah fungsi GL yang benar-benar melakukan posting ke GL.
    """
    name = func_node.name.lower()
    # Skip internal/metode khusus
    if name in ('__init__', '__post_init__', '__repr__', '__str__', '__call__',
                '__new__', '__del__', '__eq__', '__hash__', '__lt__', '__gt__'):
        return False

    # Skip jika fungsi hanya query/read
    if re.search(r'\b(get|find|query|fetch|list|search|read|load|retrieve|exists|count)\b', name):
        if not re.search(r'\b(post|save|create|update|persist|record)\b', name):
            return False

    # Skip jika fungsi hanya validasi/check (tidak melakukan persistensi)
    if re.search(r'\b(validate|check|enforce|ensure|verify|assert|is_|has_)\b', name):
        if not re.search(r'\b(post|save|record|update|create|persist)\b', name):
            return False

    # Cek apakah nama mengindikasikan GL
    gl_keywords = {'post', 'journal', 'ledger', 'gl', 'entry'}
    if not any(k in name for k in gl_keywords):
        return False

    # Cek apakah ada panggilan ke GL repository atau posting ke GL
    has_gl_persist = False
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                attr = node.func.attr.lower()
                if attr in ('save', 'add', 'persist', 'store', 'update', 'post'):
                    if isinstance(node.func.value, ast.Name):
                        var_name = node.func.value.id.lower()
                        if any(gl_repo in var_name for gl_repo in GL_REPOSITORY_NAMES):
                            has_gl_persist = True
                            break
                        if 'journal' in var_name or 'ledger' in var_name:
                            has_gl_persist = True
                            break
                    if 'post' in attr or 'journal' in attr or 'ledger' in attr:
                        has_gl_persist = True
                        break
            elif isinstance(node.func, ast.Name):
                fn_name = node.func.id.lower()
                if any(k in fn_name for k in ('post_to_gl', 'save_journal', 'save_ledger', 'post_journal')):
                    has_gl_persist = True
                    break
            elif isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name):
                    var_name = node.func.value.id.lower()
                    if any(gl_svc in var_name for gl_svc in GL_SERVICE_NAMES):
                        attr = node.func.attr.lower()
                        if any(k in attr for k in ('post', 'save', 'create', 'update')):
                            has_gl_persist = True
                            break
        elif isinstance(node, ast.With):
            for item in node.items:
                if isinstance(item.context_expr, ast.Call):
                    if isinstance(item.context_expr.func, ast.Name):
                        if 'unit_of_work' in item.context_expr.func.id.lower():
                            for child in ast.walk(node):
                                if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                                    if child.func.attr in ('save', 'add', 'persist') and isinstance(child.func.value, ast.Name):
                                        var_name = child.func.value.id.lower()
                                        if any(gl_ent in var_name for gl_ent in GL_ENTITY_NAMES):
                                            has_gl_persist = True
                                            break
                            if has_gl_persist:
                                break

    if not has_gl_persist:
        return False

    file_str = str(file_path)
    if 'subledger' in file_str and not re.search(r'post_to_gl|gl_posting|to_gl|journal.*post', name):
        return False

    return True

# ============================================================================
# FUNGSI PEMBANTU DETEKSI VALIDASI (DIREVISI v5.6)
# ============================================================================

def has_balance_validation(node: ast.AST) -> bool:
    """
    Deteksi berbagai pola validasi balance.
    """
    for child in ast.walk(node):
        if isinstance(child, ast.Raise):
            if child.exc:
                exc_str = ast.unparse(child.exc).lower()
                if 'debit' in exc_str and 'credit' in exc_str:
                    return True
        if isinstance(child, ast.If):
            if isinstance(child.test, ast.Compare):
                test_str = ast.unparse(child.test).lower()
                if ('debit' in test_str and 'credit' in test_str) or ('credit' in test_str and 'debit' in test_str):
                    for stmt in ast.walk(child):
                        if isinstance(stmt, ast.Raise):
                            return True
                    if has_validation_call(child, ['validate', 'is_balanced', 'ensure_balanced', 'check_balance']):
                        return True
        if isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name) and 'balance' in target.id.lower():
                    if isinstance(child.value, ast.Compare):
                        val_str = ast.unparse(child.value).lower()
                        if ('debit' in val_str and 'credit' in val_str) or ('credit' in val_str and 'debit' in val_str):
                            return True
        if isinstance(child, ast.Assert):
            test_str = ast.unparse(child.test).lower()
            if 'balance' in test_str and ('debit' in test_str or 'credit' in test_str):
                return True
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                fn = child.func.id.lower()
                if 'balance' in fn and ('validate' in fn or 'check' in fn or 'ensure' in fn):
                    return True
            elif isinstance(child.func, ast.Attribute):
                attr = child.func.attr.lower()
                if 'balance' in attr and ('validate' in attr or 'check' in attr or 'ensure' in attr):
                    return True
                if isinstance(child.func.value, ast.Call) and isinstance(child.func.value.func, ast.Name) and child.func.value.func.id == 'super':
                    if attr == 'validate' or 'balance' in attr:
                        return True
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        for deco in node.decorator_list:
            deco_str = ast.unparse(deco).lower()
            if ('validate' in deco_str and 'balance' in deco_str) or ('validates' in deco_str and 'balance' in deco_str):
                return True
    return False

def has_validation_call(node: ast.AST, keywords: List[str]) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                fn = child.func.id.lower()
                if any(k in fn for k in keywords):
                    return True
            elif isinstance(child.func, ast.Attribute):
                attr = child.func.attr.lower()
                if any(k in attr for k in keywords):
                    return True
                if isinstance(child.func.value, ast.Name):
                    obj = child.func.value.id.lower()
                    if any(k in obj for k in keywords):
                        return True
                if isinstance(child.func.value, ast.Call) and isinstance(child.func.value.func, ast.Name) and child.func.value.func.id == 'super':
                    if any(k in attr for k in keywords):
                        return True
    return False

def has_account_validation(node: ast.AST) -> bool:
    if has_validation_call(node, ['validate_account', 'check_account', 'account_exists', 'verify_account']):
        return True
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.Assert)):
            cond = ast.unparse(child.test).lower()
            if 'account' in cond and ('valid' in cond or 'exists' in cond or 'found' in cond or 'not' in cond):
                return True
    if has_validation_call(node, ['_validate_account', '_check_account']):
        return True
    return False

def has_period_validation(node: ast.AST) -> bool:
    if has_validation_call(node, ['validate_period', 'check_period', 'period_open', 'period_closed', 'is_period_open']):
        return True
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.Assert)):
            cond = ast.unparse(child.test).lower()
            if 'period' in cond and ('open' in cond or 'closed' in cond or 'locked' in cond):
                return True
    if has_validation_call(node, ['_validate_period', '_check_period']):
        return True
    return False

# ============================================================================
# PEMERIKSAAN ATURAN GL (DIREVISI v5.6)
# ============================================================================

def check_balance_validation(file_path: pathlib.Path, tree: ast.AST, gl_functions: List[ast.FunctionDef], ignore_functions: Set[str]) -> List[Finding]:
    findings = []
    for node in gl_functions:
        if node.name in ignore_functions:
            continue
        if has_balance_validation(node):
            continue
        if has_validation_call(node, ['validate', 'is_balanced', 'ensure_balanced', 'check_balance']):
            continue
        findings.append(Finding(
            file=str(file_path),
            line=node.lineno,
            severity="ERROR",
            category="Double-entry Balance",
            message=f"Fungsi GL '{node.name}' tidak memiliki validasi double-entry (debit == credit)",
            detail="Tambahkan pemeriksaan total debit == total credit sebelum menyimpan GL, atau panggil method validate()/is_balanced()."
        ))
    return findings

def check_account_validation(file_path: pathlib.Path, tree: ast.AST, gl_functions: List[ast.FunctionDef], ignore_functions: Set[str]) -> List[Finding]:
    findings = []
    for node in gl_functions:
        if node.name in ignore_functions:
            continue
        if has_account_validation(node):
            continue
        findings.append(Finding(
            file=str(file_path),
            line=node.lineno,
            severity="ERROR",
            category="Account Validation",
            message=f"Fungsi GL '{node.name}' tidak memvalidasi account terhadap COA",
            detail="Pastikan account yang diposting terdaftar di Chart of Accounts (panggil validate_account() atau cek keberadaan)."
        ))
    return findings

def check_period_validation(file_path: pathlib.Path, tree: ast.AST, gl_functions: List[ast.FunctionDef], ignore_functions: Set[str]) -> List[Finding]:
    findings = []
    for node in gl_functions:
        if node.name in ignore_functions:
            continue
        if has_period_validation(node):
            continue
        findings.append(Finding(
            file=str(file_path),
            line=node.lineno,
            severity="ERROR",
            category="Period Validation",
            message=f"Fungsi GL '{node.name}' tidak memeriksa status period (open/closed)",
            detail="Tambahkan pemeriksaan period status sebelum posting GL (panggil validate_period() atau cek status)."
        ))
    return findings

def check_audit_trail(file_path: pathlib.Path, tree: ast.AST, gl_functions: List[ast.FunctionDef], ignore_functions: Set[str]) -> List[Finding]:
    findings = []
    for node in gl_functions:
        if node.name in ignore_functions:
            continue
        if has_validation_call(node, ['event', 'audit', 'log', 'record', 'publish']):
            continue
        findings.append(Finding(
            file=str(file_path),
            line=node.lineno,
            severity="WARNING",
            category="Audit Trail",
            message=f"Fungsi GL '{node.name}' tidak mencatat audit trail untuk posting GL",
            detail="Tambahkan logging/event publishing untuk setiap transaksi GL (panggil publish_event() atau log())."
        ))
    return findings

def check_transaction_atomicity(file_path: pathlib.Path, tree: ast.AST, gl_functions: List[ast.FunctionDef], ignore_functions: Set[str]) -> List[Finding]:
    findings = []
    for node in gl_functions:
        if node.name in ignore_functions:
            continue
        has_tx = False
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.With):
                for item in stmt.items:
                    if isinstance(item.context_expr, ast.Call):
                        if isinstance(item.context_expr.func, ast.Name):
                            if 'transaction' in item.context_expr.func.id.lower() or 'unit_of_work' in item.context_expr.func.id.lower():
                                has_tx = True
                                break
                        elif isinstance(item.context_expr.func, ast.Attribute):
                            if 'transaction' in item.context_expr.func.attr.lower() or 'unit_of_work' in item.context_expr.func.attr.lower():
                                has_tx = True
                                break
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                if isinstance(stmt.value.func, ast.Name):
                    if 'begin_transaction' in stmt.value.func.id.lower():
                        has_tx = True
                        break
                elif isinstance(stmt.value.func, ast.Attribute):
                    if 'begin_transaction' in stmt.value.func.attr.lower():
                        has_tx = True
                        break
        if not has_tx:
            findings.append(Finding(
                file=str(file_path),
                line=node.lineno,
                severity="WARNING",
                category="Posting Integrity (Atomicity)",
                message=f"Fungsi GL '{node.name}' tidak menggunakan transaksi/Unit of Work",
                detail="Gunakan transaksi database untuk memastikan atomicity posting GL (gunakan 'with transaction:' atau UnitOfWork)."
            ))
    return findings

def check_reconciliation(file_path: pathlib.Path, tree: ast.AST) -> List[Finding]:
    findings = []
    reconcile_keywords = {'reconcile', 'reconciliation', 'match', 'compare'}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name.lower()
            if not any(k in name for k in reconcile_keywords):
                continue
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
                    category="Reconciliation",
                    message=f"Fungsi '{node.name}' tidak melakukan rekonsiliasi GL vs sub-ledger",
                    detail="Implementasikan proses rekonsiliasi untuk memastikan konsistensi GL."
                ))
    return findings

# ============================================================================
# PEMERIKSAAN UMUM (tetap)
# ============================================================================

def check_broad_except(file_path: pathlib.Path, tree: ast.AST) -> List[Finding]:
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                if handler.type is not None:
                    if isinstance(handler.type, ast.Name) and handler.type.id == "Exception":
                        findings.append(Finding(
                            file=str(file_path),
                            line=handler.lineno,
                            severity="INFO",
                            category="Exception Handling",
                            message="Menangkap 'Exception' terlalu luas",
                            detail="Pertimbangkan untuk menangkap exception yang lebih spesifik."
                        ))
    return findings

def check_open_without_context(file_path: pathlib.Path, tree: ast.AST) -> List[Finding]:
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "open":
                parent = getattr(node, 'parent', None)
                if not parent or not isinstance(parent, ast.With):
                    findings.append(Finding(
                        file=str(file_path),
                        line=node.lineno,
                        severity="WARNING",
                        category="Resource Management",
                        message="'open' digunakan tanpa context manager ('with')",
                        detail="Gunakan 'with open(...) as f:' untuk menjamin file ditutup."
                    ))
    return findings

def check_datetime_naive(file_path: pathlib.Path, tree: ast.AST) -> List[Finding]:
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "now" and isinstance(node.func.value, ast.Name) and node.func.value.id == "datetime":
                    has_tz = False
                    for kw in node.keywords:
                        if kw.arg == "tz":
                            has_tz = True
                            break
                    for arg in node.args:
                        if isinstance(arg, ast.Name) and arg.id in ("UTC", "timezone"):
                            has_tz = True
                            break
                        if isinstance(arg, ast.Attribute) and arg.attr in ("utc", "UTC"):
                            has_tz = True
                            break
                    if not has_tz:
                        findings.append(Finding(
                            file=str(file_path),
                            line=node.lineno,
                            severity="WARNING",
                            category="Timezone",
                            message="'datetime.now()' tanpa timezone",
                            detail="Gunakan 'datetime.now(UTC)' atau 'datetime.now(timezone.utc)'."
                        ))
    return findings

# ============================================================================
# RCA UNTUK ERROR PARSE/IMPORT
# ============================================================================

def check_with_rca(file_path: pathlib.Path) -> List[Finding]:
    findings = []
    if not RCA_AVAILABLE:
        return findings
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        ast.parse(src, filename=str(file_path))
    except (SyntaxError, ImportError, NameError, TypeError, ValueError) as exc:
        result = analyze_exception(exc, context={"file": str(file_path)})
        sev_map = {"FATAL": "ERROR", "CRITICAL": "ERROR", "HIGH": "WARNING",
                   "MEDIUM": "WARNING", "LOW": "INFO", "INFO": "INFO", "HINT": "INFO"}
        sev = sev_map.get(result.severity.value, "WARNING")
        findings.append(Finding(
            file=str(file_path),
            line=getattr(exc, 'lineno', 0),
            severity=sev,
            category="RCA",
            message=f"RCA: {result.root_cause[:120]}",
            detail=f"Confidence: {result.confidence:.2f}\nRekomendasi: {result.suggested_fix[:200]}",
            rca_summary=result.summary()
        ))
    return findings

# ============================================================================
# SCANNER UTAMA (v5.6)
# ============================================================================

def scan_code(use_rca: bool = False, full: bool = False, ignore_files: Set[str] = None, ignore_functions: Set[str] = None) -> Report:
    start_time = time.perf_counter()
    report = Report()
    gl_count = 0
    gl_checked = 0
    files_scanned = 0
    ignore_files = ignore_files or set()
    ignore_functions = ignore_functions or set()

    target_dirs = [
        PROJECT_ROOT / "domain",
        PROJECT_ROOT / "application" / "use_cases",
        PROJECT_ROOT / "application" / "service_layer",
        PROJECT_ROOT / "projections" / "ledger",
        PROJECT_ROOT / "infrastructure" / "persistence" / "repositories",
    ]

    exclude = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', 'dist', 'build', 'migrations', 'deployment', 'docs', 'tests', 'scripts', 'checker'}

    for dir_path in target_dirs:
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if any(part in exclude for part in py_file.parts):
                continue
            if py_file.name.startswith("__") or py_file.name in ignore_files:
                continue
            if py_file.name.startswith("general_ledger_checker"):
                continue

            files_scanned += 1
            try:
                src = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=str(py_file))
            except SyntaxError as exc:
                report.findings.append(Finding(
                    file=str(py_file),
                    line=exc.lineno or 0,
                    severity="ERROR",
                    category="Syntax",
                    message=f"SyntaxError: {exc.msg}",
                    detail=str(exc)
                ))
                if use_rca and RCA_AVAILABLE:
                    report.findings.extend(check_with_rca(py_file))
                continue

            # Kumpulkan semua fungsi GL
            gl_functions = []
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if is_gl_function(node, py_file):
                        gl_functions.append(node)
                        gl_count += 1
                        report.gl_functions_list.append((str(py_file), node.name))

            # Jalankan pemeriksaan GL hanya jika ada fungsi GL
            if gl_functions:
                # Filter fungsi yang di-ignore
                active_gl = [f for f in gl_functions if f.name not in ignore_functions]
                gl_checked += len(active_gl)
                if active_gl:
                    report.findings.extend(check_balance_validation(py_file, tree, active_gl, ignore_functions))
                    report.findings.extend(check_account_validation(py_file, tree, active_gl, ignore_functions))
                    report.findings.extend(check_period_validation(py_file, tree, active_gl, ignore_functions))
                    report.findings.extend(check_audit_trail(py_file, tree, active_gl, ignore_functions))
                    report.findings.extend(check_transaction_atomicity(py_file, tree, active_gl, ignore_functions))

            # Pemeriksaan umum (selalu)
            report.findings.extend(check_reconciliation(py_file, tree))
            report.findings.extend(check_broad_except(py_file, tree))
            report.findings.extend(check_open_without_context(py_file, tree))
            report.findings.extend(check_datetime_naive(py_file, tree))

            if use_rca and RCA_AVAILABLE:
                report.findings.extend(check_with_rca(py_file))

    report.gl_functions_found = gl_count
    report.gl_functions_checked = gl_checked
    report.files_scanned = files_scanned

    # Skor dihitung hanya berdasarkan GL functions yang di-check (tidak di-ignore)
    gl_errors = sum(1 for f in report.findings if f.severity == "ERROR" and f.category in ["Double-entry Balance", "Account Validation", "Period Validation"])
    gl_warnings = sum(1 for f in report.findings if f.severity == "WARNING" and f.category in ["Audit Trail", "Posting Integrity (Atomicity)"])
    if gl_checked > 0:
        penalty = (gl_errors * 15 + gl_warnings * 5) / max(gl_checked, 1) * 5
        report.score = max(0, int(100 - penalty))
    else:
        report.score = 100

    report.scan_time = time.perf_counter() - start_time
    return report

# ============================================================================
# OUTPUT
# ============================================================================

def print_report(report: Report, verbose: bool = False, show_rca: bool = False, limit: int = 20, show_functions: bool = False):
    c = COLOR
    print()
    print(f"{c['CYAN']}{'='*80}{c['RESET']}")
    print(f"{c['CYAN']}  GENERAL LEDGER INTEGRITY CHECKER  v5.6.0{c['RESET']}")
    print(f"{c['CYAN']}{'='*80}{c['RESET']}")

    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")
    infos = sum(1 for f in report.findings if f.severity == "INFO")
    total = len(report.findings)

    print(f"\n  {c['CYAN']}📊 Summary:{c['RESET']}")
    print(f"    Files scanned   : {report.files_scanned}")
    print(f"    GL functions    : {report.gl_functions_found} (checked: {report.gl_functions_checked})")
    print(f"    Issues          : {total}")
    print(f"    Errors (CRITICAL): {c['RED']}{errors}{c['RESET']}")
    print(f"    Warnings (MEDIUM): {c['YELLOW']}{warnings}{c['RESET']}")
    print(f"    Infos (LOW)      : {c['CYAN']}{infos}{c['RESET']}")
    print(f"    Score            : {c['GREEN'] if report.score >= 70 else c['YELLOW']}{report.score}/100{c['RESET']}")
    print(f"    RCA Engine       : {'✅ Active' if RCA_AVAILABLE else '❌ Not available'}")
    print(f"    Scan time        : {report.scan_time:.3f}s")

    # Tampilkan daftar fungsi GL jika diminta atau jika ada error
    if show_functions or (errors > 0 and report.gl_functions_list):
        print(f"\n  {c['CYAN']}📋 GL Functions Found:{c['RESET']}")
        for idx, (file, func) in enumerate(sorted(report.gl_functions_list), 1):
            # Highlight yang memiliki error
            has_err = any(f.file == file and f.severity == "ERROR" and f.category in ["Double-entry Balance", "Account Validation", "Period Validation"] for f in report.findings)
            color = c['RED'] if has_err else c['GREEN']
            print(f"    {idx:>2}. {color}{func}{c['RESET']}  ({file})")

    if report.findings:
        cat_counts = defaultdict(int)
        for f in report.findings:
            cat_counts[f.category] += 1

        print(f"\n  {c['CYAN']}📂 By Category:{c['RESET']}")
        for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
            err = sum(1 for f in report.findings if f.category == cat and f.severity == "ERROR")
            warn = sum(1 for f in report.findings if f.category == cat and f.severity == "WARNING")
            info = sum(1 for f in report.findings if f.category == cat and f.severity == "INFO")
            label = f"{cat}"
            if err:
                label = f"{c['RED']}{cat}{c['RESET']}"
            elif warn:
                label = f"{c['YELLOW']}{cat}{c['RESET']}"
            else:
                label = f"{c['CYAN']}{cat}{c['RESET']}"
            print(f"    {label}: {count} ({err}E, {warn}W, {info}I)")

        error_files = {f.file for f in report.findings if f.severity == "ERROR" and f.category in ["Double-entry Balance", "Account Validation", "Period Validation"]}
        if error_files:
            print(f"\n  {c['RED']}❌ Files with CRITICAL GL errors:{c['RESET']}")
            for f in sorted(error_files)[:10]:
                print(f"    - {f}")
            if len(error_files) > 10:
                print(f"    ... and {len(error_files)-10} more")

        print(f"\n  {c['YELLOW']}🔍 Issues (first {limit}):{c['RESET']}")
        for f in report.findings[:limit]:
            color = c["RED"] if f.severity == "ERROR" else c["YELLOW"] if f.severity == "WARNING" else c["CYAN"]
            line_info = f":{f.line}" if f.line else ""
            print(f"    {color}[{f.severity}]{c['RESET']} {f.file}{line_info}")
            print(f"      {f.message}")
            if verbose and f.detail:
                print(f"      {c['CYAN']}→ {f.detail}{c['RESET']}")
            if show_rca and f.rca_summary:
                print(f"      {c['GREEN']}RCA: {f.rca_summary}{c['RESET']}")
        if len(report.findings) > limit:
            print(f"    ... and {len(report.findings)-limit} more findings (use --json for full list)")

        print(f"\n  {c['CYAN']}💡 Recommendations:{c['RESET']}")
        if errors > 0:
            print(f"    {c['RED']}1. Fix {errors} CRITICAL errors in GL functions (balance, account, period validation).{c['RESET']}")
        if warnings > 0:
            print(f"    {c['YELLOW']}2. Address {warnings} warnings (audit trail, atomicity, resource management).{c['RESET']}")
        if infos > 0:
            print(f"    {c['CYAN']}3. Consider improving {infos} informational issues (exception handling, etc.).{c['RESET']}")
        if report.score < 70:
            print(f"    {c['RED']}4. Use --ignore-files or --ignore-functions to skip false positives.{c['RESET']}")
            print(f"    {c['YELLOW']}5. Alternatively, fix the code by adding missing validations.{c['RESET']}")
        else:
            print(f"    {c['GREEN']}✅ All critical GL checks passed. Good job!{c['RESET']}")

    print()
    if errors == 0:
        print(f"  {c['GREEN']}✅ PASS — All GL integrity checks passed.{c['RESET']}")
    else:
        print(f"  {c['RED']}❌ FAIL — Critical issues found in GL functions.{c['RESET']}")

    print()

def save_json(report: Report, filepath: str):
    data = {
        "score": report.score,
        "files_scanned": report.files_scanned,
        "gl_functions_found": report.gl_functions_found,
        "gl_functions_checked": report.gl_functions_checked,
        "gl_functions_list": [{"file": f, "function": func} for f, func in report.gl_functions_list],
        "total_findings": len(report.findings),
        "scan_time": report.scan_time,
        "findings": [
            {"file": f.file, "line": f.line, "severity": f.severity,
             "category": f.category, "message": f.message, "detail": f.detail,
             "rca_summary": f.rca_summary}
            for f in report.findings
        ]
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{c['CYAN']}JSON saved to {filepath}{c['RESET']}")

# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="General Ledger Integrity Checker v5.6.0")
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan detail")
    parser.add_argument("--rca", action="store_true", help="Aktifkan analisis RCA untuk error")
    parser.add_argument("--full", action="store_true", help="Sertakan pemeriksaan dokumentasi & kompleksitas (belum diimplementasikan)")
    parser.add_argument("--limit", type=int, default=20, help="Jumlah temuan yang ditampilkan")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    parser.add_argument("--ignore-files", metavar="FILES", help="Koma-terpisah nama file yang diabaikan (misal service_journal.py,aggregate_root.py)")
    parser.add_argument("--ignore-functions", metavar="FUNCTIONS", help="Koma-terpisah nama fungsi yang diabaikan (misal post_journal,save_ledger)")
    parser.add_argument("--show-functions", action="store_true", help="Tampilkan daftar fungsi GL yang ditemukan")
    args = parser.parse_args()

    ignore_files = set()
    if args.ignore_files:
        ignore_files = set(f.strip() for f in args.ignore_files.split(','))

    ignore_functions = set()
    if args.ignore_functions:
        ignore_functions = set(f.strip() for f in args.ignore_functions.split(','))

    if args.rca and not RCA_AVAILABLE:
        print("Peringatan: RCA tidak tersedia. Pastikan rca.py ada di checker/core/", file=sys.stderr)

    report = scan_code(use_rca=args.rca, full=args.full, ignore_files=ignore_files, ignore_functions=ignore_functions)
    print_report(report, args.verbose, args.rca, args.limit, args.show_functions)
    if args.json:
        save_json(report, args.json)

    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    sys.exit(0 if errors == 0 else 1)

if __name__ == "__main__":
    main()