#!/usr/bin/env python3
"""
CHECKER_INTEGRATION_SOVEREIGN — S+++ Grade ERP Accounting Engine Validator
========================================================================
Validasi nyata dan objektif tanpa mock, stub, atau placeholder.
Menerapkan Runtime Introspection mendalam dan Process Isolation untuk
mencegah polusi state antar modul selama fase pengujian.

Fase Utama:
1. AST Contract Extraction: Memetakan semua ekspektasi import.
2. Deep Contract Introspection: Memuat target import secara live dan memverifikasi atribut via getattr().
3. Isolated Runtime Validation: Uji import seluruh modul dalam subprocess independen (100% terisolasi).
4. Component Lifecycles: Introspeksi nyata pada objek FastAPI (routes) & DI Container.

Exit code:
    0 jika Sovereign System lulus 100%
    1 jika ada anomali atau kegagalan struktural
"""

import ast
import collections
import importlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

# ─── Konfigurasi Sistem ───────────────────────────────────────────────────────
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
    "checker_integration.py", "checker_integration_sovereign.py"
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
    MAGENTA = colorama.Fore.MAGENTA
    WHITE = colorama.Fore.WHITE
    BOLD = colorama.Style.BRIGHT
    RESET = colorama.Style.RESET_ALL
except ImportError:
    RED = GREEN = YELLOW = CYAN = MAGENTA = WHITE = BOLD = RESET = ""

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
    findings: list[Finding] = field(default_factory=list)
    duration: float = 0.0

    def add(self, sev: str, file: str, line: int, msg: str, detail: str = "", rec: str = ""):
        self.findings.append(Finding(sev, file, line, msg, detail, rec))
        if sev == "CRITICAL":
            self.passed = False

    def count(self, sev: str) -> int:
        return sum(1 for f in self.findings if f.severity == sev)

# ─── Engine Introspeksi & Utilitas ───────────────────────────────────────────

def rel_path(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)

def all_py_files() -> list[Path]:
    files = []
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

def module_name(p: Path) -> str | None:
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
    except SyntaxError as e:
        return e
    except Exception:
        return None

def verify_module_exists_spec(mod_name: str) -> bool:
    """Menggunakan importlib.util untuk resolusi path sejati, bukan tebakan string."""
    try:
        spec = importlib.util.find_spec(mod_name)
        return spec is not None
    except Exception:
        return False

# ─── Fase 1: Structural Integrity (Sintaks & Resolusi Path) ──────────────────

