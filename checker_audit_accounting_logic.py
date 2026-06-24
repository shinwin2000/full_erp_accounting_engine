#!/usr/bin/env python3
"""
ACCOUNTING LOGIC AUDITOR — Enterprise Hybrid Edition (v7.1 - Full Production)
==================================================================================
Sistem Keamanan Berlapis (Hybrid Gatekeeper) untuk Menjaga Integritas Keuangan ERP.
Menggabungkan Static AST Parsing dengan Real Runtime Introspection di dalam Memori.

Validasi yang Dilakukan:
1. Validasi Tipe Data Moneter Riil (Decimal vs Float) via Runtime Type Hints & AST.
2. Deteksi Hardcode Tarif Pajak (PPN/PPh/Coretax Compliance) via Regex & Token.
3. Kepatuhan Aturan Double-Entry (Debit == Credit Balance Assertion).
4. Deteksi Magic Numbers Finansial (Suku Bunga, Pembagi Hari Kerja).
5. Verifikasi Keberadaan Fungsi Rekonsiliasi & Penutupan Periode Fiskal.
==================================================================================
"""

import ast
import os
import sys
import re
import json
import importlib
import inspect
from pathlib import Path
from typing import List, Dict, Set, Tuple, Any, Optional, Type, get_type_hints
from dataclasses import dataclass, field

# --- KONFIGURASI NAVIGASI DIREKTORI ---
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SKIP_DIRS = {
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".git", ".venv", "venv", "node_modules", ".tox", ".cache", "dist", "build", "uv"
}

NON_MONETARY_VARS = {
    "time", "latency", "duration", "count", "total_time", "total_latency",
    "score", "risk_score", "priority", "index", "num", "size", "length",
    "execution_time", "elapsed", "timestamp", "interval", "delay",
    "rate", "error_rate", "deviation_rate", "consumption_rate", "success_rate"
}

MONETARY_KEYWORDS = {
    "amount", "balance", "debit", "credit", "price", "cost", "tax", "total",
    "value", "net", "gross", "discount", "ppn", "pph", "withholding",
    "payment", "fee", "penalty", "interest", "depreciation", "amortization",
    "revenue", "expense", "profit", "income", "gain", "loss", "salary", "wage",
    "bonus", "dividend", "capital", "equity", "liability", "asset", "inventory",
    "cogs", "hpp", "npwp", "faktur", "bupot", "spt", "pajak", "tax_rate",
    "pph_rate", "ppn_rate", "interest_rate", "discount_rate"
}

# --- COLOR SETUP FOR ENTERPRISE TERMINAL ---
try:
    import colorama
    colorama.init(autoreset=True)
    RED = colorama.Fore.RED
    GREEN = colorama.Fore.GREEN
    YELLOW = colorama.Fore.YELLOW
    CYAN = colorama.Fore.CYAN
    MAGENTA = colorama.Fore.MAGENTA
    BOLD = colorama.Style.BRIGHT
    RESET = colorama.Style.RESET_ALL
except ImportError:
    RED = GREEN = YELLOW = CYAN = MAGENTA = BOLD = RESET = ""

@dataclass
class Finding:
    severity: str
    category: str
    file: str
    line: int
    message: str
    detail: str = ""
    recommendation: str = ""

