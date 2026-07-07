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
  python accounting_posting_checker.py --group-by-file   # NEW: grup per file
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
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

# ============================================================================
# PROJECT ROOT & SYS.PATH
# ============================================================================
_script_dir = pathlib.Path(__file__).resolve().parent

# Deteksi root dinamis
if (_script_dir / "domain").exists():
    PROJECT_ROOT = _script_dir
elif (_script_dir.parent / "domain").exists():
    PROJECT_ROOT = _script_dir.parent
else:
    PROJECT_ROOT = pathlib.Path(r"E:\full_erp_accounting_engine")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ============================================================================
# RCA INTEGRATION (dengan fallback yang robust)
# ============================================================================
RCA_AVAILABLE = False
get_engine = None
analyze_exception = None
RCAResult = None

try:
    from checker.core.rca import get_engine, analyze_exception, RCAResult
    RCA_AVAILABLE = True
except ImportError:
    try:
        rca_path = PROJECT_ROOT / "checker" / "core" / "rca.py"
        if rca_path.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("checker.core.rca", rca_path)
            if spec and spec.loader:
                sys.modules["checker.core.rca"] = None
                rca_module = importlib.util.module_from_spec(spec)
                sys.modules["checker.core.rca"] = rca_module
                spec.loader.exec_module(rca_module)
                get_engine = rca_module.get_engine
                analyze_exception = rca_module.analyze_exception
                RCAResult = rca_module.RCAResult
                RCA_AVAILABLE = True
    except Exception as e:
        logging.debug(f"RCA fallback failed: {e}")
        RCA_AVAILABLE = False

if not RCA_AVAILABLE:
    def analyze_exception(exc, context=None):
        return None
    def get_engine():
        return None
    RCAResult = None

# ============================================================================
# CONFIGURATION & CONSTANTS
# ============================================================================
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
    severity: str
    category: str
    message: str
    detail: str = ""
    rca: Optional[dict] = None

@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    score: int = 100
    files_scanned: int = 0
    files_introspected: int = 0

# ============================================================================
# 1. HYBRID SCANNER KERNEL
# ============================================================================
class HybridModuleAnalyzer:
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
        if not self.is_valid_syntax:
            return
        try:
            spec = importlib.util.spec_from_file_location(self.module_name, str(self.file_path))
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[self.module_name] = module
                spec.loader.exec_module(module)
                self.runtime_module = module
        except Exception as e:
            logging.debug(f"Runtime loading failed for {self.module_name}: {e}")

    def add_finding(self, severity: str, category: str, message: str, detail: str, line: int = 1, rca: Optional[dict] = None):
        self.findings.append(Finding(str(self.file_path), line, severity, category, message, detail, rca))

    def get_ast_nodes(self, node_type: type[ast.AST]) -> list[ast.AST]:
        if not self.ast_tree:
            return []
        return [n for n in ast.walk(self.ast_tree) if isinstance(n, node_type)]

# ============================================================================
# 2. ENFORCEMENT RULES
# ============================================================================
def _is_mutative_business_logic(func_name: str, file_path: str, rule_type: str = "GENERAL") -> bool:
    name = func_name.lower()
    if name.startswith("_"):
        return False

    ignore_paths = ('kernel', 'infrastructure', 'adapters', 'migrations', 'tests', 'checker', 'core')
    if any(p in file_path for p in ignore_paths):
        return False

    ignore_files = ('query_bus', 'handler_registry', 'bus', 'registry', 'middleware', 'event_handlers')
    if any(f in file_path.lower() for f in ignore_files):
        return False

    read_only_prefixes = ('get_', 'is_', 'has_', 'can_', 'should_', 'will_', 'check_', 'validate_',
                          'fetch_', 'find_', 'read_', 'calculate_', 'compute_', 'build_', 'generate_',
                          'to_', 'from_', 'as_', 'format_', 'parse_', 'serialize_', 'deserialize_',
                          'create_')
    if any(name.startswith(p) for p in read_only_prefixes):
        return False

    ignore_keywords = ('audit', 'log', 'export', 'print', 'format', 'notify', 'alert', 'mapper', 'dto',
                       'error', 'exception', 'debug', 'info', 'warning', 'trace',
                       'factory', 'builder', 'assembler', 'converter')
    if any(k in name for k in ignore_keywords):
        return False

    if rule_type in ("DOUBLE_ENTRY", "PERIOD"):
        strict_accounting = ('post_journal', 'create_journal', 'post_entry', 'record_journal',
                             'close_period', 'settle_ledger', 'record_transaction', 'post_ledger',
                             'execute_journal', 'apply_journal', 'close_ledger')
        if any(k in name for k in strict_accounting):
            return True
        if ('journal' in name or 'ledger' in name or 'period' in name) and \
           any(k in name for k in ('post', 'record', 'close', 'create')):
            return True
        return False

    if rule_type in ("AUDIT", "APPROVAL"):
        if not any(p in file_path for p in ('service_layer', 'use_cases', 'workflows', 'commands_cqrs')):
            return False
        mutative = ('post', 'execute', 'handle', 'approve', 'record', 'submit', 'close',
                    'process', 'settle', 'reconcile', 'update', 'delete', 'create', 'modify',
                    'save', 'persist')
        return any(k in name for k in mutative)

    return False

