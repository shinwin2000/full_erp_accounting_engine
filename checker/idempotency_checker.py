#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker/idempotency_checker.py
==============================
Static checker untuk implementasi idempotensi di seluruh proyek.

Memeriksa:
1. Penggunaan Idempotency-Key (header/parameter/dekorator)
2. Penyimpanan hasil operasi (cache/DB) berdasarkan key
3. Validasi duplikasi (key existence check) sebelum eksekusi
4. Response konsisten untuk operasi duplikat
5. Operasi write yang tidak memiliki idempotensi

Dilengkapi dengan filter untuk mengurangi false positive:
- Fungsi helper/internal (normalize_, is_valid_, generate_*_from_parts, dll.)
- Value object methods (__post_init__, create, update, dll.)
- Fungsi yang tidak melakukan side effect.
- Fungsi factory/middleware/startup (create_app, create_server, dispatch, dll.)
- Private helper functions (dimulai dengan _)

Integrasi dengan RCA engine untuk pelaporan otomatis.

Usage:
    python -m checker.idempotency_checker --verbose
    python -m checker.idempotency_checker --json report.json
    python -m checker.idempotency_checker --skip-runtime
"""

from __future__ import annotations

import argparse
import ast
import importlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# ---- Project root ----
_THIS_FILE = Path(__file__).resolve()
ROOT = _THIS_FILE.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---- Color support ----
def _supports_ansi() -> bool:
    if not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
                return True
        except Exception:
            return False
    return True

_USE_COLOR = _supports_ansi()
COLOR = {
    "RED": "\033[91m" if _USE_COLOR else "",
    "GREEN": "\033[92m" if _USE_COLOR else "",
    "YELLOW": "\033[93m" if _USE_COLOR else "",
    "CYAN": "\033[96m" if _USE_COLOR else "",
    "BOLD": "\033[1m" if _USE_COLOR else "",
    "RESET": "\033[0m" if _USE_COLOR else "",
}

# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class Finding:
    file: str
    line: int
    severity: str        # ERROR / WARNING / INFO
    category: str        # key / storage / validation / response / missing
    message: str
    detail: str = ""
    suggested_fix: str = ""

@dataclass
class RuntimeError:
    module: str
    error_type: str
    error_msg: str

@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    runtime_errors: List[RuntimeError] = field(default_factory=list)
    score: int = 100
    total_files_scanned: int = 0

# ============================================================================
# CONFIGURATION
# ============================================================================

DEFAULT_TARGET_DIRS = [
    "adapters/primary_api",
    "application/use_cases",
    "application/commands_cqrs",
    "infrastructure/caching",
    "domain/shared_value_objects",
]

EXCLUDE_PATTERNS = {
    ".venv", "venv", "__pycache__", ".git", "node_modules",
    "dist", "build", "migrations", "deployment", "docs", "tests",
    "checker", "constitution", "compliance", "kernel", "foundation"
}

IDEMPOTENCY_KEYWORDS = {
    "idempotency", "idempotent", "idempotency_key", "idempotency-key",
    "Idempotency-Key", "x-idempotency-key"
}

STORAGE_KEYWORDS = {"cache", "redis", "store", "save", "set", "put", "persist", "add"}

WRITE_KEYWORDS = {"post", "create", "update", "delete", "save", "persist", "submit", "patch"}

# ---- FILTER: fungsi yang TIDAK perlu idempotensi ----
# Pola nama fungsi yang dikecualikan dari pemeriksaan "missing idempotency"
EXEMPT_FUNCTION_PATTERNS = {
    "__post_init__", "__init__", "__new__", "__repr__", "__str__", "__eq__",
    "normalize", "is_valid", "validate", "generate", "compute", "calculate",
    "format", "parse", "serialize", "deserialize", "to_dict", "from_dict",
    "to_json", "from_json", "copy", "clone", "snapshot", "audit_trail", "touch",
    "get_version", "get_id", "get_key", "get_value", "get_metadata",
    "create_root", "create_child", "create_sub", "create_from",
    "update_address", "update_contact", "update_metadata",
    "set_", "add_", "remove_", "clear_", "reset_",
    # Tambahan untuk factory, middleware, startup
    "create_app", "create_server", "create_middleware", "create_interceptor",
    "create_grpc_server", "create_http_server", "create_fastapi_app",
    "dispatch", "run", "start", "stop", "shutdown", "init", "setup", "configure",
    "create_access_token", "create_refresh_token", "create_token_pair",
    "create_rate_limit_middleware", "create_request_id_middleware",
    "create_auth_middleware", "create_audit_middleware",
    # Helper functions (private/internal)
    "_get_", "_handle_", "_create_", "_update_", "_save_", "_post_",
}
# Fungsi yang namanya mengandung kata-kata ini akan diabaikan
EXEMPT_NAME_SUBSTRINGS = {
    "helper", "internal", "private", "utility", "util", "base",
    "factory", "builder", "parser", "validator", "normalizer",
    "middleware", "interceptor", "server", "app", "service",
}

# Fungsi yang termasuk VO internal (tidak perlu idempotensi)
VO_CLASS_NAMES = {
    "cost_center", "department", "date_range", "document_number",
    "exchange_rate", "fiscal_year", "hash_chain_link", "idempotency_key",
    "signature", "tax_rate", "warehouse", "money", "percentage", "quantity",
    "accounting_period", "address", "contact", "bank_account", "cash_book",
}

# ============================================================================
# STATIC ANALYZERS
# ============================================================================

class IdempotencyAnalyzer:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.findings: List[Finding] = []
        self._definitions: Set[str] = set()
        self._idempotent_functions: Set[str] = set()
        self._class_names: Set[str] = set()

    def analyze(self) -> List[Finding]:
        try:
            src = self.file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(self.file_path))
        except SyntaxError as e:
            self.findings.append(Finding(
                file=str(self.file_path),
                line=e.lineno or 0,
                severity="ERROR",
                category="syntax",
                message=f"Syntax error: {e.msg}",
                detail=str(e),
                suggested_fix="Perbaiki sintaks file."
            ))
            return self.findings
        except Exception as e:
            self.findings.append(Finding(
                file=str(self.file_path),
                line=0,
                severity="ERROR",
                category="io",
                message=f"Tidak dapat membaca file: {e}",
                suggested_fix="Periksa izin file atau encoding."
            ))
            return self.findings

        # Kumpulkan semua definisi kelas dan fungsi
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                self._class_names.add(node.name)
                self._class_names.add(node.name.lower())
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self._definitions.add(node.name)

        # Analisis fungsi
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._analyze_function(node)

        return self.findings

    def _is_exempt_function(self, func_name: str, class_name: str | None = None) -> bool:
        """Cek apakah fungsi harus dikecualikan dari pemeriksaan idempotensi."""
        lower = func_name.lower()

        # 1. Cek pola nama fungsi yang jelas tidak memerlukan idempotensi
        if lower in EXEMPT_FUNCTION_PATTERNS:
            return True
        if any(lower.startswith(p) for p in EXEMPT_FUNCTION_PATTERNS):
            return True
        if any(lower.endswith(p) for p in EXEMPT_FUNCTION_PATTERNS):
            return True
        if any(p in lower for p in EXEMPT_NAME_SUBSTRINGS):
            return True

        # 2. Jika fungsi berada di dalam kelas VO (value object), abaikan
        if class_name and class_name.lower() in VO_CLASS_NAMES:
            return True

        # 3. Fungsi dengan pola 'create_' di VO biasanya juga tidak perlu
        if lower.startswith("create_") and class_name and class_name.lower() in VO_CLASS_NAMES:
            return True
        if lower.startswith("update_") and class_name and class_name.lower() in VO_CLASS_NAMES:
            return True

        # 4. Fungsi yang namanya diawali underscore (private) dan bukan idempotent utama
        if lower.startswith("_") and not any(kw in lower for kw in IDEMPOTENCY_KEYWORDS):
            return True

        return False

    def _analyze_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        func_name = node.name
        is_idempotent = False

        # Cari nama kelas terdekat (jika ada)
        class_name = None
        parent = node
        while hasattr(parent, 'parent'):
            if isinstance(parent, ast.ClassDef):
                class_name = parent.name
                break
            parent = getattr(parent, 'parent', None)

        # Cek dekorator @idempotent atau @idempotency
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Name):
                if decorator.id.lower() in IDEMPOTENCY_KEYWORDS:
                    is_idempotent = True
                    self._idempotent_functions.add(func_name)
            elif isinstance(decorator, ast.Call):
                if isinstance(decorator.func, ast.Name):
                    if decorator.func.id.lower() in IDEMPOTENCY_KEYWORDS:
                        is_idempotent = True
                        self._idempotent_functions.add(func_name)

        # Cek nama fungsi
        if func_name.lower() in IDEMPOTENCY_KEYWORDS:
            is_idempotent = True
            self._idempotent_functions.add(func_name)
        elif any(kw in func_name.lower() for kw in IDEMPOTENCY_KEYWORDS):
            is_idempotent = True
            self._idempotent_functions.add(func_name)

        # Jika fungsi tidak idempotent, cek apakah harus dianggap write operation
        if not is_idempotent:
            # Cek apakah ini operasi write (create/update/delete/submit/post)
            is_write = any(kw in func_name.lower() for kw in WRITE_KEYWORDS)

            # Jika bukan write, lewati
            if not is_write:
                return

            # Jika fungsi exempt (helper, VO internal, factory, middleware, dll.), lewati
            if self._is_exempt_function(func_name, class_name):
                return

            # Cek apakah ada parameter idempotency_key
            has_key_param = False
            for arg in node.args.args:
                if any(kw in arg.arg.lower() for kw in IDEMPOTENCY_KEYWORDS):
                    has_key_param = True
                    break
            if not has_key_param and not self._has_idempotency_header(node):
                self.findings.append(Finding(
                    file=str(self.file_path),
                    line=node.lineno,
                    severity="WARNING",
                    category="missing",
                    message=f"Fungsi write '{func_name}' tidak memiliki idempotensi",
                    detail="Operasi write (POST, PUT, PATCH, DELETE) sebaiknya memiliki idempotensi.",
                    suggested_fix="Tambahkan parameter idempotency_key atau gunakan dekorator @idempotent."
                ))
            return

        # --- Fungsi idempotent: periksa detail ---
        # (Hanya untuk fungsi yang benar-benar idempotent, dan bukan helper)

        # Jika fungsi exempt, lewati pemeriksaan detail (tidak perlu key, storage, validation)
        if self._is_exempt_function(func_name, class_name):
            return

        # 1. Cek parameter idempotency key
        has_key_param = False
        for arg in node.args.args:
            if any(kw in arg.arg.lower() for kw in IDEMPOTENCY_KEYWORDS):
                has_key_param = True
                break
        if not has_key_param and not self._has_idempotency_header(node):
            self.findings.append(Finding(
                file=str(self.file_path),
                line=node.lineno,
                severity="ERROR",
                category="key",
                message=f"Fungsi idempotent '{func_name}' tidak memiliki parameter idempotency key",
                detail="Idempotency key diperlukan untuk mengidentifikasi operasi unik.",
                suggested_fix="Tambahkan parameter 'idempotency_key: str' atau ambil dari header."
            ))

        # 2. Cek storage (cache/DB)
        has_storage = self._has_storage_operation(node)
        if not has_storage:
            self.findings.append(Finding(
                file=str(self.file_path),
                line=node.lineno,
                severity="WARNING",
                category="storage",
                message=f"Fungsi idempotent '{func_name}' tidak menyimpan hasil operasi",
                detail="Hasil operasi harus disimpan di cache/DB berdasarkan idempotency key.",
                suggested_fix="Simpan hasil operasi dengan key = idempotency_key."
            ))

        # 3. Cek validasi (key existence check)
        has_validation = self._has_key_check(node)
        if not has_validation:
            self.findings.append(Finding(
                file=str(self.file_path),
                line=node.lineno,
                severity="ERROR",
                category="validation",
                message=f"Fungsi idempotent '{func_name}' tidak memeriksa apakah key sudah ada",
                detail="Harus memeriksa apakah idempotency_key sudah ada di storage sebelum eksekusi.",
                suggested_fix="Tambahkan pengecekan: if key_exists(idempotency_key): return cached_result"
            ))

        # 4. Cek response consistency (multiple returns)
        returns = [stmt for stmt in ast.walk(node) if isinstance(stmt, ast.Return)]
        if len(returns) >= 2:
            self.findings.append(Finding(
                file=str(self.file_path),
                line=node.lineno,
                severity="INFO",
                category="response",
                message=f"Fungsi idempotent '{func_name}' memiliki multiple returns",
                detail="Multiple returns mungkin digunakan untuk menangani duplicate request.",
                suggested_fix="Pastikan response untuk key existing dan new operation konsisten."
            ))

    def _has_idempotency_header(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """Cek apakah fungsi mengambil idempotency key dari header (misal: request.headers.get)"""
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        if 'idempotency' in target.id.lower():
                            return True
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                if isinstance(stmt.value.func, ast.Attribute):
                    attr = stmt.value.func.attr.lower()
                    if 'get' in attr or 'header' in attr:
                        for arg in stmt.value.args:
                            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                                if 'idempotency' in arg.value.lower():
                                    return True
        return False

    def _has_storage_operation(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """Cek apakah ada operasi penyimpanan (cache.set, redis.set, db.save, dll.)"""
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                if isinstance(stmt.value.func, ast.Attribute):
                    attr = stmt.value.func.attr.lower()
                    if any(kw in attr for kw in STORAGE_KEYWORDS):
                        return True
                elif isinstance(stmt.value.func, ast.Name):
                    fn = stmt.value.func.id.lower()
                    if any(kw in fn for kw in STORAGE_KEYWORDS):
                        return True
            elif isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        if any(kw in target.id.lower() for kw in STORAGE_KEYWORDS):
                            return True
        return False

    def _has_key_check(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """Cek apakah ada pengecekan keberadaan key (exists, has, get, dll.)"""
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.If):
                cond = ast.unparse(stmt.test).lower()
                if any(kw in cond for kw in ['exists', 'has', 'already', 'get', 'contains']):
                    return True
            elif isinstance(stmt, ast.Assert):
                cond = ast.unparse(stmt.test).lower()
                if any(kw in cond for kw in ['exists', 'has', 'already']):
                    return True
            elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                if isinstance(stmt.value.func, ast.Name):
                    if any(kw in stmt.value.func.id.lower() for kw in ['exists', 'has', 'get']):
                        return True
                elif isinstance(stmt.value.func, ast.Attribute):
                    if any(kw in stmt.value.func.attr.lower() for kw in ['exists', 'has', 'get']):
                        return True
        return False


# ============================================================================
# PROJECT SCANNER
# ============================================================================

def scan_project(
    target_dirs: List[str] | None = None,
    skip_runtime: bool = True,
    exclude_patterns: Set[str] | None = None
) -> Report:
    if target_dirs is None:
        target_dirs = DEFAULT_TARGET_DIRS
    if exclude_patterns is None:
        exclude_patterns = EXCLUDE_PATTERNS

    report = Report()
    found_files = 0

    for rel_dir in target_dirs:
        dir_path = ROOT / rel_dir
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if py_file.name.startswith("__"):
                continue
            if any(part in exclude_patterns for part in py_file.parts):
                continue
            if py_file.name == "idempotency_checker.py":
                continue
            found_files += 1
            analyzer = IdempotencyAnalyzer(py_file)
            findings = analyzer.analyze()
            report.findings.extend(findings)

    report.total_files_scanned = found_files

    # Runtime import check (opsional, default skip)
    if not skip_runtime:
        for dir_path in target_dirs:
            dir_path_obj = ROOT / dir_path
            if not dir_path_obj.exists():
                continue
            for py_file in dir_path_obj.rglob("*.py"):
                if py_file.name.startswith("__"):
                    continue
                if any(part in exclude_patterns for part in py_file.parts):
                    continue
                rel = py_file.relative_to(ROOT)
                module = str(rel.with_suffix("")).replace("/", ".")
                try:
                    importlib.import_module(module)
                except Exception as e:
                    report.runtime_errors.append(RuntimeError(
                        module=module,
                        error_type=type(e).__name__,
                        error_msg=str(e)[:100]
                    ))

    # Calculate score (lebih realistis)
    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")
    runtime_err_count = len(report.runtime_errors)
    # Penalti: error -10, warning -1, runtime -0 (default skip)
    report.score = max(0, 100 - errors * 10 - warnings * 1 - runtime_err_count * 0)

    return report


# ============================================================================
# RCA INTEGRATION
# ============================================================================

def integrate_with_rca(engine=None):
    try:
        from checker.core.rca import get_engine, RCARule, Severity, ErrorCode, Category, RCAResult
    except ImportError:
        print("⚠️ RCA engine tidak ditemukan, integrasi dilewati")
        return None

    class StaticIdempotencyRule(RCARule):
        def __init__(self):
            super().__init__(priority=192, category=Category.DDD, name="StaticIdempotencyRule")
            self._checker = scan_project

        def match(self, exc, frames, context) -> bool:
            return "Idempotency" in type(exc).__name__ or "idempotent" in str(exc).lower()

        def analyze(self, exc, frames, context) -> Optional[RCAResult]:
            report = scan_project()
            if report.findings:
                errors = [f for f in report.findings if f.severity == "ERROR"]
                if errors:
                    error_msgs = [f"{e.file}:{e.line} - {e.message}" for e in errors[:3]]
                    return RCAResult(
                        severity=Severity.HIGH,
                        category=Category.DDD,
                        error_code=ErrorCode.ERP_VALIDATION,
                        root_cause="Implementasi idempotensi tidak lengkap: " + "; ".join(error_msgs),
                        evidence=[f"Total {len(errors)} error idempotensi ditemukan."],
                        impact=["Risiko duplikasi data dan inkonsistensi."],
                        suggested_fix="Periksa temuan dan tambahkan idempotensi yang hilang.",
                        raw_error=str(exc),
                        confidence=0.85
                    )
            return None

    if engine is None:
        engine = get_engine()
    engine.register_rule(StaticIdempotencyRule())
    return engine


# ============================================================================
# REPORTING
# ============================================================================

def print_report(report: Report, verbose: bool = False):
    c = COLOR
    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")
    infos = sum(1 for f in report.findings if f.severity == "INFO")
    runtime_err = len(report.runtime_errors)

    print(f"\n{c['BOLD']}{c['CYAN']}╔{'═'*72}╗")
    print("║         IDEMPOTENCY CHECKER — v2.4                   ║")
    print(f"╚{'═'*72}╝{c['RESET']}")

    print(f"\n  📁 Files Scanned: {report.total_files_scanned}")
    print(f"  📄 Total Findings: {len(report.findings)}")
    print(f"  ✅ Errors: {c['RED']}{errors}{c['RESET']}")
    print(f"  ⚠️  Warnings: {c['YELLOW']}{warnings}{c['RESET']}")
    print(f"  ℹ️  Info: {c['CYAN']}{infos}{c['RESET']}")
    if runtime_err:
        print(f"  🚨 Runtime Errors: {c['RED']}{runtime_err}{c['RESET']}")
    print(f"  🏆 Score: {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    if report.findings:
        # Group by category
        categories = {}
        for f in report.findings:
            categories.setdefault(f.category, []).append(f)

        print(f"\n{c['CYAN']}📊 By Category:{c['RESET']}")
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

        print(f"\n{c['BOLD']}{'─'*72}{c['RESET']}")
        print(f"{'Severity':10} {'Category':12} {'File:Line'}")
        print(f"{'─'*72}")

        # Tampilkan errors dulu, lalu warnings (info hanya jika verbose)
        displayed = 0
        for f in sorted(report.findings, key=lambda x: (x.severity != "ERROR", x.severity != "WARNING")):
            if f.severity == "INFO" and not verbose:
                continue
            if displayed >= 30 and f.severity != "ERROR":
                continue
            color = c["RED"] if f.severity == "ERROR" else c["YELLOW"] if f.severity == "WARNING" else c["CYAN"]
            print(f"{color}{f.severity:10}{c['RESET']} {f.category:12} {Path(f.file).name}:{f.line}")
            print(f"     {f.message}")
            if verbose and f.detail:
                print(f"     {c['CYAN']}→ {f.detail}{c['RESET']}")
            if verbose and f.suggested_fix:
                print(f"     {c['GREEN']}💡 {f.suggested_fix}{c['RESET']}")
            displayed += 1
        if len(report.findings) > displayed:
            print(f"  ... and {len(report.findings)-displayed} more findings")

    if report.runtime_errors:
        print(f"\n{c['RED']}🚨 Runtime Errors:{c['RESET']}")
        for err in report.runtime_errors[:5]:
            print(f"  {err.module}: {err.error_type} - {err.error_msg}")
        if len(report.runtime_errors) > 5:
            print(f"  ... and {len(report.runtime_errors)-5} more")

    print(f"\n{c['CYAN']}{'═'*72}{c['RESET']}")


def save_json(report: Report, filepath: str):
    data = {
        "summary": {
            "files_scanned": report.total_files_scanned,
            "total_findings": len(report.findings),
            "errors": sum(1 for f in report.findings if f.severity == "ERROR"),
            "warnings": sum(1 for f in report.findings if f.severity == "WARNING"),
            "infos": sum(1 for f in report.findings if f.severity == "INFO"),
            "runtime_errors": len(report.runtime_errors),
            "score": report.score,
        },
        "findings": [
            {
                "file": f.file,
                "line": f.line,
                "severity": f.severity,
                "category": f.category,
                "message": f.message,
                "detail": f.detail,
                "suggested_fix": f.suggested_fix,
            }
            for f in report.findings
        ],
        "runtime_errors": [
            {"module": e.module, "type": e.error_type, "message": e.error_msg}
            for e in report.runtime_errors
        ],
    }
    Path(filepath).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{c['CYAN']}✅ JSON exported to {filepath}{c['RESET']}")


# ============================================================================
# MAIN CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Idempotency Implementation Checker")
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    parser.add_argument("--skip-runtime", action="store_true", default=True, help="Lewati runtime import check (default: True)")
    parser.add_argument("--no-skip-runtime", action="store_false", dest="skip_runtime", help="Jalankan runtime import check")
    parser.add_argument("--dirs", nargs="+", help="Direktori target (default: adapters primary_api, use_cases, commands_cqrs, caching, shared_value_objects)")
    args = parser.parse_args()

    target_dirs = args.dirs if args.dirs else DEFAULT_TARGET_DIRS
    report = scan_project(target_dirs=target_dirs, skip_runtime=args.skip_runtime)

    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)

    # Exit code berdasarkan errors (runtime errors diabaikan jika skip)
    exit_errors = sum(1 for f in report.findings if f.severity == "ERROR")
    sys.exit(0 if exit_errors == 0 else 1)


if __name__ == "__main__":
    main()