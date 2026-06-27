#!/usr/bin/env python3
"""
RUNTIME ERROR DETECTOR — Super Robust Import & Runtime Scanner (Fast + Skip Checker)
====================================================================================
- 100% coverage of import‑time errors (with multi‑encoding support)
- Parallel import (--parallel) for massive speedup
- Skip already imported modules (--skip-imported)
- Fast mode (--fast) = skip-imported + parallel + 4 workers
- SELURUH FOLDER checker/ DI-SKIP (tidak dipindai)
"""

import ast
import concurrent.futures
import importlib
import multiprocessing
import sys
import time
import traceback
from pathlib import Path
from typing import Any

# ─── Colour helpers (with fallback) ──────────────────────────────────────────
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

# ─── Project root detection ──────────────────────────────────────────────────
def resolve_project_root() -> Path:
    """Cari root proyek berdasarkan file marker umum."""
    curr = Path(__file__).resolve().parent
    markers = ["pyproject.toml", "setup.py", "setup.cfg", ".git", "manage.py", "requirements.txt"]
    for _ in range(6):
        if any((curr / marker).exists() for marker in markers):
            return curr
        curr = curr.parent
    return Path(__file__).resolve().parent.parent

ROOT = resolve_project_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ─── Configuration ──────────────────────────────────────────────────────────
SKIP_DIRS = {
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".git", ".venv", "venv", "node_modules", ".tox", ".cache",
    "site-packages", "dist-packages", "dist", "build", "uv", "eggs",
    "checker",   # <--- TAMBAHKAN INI: skip seluruh folder checker
}
SKIP_FILES = {
    "main_checker.py", "main_checker_2.py", "main_checker_3.py",
    "main_checker_v5.py", "main_checker_old.py", "main_app_checker.py",
    "test_audit_import.py", "runtime_eror.py",
    Path(__file__).name,  # skip file ini sendiri
}

# ─── Module discovery ──────────────────────────────────────────────────────

def should_skip(path: Path, skip_tests: bool, skip_migrations: bool) -> bool:
    if path.name in SKIP_FILES:
        return True
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return True
    for part in rel.parts:
        if part in SKIP_DIRS or part.startswith("."):
            return True
    if skip_tests and "tests" in rel.parts:
        return True
    if skip_migrations and "migrations" in rel.parts:
        return True
    return False

def collect_modules(skip_tests: bool, skip_migrations: bool) -> list[tuple[str, Path]]:
    modules = []
    for p in ROOT.rglob("*.py"):
        if should_skip(p, skip_tests, skip_migrations):
            continue
        mod = module_name_from_path(p)
        if mod:
            modules.append((mod, p))
    seen = set()
    unique = []
    for mod, p in modules:
        if mod not in seen:
            seen.add(mod)
            unique.append((mod, p))
    return sorted(unique, key=lambda x: x[0])

def module_name_from_path(path: Path) -> str | None:
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return None
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None

# ─── Syntax validation with multi‑encoding support ──────────────────────

def read_file_with_encoding(filepath: Path) -> str | None:
    encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'cp1252']
    for enc in encodings:
        try:
            with open(filepath, encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, LookupError):
            continue
    return None

def check_syntax(filepath: Path) -> str | None:
    source = read_file_with_encoding(filepath)
    if source is None:
        return "Unsupported encoding: could not read file"
    try:
        ast.parse(source, filename=str(filepath))
        return None
    except SyntaxError as e:
        return f"SyntaxError at line {e.lineno}: {e.msg}"
    except Exception as e:
        return f"Unexpected error during syntax check: {e}"

# ─── Worker for parallel import ──────────────────────────────────────────

def import_worker(module_name: str, root: str) -> tuple[str, bool, str | None, str, str, int]:
    """
    Worker untuk proses paralel. Mengimpor modul dan mengembalikan hasil.
    """
    import sys
    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        importlib.import_module(module_name)
        return (module_name, True, None, "", "", 0)
    except SystemExit as e:
        if e.code == 0 or e.code is None:
            return (module_name, True, None, "", "", 0)
        else:
            tb = traceback.format_exc()
            return (module_name, False, f"SystemExit({e.code})", tb, "SystemExit", 0)
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        tb = traceback.format_exc()
        err_msg = f"{type(e).__name__}: {e!s}"
        if isinstance(e, ImportError):
            name = getattr(e, 'name', None)
            path = getattr(e, 'path', None)
            if name:
                err_msg = f"ImportError: cannot import name '{name}' from '{path or '?'}'"
        err_file = "Unknown"
        err_line = 0
        tb_obj = e.__traceback__
        if tb_obj:
            tb_list = traceback.extract_tb(tb_obj)
            if tb_list:
                last_trace = tb_list[-1]
                err_file = last_trace.filename
                err_line = last_trace.lineno
        return (module_name, False, err_msg, tb, err_file, err_line)