def _get_rca_for_finding(rule_id: str, message: str, context: dict) -> Optional[dict]:
    if not RCA_AVAILABLE or analyze_exception is None:
        return None
    try:
        exc = RuntimeError(f"[{rule_id}] {message}")
        result = analyze_exception(exc, context)
        if result and hasattr(result, 'to_dict'):
            return result.to_dict()
        return None
    except Exception:
        return None

def enforce_double_entry(analyzer: HybridModuleAnalyzer):
    funcs = analyzer.get_ast_nodes((ast.FunctionDef, ast.AsyncFunctionDef))
    for func in funcs:
        if not _is_mutative_business_logic(func.name, str(analyzer.file_path), "DOUBLE_ENTRY"):
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
            rca = _get_rca_for_finding("DOUBLE_ENTRY", f"Fungsi '{func.name}' kehilangan validasi Double-Entry Axiom.",
                                       {"file": str(analyzer.file_path), "line": getattr(func, 'lineno', 1)})
            analyzer.add_finding("ERROR", "DOUBLE_ENTRY", f"Fungsi '{func.name}' kehilangan validasi Double-Entry Axiom.",
                                 "Wajib gunakan 'BalanceGuard' sebelum state persisten.",
                                 getattr(func, 'lineno', 1), rca)

def enforce_period_status(analyzer: HybridModuleAnalyzer):
    funcs = analyzer.get_ast_nodes((ast.FunctionDef, ast.AsyncFunctionDef))
    for func in funcs:
        if not _is_mutative_business_logic(func.name, str(analyzer.file_path), "PERIOD"):
            continue
        has_period_lock = False
        for node in ast.walk(func):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", "") + getattr(node.func, "attr", "")
                if any(x in name.lower() for x in ('periodguard', 'check_open', 'period_closure_enforcer', 'is_period_open')):
                    has_period_lock = True
                    break
        if not has_period_lock:
            rca = _get_rca_for_finding("PERIOD", f"Fungsi '{func.name}' gagal mengimplementasikan Temporal Consistency.",
                                       {"file": str(analyzer.file_path), "line": getattr(func, 'lineno', 1)})
            analyzer.add_finding("ERROR", "PERIOD", f"Fungsi '{func.name}' gagal mengimplementasikan Temporal Consistency.",
                                 "Pasang 'PeriodGuard' untuk mencegah posting bypass.",
                                 getattr(func, 'lineno', 1), rca)

