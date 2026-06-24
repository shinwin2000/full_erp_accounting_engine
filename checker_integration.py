#!/usr/bin/env python3
"""
CHECKER_INTEGRATION — Sistem ERP Accounting Engine Integration Validator
========================================================================
Memeriksa integritas seluruh sistem secara menyeluruh:
- Circular imports, broken imports, dynamic imports (AST)
- Runtime import semua modul produksi (real import)
- Critical modules import
- ASGI app bootstrap (create app)
- DI container resolution (opsional)
- Database connectivity (opsional)

Tidak ada mock, stub, atau placeholder — semua validasi real.
Menangkap error sedini mungkin sebelum aplikasi dijalankan.

Usage:
    python checker_integration.py [--verbose] [--json report.json] [--no-runtime] [--no-db]

Exit code:
    0 jika semua lulus
    1 jika ada critical issue
"""

import sys
import os
import ast
import json
import time
import importlib
import traceback
import collections
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass, field

# ─── Konfigurasi ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent

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
    "main_checker.py", "main_checker_2.py", "main_checker_3.py",
    "main_checker_v5.py", "main_checker_old.py", "main_app_checker.py",
    "checker_integration.py",
}

PROTECTED_LAYERS = {"domain", "kernel", "application", "ports", "axioms", "constitution"}

# ─── Color ──────────────────────────────────────────────────────────────────
try:
    import colorama
    colorama.init(autoreset=True)
    RED = colorama.Fore.RED
    GREEN = colorama.Fore.GREEN
    YELLOW = colorama.Fore.YELLOW
    CYAN = colorama.Fore.CYAN
    WHITE = colorama.Fore.WHITE
    BOLD = colorama.Style.BRIGHT
    RESET = colorama.Style.RESET_ALL
except ImportError:
    RED = GREEN = YELLOW = CYAN = WHITE = BOLD = RESET = ""

@dataclass
class Finding:
    severity: str
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

# ─── Helpers ──────────────────────────────────────────────────────────────────

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

def get_ast_tree(p: Path):
    try:
        return ast.parse(p.read_text(encoding="utf-8", errors="replace"), filename=str(p))
    except:
        return None

def top_layer(mod: str) -> str:
    return mod.split(".")[0]

def safe_import(module_name: str) -> Tuple[bool, Optional[str]]:
    try:
        importlib.import_module(module_name)
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:150]}"

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

# ─── Phase implementations ────────────────────────────────────────────────────

def phase_circular_imports() -> PhaseResult:
    pr = PhaseResult("Circular Imports")
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
        for _, imp in extract_imports(tree):
            if imp in local_mods:
                if mod != imp:
                    graph[mod].add(imp)
            else:
                for local in local_mods:
                    if local.startswith(imp + "."):
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
    for node in graph:
        if node not in indices:
            strongconnect(node)
    if sccs:
        for scc in sccs:
            cycle_list = list(scc)
            first_file = module_map.get(cycle_list[0], Path("?"))
            pr.add("WARNING", rel_path(first_file), 0,
                   f"Circular import cycle: {' → '.join(cycle_list[:5])}",
                   rec="Refactor to break the cycle")
        # Warnings only, not critical
        pr.passed = True
    else:
        pr.add("PASS", ".", 0, f"No circular imports among {len(local_mods)} modules")
    pr.duration = time.monotonic() - t0
    return pr