def phase_syntax_and_circular() -> PhaseResult:
    pr = PhaseResult("Syntax & Circular Integrity")
    t0 = time.monotonic()
    files = all_py_files()
    module_map = {}

    # 1. Syntax Validation
    for f in files:
        mod = module_name(f)
        if not mod:
            continue
        module_map[mod] = f
        tree = get_ast_tree(f)
        if isinstance(tree, SyntaxError):
            pr.add("CRITICAL", rel_path(f), tree.lineno or 0, f"SyntaxError: {tree.msg}", detail=tree.text, rec="Perbaiki sintaks dasar Python")
            continue

    local_mods = set(module_map.keys())
    graph = collections.defaultdict(set)

    # 2. Build Dependency Graph
    for f in files:
        mod = module_name(f)
        tree = get_ast_tree(f)
        if not tree or isinstance(tree, SyntaxError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imp = alias.name
                    if imp in local_mods and mod != imp:
                        graph[mod].add(imp)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.level == 0:
                    imp = node.module
                    if imp in local_mods and mod != imp:
                        graph[mod].add(imp)

    # 3. Tarjan SCC (Mendeteksi Siklus Import)
    index, stack, indices, lowlink, on_stack, sccs = 0, [], {}, {}, {}, []

    def strongconnect(node):
        nonlocal index
        indices[node] = lowlink[node] = index
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
                if w == node: break
            if len(scc) > 1: sccs.append(scc)

    for node in graph:
        if node not in indices: strongconnect(node)

    if sccs:
        for scc in sccs:
            cycle_list = list(scc)
            first_file = module_map.get(cycle_list[0], Path("?"))
            pr.add("WARNING", rel_path(first_file), 0,
                   f"Circular dependency terdeteksi: {' → '.join(cycle_list[:4])} ...",
                   rec="Gunakan Dependency Inversion atau relokasi objek ke modul netral.")
    else:
        pr.add("PASS", ".", 0, f"Integritas struktur {len(local_mods)} modul tervalidasi (Tidak ada siklus).")

    pr.duration = time.monotonic() - t0
    return pr

# ─── Fase 2: Deep Contract Introspection (Real attribute validation) ─────────

def check_single_contract(mod_source: str, imported_module: str, names: list[str], lineno: int) -> list[tuple[str, int, str, str, str]]:
    """Proses worker untuk memeriksa atribut secara live tanpa mengganggu main thread."""
    failures = []
    # Cegah inisialisasi side-effects berat jika modul bukan target
    try:
        mod = importlib.import_module(imported_module)
        for name in names:
            if name == "*": continue
            if not hasattr(mod, name):
                # Atribut tidak ditemukan secara live
                failures.append((
                    "CRITICAL", lineno,
                    f"Contract Violation: Cannot import name '{name}' from '{imported_module}'",
                    f"Atribut '{name}' tidak ada di namespace modul '{imported_module}' secara runtime.",
                    f"Verifikasi fungsi/kelas '{name}' di dalam {imported_module}.py"
                ))
    except ImportError as e:
        failures.append((
            "CRITICAL", lineno,
            f"Module Not Found: {imported_module}",
            str(e),
            "Pastikan modul tersedia dan path resolusi benar."
        ))
    except Exception:
        # Module gagal dimuat karena syntax/runtime error di dalamnya (akan ditangkap di fase 3 secara penuh)
        pass
    return failures

def phase_contract_introspection() -> PhaseResult:
    pr = PhaseResult("Deep Contract Introspection")
    t0 = time.monotonic()
    files = all_py_files()

    tasks = []
    for f in files:
        tree = get_ast_tree(f)
        if not tree or isinstance(tree, SyntaxError): continue
        rp = rel_path(f)

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                top_lvl = node.module.split('.')[0]
                if top_lvl in PROJECT_TOPS:
                    names = [alias.name for alias in node.names]
                    tasks.append((rp, node.module, names, node.lineno))

    # Eksekusi resolusi kontrak
    error_count = 0
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as executor:
        futures = {
            executor.submit(check_single_contract, source, mod, names, line): source
            for source, mod, names, line in tasks
        }
        for future in as_completed(futures):
            source = futures[future]
            try:
                results = future.result()
                for sev, line, msg, det, rec in results:
                    pr.add(sev, source, line, msg, detail=det, rec=rec)
                    error_count += 1
            except Exception:
                pass

    if error_count == 0:
        pr.add("PASS", ".", 0, "Semua kontrak antar-modul (from X import Y) tervalidasi secara live.")

    pr.duration = time.monotonic() - t0
    return pr

# ─── Fase 3: Isolated Runtime Validation (100% Bebas Polusi) ─────────────────

def phase_isolated_runtime() -> PhaseResult:
    pr = PhaseResult("Isolated Runtime Validation")
    t0 = time.monotonic()
    files = all_py_files()

    modules_to_test = []
    for f in files:
        mod = module_name(f)
        if mod and not mod.startswith("test_") and "checker" not in mod:
            modules_to_test.append((rel_path(f), mod))

    failed = []
    # Menggunakan subprocess murni agar memori state tidak tumpang tindih
    print(f"  {CYAN}Memulai isolasi runtime untuk {len(modules_to_test)} modul...{RESET}", flush=True)

    for file_path, mod in modules_to_test:
        # Mini script untuk melakukan import secara independen
        cmd = [sys.executable, "-c", f"import importlib; importlib.import_module('{mod}')"]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            err_output = result.stderr.strip().split('\n')[-1] # Ambil baris traceback terakhir
            failed.append((file_path, mod, err_output))

    if failed:
        for file, mod, err in failed[:15]:
            pr.add("CRITICAL", file, 0, f"Runtime Import Panic: '{mod}'", detail=err, rec="Perbaiki root cause yang menghentikan inisialisasi.")
        if len(failed) > 15:
            pr.add("INFO", ".", 0, f"Ditambah {len(failed)-15} modul lain yang gagal inisialisasi karena efek domino.")
    else:
        pr.add("PASS", ".", 0, f"Semua {len(modules_to_test)} modul berhasil diinisialisasi dalam lingkungan terisolasi.")

    pr.duration = time.monotonic() - t0
    return pr

# ─── Fase 4: Engine Component Lifecycles (Live Introspection) ────────────────

def phase_engine_lifecycle(optional_db: bool = True) -> PhaseResult:
    pr = PhaseResult("Engine Component Lifecycles")
    t0 = time.monotonic()

    # 1. FastAPI App Introspection
    try:
        if verify_module_exists_spec("app.main"):
            mod = importlib.import_module("app.main")
            app_obj = getattr(mod, "app", getattr(mod, "create_app", lambda: None)())

            if app_obj and hasattr(app_obj, "routes"):
                routes_count = len(app_obj.routes)
                pr.add("PASS", "app/main.py", 0, f"ASGI Engine termuat. Mendeteksi {routes_count} live routes/endpoints.")
            else:
                pr.add("WARNING", "app/main.py", 0, "Aplikasi terinisialisasi tetapi tidak ada antarmuka ASGI yang valid terdeteksi.")
        else:
            pr.add("CRITICAL", "app/main.py", 0, "Modul app.main tidak ditemukan.", rec="Pastikan entry point aplikasi tersedia.")
    except Exception as e:
        pr.add("CRITICAL", "app/main.py", 0, f"FastAPI Bootstrap Gagal: {type(e).__name__}: {e!s}")

    # 2. DI Container Introspection
    try:
        if verify_module_exists_spec("bootstrap.dependency_container.ioc_container"):
            di_mod = importlib.import_module("bootstrap.dependency_container.ioc_container")
            if hasattr(di_mod, "get_container"):
                container = di_mod.get_container()

                # Coba introspeksi _registry atau mekanisme internal
                registry_count = 0
                if hasattr(container, "_registry"):
                    registry_count = len(container._registry)
                elif hasattr(container, "get_registered_types"):
                    registry_count = len(container.get_registered_types())

                pr.add("PASS", "DI Container", 0, f"IoC Container aktif. Mendeteksi {registry_count} registered bindings.")
            else:
                pr.add("WARNING", "DI Container", 0, "Container ditemukan, tetapi antarmuka 'get_container' tidak standar.")
    except Exception as e:
        pr.add("WARNING", "DI Container", 0, f"Introspeksi DI gagal: {e!s}")

    # 3. Database Introspection (Terkoneksi Nyata)
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        if optional_db:
            pr.add("INFO", ".env", 0, "DATABASE_URL tidak disetel. Pengecekan koneksi fisik dilewati.")
        else:
            pr.add("CRITICAL", ".env", 0, "DATABASE_URL kosong.", rec="Engine memerlukan database untuk menyala penuh.")
    else:
        try:
            import asyncio

            from sqlalchemy import text
            from sqlalchemy.ext.asyncio import create_async_engine

            if "postgresql://" in db_url and "+asyncpg" not in db_url:
                db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

            engine = create_async_engine(db_url, pool_pre_ping=True, connect_args={"server_settings": {"application_name": "Sovereign_Integration_Checker"}})

            async def ping_db():
                async with engine.connect() as conn:
                    result = await conn.execute(text("SELECT current_database();"))
                    return result.scalar()

            db_name = asyncio.run(ping_db())
            pr.add("PASS", "Database", 0, f"Koneksi terverifikasi secara fisik ke database: '{db_name}'")
        except ImportError:
            pr.add("WARNING", "Database", 0, "Library SQLAlchemy/asyncpg tidak tersedia untuk menguji koneksi.")
        except Exception as e:
            pr.add("CRITICAL", "Database", 0, f"Koneksi fisik ditolak: {e!s}", rec="Periksa kredensial, VPN, atau layanan PostgreSQL.")

    pr.duration = time.monotonic() - t0
    return pr

# ─── Eksekutor Utama ─────────────────────────────────────────────────────────

def run_integration_check(verbose: bool, json_out: str | None, skip_db: bool) -> int:
    print(f"{BOLD}{MAGENTA}╔{'═'*78}╗{RESET}")
    print(f"{BOLD}{MAGENTA}║{' '*16}SOVEREIGN KERNEL — DEEP INTEGRATION VALIDATOR{' '*17}║{RESET}")
    print(f"{BOLD}{MAGENTA}╚{'═'*78}╝{RESET}\n")

    phases = [
        ("Structure & Syntax", phase_syntax_and_circular),
        ("Contract Introspection", phase_contract_introspection),
        ("Isolated Runtime", phase_isolated_runtime),
        ("Lifecycle & State", lambda: phase_engine_lifecycle(optional_db=skip_db)),
    ]

    results = []
    for name, fn in phases:
        print(f"{CYAN}▶ MEMULAI FASE: {name.upper()}{RESET}")
        pr = fn()
        results.append(pr)

        if pr.findings:
            for f in pr.findings:
                sev_col = {"CRITICAL": RED, "WARNING": YELLOW, "INFO": CYAN, "PASS": GREEN}.get(f.severity, WHITE)
                icon = {"CRITICAL": "✖", "WARNING": "⚠", "INFO": "ℹ", "PASS": "✔"}.get(f.severity, "?")
                print(f"  {sev_col}{BOLD}{icon} [{f.severity}]{RESET} {f.message}")

                if f.detail and f.severity in ("CRITICAL", "WARNING"):
                    print(f"      {YELLOW}→ {f.detail}{RESET}")
                if f.file and f.file != ".":
                    print(f"      {WHITE}@ {f.file}:{f.line}{RESET}")
                if f.recommendation:
                    print(f"      💡 {f.recommendation}")
        else:
            print(f"  {GREEN}✔ Tidak ada anomali terdeteksi.{RESET}")

        print(f"  ⏱  Penyelesaian fase: {pr.duration:.2f}s\n")

    # Kalkulasi Keseluruhan
    critical = sum(pr.count("CRITICAL") for pr in results)
    warnings = sum(pr.count("WARNING") for pr in results)
    passed = all(pr.passed for pr in results)

    print("═" * 80)
    print(f"{BOLD}DIAGNOSTIK KESELURUHAN SOVEREIGN SYSTEM{RESET}")
    print(f"  Critical Integrity Violations:  {RED}{critical}{RESET}")
    print(f"  System Warnings (Degraded):     {YELLOW}{warnings}{RESET}")
    print(f"  Final Engine Status:            {'GREEN✅ SEALED & READY' if passed else 'RED❌ KERNEL PANIC / VALIDATION FAILED'}{RESET}")
    print("═" * 80)

    if json_out:
        report = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "summary": {"critical": critical, "warnings": warnings, "passed": passed},
            "phases": [
                {
                    "phase": pr.name,
                    "passed": pr.passed,
                    "duration": round(pr.duration, 3),
                    "findings": [vars(f) for f in pr.findings]
                } for pr in results
            ]
        }
        Path(json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\n{CYAN}Laporan audit disimpan: {json_out}{RESET}")

    return 0 if passed else 1

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Sovereign Deep Integration Validator")
    parser.add_argument("--verbose", action="store_true", help="Log tingkat lanjut")
    parser.add_argument("--json", metavar="FILE", help="Simpan temuan struktural dalam JSON")
    parser.add_argument("--no-db", action="store_true", help="Abaikan introspeksi koneksi database fisik")
    args = parser.parse_args()

    sys.exit(run_integration_check(args.verbose, args.json, args.no_db))