def enforce_audit_trail(analyzer: HybridModuleAnalyzer):
    funcs = analyzer.get_ast_nodes((ast.FunctionDef, ast.AsyncFunctionDef))
    for func in funcs:
        if not _is_mutative_business_logic(func.name, str(analyzer.file_path), "AUDIT"):
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
            rca = _get_rca_for_finding("AUDIT", f"Fungsi mutasi '{func.name}' tanpa jejak Audit/Event Sourcing.",
                                       {"file": str(analyzer.file_path), "line": getattr(func, 'lineno', 1)})
            analyzer.add_finding("WARNING", "AUDIT", f"Fungsi mutasi '{func.name}' tanpa jejak Audit/Event Sourcing.",
                                 "Gunakan fungsi/hash-chain builder untuk memastikan traceability.",
                                 getattr(func, 'lineno', 1), rca)

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
                        rca = _get_rca_for_finding("APPROVAL", f"Class '{cls.name}' tidak menerapkan SOD eksplisit.",
                                                   {"file": str(analyzer.file_path), "line": cls.lineno})
                        analyzer.add_finding("WARNING", "APPROVAL", f"Class '{cls.name}' tidak menerapkan SOD eksplisit.",
                                             "Pastikan implementasi segregation of duties/authority matrix.",
                                             cls.lineno, rca)
                except Exception:
                    pass

    for func in funcs:
        if not _is_mutative_business_logic(func.name, str(analyzer.file_path), "APPROVAL"):
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
            rca = _get_rca_for_finding("APPROVAL", f"Fungsi '{func.name}' tidak memiliki check SOD/Otoritas.",
                                       {"file": str(analyzer.file_path), "line": getattr(func, 'lineno', 1)})
            analyzer.add_finding("WARNING", "APPROVAL", f"Fungsi '{func.name}' tidak memiliki check SOD/Otoritas.",
                                 "Tambahkan verifikasi 'authority_matrix'.",
                                 getattr(func, 'lineno', 1), rca)

# ============================================================================
# 3. ORCHESTRATOR
# ============================================================================
def _collect_files(directories: list[pathlib.Path]) -> list[pathlib.Path]:
    exclude_dirs = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', 'dist', 'tests', 'migrations'}
    py_files = []
    for directory in directories:
        if not directory.exists():
            continue
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for file in files:
                if file.endswith(".py") and not file.startswith("__"):
                    py_files.append(pathlib.Path(root) / file)
    return list(set(py_files))

def scan_project() -> Report:
    report = Report()
    journal_dirs = [
        PROJECT_ROOT / "domain" / "journal",
        PROJECT_ROOT / "domain" / "ledger",
    ]
    app_dirs = [
        PROJECT_ROOT / "application" / "service_layer",
        PROJECT_ROOT / "application" / "use_cases",
        PROJECT_ROOT / "application" / "workflows",
        PROJECT_ROOT / "application" / "commands_cqrs",
    ]

    journal_files = _collect_files(journal_dirs)
    app_files = _collect_files(app_dirs)

    for py_file in journal_files:
        report.files_scanned += 1
        analyzer = HybridModuleAnalyzer(py_file)
        if analyzer.runtime_module:
            report.files_introspected += 1
        enforce_double_entry(analyzer)
        enforce_period_status(analyzer)
        report.findings.extend(analyzer.findings)

    for py_file in app_files:
        report.files_scanned += 1
        analyzer = HybridModuleAnalyzer(py_file)
        if analyzer.runtime_module:
            report.files_introspected += 1
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
# 4. REPORTING
# ============================================================================
def print_grouped_report(report: Report, verbose: bool = False):
    """Mencetak laporan yang dikelompokkan per file."""
    c = COLOR
    grouped = defaultdict(list)
    for f in report.findings:
        # Gunakan path relatif sebagai key
        try:
            rel_path = str(pathlib.Path(f.file).relative_to(PROJECT_ROOT))
        except ValueError:
            rel_path = f.file
        grouped[rel_path].append(f)

    print(f"\n{c['MAGENTA']}{'='*80}{c['RESET']}")
    print(f"{c['MAGENTA']} SOVEREIGN ACCOUNTING POSTING CHECKER - GROUPED BY FILE {c['RESET']}")
    print(f"{c['MAGENTA']}{'='*80}{c['RESET']}")

    print(f"\n  Total Findings: {c['YELLOW']}{len(report.findings)}{c['RESET']}")
    print(f"  Files with Issues: {c['YELLOW']}{len(grouped)}{c['RESET']}")
    print(f"  RCA Engine: {'✅ Aktif' if RCA_AVAILABLE else '⚠️ Tidak tersedia'}\n")

    for file_path, findings in sorted(grouped.items()):
        # Hitung jumlah per kategori
        cats = defaultdict(int)
        for f in findings:
            cats[f.category] += 1
        cat_summary = " | ".join(f"{k}:{v}" for k, v in cats.items())
        print(f"{c['CYAN']}📄 {file_path}{c['RESET']} ({len(findings)} temuan) [{cat_summary}]")
        for f in findings[:10]:  # tampilkan maks 10 per file
            color = c["RED"] if f.severity in ["CRITICAL", "ERROR"] else c["YELLOW"]
            print(f"    {color}[{f.severity}][{f.category}]{c['RESET']} line {f.line}: {f.message}")
            if verbose and f.detail:
                print(f"       💡 {f.detail}")
            if verbose and f.rca:
                root_cause = f.rca.get('root_cause', '')
                if root_cause:
                    print(f"       🔍 RCA: {root_cause[:100]}")
        if len(findings) > 10:
            print(f"    ... dan {len(findings)-10} temuan lainnya dalam file ini.")
        print()