# ─── Safe import (sequential) ─────────────────────────────────────────────

def safe_import_module(module_name: str) -> tuple[bool, str | None, str, str, int]:
    initial_modules = set(sys.modules.keys())
    try:
        importlib.import_module(module_name)
        return True, None, "", "", 0
    except SystemExit as e:
        if e.code == 0 or e.code is None:
            return True, None, "", "", 0
        else:
            tb = traceback.format_exc()
            return False, f"SystemExit({e.code})", tb, "SystemExit", 0
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        tb = traceback.format_exc()
        err_msg = f"{type(e).__name__}: {e!s}"
        if isinstance(e, ImportError):
            name = getattr(e, 'name', None)
            path = getattr(e, 'path', None)
            if name:
                err_msg = f"ImportError: cannot import name '{name}' from '{path or '?'}'"
        err_file = "Unknown"
        err_line = 0
        tb_obj = e.__traceback__
        if tb_obj:
            tb_list = traceback.extract_tb(tb_obj)
            if tb_list:
                last_trace = tb_list[-1]
                err_file = last_trace.filename
                err_line = last_trace.lineno
        # cleanup
        current_modules = set(sys.modules.keys())
        for mod in current_modules - initial_modules:
            if mod.startswith(module_name):
                sys.modules.pop(mod, None)
        return False, err_msg, tb, err_file, err_line

# ─── Progress bar helper ──────────────────────────────────────────────────

def show_progress(current, total, start_time):
    elapsed = time.monotonic() - start_time
    if total == 0:
        return
    pct = current / total * 100
    bar_len = 40
    filled = int(bar_len * current / total)
    bar = '█' * filled + '░' * (bar_len - filled)
    print(f"\r[{bar}] {current}/{total} ({pct:.1f}%)  {elapsed:.1f}s", end='', flush=True)

# ─── Main audit ────────────────────────────────────────────────────────────

