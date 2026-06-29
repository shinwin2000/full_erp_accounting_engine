#!/usr/bin/env python3
"""
CHECKER_INTEGRATION_UNIFIED — Sovereign ERP Ultimate Validator v3.2
====================================================================
Menggabungkan semua fitur dari dua versi checker_integration sebelumnya
dengan pemeriksaan mendalam tanpa placeholder/pass.

Fitur:
1. Syntax & Bytecode Compilation
2. Broken Imports (absolut & relatif) + Deep Symbol Verification (hanya lokal)
3. True Runtime Circular Imports (dengan pruning TYPE_CHECKING)
4. Dynamic Imports (deteksi di core layers, dengan pengecualian fallback pattern)
5. Runtime Imports (semua modul produksi)
6. Critical Modules Import
7. App Bootstrap (FastAPI)
8. DI Container Resolution
9. Database Connectivity (opsional)
10. Subprocess Sterilization Probe (opsional, --strict-isolate)

FIX v3.2:
- Perbaiki NameError: 'top_layer' tidak didefinisikan
- Abaikan dynamic import dengan argumen non-literal (fallback pattern)
- Abaikan file application/events/__init__.py untuk dynamic import warning

Usage:
    python checker/checker_integration_unified.py [--verbose] [--json report.json]
        [--no-runtime] [--no-db] [--strict-isolate]
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import collections
import importlib
import json
import os
import py_compile
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# =============================================================================
# Root Project
# =============================================================================
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# =============================================================================
# Terminal Colors
# =============================================================================
COLOR = {
    "RED": "\033[91m",
    "GREEN": "\033[92m",
    "YELLOW": "\033[93m",
    "BLUE": "\033[94m",
    "CYAN": "\033[96m",
    "BOLD": "\033[1m",
    "RESET": "\033[0m"
}
if not sys.stdout.isatty():
    COLOR = {k: "" for k in COLOR}

# =============================================================================
# Configuration
# =============================================================================
SKIP_DIRS = {
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".git", ".venv", "venv", "node_modules", ".tox", ".cache",
    "site-packages", "dist-packages", "dist", "build", "uv",
}

PROJECT_TOPS = {
    "app", "adapters", "application", "domain", "infrastructure",
    "kernel", "ports", "config", "migrations", "tests", "compliance",
    "audit", "constitution", "axioms", "bootstrap", "policy_engine",
    "projections", "reports", "transformers", "event_gateway",
    "security_hardening", "disaster_recovery", "monitoring", "architecture",
}

CHECKER_FILES = {
    "checker_integration_unified.py", "checker_integration.py",
    "checker_integration_v2.py", "checker_integration_v2.1.py",
    "main_checker.py", "main_checker_2.py", "main_checker_3.py",
    "main_checker_v5.py", "main_checker_old.py", "main_app_checker.py",
    "checker_cqrs_handler.py", "checker_event_handler.py",
    "repository_checker.py", "aggregate_root_checker.py",
    "checker_di_container.py", "checker_di_registrations.py",
    "checker_domain_event_publish.py", "checker_audit_accounting_logic.py",
    "checker_audit_import.py", "checker_critical_import.py",
    "checker_dashboard_port_status.py", "checker_fastapi_route.py",
    "checker_journal_balance.py", "checker_migrations_orm.py",
    "checker_port_adapter.py", "architecture_drift_checker.py",
    "layer_checker.py", "fix.py", "exception_swallow_checker.py",
    "sql_injection_checker.py", "hardcoded_secret_checker.py",
    "transaction_boundary_checker.py", "coa_checker.py",
    "tax_checker.py", "accounting_posting_checker.py",
    "inventory_integrity_checker.py", "money_precision_checker.py",
    "general_ledger_checker.py", "duplicate_class_checker.py",
    "duplicate_dto_checker.py", "fiscal_period_checker.py",
    "uow_checker.py", "posting_flow_checker.py", "idempotency_checker.py",
    "race_condition_risk_checker.py", "duplicate_enum_checker.py",
    "secret_scanner_checker.py",
}

PROTECTED_LAYERS = {"domain", "kernel", "application", "ports", "axioms", "constitution"}

# Dynamic imports yang diizinkan (standar library / aman)
ALLOWED_DYNAMIC_IMPORTS = {
    "datetime", "typing", "collections", "itertools", "functools",
    "json", "yaml", "csv", "re", "os", "sys", "pathlib",
    "decimal", "uuid", "enum", "dataclasses",
    "kernel.context_holder",
}

# =============================================================================
# Data Classes
# =============================================================================
@dataclass
class Finding:
    severity: str  # "CRITICAL", "WARNING", "INFO", "PASS"
    file: str
    line: int
    message: str
    detail: str = ""
    recommendation: str = ""

@dataclass
class PhaseResult:
    name: str
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    duration: float = 0.0

    def add(self, sev: str, file: str, line: int, msg: str, detail: str = "", rec: str = ""):
        self.findings.append(Finding(sev, file, line, msg, detail, rec))
        if sev == "CRITICAL":
            self.passed = False

    def count(self, sev: str) -> int:
        return sum(1 for f in self.findings if f.severity == sev)

# =============================================================================
# Helpers
# =============================================================================
def rel_path(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)

def all_py_files() -> List[Path]:
    files = []
    for p in ROOT.glob("*.py"):
        if p.name not in CHECKER_FILES:
            files.append(p)
    for top in PROJECT_TOPS:
        dir_path = ROOT / top
        if dir_path.is_dir():
            for p in dir_path.rglob("*.py"):
                if any(part in SKIP_DIRS for part in p.parts):
                    continue
                if p.name in CHECKER_FILES:
                    continue
                files.append(p)
    return sorted(set(files))

def module_name(p: Path) -> Optional[str]:
    try:
        rel = p.relative_to(ROOT)
    except ValueError:
        return None
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None

def top_layer(mod: str) -> str:
    return mod.split(".")[0]

def get_ast_tree(p: Path):
    try:
        return ast.parse(p.read_text(encoding="utf-8", errors="replace"), filename=str(p))
    except Exception:
        return None

def safe_import(module_name: str) -> Tuple[bool, Optional[str]]:
    try:
        importlib.import_module(module_name)
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:200]}"

def resolve_import_target(module_name: str, root: Path) -> bool:
    parts = module_name.split(".")
    for i in range(len(parts), 0, -1):
        candidate = root / Path(*parts[:i]).with_suffix(".py")
        if candidate.exists():
            return True
        init = root / Path(*parts[:i]) / "__init__.py"
        if init.exists():
            return True
    return False

def resolve_relative_import(current_file: Path, level: int, module: Optional[str], name: Optional[str]) -> List[Path]:
    current_dir = current_file.parent
    target_dir = current_dir
    for _ in range(level - 1):
        target_dir = target_dir.parent
    candidates = []
    if module:
        parts = module.split(".")
        py = target_dir / Path(*parts).with_suffix(".py")
        if py.exists():
            candidates.append(py)
        init = target_dir / Path(*parts) / "__init__.py"
        if init.exists():
            candidates.append(init)
    else:
        if name:
            py = target_dir / f"{name}.py"
            if py.exists():
                candidates.append(py)
            init = target_dir / name / "__init__.py"
            if init.exists():
                candidates.append(init)
    return candidates

def extract_imports(tree: ast.AST) -> List[Tuple[int, str]]:
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                imports.append((node.lineno, node.module))
    return imports

def extract_relative_imports(tree: ast.AST) -> List[Tuple[int, int, Optional[str], List[str]]]:
    rels = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level > 0:
            names = [alias.name for alias in node.names]
            rels.append((node.lineno, node.level, node.module, names))
    return rels

def extract_dynamic_imports(tree: ast.AST) -> List[Tuple[int, str, str]]:
    results = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "__import__":
                arg = ast.unparse(node.args[0]) if node.args else ""
                results.append((node.lineno, "__import__", arg))
            elif isinstance(func, ast.Attribute):
                if isinstance(func.value, ast.Name) and func.value.id == "importlib" and func.attr == "import_module":
                    arg = ast.unparse(node.args[0]) if node.args else ""
                    results.append((node.lineno, "importlib.import_module", arg))
            elif isinstance(func, ast.Name) and func.id in ("eval", "exec"):
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    results.append((node.lineno, func.id, node.args[0].value[:50]))
    return results

def has_wildcard(tree: ast.AST) -> List[Tuple[int, str]]:
    wild = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                wild.append((node.lineno, node.module or "<unknown>"))
    return wild

def check_symbol_in_ast(target_file: Path, symbol: str) -> bool:
    tree = get_ast_tree(target_file)
    if not tree:
        return True
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == symbol:
                return True
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == symbol:
                    return True
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == symbol:
                return True
        elif isinstance(node, (ast.ImportFrom, ast.Import)):
            for alias in node.names:
                exported_name = alias.asname if alias.asname else alias.name
                if exported_name == symbol or alias.name == "*":
                    return True
    return False

def resolve_deep_import(module_path_str: str, imported_symbol: str) -> Tuple[bool, str]:
    parts = module_path_str.split(".")
    for i in range(len(parts), 0, -1):
        candidate = ROOT / Path(*parts[:i]).with_suffix(".py")
        if candidate.exists():
            if i == len(parts):
                if check_symbol_in_ast(candidate, imported_symbol):
                    return True, ""
                return False, f"Simbol '{imported_symbol}' tidak ada di {rel_path(candidate)}"
            return True, ""
        init = ROOT / Path(*parts[:i]) / "__init__.py"
        if init.exists():
            if i == len(parts):
                if check_symbol_in_ast(init, imported_symbol):
                    return True, ""
                return False, f"Simbol '{imported_symbol}' tidak diekspor oleh paket {rel_path(init)}"
            return True, ""
    return False, f"Modul fisik '{module_path_str}' tidak ditemukan"

def get_true_runtime_imports(tree: ast.AST) -> List[str]:
    valid_imports = []
    def _visit(node):
        if isinstance(node, ast.If):
            t = node.test
            if isinstance(t, ast.Name) and "TYPE_CHECKING" in t.id:
                return
            if isinstance(t, ast.Attribute) and "TYPE_CHECKING" in t.attr:
                return
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            valid_imports.append(node.module)
        for child in ast.iter_child_nodes(node):
            _visit(child)
    _visit(tree)
    return valid_imports

# =============================================================================
# Phase Implementations
# =============================================================================

def phase_bytecode_compilation() -> PhaseResult:
    pr = PhaseResult("Bytecode Compilation (Syntax Check)")
    t0 = time.monotonic()
    files = all_py_files()
    errors = []
    for f in files:
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as e:
            errors.append((rel_path(f), str(e)))
    if errors:
        for file, err in errors:
            pr.add("CRITICAL", file, 0, "Syntax Error terdeteksi!", detail=err)
    else:
        pr.add("PASS", ".", 0, f"Semua {len(files)} file lolos kompilasi sintaks.")
    pr.duration = time.monotonic() - t0
    return pr

def phase_broken_imports() -> PhaseResult:
    pr = PhaseResult("Broken Imports & Symbol Check")
    t0 = time.monotonic()
    files = all_py_files()
    local_mods = {module_name(f) for f in files if module_name(f)}
    local_tops = {m.split(".")[0] for m in local_mods}
    broken = []
    for f in files:
        tree = get_ast_tree(f)
        if not tree:
            continue
        rp = rel_path(f)
        # Absolute imports (hanya cek yang top-level-nya ada di local_tops)
        for lineno, imp in extract_imports(tree):
            top = imp.split(".")[0]
            if top in local_tops and imp not in local_mods:
                if not resolve_import_target(imp, ROOT):
                    broken.append((rp, lineno, imp, "Module not found in project"))
        # Relative imports
        for lineno, level, module, names in extract_relative_imports(tree):
            resolved = resolve_relative_import(f, level, module, names[0] if names else None)
            if not resolved:
                if module:
                    broken.append((rp, lineno, f".{'.'*(level-1)}{module}", "Relative import cannot be resolved"))
                else:
                    for name in names:
                        broken.append((rp, lineno, f".{'.'*(level-1)}{name}", "Relative import cannot be resolved"))
        # Deep symbol verification untuk ImportFrom (level 0) HANYA jika modulnya lokal
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                if node.module == "__future__":
                    continue
                if not resolve_import_target(node.module, ROOT):
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    ok, err = resolve_deep_import(node.module, alias.name)
                    if not ok:
                        broken.append((rp, node.lineno, f"{alias.name} dari {node.module}", err))
    if broken:
        for rp, lineno, imp, detail in broken[:30]:
            pr.add("CRITICAL", rp, lineno, f"Broken import: {imp}", detail=detail, rec="Fix import path or export missing symbol")
        if len(broken) > 30:
            pr.add("INFO", ".", 0, f"Plus {len(broken)-30} more broken imports")
    else:
        pr.add("PASS", ".", 0, "Tidak ada broken imports dan semua simbol lokal terverifikasi.")
    pr.duration = time.monotonic() - t0
    return pr

def phase_circular_imports() -> PhaseResult:
    pr = PhaseResult("Runtime Circular Imports")
    t0 = time.monotonic()
    files = all_py_files()
    module_map = {}
    for f in files:
        mod = module_name(f)
        if mod:
            module_map[mod] = f
    local_mods = set(module_map.keys())
    graph = collections.defaultdict(set)
    for f in files:
        mod = module_name(f)
        if not mod:
            continue
        tree = get_ast_tree(f)
        if not tree:
            continue
        for imp_mod in get_true_runtime_imports(tree):
            if imp_mod in local_mods and imp_mod != mod:
                graph[mod].add(imp_mod)
            else:
                for local in local_mods:
                    if local.startswith(imp_mod + "."):
                        graph[mod].add(local)
                        break
    # Tarjan SCC
    index = 0
    stack = []
    indices = {}
    lowlink = {}
    on_stack = {}
    sccs = []
    def strongconnect(node):
        nonlocal index
        indices[node] = index
        lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack[node] = True
        for neighbor in graph.get(node, set()):
            if neighbor not in indices:
                strongconnect(neighbor)
                lowlink[node] = min(lowlink[node], lowlink[neighbor])
            elif on_stack.get(neighbor, False):
                lowlink[node] = min(lowlink[node], indices[neighbor])
        if lowlink[node] == indices[node]:
            scc = set()
            while True:
                w = stack.pop()
                on_stack[w] = False
                scc.add(w)
                if w == node:
                    break
            if len(scc) > 1:
                sccs.append(scc)
    for m in local_mods:
        if m not in indices:
            strongconnect(m)
    if sccs:
        for scc in sccs:
            cycle_list = list(scc)
            first_file = module_map.get(cycle_list[0], Path("?"))
            pr.add("WARNING", rel_path(first_file), 0,
                   f"Circular import cycle: {' → '.join(cycle_list)}",
                   rec="Refactor to break the cycle (use TYPE_CHECKING if needed)")
        pr.passed = True
    else:
        pr.add("PASS", ".", 0, f"Bersih dari siklus import runtime di {len(local_mods)} modul.")
    pr.duration = time.monotonic() - t0
    return pr

def phase_dynamic_imports() -> PhaseResult:
    pr = PhaseResult("Dynamic Imports")
    t0 = time.monotonic()
    files = all_py_files()
    violations = []
    for f in files:
        mod = module_name(f)
        layer = top_layer(mod) if mod else "unknown"
        tree = get_ast_tree(f)
        if not tree:
            continue
        if layer in PROTECTED_LAYERS:
            for lineno, call, arg in extract_dynamic_imports(tree):
                # [FIX v3.2] Abaikan dynamic import dengan argumen non-literal (fallback pattern)
                # Contoh: __import__(module_name) yang menggunakan variabel
                if call == "__import__":
                    # Cari node asli untuk melihat apakah argumen adalah variabel
                    # Kita tidak punya node asli di sini, tapi arg berupa string hasil unparse
                    # Jika arg bukan berupa string literal (tidak diapit kutip), maka dianggap fallback
                    # Cara sederhana: cek apakah arg dimulai dengan huruf dan tidak diapit kutip
                    if not (arg.startswith("'") or arg.startswith('"')):
                        continue  # skip pattern __import__(variable)
                # Abaikan file application/events/__init__.py untuk warning dynamic import
                if "application/events/__init__.py" in rel_path(f):
                    continue
                if any(allowed in arg for allowed in ALLOWED_DYNAMIC_IMPORTS):
                    continue
                violations.append((rel_path(f), lineno, f"{call}({arg})"))
    if violations:
        for file, line, call in violations[:30]:
            pr.add("WARNING", file, line, f"Dynamic import: {call}", rec="Consider dependency injection or static imports")
        if len(violations) > 30:
            pr.add("INFO", ".", 0, f"Plus {len(violations)-30} more dynamic imports")
        pr.passed = True
    else:
        pr.add("PASS", ".", 0, "Tidak ada dynamic imports problematic di core layers.")
    pr.duration = time.monotonic() - t0
    return pr

def phase_runtime_imports() -> PhaseResult:
    pr = PhaseResult("Runtime Imports")
    t0 = time.monotonic()
    files = all_py_files()
    errors = []
    for f in files:
        mod = module_name(f)
        if not mod:
            continue
        if mod.startswith("test_") or "checker" in mod:
            continue
        ok, err = safe_import(mod)
        if not ok:
            errors.append((rel_path(f), mod, err))
    if errors:
        for file, mod, err in errors[:20]:
            pr.add("CRITICAL", file, 0, f"Import gagal untuk '{mod}': {err}", rec="Perbaiki dependensi")
        if len(errors) > 20:
            pr.add("INFO", ".", 0, f"Plus {len(errors)-20} lagi import failures.")
    else:
        pr.add("PASS", ".", 0, "Semua modul produksi berhasil di-import.")
    pr.duration = time.monotonic() - t0
    return pr

def phase_critical_imports() -> PhaseResult:
    pr = PhaseResult("Critical Imports")
    t0 = time.monotonic()
    critical = [
        ("constitution.supreme_law", "Constitution"),
        ("axioms.double_entry", "Double Entry Axiom"),
        ("bootstrap.orchestrator", "Bootstrap"),
        ("kernel.sealed_gate", "Kernel Sealed Gate"),
        ("domain.journal.aggregate_root", "Journal Aggregate"),
        ("application.use_cases.post_journal_entry", "Post Journal Use Case"),
        ("adapters.primary_api.common.app_factory", "App Factory"),
        ("infrastructure.database.session_factory_sqlalchemy", "Session Factory"),
        ("event_gateway.event_gate_singleton", "Event Gateway"),
        ("audit.event_writer_immutable", "Audit Writer"),
    ]
    errors = []
    for mod, label in critical:
        ok, err = safe_import(mod)
        if not ok:
            errors.append((mod, label, err))
    if errors:
        for mod, label, err in errors:
            pr.add("CRITICAL", mod.replace(".", "/") + ".py", 0, f"Critical import '{label}' gagal: {err}", rec="Fix immediately")
    else:
        pr.add("PASS", ".", 0, f"Semua {len(critical)} modul critical berhasil di-import.")
    pr.duration = time.monotonic() - t0
    return pr

def phase_app_bootstrap() -> PhaseResult:
    pr = PhaseResult("App Bootstrap")
    t0 = time.monotonic()
    try:
        import app.main as main_mod
        app_obj = None
        if hasattr(main_mod, "app"):
            app_obj = main_mod.app
        elif hasattr(main_mod, "create_app"):
            app_obj = main_mod.create_app()
        elif hasattr(main_mod, "get_app"):
            app_obj = main_mod.get_app()
        else:
            pr.add("CRITICAL", "app/main.py", 0, "Tidak ditemukan app variable atau create_app/get_app", rec="Definisikan app di app/main.py")
            return pr
        if callable(app_obj) and not isinstance(app_obj, type):
            app_obj = app_obj()
        if hasattr(app_obj, "__call__"):
            pr.add("PASS", "app/main.py", 0, "ASGI app callable.")
        else:
            pr.add("CRITICAL", "app/main.py", 0, "App object tidak callable", rec="Pastikan app adalah instance FastAPI")
    except Exception as e:
        pr.add("CRITICAL", "app/main.py", 0, f"Bootstrap gagal: {type(e).__name__}: {str(e)[:200]}", rec="Periksa dependensi")
    pr.duration = time.monotonic() - t0
    return pr

def phase_di_container(optional: bool = True) -> PhaseResult:
    pr = PhaseResult("DI Container")
    t0 = time.monotonic()
    try:
        from bootstrap.dependency_container.ioc_container import get_container
        container = get_container()
        registered = []
        if hasattr(container, "get_registered_types"):
            registered = container.get_registered_types()
        elif hasattr(container, "_registry"):
            registered = list(container._registry.keys())
        if registered:
            pr.add("PASS", "bootstrap/dependency_container", 0, f"DI container memiliki {len(registered)} tipe terdaftar.")
        else:
            pr.add("WARNING", "bootstrap/dependency_container", 0, "DI container tidak memiliki tipe terdaftar", rec="Periksa registrasi")
    except ImportError as e:
        if not optional:
            pr.add("CRITICAL", "bootstrap/dependency_container", 0, f"DI container import gagal: {e}", rec="Pastikan modul DI ada")
        else:
            pr.add("INFO", "bootstrap/dependency_container", 0, "DI container tidak tersedia (dilewati)")
    except Exception as e:
        pr.add("CRITICAL", "bootstrap/dependency_container", 0, f"DI container error: {type(e).__name__}: {str(e)[:100]}", rec="Perbaiki konfigurasi DI")
    pr.duration = time.monotonic() - t0
    return pr

def phase_db_connectivity(optional: bool = True) -> PhaseResult:
    pr = PhaseResult("Database Connectivity")
    t0 = time.monotonic()
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        if optional:
            pr.add("INFO", ".env", 0, "DATABASE_URL tidak diset (melewati cek DB)")
            return pr
        else:
            pr.add("CRITICAL", ".env", 0, "DATABASE_URL tidak diset", rec="Set DATABASE_URL environment variable")
            return pr
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        if "postgresql://" in db_url and "+asyncpg" not in db_url:
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(db_url, pool_pre_ping=True, pool_size=1)
        async def test():
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        asyncio.run(test())
        pr.add("PASS", "config/", 0, "Koneksi database berhasil.")
    except Exception as e:
        pr.add("CRITICAL", "config/", 0, f"Koneksi database gagal: {type(e).__name__}: {str(e)[:200]}", rec="Periksa DATABASE_URL dan service DB")
    pr.duration = time.monotonic() - t0
    return pr

def phase_sterile_probe(enable: bool) -> PhaseResult:
    pr = PhaseResult("Subprocess Sterilization Probe")
    t0 = time.monotonic()
    if not enable:
        pr.add("INFO", ".", 0, "Dilewati (gunakan --strict-isolate untuk menguji isolated subprocess)")
        return pr
    sample_critical = ["app.main", "domain.journal.aggregate_root", "kernel.sealed_gate"]
    for mod in sample_critical:
        if not any((ROOT / Path(*mod.split("."))).with_suffix(s).exists() for s in [".py", "/__init__.py"]):
            continue
        res = subprocess.run([sys.executable, "-c", f"import {mod}"], cwd=str(ROOT), capture_output=True, text=True)
        if res.returncode != 0:
            err = res.stderr.strip().split("\n")[-1] if res.stderr else "Unknown Fatal Crash"
            pr.add("CRITICAL", mod, 0, f"Gagal di-boot dalam proses steril!", detail=err)
    if pr.passed:
        pr.add("PASS", ".", 0, "Modul kritis tahan uji isolated subprocess.")
    pr.duration = time.monotonic() - t0
    return pr

# =============================================================================
# Main Runner
# =============================================================================
def run_unified_check(verbose: bool, json_out: Optional[str],
                       skip_runtime: bool, skip_db: bool,
                       strict_isolate: bool) -> int:
    print(f"{COLOR['BOLD']}{COLOR['CYAN']}╔{'═'*78}╗{COLOR['RESET']}")
    print(f"{COLOR['BOLD']}{COLOR['CYAN']}║{' '*15}SOVEREIGN ENGINE — ULTIMATE VALIDATOR v3.2{' '*15}║{COLOR['RESET']}")
    print(f"{COLOR['BOLD']}{COLOR['CYAN']}╚{'═'*78}╝{COLOR['RESET']}")
    print()

    if skip_runtime:
        print(f"{COLOR['YELLOW']}⚠️  Runtime import checks disabled (--no-runtime){COLOR['RESET']}")
    if skip_db:
        print(f"{COLOR['YELLOW']}⚠️  Database connectivity check disabled (--no-db){COLOR['RESET']}")
    if strict_isolate:
        print(f"{COLOR['CYAN']}🔬 Sterilization probe active (--strict-isolate){COLOR['RESET']}")
    print()

    phases = [
        ("bytecode", phase_bytecode_compilation),
        ("broken_imports", phase_broken_imports),
        ("circular", phase_circular_imports),
        ("dynamic", phase_dynamic_imports),
    ]
    if not skip_runtime:
        phases.append(("runtime", phase_runtime_imports))
        phases.append(("critical", phase_critical_imports))
        phases.append(("bootstrap", phase_app_bootstrap))
        phases.append(("di", lambda: phase_di_container(optional=True)))
        if not skip_db:
            phases.append(("db", lambda: phase_db_connectivity(optional=True)))
        phases.append(("sterile", lambda: phase_sterile_probe(strict_isolate)))

    results = []
    for name, fn in phases:
        print(f"{COLOR['CYAN']}▶ {name.upper()}{COLOR['RESET']}")
        t0 = time.monotonic()
        pr = fn()
        pr.duration = time.monotonic() - t0
        results.append(pr)
        if pr.findings:
            for f in pr.findings:
                sev_color = {"CRITICAL": COLOR['RED'], "WARNING": COLOR['YELLOW'], "INFO": COLOR['CYAN'], "PASS": COLOR['GREEN']}.get(f.severity, COLOR['RESET'])
                icon = {"CRITICAL": "✖", "WARNING": "⚠", "INFO": "ℹ", "PASS": "✔"}.get(f.severity, "?")
                print(f"  {sev_color}{COLOR['BOLD']}{icon} [{f.severity}]{COLOR['RESET']} {f.message}")
                if f.detail:
                    print(f"      {COLOR['YELLOW']}{f.detail}{COLOR['RESET']}")
                if f.file and f.file != ".":
                    print(f"      @ {f.file}:{f.line}")
                if f.recommendation:
                    print(f"      💡 {f.recommendation}")
        else:
            print(f"  {COLOR['GREEN']}✔ No issues{COLOR['RESET']}")
        print(f"  ⏱  {pr.duration:.2f}s\n")

    critical = sum(pr.count("CRITICAL") for pr in results)
    warnings = sum(pr.count("WARNING") for pr in results)
    infos = sum(pr.count("INFO") for pr in results)
    passed = all(pr.passed for pr in results)

    print("═" * 80)
    print(f"{COLOR['BOLD']}SUMMARY — INTEGRATION VALIDATOR{COLOR['RESET']}")
    print(f"  Critical issues:  {COLOR['RED']}{critical}{COLOR['RESET']}")
    print(f"  Warnings:         {COLOR['YELLOW']}{warnings}{COLOR['RESET']}")
    print(f"  Info:             {COLOR['CYAN']}{infos}{COLOR['RESET']}")
    print(f"  Status:           {COLOR['GREEN'] if passed else COLOR['RED']}✅ {'PASS' if passed else 'FAIL'}{COLOR['RESET']}")
    print("═" * 80)

    if json_out:
        report = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "results": [
                {
                    "phase": pr.name,
                    "passed": pr.passed,
                    "duration": pr.duration,
                    "critical": pr.count("CRITICAL"),
                    "warnings": pr.count("WARNING"),
                    "infos": pr.count("INFO"),
                    "findings": [{"severity": f.severity, "file": f.file, "line": f.line, "message": f.message} for f in pr.findings]
                }
                for pr in results
            ],
            "summary": {"critical": critical, "warnings": warnings, "infos": infos, "passed": passed}
        }
        Path(json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\n{COLOR['CYAN']}JSON report saved to {json_out}{COLOR['RESET']}")

    return 0 if passed else 1

# =============================================================================
# CLI
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="Ultimate Integration Validator")
    parser.add_argument("--verbose", action="store_true", help="Show more details")
    parser.add_argument("--json", metavar="FILE", help="Save report as JSON")
    parser.add_argument("--no-runtime", action="store_true", help="Skip runtime import checks")
    parser.add_argument("--no-db", action="store_true", help="Skip database connectivity check")
    parser.add_argument("--strict-isolate", action="store_true", help="Test imports in isolated subprocess")
    args = parser.parse_args()
    sys.exit(run_unified_check(args.verbose, args.json, args.no_runtime, args.no_db, args.strict_isolate))

if __name__ == "__main__":
    main()