def print_report(report: Report, verbose: bool = False, group: bool = False):
    if group:
        print_grouped_report(report, verbose)
        return

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
    print(f"  RCA Engine: {'✅ Aktif' if RCA_AVAILABLE else '⚠️ Tidak tersedia'}")

    if report.findings:
        print(f"\n{c['RED'] if errors or criticals else c['YELLOW']}Detail Temuan (sample 50):{c['RESET']}")
        sorted_findings = sorted(report.findings, key=lambda x: {"CRITICAL": 0, "ERROR": 1, "WARNING": 2}[x.severity])

        for idx, f in enumerate(sorted_findings[:50]):
            color = c["RED"] if f.severity in ["CRITICAL", "ERROR"] else c["YELLOW"]
            try:
                rel_path = pathlib.Path(f.file).relative_to(PROJECT_ROOT)
            except ValueError:
                rel_path = f.file

            print(f"  {color}[{f.severity}][{f.category}]{c['RESET']} {rel_path}:{f.line}")
            print(f"     {f.message}")
            if verbose and f.detail:
                print(f"     {c['CYAN']}→ Resolusi: {f.detail}{c['RESET']}")
            if verbose and f.rca:
                root_cause = f.rca.get('root_cause', '')
                if root_cause:
                    print(f"     {c['MAGENTA']}🔍 RCA: {root_cause[:120]}{c['RESET']}")

        if len(report.findings) > 50:
            print(f"\n  ... dan {len(report.findings)-50} temuan lainnya.")
            print("  Gunakan --group-by-file untuk melihat per file.")

def save_json(report: Report, filepath: str):
    data = {
        "metadata": {
            "files_scanned": report.files_scanned,
            "files_introspected": report.files_introspected,
            "score": report.score,
            "rca_enabled": RCA_AVAILABLE
        },
        "findings": [
            {
                "file": f.file,
                "line": f.line,
                "severity": f.severity,
                "category": f.category,
                "message": f.message,
                "detail": f.detail,
                "rca": f.rca
            } for f in report.findings
        ]
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"\n{COLOR['CYAN']}Laporan lengkap JSON disimpan di: {filepath}{COLOR['RESET']}")

# ============================================================================
# 5. CLI
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description="Sovereign Accounting Hybrid Checker")
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan resolusi dan detail rekomendasi kode")
    parser.add_argument("--json", metavar="FILE", help="Ekspor laporan ke format JSON")
    parser.add_argument("--group-by-file", "-g", action="store_true", help="Tampilkan laporan yang dikelompokkan per file")
    parser.add_argument("--debug", action="store_true", help="Tampilkan log debug untuk proses Introspection")
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format='%(levelname)s - %(message)s')
    else:
        logging.basicConfig(level=logging.WARNING)

    report = scan_project()
    print_report(report, args.verbose, args.group_by_file)

    if args.json:
        save_json(report, args.json)

    criticals_errors = sum(1 for f in report.findings if f.severity in ["CRITICAL", "ERROR"])
    sys.exit(0 if criticals_errors == 0 else 1)

if __name__ == "__main__":
    main()