def audit_runtime_imports(verbose: bool, skip_tests: bool, skip_migrations: bool,
                          deep: bool, parallel: bool, workers: int, skip_imported: bool):
    print(f"{BOLD}{CYAN}┌──────────────────────────────────────────────────────────────────────────────────┐")
    print("│                    🛡️  CRITICAL RUNTIME ERROR DETECTOR V3 (FAST)                  │")
    print(f"└──────────────────────────────────────────────────────────────────────────────────┘{RESET}\n")

    print(f"🔍 Scanning project root: {ROOT}")

    # 1. Kumpulkan modul
    modules = collect_modules(skip_tests, skip_migrations)
    total = len(modules)
    if total == 0:
        print(f"{YELLOW}⚠ No modules discovered. Verify project root or skip settings.{RESET}")
        sys.exit(1)

    # 2. Syntax check
    print(f"{BOLD}{WHITE}📄 Validating syntax of all Python files...{RESET}")
    syntax_errors = []
    for mod, path in modules:
        err = check_syntax(path)
        if err:
            syntax_errors.append((mod, path, err))
    if syntax_errors:
        print(f"{RED}{BOLD}❌ Found {len(syntax_errors)} file(s) with syntax errors:{RESET}")
        for mod, path, err in syntax_errors:
            rel = path.relative_to(ROOT)
            print(f"  {RED}✖{RESET} {mod} ({rel}): {err}")
        print(f"\n{RED}{BOLD}🛑 DEPLOYMENT GUARD: FAILED due to syntax errors.{RESET}\n")
        sys.exit(1)
    else:
        print(f"{GREEN}✅ All files have valid syntax.{RESET}\n")

    # 3. Tampilkan ringkasan (singkat)
    layer_counts = {}
    for mod, _ in modules:
        top = mod.split(".")[0]
        layer_counts[top] = layer_counts.get(top, 0) + 1

    print(f"{BOLD}{WHITE}📊 MODULE DISCOVERY SUMMARY:{RESET}")
    print("┌───────────────────────────────┬──────────────────────┐")
    print("│ Top-Level Layer               │ Total Modules        │")
    print("├───────────────────────────────┼──────────────────────┤")
    for layer, count in sorted(layer_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"│  {layer:<28} │ {count:<20} │")
    if len(layer_counts) > 10:
        print(f"│  ... and {len(layer_counts)-10} more layers       │                      │")
    print("└───────────────────────────────┴──────────────────────┘")
    print(f"👉 {BOLD}{GREEN}Total modules to process: {total}{RESET}\n")

    # 4. Filter modul yang sudah diimport (jika skip_imported)
    if skip_imported:
        existing = set(sys.modules.keys())
        modules_to_import = [(mod, path) for mod, path in modules if mod not in existing]
        print(f"{YELLOW}⏩ Skipping {total - len(modules_to_import)} already imported modules.{RESET}")
        total = len(modules_to_import)
        if total == 0:
            print(f"{GREEN}All modules already imported. Nothing to do.{RESET}")
            sys.exit(0)
    else:
        modules_to_import = modules

    failures = []
    successes = 0

    print(f"{BOLD}{WHITE}🚀 Importing {total} modules...{RESET}")

    start_time = time.monotonic()
    if parallel:
        print(f"   Using {workers} parallel workers.")
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(import_worker, mod, str(ROOT)): (mod, path) for mod, path in modules_to_import}
            completed = 0
            for future in concurrent.futures.as_completed(futures):
                mod, path = futures[future]
                try:
                    res = future.result(timeout=30)  # timeout per modul 30 detik
                except concurrent.futures.TimeoutError:
                    failures.append((mod, path, "Timeout (30s)", "", "Timeout", 0))
                    completed += 1
                    show_progress(completed, total, start_time)
                    continue
                except Exception as e:
                    failures.append((mod, path, f"Worker exception: {e}", traceback.format_exc(), "Worker", 0))
                    completed += 1
                    show_progress(completed, total, start_time)
                    continue

                module_name, ok, err, tb, err_file, err_line = res
                if ok:
                    successes += 1
                else:
                    try:
                        p_err_file = str(Path(err_file).relative_to(ROOT))
                    except (ValueError, TypeError):
                        p_err_file = err_file
                    failures.append((mod, path, err, tb, p_err_file, err_line))
                completed += 1
                if verbose or completed % 50 == 0:
                    show_progress(completed, total, start_time)
        print()  # newline after progress
    else:
        # Sequential
        for idx, (mod, path) in enumerate(modules_to_import, 1):
            if verbose:
                print(f"[{idx:4d}/{total}] {mod} ... ", end="", flush=True)
            ok, err, tb, err_file, err_line = safe_import_module(mod)
            if ok:
                successes += 1
                if verbose:
                    print(f"{GREEN}✅ SUCCESS{RESET}")
            else:
                try:
                    p_err_file = str(Path(err_file).relative_to(ROOT))
                except (ValueError, TypeError):
                    p_err_file = err_file
                failures.append((mod, path, err, tb, p_err_file, err_line))
                if verbose:
                    print(f"{RED}❌ CRASH -> {err}{RESET}")
            if not verbose and idx % 50 == 0:
                show_progress(idx, total, start_time)
        if not verbose:
            print()

    elapsed = time.monotonic() - start_time

    # 5. Deep function execution (hanya jika tidak paralel dan tidak ada failures)
    if deep and not failures and not parallel:
        print(f"\n{BOLD}{WHITE}🔍 Deep function execution (--deep) ...{RESET}")
        deep_failures = []
        for mod_name, _ in modules_to_import:
            try:
                mod = sys.modules.get(mod_name)
                if mod is None:
                    continue
                funcs = get_functions_to_call(mod, mod_name)
                for func_name, func in funcs:
                    ok, err, tb = safe_call_function(func, func_name, mod_name)
                    if not ok:
                        deep_failures.append((mod_name, func_name, err, tb))
            except Exception as e:
                deep_failures.append((mod_name, "<enumeration>", str(e), traceback.format_exc()))
        if deep_failures:
            print(f"{RED}{BOLD}❌ Found {len(deep_failures)} runtime errors inside functions:{RESET}")
            for mod_name, func_name, err, tb in deep_failures:
                print(f"  {RED}✖{RESET} {mod_name}.{func_name}() -> {err}")
                if verbose and tb:
                    print(tb)
            print(f"\n{RED}{BOLD}🛑 DEPLOYMENT GUARD: FAILED due to deep runtime errors.{RESET}\n")
            sys.exit(1)
        else:
            print(f"{GREEN}✅ All callable functions executed without errors.{RESET}")

    # ─── FINAL REPORT ────────────────────────────────────────────────────
    print("\n" + "═" * 80)
    print(f"{BOLD}📊 FINAL RUNTIME AUDIT REPORT{RESET}")
    print(f"  • Total Modules Imported  : {total}")
    print(f"  • Successfully Loaded     : {BOLD}{GREEN}{successes}{RESET}")
    print(f"  • Fatal Crashes           : {BOLD}{RED if failures else GREEN}{len(failures)}{RESET}")
    if parallel:
        print(f"  • Parallel workers        : {workers}")
    if skip_imported:
        print("  • Skipped already imported: yes")
    print(f"  • Execution Duration      : {elapsed:.2f}s")
    print("═" * 80)

    if failures:
        print(f"\n{RED}{BOLD}🚨 FATAL CRASH LOGS DETECTED ({len(failures)}):{RESET}")
        # Tampilkan hanya 10 error pertama agar tidak terlalu panjang
        for idx, (mod, path, err, tb, err_file, err_line) in enumerate(failures[:10], 1):
            rel_path = str(path.relative_to(ROOT)) if path.parent != ROOT else path.name
            print(f"\n  {BOLD}{idx}. Module: {CYAN}{mod}{RESET}")
            print(f"     📍 File          : {rel_path}")
            print(f"     🔥 Error         : {RED}{err}{RESET}")
            print(f"     🎯 Location      : {MAGENTA}{err_file}{RESET} line {BOLD}{YELLOW}{err_line}{RESET}")
            if verbose and tb:
                print(f"     📚 Stack trace:\n{tb}")
        if len(failures) > 10:
            print(f"\n  ... and {len(failures)-10} more errors. Run with --verbose to see all.")
        print(f"\n{RED}{BOLD}🛑 DEPLOYMENT GUARD: FAILED. Fix the issues listed above.{RESET}\n")
        sys.exit(1)
    else:
        print(f"\n{GREEN}{BOLD}🎉 DEPLOYMENT GUARD: PASSED. All modules boot up successfully!{RESET}\n")
        sys.exit(0)