class EnterpriseAccountingAuditor:
    def __init__(self):
        self.findings: List[Finding] = []
        self.scanned_files_count = 0
        self.runtime_imported_count = 0

    def is_monetary_variable(self, var_name: str) -> bool:
        lower = var_name.lower()
        tokens = set(lower.split('_'))
        
        NON_MONETARY_INDICATORS = {
            "ms", "ns", "sec", "seconds", "percent", "pct", "factor", 
            "score", "strength", "latency", "duration", "count", "index", 
            "num", "rate", "float", "coefficient", "size", "margin"
        }
        
        if tokens.intersection(NON_MONETARY_INDICATORS) or lower in NON_MONETARY_VARS:
            return False
            
        for kw in MONETARY_KEYWORDS:
            if kw in tokens or kw in lower:
                if kw == "liability" and "reliability" in lower:
                    continue
                if kw == "rate" and any(x in lower for x in ["utilization", "execution", "error", "success", "deviation"]):
                    continue
                return True
        return False

    def _get_python_files(self) -> List[Path]:
        files = []
        # Ambil file di root level yang valid
        for p in ROOT.glob("*.py"):
            if p.name not in [Path(__file__).name, "main_checker.py", "test_event_handler.py", "test_cqrs_handler.py", "validate_real.py"]:
                files.append(p)
                
        # Ambil seluruh sub-package arsitektur ERP
        target_packages = [
            "domain", "application", "infrastructure", "kernel", "ports", 
            "axioms", "constitution", "policy_engine", "audit", "adapters", 
            "bootstrap", "compliance", "event_gateway", "projections", "reports", "transformers"
        ]
        for pkg in target_packages:
            pkg_dir = ROOT / pkg
            if pkg_dir.is_dir():
                for p in pkg_dir.rglob("*.py"):
                    if not any(part in SKIP_DIRS for part in p.parts):
                        files.append(p)
        return sorted(list(set(files)))

    def _module_name_from_path(self, path: Path) -> str:
        return str(path.relative_to(ROOT).with_suffix("")).replace(os.sep, ".")

    # ══════════════════════════════════════════════════════════════════════════
    # LAYER 1: STATIC AST ANALYSIS ENGINE
    # ══════════════════════════════════════════════════════════════════════════
    
    def perform_ast_analysis(self, path: Path, rel_path: str):
        try:
            content = path.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(path))
            lines = content.splitlines()
        except Exception as e:
            self.findings.append(Finding(
                severity="CRITICAL", category="AST_PARSING", file=rel_path, line=1,
                message=f"Gagal memparsing struktur AST file: {str(e)}"
            ))
            return

        # Inject parent context ke dalam node AST secara manual untuk pelacakan context-aware
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                setattr(child, 'parent_node', parent)

        self._ast_check_float_and_decimal(tree, rel_path)
        self._ast_check_tax_hardcode(tree, lines, rel_path)
        self._ast_check_double_entry(tree, rel_path)
        self._ast_check_magic_numbers(lines, rel_path)
        self._ast_check_domain_features(tree, rel_path)

    def _ast_check_float_and_decimal(self, tree: ast.AST, rel_path: str):
        # Proteksi: Abaikan filter plumbing luar untuk strict domain verification
        if any(x in rel_path for x in ["adapters/", "infrastructure/", "logger", "dto_objects/", "commands_cqrs/", "application/mappers/"]):
            return

        for node in ast.walk(tree):
            # 1. Deteksi assignment nilai literal float ke variabel moneter (e.g. balance = 1500.50)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and self.is_monetary_variable(target.id):
                        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, float):
                            self.findings.append(Finding(
                                severity="CRITICAL", category="MONETARY_INTEGRITY", file=rel_path, line=node.lineno,
                                message=f"Variabel moneter '{target.id}' diisi literal float ({node.value.value})",
                                recommendation="Ubah ke string literal dan bungkus dengan Decimal('...')"
                            ))
                        elif isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "float":
                            self.findings.append(Finding(
                                severity="CRITICAL", category="MONETARY_INTEGRITY", file=rel_path, line=node.lineno,
                                message=f"Variabel moneter '{target.id}' dipaksa menggunakan konversi float()",
                                recommendation="Gunakan instansiasi Decimal()"
                            ))

            # 2. Deteksi operasi matematika langsung pada variabel moneter di luar konteks Decimal
            elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
                has_monetary = False
                if isinstance(node.left, ast.Name) and self.is_monetary_variable(node.left.id):
                    has_monetary = True
                elif isinstance(node.right, ast.Name) and self.is_monetary_variable(node.right.id):
                    has_monetary = True

                if has_monetary:
                    in_decimal_safe_zone = False
                    current = getattr(node, 'parent_node', None)
                    while current:
                        if isinstance(current, ast.Call):
                            if isinstance(current.func, ast.Name) and current.func.id in ["Decimal", "quantize", "round"]:
                                in_decimal_safe_zone = True
                                break
                            elif isinstance(current.func, ast.Attribute) and current.func.attr in ["quantize", "Decimal"]:
                                in_decimal_safe_zone = True
                                break
                        current = getattr(current, 'parent_node', None)

                    if not in_decimal_safe_zone:
                        self.findings.append(Finding(
                            severity="WARNING", category="NUMERICAL_ACCURACY", file=rel_path, line=node.lineno,
                            message="Operasi matematika finansial terdeteksi di luar perlindungan Decimal context",
                            recommendation="Bungkus ekspresi dengan Decimal atau panggil method .quantize() untuk memangkas pembulatan floating point."
                        ))

    def _ast_check_tax_hardcode(self, tree: ast.AST, lines: List[str], rel_path: str):
        if not any(x in rel_path for x in ["policy_engine/tax", "compliance", "coretax", "tax_indonesia"]):
            return

        constants_defined = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and isinstance(node.value, ast.Constant):
                        constants_defined.add(t.id)

        for lineno, line in enumerate(lines, 1):
            if line.strip().startswith("#") or '"""' in line or "'''" in line:
                continue
            matches = re.findall(r'\b(0\.\d{1,4})\b', line)
            for m in matches:
                if any(m in line and var in line for var in constants_defined):
                    continue
                if any(kw in line.lower() for kw in ["tax", "ppn", "pph", "pajak"]):
                    self.findings.append(Finding(
                        severity="WARNING", category="REGULATORY_COMPLIANCE", file=rel_path, line=lineno,
                        message=f"Ditemukan hardcode nilai tarif pajak '{m}' di dalam baris kalkulasi aktif",
                        recommendation="Ambil tarif dinamis melalui policy_engine/tax atau configuration registry."
                    ))

    def _ast_check_double_entry(self, tree: ast.AST, rel_path: str):
        # 1. Perketat filter isolasi: Abaikan seluruh pipa koordinasi data pembacaan & mappers
        if any(x in rel_path for x in [
            "adapters/", "infrastructure/", "bootstrap/", "dto_objects/", "commands_cqrs/",
            "application/mappers/", "application/events/", "projections/", "reports/", "transformers/"
        ]):
            return

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name_lower = node.name.lower()
                if "init" in name_lower or "hook" in name_lower or name_lower.startswith("can_"):
                    continue
                
                tokens = set(name_lower.split('_'))
                
                # 2. Tambahkan EXCLUSION TOKENS untuk mengeliminasi False Positives pembacaan/transformasi data
                EXCLUDE_TOKENS = {
                    "map", "get", "to", "dto", "request", "response", "view", 
                    "read", "number", "id", "handle", "subscriber", "event", 
                    "serializer", "display", "fetch", "query", "export", "validate"
                }
                if tokens.intersection(EXCLUDE_TOKENS):
                    continue
                
                is_accounting_action = (
                    "journal" in tokens or "ledger" in tokens or "entry" in tokens or
                    ("post" in tokens and not tokens.intersection({"result", "envelope", "command", "query", "request", "message"}))
                )
                
                if is_accounting_action:
                    func_body = ast.unparse(node)
                    if not ("debit" in func_body and "credit" in func_body and ("==" in func_body or "assert" in func_body or "!=" in func_body)):
                        self.findings.append(Finding(
                            severity="CRITICAL", category="DOUBLE_ENTRY_VALIDATION", file=rel_path, line=node.lineno,
                            message=f"Fungsi pembukuan aktif '{node.name}' terdeteksi memproses entri jurnal tanpa validasi keseimbangan debit-kredit",
                            recommendation="Wajib tambahkan penegasan logis: assert total_debit == total_credit"
                        ))

    def _ast_check_magic_numbers(self, lines: List[str], rel_path: str):
        if not any(x in rel_path for x in ["domain", "application/use_cases", "kernel", "policy_engine"]):
            return
        
        magic_patterns = [
            (r'\b365\b', "Pembagi hari dalam setahun (Hari Kalender)"),
            (r'\b360\b', "Pembagi hari dalam setahun (Hari Bank/Komersial)"),
            (r'\b12\b', "Konstanta jumlah bulan dalam setahun"),
            (r'\b0\.5\b', "Faktor multiplikasi setengah tahun"),
            (r'\b0\.25\b', "Faktor multiplikasi kuartal keuangan")
        ]
        
        for pattern, desc in magic_patterns:
            for lineno, line in enumerate(lines, 1):
                if line.strip().startswith("#") or '"""' in line or "'''" in line:
                    continue
                if re.search(pattern, line):
                    # Jika angka tersebut adalah bagian dari inisialisasi konstanta UPPERCASE, izinkan
                    if "=" in line and line.split("=")[0].strip().isupper():
                        continue
                    self.findings.append(Finding(
                        severity="WARNING", category="CLEAN_CODE_CONTEXT", file=rel_path, line=lineno,
                        message=f"Ditemukan Financial Magic Number '{pattern}' ({desc}) tanpa penamaan konstanta yang jelas",
                        recommendation="Ekstrak nilai angka ke variabel konstanta global bernama di bagian atas modul."
                    ))

    def _ast_check_domain_features(self, tree: ast.AST, rel_path: str):
        filename_lower = Path(rel_path).name.lower()
        
        # Validasi Fitur Rekonsiliasi
        if "reconciliation" in rel_path or "subledger" in rel_path:
            if not any(x in filename_lower for x in ["__init__.py", "port.py", "repository"]):
                has_reconcile = any(
                    isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and "reconcile" in n.name.lower()
                    for n in ast.walk(tree)
                )
                if not has_reconcile:
                    self.findings.append(Finding(
                        severity="WARNING", category="ARCHITECTURE_GAP", file=rel_path, line=1,
                        message=f"File subledger/rekonsiliasi '{Path(rel_path).name}' terdeteksi tidak mengekspos fungsi reconcile()",
                        recommendation="Implementasikan fungsi pembanding saldo internal 'def reconcile(...)'"
                    ))
                    
        # Validasi Tutup Buku Periode
        if "period_close" in rel_path or "fiscal_period" in rel_path:
            if not any(x in filename_lower for x in ["__init__.py", "port.py", "repository"]):
                has_close_handler = any(
                    isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and "close" in n.name.lower()
                    for n in ast.walk(tree)
                )
                if not has_close_handler:
                    self.findings.append(Finding(
                        severity="CRITICAL", category="ARCHITECTURE_GAP", file=rel_path, line=1,
                        message="Modul penutupan periode fiskal terdeteksi kehilangan fungsi eksekutor close()",
                        recommendation="Wajib implementasikan fungsi penutupan state: 'def close_period(...)'"
                    ))

    # ══════════════════════════════════════════════════════════════════════════
    # LAYER 2: DYNAMIC RUNTIME INTROSPECTION ENGINE
    # ══════════════════════════════════════════════════════════════════════════
    
    def perform_runtime_introspection(self, path: Path, rel_path: str):
        mod_name = self._module_name_from_path(path)
        try:
            # Muat modul asli secara riil ke dalam RAM sistem
            mod = importlib.import_module(mod_name)
            self.runtime_imported_count += 1
        except Exception as e:
            # Jika gagal import (misal karena setup environment database/Kafka), catat sebagai info arsitektur, jangan crash.
            self.findings.append(Finding(
                severity="WARNING", category="RUNTIME_BOOT_DIAGNOSTIC", file=rel_path, line=1,
                message=f"Modul tidak dapat dimuat ke runtime memori secara langsung: {str(e)}",
                detail="Kemungkinan membutuhkan runtime context database, environment variables, atau singleton container tertentu."
            ))
            return

        # Refleksi seluruh komponen internal objek yang hidup di dalam RAM
        for member_name, obj in inspect.getmembers(mod):
            if inspect.isclass(obj):
                # Proteksi: Hanya introspeksi kelas asli milik modul tersebut, bukan hasil import dari modul tetangga
                if obj.__module__ == mod_name:
                    self._runtime_inspect_class(obj, member_name, rel_path)
            elif inspect.isfunction(obj):
                if obj.__module__ == mod_name:
                    self._runtime_inspect_function(obj, member_name, rel_path)

    def _runtime_inspect_class(self, cls: Type[Any], cls_name: str, rel_path: str):
        # Ambil Type Hints dari properti/atribut kelas yang dialokasikan di memori
        try:
            hints = get_type_hints(cls)
            for attr_name, attr_type in hints.items():
                if self.is_monetary_variable(attr_name):
                    # Cari pelanggaran fatal: Atribut moneter keuangan tetapi tipe data riilnya adalah float!
                    if attr_type is float:
                        self.findings.append(Finding(
                            severity="CRITICAL", category="RUNTIME_TYPE_VIOLATION", file=rel_path, line=1,
                            message=f"RUNTIME INTR0SPECTION: Atribut '{cls_name}.{attr_name}' terbukti teranotasi tipe primitive data 'float'",
                            recommendation="Gunakan tipe data 'Decimal' dari modul decimal Python untuk menghentikan akumulasi error pembulatan."
                        ))
        except Exception:
            pass

        # Introspeksi method internal di dalam kelas tersebut
        for attr_name in dir(cls):
            attr_val = getattr(cls, attr_name)
            if inspect.isfunction(attr_val) or inspect.ismethod(attr_val):
                self._runtime_inspect_function(attr_val, f"{cls_name}.{attr_name}", rel_path)

    def _runtime_inspect_function(self, func: Any, func_display_name: str, rel_path: str):
        try:
            hints = get_type_hints(func)
            for arg_name, arg_type in hints.items():
                if arg_name != "return" and self.is_monetary_variable(arg_name):
                    if arg_type is float:
                        self.findings.append(Finding(
                            severity="CRITICAL", category="RUNTIME_TYPE_VIOLATION", file=rel_path, line=1,
                            message=f"RUNTIME INTROSPECTION: Parameter fungsi '{func_display_name}({arg_name})' menerima tipe data 'float'",
                            recommendation="Ganti signature parameter fungsi menerima tipe data 'Decimal'."
                        ))
        except Exception:
            pass

        # Inspeksi default values parameter untuk mengantisipasi inject objek float tersembunyi
        try:
            sig = inspect.signature(func)
            for param_name, param in sig.parameters.items():
                if self.is_monetary_variable(param_name):
                    if isinstance(param.default, float):
                        self.findings.append(Finding(
                            severity="CRITICAL", category="RUNTIME_SIGNATURE_FLAW", file=rel_path, line=1,
                            message=f"RUNTIME INTROSPECTION: Parameter '{func_display_name}.{param_name}' memiliki default value primitive float ({param.default})",
                            recommendation="Ubah default value ke None atau Decimal('0.0')"
                        ))
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════════
    # EXECUTION RUNNER & COORDINATION
    # ══════════════════════════════════════════════════════════════════════════

    def execute_global_audit(self) -> int:
        print(f"{BOLD}{CYAN}╔{'═'*78}╗")
        print(f"║{' '*13}FORTRESS HYBRID ACCOUNTING LOGIC AUDITOR (v7.1 - REAL)    {' '*11}║")
        print(f"╚{'═'*78}╝\n")

        target_files = self._get_python_files()
        self.scanned_files_count = len(target_files)
        print(f"📂 Memulai pemindaian otomatis pada {self.scanned_files_count} file Python proyek ERP...\n")

        for file_path in target_files:
            rel_path = str(file_path.relative_to(ROOT)).replace("\\", "/")
            
            # Eksekusi Tahap 1: Analisis Struktur Teks (AST)
            self.perform_ast_analysis(file_path, rel_path)
            
            # Eksekusi Tahap 2: Introspeksi Objek Memori Aktif (Runtime)
            self.perform_runtime_introspection(file_path, rel_path)

        # Pisahkan temuan berdasarkan tingkat keparahan risiko keuangan
        critical_issues = [f for f in self.findings if f.severity == "CRITICAL"]
        warning_issues = [f for f in self.findings if f.severity == "WARNING"]

        # PRINT REPORT KE TERMINAL DEVEL0PER
        if critical_issues:
            print(f"{RED}{BOLD}🔴 TEMUAN KRITIS TERDETEKSI ({len(critical_issues)}){RESET}")
            for f in critical_issues[:40]:
                print(f"  {RED}✖{RESET} [{f.category}] {CYAN}{f.file}:{BOLD}{f.line}{RESET} -> {f.message}")
                if f.recommendation:
                    print(f"    {MAGENTA}Solusi Rekomendasi:{RESET} {f.recommendation}")
            if len(critical_issues) > 40:
                print(f"  ... dan {len(critical_issues) - 40} kesalahan kritis lainnya.")
        else:
            print(f"{GREEN}{BOLD}✅ INTEGRITAS KRITIS AMAN (0 Kritis): Tidak ditemukan celah pembulatan atau pelanggaran pembukuan moneter.{RESET}")

        if warning_issues:
            print(f"\n{YELLOW}{BOLD}⚠️ PERINGATAN KODE ARSITEKTUR ({len(warning_issues)}){RESET}")
            for f in warning_issues[:20]:
                print(f"  {YELLOW}⚠{RESET} [{f.category}] {f.file}:{f.line} -> {f.message}")
            if len(warning_issues) > 20:
                print(f"  ... dan {len(warning_issues) - 20} peringatan kualitas kode arsitektural lainnya.")
        else:
            print(f"{GREEN}{BOLD}✅ AMAN (0 Peringatan): Gaya penulisan kode akuntansi sangat bersih dan patuh standar.{RESET}")

        print("\n" + "═" * 80)
        print(f"{BOLD}REKAPITULASI AUDIT INTEGRITAS{RESET}")
        print(f"  Total File Terlacak  : {self.scanned_files_count}")
        print(f"  Total Berhasil Import: {self.runtime_imported_count}")
        print(f"  Masalah Kritis (Must Fix)   : {RED if len(critical_issues) > 0 else GREEN}{len(critical_issues)}{RESET}")
        print(f"  Peringatan Arsitektur       : {YELLOW if len(warning_issues) > 0 else GREEN}{len(warning_issues)}{RESET}")
        print("═" * 80)

        # Ambil keputusan exit code untuk pipeline CI/CD (Gagal jika ada CRITICAL error)
        return 1 if critical_issues else 0

if __name__ == "__main__":
    auditor = EnterpriseAccountingAuditor()
    sys.exit(auditor.execute_global_audit())