def phase_broken_imports() -> PhaseResult:
    pr = PhaseResult("Broken Imports")
    t0 = time.monotonic()
    files = all_py_files()
    local_mods = {module_name(f) for f in files if module_name(f)}
    local_tops = {m.split(".")[0] for m in local_mods}
    broken = []
    for f in files:
        mod = module_name(f)
        tree = get_ast_tree(f)
        if not tree:
            continue
        rp = rel_path(f)
        # Absolute imports
        for lineno, imp in extract_imports(tree):
            top = imp.split(".")[0]
            if top in local_tops and imp not in local_mods:
                if not resolve_import_target(imp, ROOT):
                    broken.append((rp, lineno, imp, "Module not found"))
        # Relative imports
        for lineno, level, module, names in extract_relative_imports(tree):
            resolved = resolve_relative_import(f, level, module, names[0] if names else None)
            if not resolved:
                if module:
                    broken.append((rp, lineno, f".{'.'*(level-1)}{module}", "Relative import cannot be resolved"))
                else:
                    for name in names:
                        broken.append((rp, lineno, f".{'.'*(level-1)}{name}", "Relative import cannot be resolved"))
    if broken:
        for rp, lineno, imp, detail in broken[:20]:
            pr.add("CRITICAL", rp, lineno, f"Broken import: {imp}", detail=detail, rec="Fix the import path")
        if len(broken) > 20:
            pr.add("INFO", ".", 0, f"Plus {len(broken)-20} more broken imports")
    else:
        pr.add("PASS", ".", 0, "No broken imports")
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
                violations.append((rel_path(f), lineno, f"{call}({arg})"))
    if violations:
        for file, line, call in violations:
            pr.add("CRITICAL", file, line, f"Forbidden dynamic import: {call}", rec="Use dependency injection or static imports")
    else:
        pr.add("PASS", ".", 0, "No forbidden dynamic imports in core layers")
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
        # Skip test and checker files
        if mod.startswith("test_") or mod.startswith("main_checker") or mod in ("checker_integration",):
            continue
        ok, err = safe_import(mod)
        if not ok:
            errors.append((rel_path(f), mod, err))
    if errors:
        for file, mod, err in errors[:20]:
            pr.add("CRITICAL", file, 0, f"Import failed for '{mod}': {err}", rec="Fix dependencies")
        if len(errors) > 20:
            pr.add("INFO", ".", 0, f"Plus {len(errors)-20} more import failures")
    else:
        pr.add("PASS", ".", 0, f"All production modules imported successfully")
    pr.duration = time.monotonic() - t0
    return pr

def phase_critical_imports() -> PhaseResult:
    pr = PhaseResult("Critical Imports")
    t0 = time.monotonic()
    # Core modules - use a reduced set to avoid too many
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
            pr.add("CRITICAL", mod.replace(".", "/") + ".py", 0, f"Critical import '{label}' failed: {err}", rec="Fix immediately")
    else:
        pr.add("PASS", ".", 0, f"All {len(critical)} critical modules imported")
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
            pr.add("CRITICAL", "app/main.py", 0, "No app variable or create_app/get_app found", rec="Define app in app/main.py")
            return pr
        if callable(app_obj) and not isinstance(app_obj, type):
            app_obj = app_obj()
        if hasattr(app_obj, "__call__"):
            pr.add("PASS", "app/main.py", 0, "ASGI app is callable")
        else:
            pr.add("CRITICAL", "app/main.py", 0, "App object is not callable", rec="Ensure app is a FastAPI instance")
    except Exception as e:
        pr.add("CRITICAL", "app/main.py", 0, f"Bootstrap failed: {type(e).__name__}: {str(e)[:150]}", rec="Check dependencies")
    pr.duration = time.monotonic() - t0
    return pr

def phase_di_container(optional: bool = True) -> PhaseResult:
    pr = PhaseResult("DI Container")
    t0 = time.monotonic()
    try:
        from bootstrap.dependency_container.ioc_container import get_container
        container = get_container()
        # Try to get registered types
        registered = []
        if hasattr(container, "get_registered_types"):
            registered = container.get_registered_types()
        elif hasattr(container, "_registry"):
            registered = list(container._registry.keys())
        if registered:
            pr.add("PASS", "bootstrap/dependency_container", 0, f"DI container has {len(registered)} registered types")
        else:
            pr.add("WARNING", "bootstrap/dependency_container", 0, "DI container has no registered types", rec="Check registration")
    except ImportError as e:
        if not optional:
            pr.add("CRITICAL", "bootstrap/dependency_container", 0, f"DI container import failed: {e}", rec="Ensure DI module exists")
        else:
            pr.add("INFO", "bootstrap/dependency_container", 0, "DI container not available (skipped)")
    except Exception as e:
        pr.add("CRITICAL", "bootstrap/dependency_container", 0, f"DI container error: {type(e).__name__}: {str(e)[:100]}", rec="Fix DI configuration")
    pr.duration = time.monotonic() - t0
    return pr

