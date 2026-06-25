#!/usr/bin/env python3
"""
RUNTIME ERROR DETECTOR — Super Robust Import & Runtime Scanner
================================================================
Aggressively imports every production module to catch deep runtime issues.
Fixed Traceback extraction bugs, SystemExit safety, and Environment Pollution guard.
"""

import ast
import importlib
import sys
import time
import traceback
from pathlib import Path
from typing import List, Tuple, Dict, Set, Optional

# ─── Configuration ────────────────────────────────────────────────────────────
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
    "test_audit_import.py", "runtime_eror.py",
}

# ─── Colour helpers ──────────────────────────────────────────────────────────
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

# ─── File discovery ──────────────────────────────────────────────────────────

def should_skip_file(path: Path, skip_tests: bool, skip_migrations: bool) -> bool:
    if path.name in CHECKER_FILES or path.name == Path(__file__).name:
        return True
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return True

    for part in rel.parts:
        if part in SKIP_DIRS or part.startswith("__pycache__") or part.startswith(".pytest_cache"):
            return True

    if skip_tests and ("tests" in rel.parts):
        return True
    if skip_migrations and ("migrations" in rel.parts):
        return True

    return False

def collect_modules(skip_tests: bool, skip_migrations: bool) -> List[Tuple[str, Path]]:
    modules = []
    for p in ROOT.glob("*.py"):
        if not should_skip_file(p, skip_tests, skip_migrations):
            mod = module_name_from_path(p)
            if mod: modules.append((mod, p))

    for top in PROJECT_TOPS:
        top_dir = ROOT / top
        if not top_dir.is_dir():
            continue
        for p in top_dir.rglob("*.py"):
            if not should_skip_file(p, skip_tests, skip_migrations):
                mod = module_name_from_path(p)
                if mod: modules.append((mod, p))

    seen = set()
    unique = []
    for mod, path in modules:
        if mod not in seen:
            seen.add(mod)
            unique.append((mod, path))
    return sorted(unique, key=lambda x: x[0])

def module_name_from_path(path: Path) -> Optional[str]:
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return None
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None

# ─── Import tester ──────────────────────────────────────────────────────────

def safe_import_module(module_name: str) -> Tuple[bool, Optional[str], str, str, int]:
    """
    Attempt to import a module safely.
    Returns: (success, error_msg, full_traceback, err_file, err_line)
    """
    # Catat modul yang sudah ada sebelum import untuk mencegah polusi lingkungan global sys.modules
    initial_modules = set(sys.modules.keys())
    
    try:
        importlib.import_module(module_name)
        return True, None, "", "", 0
    except BaseException as e:
        # Jika user menekan Ctrl+C, izinkan aplikasi keluar
        if isinstance(e, KeyboardInterrupt):
            raise e
            
        tb_str = traceback.format_exc()
        error_msg = f"{type(e).__name__}: {str(e)}"
        
        # Bersihkan nama jika terjadi kesalahan nama import khusus
        if isinstance(e, ImportError):
            name = getattr(e, 'name', None)
            path = getattr(e, 'path', None)
            if name:
                error_msg = f"ImportError: cannot import name '{name}' from '{path or '?'}'"

        # EKSTRAKSI PRESISI: Ambil line number dan filename langsung dari stack traceback terakhir
        err_file = "Unknown"
        err_line = 0
        tb = e.__traceback__
        if tb:
            tb_list = traceback.extract_tb(tb)
            if tb_list:
                # Ambil investigasi terdalam tempat crash sesungguhnya terjadi
                last_trace = tb_list[-1]
                err_file = last_trace.filename
                err_line = last_trace.lineno
                
        # Penanganan Kebersihan Lingkungan: Bersihkan modul yang gagal di-load agar tidak merusak pencarian selanjutnya
        current_modules = set(sys.modules.keys())
        for mod in current_modules - initial_modules:
            if mod.startswith(module_name):
                sys.modules.pop(mod, None)
                
        return False, error_msg, tb_str, err_file, err_line

# ─── Main audit ──────────────────────────────────────────────────────────────

