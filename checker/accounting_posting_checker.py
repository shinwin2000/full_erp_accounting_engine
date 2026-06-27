#!/usr/bin/env python3
"""
accounting_posting_checker.py - Hardened Accounting Posting Rules Validator
===========================================================================
Menggabungkan Deep AST Analysis dan Safe Runtime Introspection untuk
memeriksa kepatuhan terhadap S+ Grade Sovereign Accounting Invariants:
1. Conservation of Value (Double-entry)
2. Temporal Consistency (Period status/lock)
3. Immutability & Audit Trail (Hash chain, Event Sourcing)
4. Four-Eyes Principle (Approval workflow)

Penggunaan:
  python accounting_posting_checker.py
  python accounting_posting_checker.py --verbose
  python accounting_posting_checker.py --json report.json
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import inspect
import json
import logging
import os
import pathlib
import sys
from dataclasses import dataclass, field
from typing import Any

# ============================================================================
# CONFIGURATION & CONSTANTS
# ============================================================================
_script_dir = pathlib.Path(__file__).resolve().parent

# Deteksi root dinamis: mundur satu folder jika kita ada di dalam sub-folder 'checker'
if (_script_dir / "domain").exists():
    PROJECT_ROOT = _script_dir
elif (_script_dir.parent / "domain").exists():
    PROJECT_ROOT = _script_dir.parent
else:
    # Hardcode absolute path sebagai fallback darurat (S-Grade Fallback)
    PROJECT_ROOT = pathlib.Path(r"E:\full_erp_accounting_engine")

# Tambahkan root ke sys.path agar dynamic import bisa resolve absolute imports
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Terminal Colors
COLOR = {"RED": "", "GREEN": "", "YELLOW": "", "CYAN": "", "MAGENTA": "", "RESET": ""}
try:
    import colorama
    colorama.init(autoreset=True)
    COLOR.update({
        "RED": colorama.Fore.RED,
        "GREEN": colorama.Fore.GREEN,
        "YELLOW": colorama.Fore.YELLOW,
        "CYAN": colorama.Fore.CYAN,
        "MAGENTA": colorama.Fore.MAGENTA,
        "RESET": colorama.Style.RESET_ALL
    })
except ImportError:
    pass

@dataclass
class Finding:
    file: str
    line: int
    severity: str       # CRITICAL / ERROR / WARNING
    category: str       # DOUBLE_ENTRY / PERIOD / AUDIT / APPROVAL / RUNTIME
    message: str
    detail: str = ""

@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    score: int = 100
    files_scanned: int = 0
    files_introspected: int = 0

# ============================================================================
# 1. HYBRID SCANNER KERNEL (AST + RUNTIME)
# ============================================================================
class HybridModuleAnalyzer:
    """Menganalisis file melalui AST secara statis dan Runtime Introspection secara dinamis."""

    def __init__(self, file_path: pathlib.Path):
        self.file_path = file_path
        self.module_name = self._get_module_name()
        self.ast_tree: ast.Module | None = None
        self.runtime_module: Any | None = None
        self.findings: list[Finding] = []
        self.is_valid_syntax = False

        self._parse_ast()
        self._load_runtime()

    def _get_module_name(self) -> str:
        try:
            rel_path = self.file_path.relative_to(PROJECT_ROOT)
            return str(rel_path).replace(os.sep, ".").replace(".py", "")
        except ValueError:
            return self.file_path.stem

    def _parse_ast(self):
        try:
            source = self.file_path.read_text(encoding="utf-8")
            self.ast_tree = ast.parse(source, filename=str(self.file_path))
            self.is_valid_syntax = True
        except SyntaxError as e:
            self.add_finding("CRITICAL", "SYNTAX", f"Syntax error at line {e.lineno}", str(e), e.lineno or 1)
        except Exception as e:
            self.add_finding("CRITICAL", "IO", "Gagal membaca file", str(e), 1)

    def _load_runtime(self):
        """Memuat modul secara dinamis dan aman untuk inspeksi runtime."""
        if not self.is_valid_syntax:
            return

        try:
            spec = importlib.util.spec_from_file_location(self.module_name, str(self.file_path))
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[self.module_name] = module
                # Mengeksekusi modul (bisa gagal jika ada side-effects di module-level atau koneksi DB)
                spec.loader.exec_module(module)
                self.runtime_module = module
        except Exception as e:
            # Tidak menambahkan sebagai error utama karena ini wajar di static analysis
            logging.debug(f"Runtime loading failed for {self.module_name}: {e}")
            pass

    def add_finding(self, severity: str, category: str, message: str, detail: str, line: int = 1):
        self.findings.append(Finding(str(self.file_path), line, severity, category, message, detail))

    def get_ast_nodes(self, node_type: type[ast.AST]) -> list[ast.AST]:
        if not self.ast_tree: return []
        return [n for n in ast.walk(self.ast_tree) if isinstance(n, node_type)]

# ============================================================================
# 2. ENFORCEMENT RULES (CONTEXT-AWARE HEURISTICS)
# ============================================================================

def _is_mutative_business_logic(func_name: str, file_path: str, rule_type: str = "GENERAL") -> bool:
    """
    Heuristik cerdas yang memahami Domain-Driven Design (DDD) dan batas lapisan akuntansi.
    """
    name = func_name.lower()

    # 1. KEKUASAAN MUTLAK: Abaikan method private/protected (contoh: _record_audit, _helper)
    if name.startswith("_"):
        return False

    # 2. Abaikan komponen sistem dan infrastruktur
    if "kernel" in file_path or "infrastructure" in file_path or "adapters" in file_path:
        return False

    # 3. Abaikan fungsi read-only, kalkulasi, atau murni utilitas/log
    ignore_prefixes = ('get_', 'is_', 'check_', 'validate_', 'fetch_', 'find_', 'read_', 'calculate_', 'compute_', 'build_', 'generate_')
    ignore_keywords = ('audit', 'log', 'export', 'print', 'format', 'notify', 'alert', 'mapper', 'dto')

    if any(name.startswith(p) for p in ignore_prefixes): return False
    if any(k in name for k in ignore_keywords): return False

    # 4. KONTEKS AKUNTANSI STRICT (Hanya untuk Double-Entry & Period Lock)
    if rule_type in ("DOUBLE_ENTRY", "PERIOD"):
        # Jangan paksa modul upstream (seperti Sales/Inventory) untuk memvalidasi jurnal.
        # Aturan ini HANYA berlaku untuk core ledger dan eksekutor jurnal.
        strict_accounting_keywords = ('post_journal', 'create_journal', 'post_entry', 'record_journal', 'close_period', 'settle_ledger', 'record_transaction')
        return any(k in name for k in strict_accounting_keywords)

    # 5. KONTEKS MUTASI UMUM (Untuk Audit Trail dan Approval Workflow)
    mutative_keywords = ('post', 'execute', 'handle', 'approve', 'record', 'submit', 'close', 'process', 'settle', 'reconcile')
    return any(k in name for k in mutative_keywords)


def enforce_double_entry(analyzer: HybridModuleAnalyzer):
    funcs = analyzer.get_ast_nodes((ast.FunctionDef, ast.AsyncFunctionDef))
    for func in funcs:
        # Panggil dengan konteks DOUBLE_ENTRY
        if not _is_mutative_business_logic(func.name, analyzer.file_path.name, "DOUBLE_ENTRY"):
            continue

        has_guard = False
        for node in ast.walk(func):
            if isinstance(node, ast.Call):
                func_id = getattr(node.func, "id", "")
                func_attr = getattr(node.func, "attr", "")
                if any(x in func_id.lower() or x in func_attr.lower() for x in ('balanceguard', 'check_balance', 'validate_double_entry', 'conservation_of_value')):
                    has_guard = True
                    break

        if analyzer.runtime_module and hasattr(analyzer.runtime_module, func.name):
            obj = getattr(analyzer.runtime_module, func.name)
            if inspect.isfunction(obj) or inspect.ismethod(obj):
                if hasattr(obj, '__wrapped__'):
                    closure_vars = inspect.getclosurevars(obj)
                    if any('balance' in k.lower() for k in closure_vars.nonlocals.keys()):
                        has_guard = True

        if not has_guard:
            analyzer.add_finding("ERROR", "DOUBLE_ENTRY", f"Fungsi '{func.name}' kehilangan validasi Double-Entry Axiom.", "Wajib gunakan 'BalanceGuard' sebelum state persisten.", getattr(func, 'lineno', 1))


def enforce_period_status(analyzer: HybridModuleAnalyzer):
    funcs = analyzer.get_ast_nodes((ast.FunctionDef, ast.AsyncFunctionDef))
    for func in funcs:
        # Panggil dengan konteks PERIOD
        if not _is_mutative_business_logic(func.name, analyzer.file_path.name, "PERIOD"):
            continue

        has_period_lock = False
        for node in ast.walk(func):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", "") + getattr(node.func, "attr", "")
                if any(x in name.lower() for x in ('periodguard', 'check_open', 'period_closure_enforcer', 'is_period_open')):
                    has_period_lock = True
                    break

        if not has_period_lock:
            analyzer.add_finding("ERROR", "PERIOD", f"Fungsi '{func.name}' gagal mengimplementasikan Temporal Consistency.", "Pasang 'PeriodGuard' untuk mencegah posting bypass.", getattr(func, 'lineno', 1))


def enforce_audit_trail(analyzer: HybridModuleAnalyzer):
    funcs = analyzer.get_ast_nodes((ast.FunctionDef, ast.AsyncFunctionDef))
    for func in funcs:
        # Panggil dengan konteks GENERAL (Mutasi)
        if not _is_mutative_business_logic(func.name, analyzer.file_path.name, "GENERAL"):
            continue

        has_audit = False
        for dec in func.decorator_list:
            dec_name = getattr(dec, "id", "") if isinstance(dec, ast.Name) else getattr(getattr(dec, "func", None), "id", "")
            if 'audit' in dec_name.lower() or 'event' in dec_name.lower() or 'transactional' in dec_name.lower():
                has_audit = True

        if not has_audit:
            for node in ast.walk(func):
                if isinstance(node, ast.Call):
                    name = getattr(node.func, "id", "") + getattr(node.func, "attr", "")
                    if any(x in name.lower() for x in ('publish_event', 'hash_chain', 'append_only_store', 'audit_trail_writer', 'emit')):
                        has_audit = True
                        break

        if not has_audit:
            analyzer.add_finding("WARNING", "AUDIT", f"Fungsi mutasi '{func.name}' tanpa jejak Audit/Event Sourcing.", "Gunakan fungsi/hash-chain builder untuk memastikan traceability.", getattr(func, 'lineno', 1))


def enforce_approval_workflow(analyzer: HybridModuleAnalyzer):
    classes = analyzer.get_ast_nodes(ast.ClassDef)
    funcs = analyzer.get_ast_nodes((ast.FunctionDef, ast.AsyncFunctionDef))

    for cls in classes:
        if 'handler' in cls.name.lower() and 'command' in cls.name.lower():
            if analyzer.runtime_module:
                try:
                    runtime_cls = getattr(analyzer.runtime_module, cls.name)
                    bases = [b.__name__ for b in inspect.getmro(runtime_cls)]
                    if 'CommandHandler' in bases and not hasattr(runtime_cls, 'approve') and not hasattr(runtime_cls, 'validate_authority'):
                        analyzer.add_finding("WARNING", "APPROVAL", f"Class '{cls.name}' tidak menerapkan SOD eksplisit.", "Pastikan implementasi segregation of duties/authority matrix.", cls.lineno)
                except Exception:
                    pass

    for func in funcs:
        # Panggil dengan konteks GENERAL (Mutasi)
        if not _is_mutative_business_logic(func.name, analyzer.file_path.name, "GENERAL"):
            continue

        has_approval = False
        for node in ast.walk(func):
            if isinstance(node, ast.If):
                cond_str = ast.unparse(node.test).lower()
                if 'approv' in cond_str or 'four_eyes' in cond_str or 'sod_' in cond_str or 'authority' in cond_str:
                    has_approval = True
                    break
            elif isinstance(node, ast.Call):
                name = getattr(node.func, "id", "") + getattr(node.func, "attr", "")
                if 'authority' in name.lower() or 'sod_enforcer' in name.lower() or 'four_eyes' in name.lower():
                    has_approval = True
                    break

        if not has_approval:
            analyzer.add_finding("WARNING", "APPROVAL", f"Fungsi '{func.name}' tidak memiliki check SOD/Otoritas.", "Tambahkan verifikasi 'authority_matrix'.", getattr(func, 'lineno', 1))
# ============================================================================
# 3. ORCHESTRATOR
# ============================================================================

def scan_project() -> Report:
    report = Report()

    # Hanya scan direktori di mana Core Business Logic/Mutasi dieksekusi.
    # Kita KELUARKAN 'kernel/guards' dan 'infrastructure' dari radar.
    target_dirs = [
        PROJECT_ROOT / "domain" / "journal",
        PROJECT_ROOT / "domain" / "bank_cash",
        PROJECT_ROOT / "domain" / "subledger_ap",
        PROJECT_ROOT / "domain" / "subledger_ar",
        PROJECT_ROOT / "domain" / "manufacturing",
        PROJECT_ROOT / "application" / "use_cases",
        PROJECT_ROOT / "application" / "commands_cqrs",
        PROJECT_ROOT / "application" / "workflows",
        PROJECT_ROOT / "application" / "service_layer",
    ]

    exclude_dirs = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', 'dist', 'tests', 'migrations'}

    py_files: list[pathlib.Path] = []
    for directory in target_dirs:
        if not directory.exists():
            continue
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for file in files:
                if file.endswith(".py") and not file.startswith("__"):
                    py_files.append(pathlib.Path(root) / file)

    for py_file in set(py_files):
        report.files_scanned += 1
        analyzer = HybridModuleAnalyzer(py_file)

        if analyzer.runtime_module:
            report.files_introspected += 1

        enforce_double_entry(analyzer)
        enforce_period_status(analyzer)
        enforce_audit_trail(analyzer)
        enforce_approval_workflow(analyzer)

        report.findings.extend(analyzer.findings)

    criticals = sum(1 for f in report.findings if f.severity == "CRITICAL")
    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")

    deduction = (criticals * 25) + (errors * 10) + (warnings * 3)
    report.score = max(0, 100 - deduction)

    return report
# ============================================================================
# 4. REPORTING & CLI
# ============================================================================

def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['MAGENTA']}{'='*80}{c['RESET']}")
    print(f"{c['MAGENTA']} SOVEREIGN ACCOUNTING POSTING CHECKER - HYBRID ANALYSIS REPORT {c['RESET']}")
    print(f"{c['MAGENTA']}{'='*80}{c['RESET']}")

    print(f"\n  Files Scanned (AST): {c['CYAN']}{report.files_scanned}{c['RESET']}")
    print(f"  Files Introspected (Runtime): {c['CYAN']}{report.files_introspected}{c['RESET']}")

    criticals = sum(1 for f in report.findings if f.severity == "CRITICAL")
    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")

    print(f"  Findings: CRITICAL: {c['RED']}{criticals}{c['RESET']} | ERROR: {c['RED']}{errors}{c['RESET']} | WARNING: {c['YELLOW']}{warnings}{c['RESET']}")

    score_color = c['GREEN'] if report.score >= 90 else (c['YELLOW'] if report.score >= 70 else c['RED'])
    print(f"  System Compliance Score: {score_color}{report.score}/100{c['RESET']}")

    if report.findings:
        print(f"\n{c['RED'] if errors or criticals else c['YELLOW']}Detail Temuan:{c['RESET']}")
        # Urutkan berdasarkan severity
        sorted_findings = sorted(report.findings, key=lambda x: {"CRITICAL": 0, "ERROR": 1, "WARNING": 2}[x.severity])

        for idx, f in enumerate(sorted_findings[:50]):
            color = c["RED"] if f.severity in ["CRITICAL", "ERROR"] else c["YELLOW"]
            # Gunakan path relatif dari root proyek agar lebih rapi
            try:
                rel_path = pathlib.Path(f.file).relative_to(PROJECT_ROOT)
            except ValueError:
                rel_path = f.file

            print(f"  {color}[{f.severity}][{f.category}]{c['RESET']} {rel_path}:{f.line}")
            print(f"     {f.message}")
            if verbose and f.detail:
                print(f"     {c['CYAN']}→ Resolusi: {f.detail}{c['RESET']}")

        if len(report.findings) > 50:
            print(f"\n  ... dan {len(report.findings)-50} temuan lainnya (gunakan export JSON untuk melihat semua).")

def save_json(report: Report, filepath: str):
    data = {
        "metadata": {
            "files_scanned": report.files_scanned,
            "files_introspected": report.files_introspected,
            "score": report.score
        },
        "findings": [
            {
                "file": f.file,
                "line": f.line,
                "severity": f.severity,
                "category": f.category,
                "message": f.message,
                "detail": f.detail
            } for f in report.findings
        ]
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{COLOR['CYAN']}Laporan lengkap JSON disimpan di: {filepath}{COLOR['RESET']}")

def main():
    parser = argparse.ArgumentParser(description="Sovereign Accounting Hybrid Checker")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan resolusi dan detail rekomendasi kode")
    parser.add_argument("--json", metavar="FILE", help="Ekspor laporan ke format JSON")
    parser.add_argument("--debug", action="store_true", help="Tampilkan log debug untuk proses Introspection")
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format='%(levelname)s - %(message)s')
    else:
        logging.basicConfig(level=logging.WARNING)

    report = scan_project()
    print_report(report, args.verbose)

    if args.json:
        save_json(report, args.json)

    criticals_errors = sum(1 for f in report.findings if f.severity in ["CRITICAL", "ERROR"])
    sys.exit(0 if criticals_errors == 0 else 1)

if __name__ == "__main__":
    main()