def phase_db_connectivity(optional: bool = True) -> PhaseResult:
    pr = PhaseResult("Database Connectivity")
    t0 = time.monotonic()
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        if optional:
            pr.add("INFO", ".env", 0, "DATABASE_URL not set (skipping DB check)")
            return pr
        else:
            pr.add("CRITICAL", ".env", 0, "DATABASE_URL not set", rec="Set DATABASE_URL environment variable")
            return pr
    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        # Ensure async driver
        if "postgresql://" in db_url and "+asyncpg" not in db_url:
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        engine = create_async_engine(db_url, pool_pre_ping=True, pool_size=1)
        import asyncio
        async def test():
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        asyncio.run(test())
        pr.add("PASS", "config/", 0, "Database connection successful")
    except Exception as e:
        pr.add("CRITICAL", "config/", 0, f"Database connection failed: {type(e).__name__}: {str(e)[:150]}", rec="Check DATABASE_URL and DB service")
    pr.duration = time.monotonic() - t0
    return pr

# ─── Main runner ─────────────────────────────────────────────────────────────

def run_integration_check(verbose: bool, json_out: Optional[str], skip_runtime: bool, skip_db: bool) -> int:
    print(f"{BOLD}{CYAN}╔{'═'*78}╗{RESET}")
    print(f"{BOLD}{CYAN}║{' '*20}CHECKER_INTEGRATION — SISTEM VALIDATOR{' '*21}║{RESET}")
    print(f"{BOLD}{CYAN}╚{'═'*78}╝{RESET}")
    print()

    if skip_runtime:
        print(f"{YELLOW}⚠️  Runtime import checks disabled (--no-runtime){RESET}")
    if skip_db:
        print(f"{YELLOW}⚠️  Database connectivity check disabled (--no-db){RESET}")
    print()

    phases = [
        ("circular", phase_circular_imports),
        ("broken", phase_broken_imports),
        ("dynamic", phase_dynamic_imports),
    ]
    if not skip_runtime:
        phases.append(("runtime", phase_runtime_imports))
        phases.append(("critical", phase_critical_imports))
        phases.append(("bootstrap", phase_app_bootstrap))
        phases.append(("di", lambda: phase_di_container(optional=True)))
        if not skip_db:
            phases.append(("db", lambda: phase_db_connectivity(optional=True)))

    results = []
    for name, fn in phases:
        print(f"{CYAN}▶ {name.upper()}{RESET}")
        t0 = time.monotonic()
        pr = fn()
        pr.duration = time.monotonic() - t0
        results.append(pr)
        # Print findings
        if pr.findings:
            for f in pr.findings:
                severity_col = {"CRITICAL": RED, "WARNING": YELLOW, "INFO": CYAN, "PASS": GREEN}.get(f.severity, WHITE)
                icon = {"CRITICAL": "✖", "WARNING": "⚠", "INFO": "ℹ", "PASS": "✔"}.get(f.severity, "?")
                print(f"  {severity_col}{BOLD}{icon} [{f.severity}]{RESET} {f.message}")
                if f.detail:
                    print(f"      {YELLOW}{f.detail}{RESET}")
                if f.file:
                    print(f"      {WHITE}@ {f.file}:{f.line}{RESET}")
                if f.recommendation:
                    print(f"      💡 {f.recommendation}")
        else:
            print(f"  {GREEN}✔ No issues{RESET}")
        print(f"  ⏱  {pr.duration:.2f}s\n")

    # Summary
    critical = sum(pr.count("CRITICAL") for pr in results)
    warnings = sum(pr.count("WARNING") for pr in results)
    infos = sum(pr.count("INFO") for pr in results)
    passed = all(pr.passed for pr in results)

    print("═" * 80)
    print(f"{BOLD}SUMMARY — INTEGRATION CHECK{RESET}")
    print(f"  Critical issues:  {RED}{critical}{RESET}")
    print(f"  Warnings:         {YELLOW}{warnings}{RESET}")
    print(f"  Info:             {CYAN}{infos}{RESET}")
    print(f"  Status:           {'GREEN✅ PASS' if passed else 'RED❌ FAIL'}{RESET}")
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
        print(f"\n{CYAN}JSON report saved to {json_out}{RESET}")

    return 0 if passed else 1

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Integration Checker")
    parser.add_argument("--verbose", action="store_true", help="Show more details")
    parser.add_argument("--json", metavar="FILE", help="Save report as JSON")
    parser.add_argument("--no-runtime", action="store_true", help="Skip runtime import checks")
    parser.add_argument("--no-db", action="store_true", help="Skip database connectivity check")
    args = parser.parse_args()
    sys.exit(run_integration_check(args.verbose, args.json, args.no_runtime, args.no_db))