# ─── Helper untuk deep scan (diperlukan) ──────────────────────────────────

def get_functions_to_call(module, module_name: str) -> list[tuple[str, Any]]:
    functions = []
    for name, obj in module.__dict__.items():
        if callable(obj) and not name.startswith("_"):
            try:
                import inspect
                sig = inspect.signature(obj)
                params = sig.parameters
                if all(p.default != inspect.Parameter.empty for p in params.values()) or len(params) == 0:
                    functions.append((name, obj))
            except (ValueError, TypeError):
                continue
    return functions

def safe_call_function(func, func_name: str, module_name: str) -> tuple[bool, str | None, str]:
    try:
        func()
        return True, None, ""
    except SystemExit as e:
        if e.code == 0 or e.code is None:
            return True, None, ""
        else:
            return False, f"SystemExit({e.code})", traceback.format_exc()
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        return False, f"{type(e).__name__}: {e!s}", traceback.format_exc()

# ─── CLI ──────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Runtime Error Detector (Fast + Skip Checker)")
    parser.add_argument("--verbose", action="store_true", help="Show full stack traces")
    parser.add_argument("--skip-tests", action="store_true", help="Skip tests/ directory")
    parser.add_argument("--skip-migrations", action="store_true", help="Skip migrations/ directory")
    parser.add_argument("--deep", action="store_true", help="Attempt to call parameterless functions (sequential only)")
    parser.add_argument("--parallel", action="store_true", help="Use parallel import (fast)")
    parser.add_argument("--workers", type=int, default=multiprocessing.cpu_count(),
                        help="Number of parallel workers (default: CPU count)")
    parser.add_argument("--skip-imported", action="store_true", help="Skip modules already in sys.modules")
    parser.add_argument("--fast", action="store_true", help="Alias for --skip-imported --parallel --workers 4")
    args = parser.parse_args()

    if args.fast:
        args.skip_imported = True
        args.parallel = True
        if args.workers == multiprocessing.cpu_count():  # jika tidak diubah manual
            args.workers = 4

    audit_runtime_imports(
        verbose=args.verbose,
        skip_tests=args.skip_tests,
        skip_migrations=args.skip_migrations,
        deep=args.deep,
        parallel=args.parallel,
        workers=args.workers,
        skip_imported=args.skip_imported,
    )

if __name__ == "__main__":
    main()