def audit_runtime_imports(verbose: bool, skip_tests: bool, skip_migrations: bool):
    print(f"{BOLD}{CYAN}┌──────────────────────────────────────────────────────────────────────────────┐")
    print(f"│                    🛡️  CRITICAL RUNTIME ERROR DETECTOR V2                    │")
    print(f"└──────────────────────────────────────────────────────────────────────────────┘{RESET}\n")

    print(f"🔍 Indexing Python layers and production directories...")
    modules = collect_modules(skip_tests, skip_migrations)
    total = len(modules)
    
    # Hitung persebaran per top-layer
    layer_counts = {}
    for mod, _ in modules:
        top = mod.split(".")[0]
        layer_counts[top] = layer_counts.get(top, 0) + 1

    # Tampilkan summary index yang sangat informatif
    print(f"\n{BOLD}{WHITE}📊 MODULE DISCOVERY SUMMARY:{RESET}")
    print(f"┌───────────────────────────────┬──────────────────────┐")
    print(f"│ Project Top-Level Layer       │ Total Found Modules  │")
    print(f"├───────────────────────────────┼──────────────────────┤")
    for layer, count in sorted(layer_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"│  {layer:<28} │ {count:<20} │")
    print(f"└───────────────────────────────┴──────────────────────┘")
    print(f"👉 {BOLD}{GREEN}Target Modules Prepared to Execution: {total}{RESET}\n")

    if total == 0:
        print(f"{YELLOW}⚠ No modules discovered. Verify execution target root.{RESET}")
        sys.exit(1)

    failures = []  # List of tuples: (mod, path, err, tb, err_file, err_line)
    successes = 0

    print(f"{BOLD}{WHITE}🚀 Executing Import Aggression Strategy...{RESET}")
    print("─" * 80)

    start_time = time.monotonic()
    for idx, (mod, path) in enumerate(modules, 1):
        if verbose:
            print(f"[{idx:4d}/{total}] {mod} ... ", end="", flush=True)

        # Jalankan safe import robust
        ok, err, tb, err_file, err_line = safe_import_module(mod)

        if ok:
            successes += 1
            if verbose:
                print(f"{GREEN}✅ SUCCESS{RESET}")
        else:
            # Sederhanakan path error file jika berada di dalam ROOT
            try:
                p_err_file = str(Path(err_file).relative_to(ROOT))
            except ValueError:
                p_err_file = err_file
                
            failures.append((mod, path, err, tb, p_err_file, err_line))
            
            if verbose:
                print(f"{RED}❌ CRASH -> {err}{RESET}")
            else:
                print(f"  {RED}✖{RESET} [{idx:4d}/{total}] {BOLD}{mod}{RESET} ➔ {RED}{err}{RESET}")

    elapsed = time.monotonic() - start_time

    # ─── SUMMARY OVERVIEW ────────────────────────────────────────────────────
    print("\n" + "═" * 80)
    print(f"{BOLD}📊 FINAL RUNTIME AUDIT REPORT{RESET}")
    print(f"  • Total Executed Modules : {total}")
    print(f"  • Successfully Clean     : {BOLD}{GREEN}{successes}{RESET}")
    print(f"  • Absolute Fatal Crashes : {BOLD}{RED if len(failures) > 0 else GREEN}{len(failures)}{RESET}")
    print(f"  • Execution Duration     : {elapsed:.2f}s")
    print("═" * 80)

    if failures:
        print(f"\n{RED}{BOLD}🚨 FATAL CRASH LOGS DETECTED ({len(failures)}):{RESET}")
        for idx, (mod, path, err, tb, err_file, err_line) in enumerate(failures, 1):
            rel_path = str(path.relative_to(ROOT)) if path.parent != ROOT else path.name
            print(f"\n  {BOLD}{idx}. Modul: {CYAN}{mod}{RESET}")
            print(f"     📍 Target File   : {rel_path}")
            print(f"     🔥 Source Error  : {RED}{err}{RESET}")
            print(f"     🎯 Exact Location: Line {BOLD}{YELLOW}{err_line}{RESET} inside {MAGENTA}{err_file}{RESET}")
            if verbose and tb:
                print(f"     📚 Core Stack Trace:\n{tb}")
        print(f"\n{RED}{BOLD}🛑 DEPLOYMENT GUARD: FAILED. Fix the execution issues listed above.{RESET}\n")
        sys.exit(1)
    else:
        print(f"\n{GREEN}{BOLD}🎉 DEPLOYMENT GUARD: PASSED. All modules boot up successfully!{RESET}\n")
        sys.exit(0)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Runtime Error Detector")
    parser.add_argument("--verbose", action="store_true", help="Show full traceback for each error")
    parser.add_argument("--skip-tests", action="store_true", help="Skip tests/ directory")
    parser.add_argument("--skip-migrations", action="store_true", help="Skip migrations/ directory")
    args = parser.parse_args()

    audit_runtime_imports(
        verbose=args.verbose,
        skip_tests=args.skip_tests,
        skip_migrations=args.skip_migrations,
    )

if __name__ == "__main__":
    main()