#!/usr/bin/env python3
"""
checker/master_checker.py
==========================================================================
MASTER CHECKER — Penggabung Seluruh Checker Menjadi 1 Output Menyeluruh
==========================================================================

... (dokumentasi tetap sama)
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# ==========================================================================
# 1. REGISTRY — daftar seluruh checker (tidak ada yang duplikat)
# ==========================================================================
CATEGORY_ARCH = "Arsitektur & Struktur Kode"
CATEGORY_ACCOUNTING = "Domain Akuntansi & Keuangan"
CATEGORY_SECURITY = "Keamanan"
CATEGORY_RUNTIME = "Runtime, Integrasi & Kualitas"
CATEGORY_GOVERNANCE = "Governance / Aturan Proyek"

CHECKER_REGISTRY: list[dict[str, Any]] = [
    # --- Arsitektur & Struktur Kode ---
    {"module": "layer_checker", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "architecture_drift_checker", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "interface_checker", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "use_cases_checker", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "checker_port_adapter", "category": CATEGORY_ARCH, "json": False, "heavy": False},
    {"module": "checker_unified_import_validator", "category": CATEGORY_ARCH, "json": False, "heavy": True},
    {"module": "duplicate_symbol_checker", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "kernel_checker", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "checker_di_container", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "checker_di_registrations", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "repository_checker", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "mapper_checker", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "checker_cqrs_handler", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "checker_event_handler", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "checker_domain_event_publish", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "aggregate_root_checker", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "saga_checker", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "outbox_checker", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "uow_checker", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "transaction_boundary_checker", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "idempotency_checker", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "race_condition_risk_checker", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "guards_checker", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "circular_dependency_checker", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "dependency_graph_checker", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "dead_code_checker", "category": CATEGORY_ARCH, "json": True, "heavy": False},
    {"module": "transaction_leak_checker", "category": CATEGORY_ARCH, "json": True, "heavy": False},

    # --- Domain Akuntansi & Keuangan ---
    {"module": "accounting_posting_checker", "category": CATEGORY_ACCOUNTING, "json": True, "heavy": False},
    {"module": "checker_journal_balance", "category": CATEGORY_ACCOUNTING, "json": True, "heavy": False},
    {"module": "general_ledger_checker", "category": CATEGORY_ACCOUNTING, "json": True, "heavy": False},
    {"module": "coa_checker", "category": CATEGORY_ACCOUNTING, "json": True, "heavy": False},
    {"module": "fiscal_period_checker", "category": CATEGORY_ACCOUNTING, "json": True, "heavy": False},
    {"module": "tax_checker", "category": CATEGORY_ACCOUNTING, "json": True, "heavy": False},
    {"module": "money_precision_checker", "category": CATEGORY_ACCOUNTING, "json": True, "heavy": False},
    {"module": "posting_flow_checker", "category": CATEGORY_ACCOUNTING, "json": True, "heavy": False},
    {"module": "checker_audit_accounting_logic", "category": CATEGORY_ACCOUNTING, "json": True, "heavy": False},
    {"module": "inventory_integrity_checker", "category": CATEGORY_ACCOUNTING, "json": True, "heavy": False},
    {"module": "audit_trail_completeness_checker", "category": CATEGORY_ACCOUNTING, "json": True, "heavy": False},
    {"module": "ledger_replay_checker", "category": CATEGORY_ACCOUNTING, "json": True, "heavy": False},
    {"module": "double_entry_integrity_checker", "category": CATEGORY_ACCOUNTING, "json": True, "heavy": False},
    {"module": "business_rule_conflict_checker", "category": CATEGORY_ACCOUNTING, "json": True, "heavy": False},

    # --- Keamanan ---
    {"module": "sql_injection_checker", "category": CATEGORY_SECURITY, "json": True, "heavy": False},
    {"module": "secret_scanner_checker", "category": CATEGORY_SECURITY, "json": True, "heavy": False},

    # --- Runtime, Integrasi & Kualitas ---
    {"module": "exception_swallow_checker", "category": CATEGORY_RUNTIME, "json": True, "heavy": False},
    {"module": "async_safety_checker", "category": CATEGORY_RUNTIME, "json": True, "heavy": False},
    {"module": "performance_anti_pattern_checker", "category": CATEGORY_RUNTIME, "json": True, "heavy": False},
    {"module": "runtime_exhaustive_checker", "category": CATEGORY_RUNTIME, "json": True, "heavy": True},
    {"module": "checker_startup_runtime", "category": CATEGORY_RUNTIME, "json": False, "heavy": True},
    {"module": "checker_fastapi_route", "category": CATEGORY_RUNTIME, "json": False, "heavy": True},
    {"module": "checker_migrations_orm", "category": CATEGORY_RUNTIME, "json": False, "heavy": True},
    {"module": "query_checker", "category": CATEGORY_RUNTIME, "json": True, "heavy": False},
    {"module": "checker_external_services", "category": CATEGORY_RUNTIME, "json": False, "heavy": True},
    {"module": "checker_dashboard_port_status", "category": CATEGORY_RUNTIME, "json": True, "heavy": True},
    {"module": "checker_integration", "category": CATEGORY_RUNTIME, "json": True, "heavy": True},
    {"module": "pytest_checker", "category": CATEGORY_RUNTIME, "json": True, "heavy": True},
    {"module": "smoke_test", "category": CATEGORY_RUNTIME, "json": False, "heavy": True},

    # --- Governance / Aturan Proyek ---
    {"module": "constitution_checker", "category": CATEGORY_GOVERNANCE, "json": True, "heavy": False},
    {"module": "ethics_checker", "category": CATEGORY_GOVERNANCE, "json": True, "heavy": False},
    {"module": "legal_checker", "category": CATEGORY_GOVERNANCE, "json": True, "heavy": False},
    {"module": "compliance_checker", "category": CATEGORY_GOVERNANCE, "json": True, "heavy": False},
    {"module": "immutable_laws_checker", "category": CATEGORY_GOVERNANCE, "json": True, "heavy": False},
    {"module": "axioms_checker", "category": CATEGORY_GOVERNANCE, "json": False, "heavy": False},
]

# Pastikan tidak ada duplikat
_seen = set()
for _row in CHECKER_REGISTRY:
    assert _row["module"] not in _seen, f"Checker duplikat: {_row['module']}"
    _seen.add(_row["module"])

# 🔥 PERBAIKAN: tambahkan "overall_score" ke daftar kunci yang dicari
SCORE_KEY_CANDIDATES = [
    "overall_score",          # <--- baru
    "score", "overall_score", "final_score", "score_percent",
    "score_percentage", "health_score", "compliance_score",
    "overall_quality_score", "quality_score", "overall_health_score",
]
PASSED_KEY_CANDIDATES = ["passed", "is_passed", "success"]
NESTED_CONTAINERS = ["metadata", "summary", "report", "result"]

TIMEOUT_OVERRIDES = {
    "checker_integration": 600,
    "smoke_test": 600,
    "pytest_checker": 600,
    "checker_external_services": 120,
    "checker_startup_runtime": 600,
    "runtime_exhaustive_checker": 600,
    "checker_unified_import_validator": 600,
}

@dataclass
class CheckerRun:
    module: str
    category: str
    supports_json: bool
    ok: bool = False
    returncode: int | None = None
    score: float | None = None
    binary_score: bool = False
    duration_sec: float = 0.0
    error: str | None = None
    status: str = "ERROR"

def find_score(data: Any) -> tuple[float, bool] | None:
    if not isinstance(data, dict):
        return None
    for key in SCORE_KEY_CANDIDATES:
        if key in data and isinstance(data[key], (int, float)):
            val = float(data[key])
            # Normalisasi jika nilai antara 0-1 (misal 0.95)
            if 0.0 <= val <= 1.0 and key not in ("score", "overall_score", "final_score"):
                val = val * 100.0
            return (val, True)
    for container in NESTED_CONTAINERS:
        if container in data and isinstance(data[container], dict):
            found = find_score(data[container])
            if found is not None:
                return found
    # Fallback ke field boolean
    for key in PASSED_KEY_CANDIDATES:
        if key in data and isinstance(data[key], bool):
            return (100.0 if data[key] else 0.0, False)
    for container in NESTED_CONTAINERS:
        if container in data and isinstance(data[container], dict):
            for key in PASSED_KEY_CANDIDATES:
                if key in data[container] and isinstance(data[container][key], bool):
                    return (100.0 if data[container][key] else 0.0, False)
    return None

def run_one_checker(row: dict[str, Any], project_root: Path, package_name: str, timeout: int) -> CheckerRun:
    module = row["module"]
    run = CheckerRun(module=module, category=row["category"], supports_json=row["json"])

    env = os.environ.copy()
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(project_root) + (os.pathsep + existing_pp if existing_pp else "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONLEGACYWINDOWSSTDIO"] = "0"

    tmp_path = None
    cmd = [sys.executable, "-m", f"{package_name}.{module}"]
    if row["json"]:
        fd, tmp_path = tempfile.mkstemp(prefix=f"mc_{module}_", suffix=".json")
        os.close(fd)
        cmd += ["--json", tmp_path]

    start = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=str(project_root), env=env,
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        run.ok = True
        run.returncode = proc.returncode

        def _extract_from(text: str) -> list[str]:
            if not text or not text.strip():
                return []
            lines = [ln for ln in text.strip().splitlines() if ln.strip()]
            error_markers = ("Traceback", "Error", "Exception", "CRITICAL", "FATAL", "❌", "assert")
            return [ln for ln in lines if any(m in ln for m in error_markers)]

        def stderr_excerpt() -> str:
            candidates = _extract_from(proc.stderr)
            source = "stderr"
            if not candidates:
                candidates = _extract_from(proc.stdout)
                source = "stdout"
            if candidates:
                tail = candidates[-3:]
                prefix = f"[{source}] " if source == "stdout" else ""
                return prefix + " | ".join(t.strip()[:200] for t in tail)
            lines = [ln for ln in (proc.stderr or "").strip().splitlines() if ln.strip()]
            if not lines:
                lines = [ln for ln in (proc.stdout or "").strip().splitlines() if ln.strip()]
            return lines[-1].strip()[:200] if lines else ""

        if row["json"] and tmp_path and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            try:
                with open(tmp_path, encoding="utf-8", errors="replace") as fh:
                    data = json.load(fh)
                found = find_score(data)
                if found is not None:
                    score, is_granular = found
                    run.score = max(0.0, min(100.0, score))
                    run.binary_score = not is_granular
                else:
                    run.score = 100.0 if proc.returncode == 0 else 0.0
                    run.binary_score = True
                    if proc.returncode != 0:
                        run.error = stderr_excerpt() or "skor tidak ditemukan di JSON, fallback ke exit code"
            except Exception as exc:
                run.score = 100.0 if proc.returncode == 0 else 0.0
                run.binary_score = True
                run.error = f"JSON tidak terbaca ({exc.__class__.__name__})" + (
                    f" | stderr: {stderr_excerpt()}" if stderr_excerpt() else ""
                )
        else:
            run.score = 100.0 if proc.returncode == 0 else 0.0
            run.binary_score = True
            if row["json"]:
                reason = stderr_excerpt()
                run.error = (
                    f"checker tidak menghasilkan file --json | penyebab: {reason}"
                    if reason else
                    "checker tidak menghasilkan file --json (fallback ke exit code)"
                )
            elif proc.returncode != 0:
                run.error = stderr_excerpt()

        if run.score is not None and run.score >= 80:
            run.status = "PASS"
        elif run.score is not None:
            run.status = "FAIL"

    except subprocess.TimeoutExpired:
        run.ok = False
        run.status = "ERROR"
        run.error = f"Timeout > {timeout}s"
    except FileNotFoundError as exc:
        run.ok = False
        run.status = "ERROR"
        run.error = f"Modul tidak ditemukan: {exc}"
    except Exception as exc:
        run.ok = False
        run.status = "ERROR"
        run.error = f"{exc.__class__.__name__}: {exc}"
    finally:
        run.duration_sec = time.time() - start
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return run

# ==========================================================================
# 2. TAMPILAN LAPORAN (tidak berubah)
# ==========================================================================

class Colors:
    def __init__(self, enabled: bool):
        self.RED = "\033[91m" if enabled else ""
        self.GREEN = "\033[92m" if enabled else ""
        self.YELLOW = "\033[93m" if enabled else ""
        self.CYAN = "\033[96m" if enabled else ""
        self.BOLD = "\033[1m" if enabled else ""
        self.DIM = "\033[2m" if enabled else ""
        self.RESET = "\033[0m" if enabled else ""

def status_color(c: Colors, status: str) -> str:
    return {"PASS": c.GREEN, "FAIL": c.RED, "ERROR": c.YELLOW, "SKIP": c.DIM}.get(status, "")

def print_report(runs: list[CheckerRun], c: Colors, fail_under: float, elapsed: float) -> dict[str, Any]:
    by_category: dict[str, list[CheckerRun]] = {}
    for r in runs:
        by_category.setdefault(r.category, []).append(r)

    print(f"\n{c.BOLD}{'=' * 78}{c.RESET}")
    print(f"{c.BOLD}  LAPORAN GABUNGAN SELURUH CHECKER  ({len(runs)} checker dijalankan){c.RESET}")
    print(f"{c.BOLD}{'=' * 78}{c.RESET}")

    for category, items in by_category.items():
        print(f"\n{c.CYAN}{c.BOLD}## {category}{c.RESET}")
        for r in sorted(items, key=lambda x: x.module):
            tag = f"{status_color(c, r.status)}{r.status:<5}{c.RESET}"
            score_txt = "   -  " if r.score is None else f"{r.score:5.1f}"
            bin_tag = f"{c.DIM}[BINARY]{c.RESET}" if r.binary_score else "        "
            err_txt = f"  {c.DIM}{r.error}{c.RESET}" if r.error else ""
            print(f"  [{tag}] {r.module:<42} skor={score_txt} {bin_tag} ({r.duration_sec:5.1f}s){err_txt}")

    scored = [r.score for r in runs if r.score is not None]
    n_pass = sum(1 for r in runs if r.status == "PASS")
    n_fail = sum(1 for r in runs if r.status == "FAIL")
    n_error = sum(1 for r in runs if r.status == "ERROR")
    overall = round(statistics.mean(scored), 2) if scored else 0.0

    print(f"\n{c.BOLD}{'-' * 78}{c.RESET}")
    print(f"{c.BOLD}RINGKASAN PER KATEGORI (rata-rata skor proporsional){c.RESET}")
    for category, items in by_category.items():
        cat_scores = [r.score for r in items if r.score is not None]
        cat_avg = round(statistics.mean(cat_scores), 1) if cat_scores else 0.0
        print(f"  - {category:<32} : {cat_avg:5.1f} / 100  ({len(items)} checker)")

    print(f"\n{c.BOLD}TOTAL{c.RESET}")
    print(f"  PASS  : {c.GREEN}{n_pass}{c.RESET}")
    print(f"  FAIL  : {c.RED}{n_fail}{c.RESET}")
    print(f"  ERROR : {c.YELLOW}{n_error}{c.RESET}  (checker gagal dijalankan / timeout / crash)")
    print(f"  Waktu total : {elapsed:.1f}s")

    final_color = c.GREEN if overall >= fail_under else c.RED
    print(f"\n{c.BOLD}SKOR AKHIR PROPORSIONAL : {final_color}{overall:.2f} / 100{c.RESET}")
    verdict = "LULUS" if (overall >= fail_under and n_error == 0) else "TIDAK LULUS"
    verdict_color = c.GREEN if verdict == "LULUS" else c.RED
    print(f"VERDICT                  : {verdict_color}{c.BOLD}{verdict}{c.RESET}")
    print(f"{c.BOLD}{'=' * 78}{c.RESET}\n")

    return {
        "overall_score": overall,
        "verdict": verdict,
        "total_checkers": len(runs),
        "pass": n_pass,
        "fail": n_fail,
        "error": n_error,
        "elapsed_sec": round(elapsed, 2),
        "by_category": {
            cat: round(statistics.mean([r.score for r in items if r.score is not None]), 1)
            if any(r.score is not None for r in items) else 0.0
            for cat, items in by_category.items()
        },
        "checkers": [asdict(r) for r in runs],
    }

# ==========================================================================
# 3. AUTO-DETEKSI LOKASI (tidak berubah)
# ==========================================================================

def detect_project_root_and_package(script_path: Path) -> tuple[Path, str]:
    script_dir = script_path.resolve().parent
    known_modules = {r["module"] for r in CHECKER_REGISTRY}

    if (script_dir / "__init__.py").exists():
        py_stems = {p.stem for p in script_dir.glob("*.py")}
        if len(py_stems & known_modules) >= 5:
            return script_dir.parent, script_dir.name

    candidate = script_dir / "checker"
    if (candidate / "__init__.py").exists():
        py_stems = {p.stem for p in candidate.glob("*.py")}
        if len(py_stems & known_modules) >= 5:
            return script_dir, "checker"

    try:
        for sub in script_dir.iterdir():
            if sub.is_dir() and (sub / "__init__.py").exists():
                py_stems = {p.stem for p in sub.glob("*.py")}
                if len(py_stems & known_modules) >= 5:
                    return script_dir, sub.name
    except OSError:
        pass

    return script_dir.parent, script_dir.name

# ==========================================================================
# 4. ENTRY POINT (tidak berubah)
# ==========================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Menjalankan seluruh checker di folder checker/ dan menggabungkan hasilnya jadi 1 laporan."
    )
    parser.add_argument("--only", type=str, default=None,
                         help="Comma-separated nama modul checker yang ingin dijalankan saja.")
    parser.add_argument("--exclude", type=str, default=None,
                         help="Comma-separated nama modul checker yang ingin dilewati.")
    parser.add_argument("--workers", type=int, default=4, help="Jumlah checker paralel (default 4).")
    parser.add_argument("--timeout", type=int, default=600, help="Timeout per checker dalam detik (default 600).")
    parser.add_argument("--json", type=str, default=None, help="Simpan laporan gabungan ke file JSON ini.")
    parser.add_argument("--fail-under", type=float, default=80.0,
                         help="Ambang skor akhir untuk dianggap LULUS (default 80).")
    parser.add_argument("--no-color", action="store_true", help="Matikan warna terminal.")
    parser.add_argument("--list", action="store_true", help="Tampilkan daftar checker lalu keluar.")
    parser.add_argument("--project-root", type=str, default=None,
                         help="Paksa root project secara manual (override auto-deteksi).")
    parser.add_argument("--package-name", type=str, default=None,
                         help="Paksa nama package checker secara manual, default: auto-deteksi (biasanya 'checker').")
    args = parser.parse_args()

    auto_root, auto_package = detect_project_root_and_package(Path(__file__))
    project_root = Path(args.project_root).resolve() if args.project_root else auto_root
    package_name = args.package_name if args.package_name else auto_package

    package_dir = project_root / package_name
    if not (package_dir / "__init__.py").exists():
        print(
            f"[PERINGATAN] Tidak menemukan '{package_dir}\\__init__.py'.\n"
            f"  project_root  = {project_root}\n"
            f"  package_name  = {package_name}\n"
            f"  Jika ini salah, jalankan ulang dengan:\n"
            f"    --project-root \"<folder yang berisi folder {package_name}>\" --package-name {package_name}\n"
        )

    registry = CHECKER_REGISTRY
    if args.only:
        wanted = {m.strip() for m in args.only.split(",") if m.strip()}
        registry = [r for r in registry if r["module"] in wanted]
    if args.exclude:
        excluded = {m.strip() for m in args.exclude.split(",") if m.strip()}
        registry = [r for r in registry if r["module"] not in excluded]

    if args.list:
        for r in CHECKER_REGISTRY:
            mode = "json " if r["json"] else "binary"
            print(f"[{mode}] {r['category']:<32} {r['module']}")
        print(f"\nTotal: {len(CHECKER_REGISTRY)} checker terdaftar (tidak ada duplikat).")
        return 0

    c = Colors(enabled=not args.no_color and sys.stdout.isatty())

    static_batch = [r for r in registry if not r.get("heavy")]
    heavy_batch = [r for r in registry if r.get("heavy")]

    print(f"{c.BOLD}Project root  : {project_root}{c.RESET}")
    print(f"{c.BOLD}Package       : {package_name}  (dari {package_dir}){c.RESET}")
    print(f"{c.BOLD}Menjalankan {len(static_batch)} checker analisis-statis (paralel, workers={args.workers})"
          f" + {len(heavy_batch)} checker runtime/heavy (berurutan, satu-satu)...{c.RESET}")
    if heavy_batch:
        print(f"{c.DIM}  (checker heavy benar-benar mengimpor/menjalankan aplikasi Anda -- "
              f"sengaja dijalankan satu-satu supaya tidak rebutan resource DB/port/dsb){c.RESET}")

    start = time.time()
    runs: list[CheckerRun] = []

    if static_batch:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {
                pool.submit(run_one_checker, row, project_root, package_name, args.timeout): row
                for row in static_batch
            }
            done_count = 0
            for fut in concurrent.futures.as_completed(futures):
                row = futures[fut]
                done_count += 1
                try:
                    run = fut.result()
                except Exception as exc:
                    run = CheckerRun(module=row["module"], category=row["category"],
                                      supports_json=row["json"], ok=False, status="ERROR",
                                      error=f"Unhandled: {exc}")
                runs.append(run)
                print(f"  {c.DIM}[{done_count}/{len(static_batch)}]{c.RESET} selesai: {run.module}")

    for i, row in enumerate(heavy_batch, start=1):
        timeout = TIMEOUT_OVERRIDES.get(row["module"], args.timeout)
        print(f"  {c.DIM}[heavy {i}/{len(heavy_batch)}]{c.RESET} menjalankan: {row['module']} (timeout={timeout}s) ...")
        try:
            run = run_one_checker(row, project_root, package_name, timeout)
        except Exception as exc:
            run = CheckerRun(module=row["module"], category=row["category"],
                              supports_json=row["json"], ok=False, status="ERROR",
                              error=f"Unhandled: {exc}")
        runs.append(run)
        print(f"  {c.DIM}[heavy {i}/{len(heavy_batch)}]{c.RESET} selesai: {run.module} -> {run.status}")

    elapsed = time.time() - start
    result = print_report(runs, c, args.fail_under, elapsed)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, ensure_ascii=False)
        print(f"Laporan JSON gabungan disimpan ke: {args.json}")

    return 0 if (result["overall_score"] >= args.fail_under and result["error"] == 0) else 1

if __name__ == "__main__":
    sys.exit(main())