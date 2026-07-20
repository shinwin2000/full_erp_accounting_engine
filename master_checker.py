#!/usr/bin/env python3
"""
checker/master_checker.py
==========================================================================
MASTER CHECKER — Penggabung Seluruh Checker Menjadi 1 Output Menyeluruh
==========================================================================
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# ==========================================================================
# 1. REGISTRY — daftar seluruh checker
# ==========================================================================
CATEGORY_ARCH = "Arsitektur & Struktur Kode"
CATEGORY_ACCOUNTING = "Domain Akuntansi & Keuangan"
CATEGORY_SECURITY = "Keamanan"
CATEGORY_RUNTIME = "Runtime, Integrasi & Kualitas"
CATEGORY_GOVERNANCE = "Governance / Aturan Proyek"
CATEGORY_ENTERPRISE_AUDIT_DETAIL = "Enterprise Audit Detail (16 tes)"
CATEGORY_ENTERPRISE_CHECKER_DETAIL = "Enterprise Checker Detail (32 tes)"

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
    # Dua checker pytest baru (eksternal, tanpa --json)
    {"module": "pytest_checker_1", "category": CATEGORY_RUNTIME, "json": False, "heavy": False, "external": True, "args": ["."]},
    {"module": "pytest_checker_2", "category": CATEGORY_RUNTIME, "json": False, "heavy": False, "external": True, "args": ["."]},
    {"module": "smoke_test", "category": CATEGORY_RUNTIME, "json": False, "heavy": True},

    # --- Governance ---
    {"module": "constitution_checker", "category": CATEGORY_GOVERNANCE, "json": True, "heavy": False},
    {"module": "ethics_checker", "category": CATEGORY_GOVERNANCE, "json": True, "heavy": False},
    {"module": "legal_checker", "category": CATEGORY_GOVERNANCE, "json": True, "heavy": False},
    {"module": "compliance_checker", "category": CATEGORY_GOVERNANCE, "json": True, "heavy": False},
    {"module": "immutable_laws_checker", "category": CATEGORY_GOVERNANCE, "json": True, "heavy": False},
    {"module": "axioms_checker", "category": CATEGORY_GOVERNANCE, "json": False, "heavy": False},

    # --- Dua checker eksternal utama ---
    {"module": "enterprise_audit_checker", "category": CATEGORY_ACCOUNTING, "json": True, "heavy": False, "external": True},
    {"module": "enterprise_checker", "category": CATEGORY_ACCOUNTING, "json": False, "heavy": True, "external": True},
]

# Validasi duplikat
_seen = set()
for _row in CHECKER_REGISTRY:
    assert _row["module"] not in _seen, f"Duplikat: {_row['module']}"
    _seen.add(_row["module"])

# Key untuk cari skor
SCORE_KEY_CANDIDATES = [
    "overall_score", "score", "final_score", "score_percent",
    "score_percentage", "health_score", "compliance_score",
    "overall_quality_score", "quality_score", "overall_health_score",
]
PASSED_KEY_CANDIDATES = ["passed", "is_passed", "success"]
NESTED_CONTAINERS = ["metadata", "summary", "report", "result"]

TIMEOUT_DEFAULT = 500
TIMEOUT_OVERRIDES = {
    "checker_integration": 800,
    "smoke_test": 800,
    "pytest_checker": 600,
    "checker_external_services": 120,
    "checker_startup_runtime": 600,
    "runtime_exhaustive_checker": 600,
    "checker_unified_import_validator": 600,
    "enterprise_checker": 1200,
    "enterprise_audit_checker": 600,
    "checker_dashboard_port_status": 120,
    "architecture_drift_checker": 300,
    "circular_dependency_checker": 300,
    "dead_code_checker": 600,
    "dependency_graph_checker": 200,
    "duplicate_symbol_checker": 300,
    "layer_checker": 300,
    "interface_checker": 300,
    "pytest_checker_1": 300,
    "pytest_checker_2": 300,
}

@dataclass
class CheckerRun:
    module: str
    category: str
    supports_json: bool
    external: bool = False
    ok: bool = False
    returncode: int | None = None
    score: float | None = None
    binary_score: bool = False
    duration_sec: float = 0.0
    error: str | None = None
    status: str = "ERROR"
    details: str = ""
    extra_info: str = ""

# ==========================================================================
# Fungsi bantu
# ==========================================================================

def find_score(data: Any) -> tuple[float, bool] | None:
    if not isinstance(data, dict):
        return None
    for key in SCORE_KEY_CANDIDATES:
        if key in data and isinstance(data[key], (int, float)):
            val = float(data[key])
            if 0.0 <= val <= 1.0 and key not in ("score", "overall_score", "final_score"):
                val *= 100.0
            return (val, True)
    for container in NESTED_CONTAINERS:
        if container in data and isinstance(data[container], dict):
            found = find_score(data[container])
            if found:
                return found
    for key in PASSED_KEY_CANDIDATES:
        if key in data and isinstance(data[key], bool):
            return (100.0 if data[key] else 0.0, False)
    for container in NESTED_CONTAINERS:
        if container in data and isinstance(data[container], dict):
            for key in PASSED_KEY_CANDIDATES:
                if key in data[container] and isinstance(data[container][key], bool):
                    return (100.0 if data[container][key] else 0.0, False)
    return None

def extract_extra_info(text: str) -> str:
    lines = text.splitlines()
    infos = []
    patterns = [
        (r"(\d+)\s+pelanggaran", "pelanggaran"),
        (r"(\d+)\s+violations?", "violations"),
        (r"(\d+)\s+warnings?", "warnings"),
        (r"(\d+)\s+errors?", "errors"),
        (r"(\d+)\s+issues?", "issues"),
        (r"(\d+)\s+fail", "fail"),
        (r"(\d+)\s+passed", "passed"),
        (r"(\d+)\s+skipped", "skipped"),
        (r"score[:\s]+([\d.]+)", "score"),
        (r"overall[:\s]+([\d.]+)", "overall"),
    ]
    for line in lines:
        for pat, label in patterns:
            m = re.search(pat, line, re.I)
            if m:
                infos.append(f"{label}={m.group(1)}")
                break
    if infos:
        return " | ".join(infos[:5])
    for line in lines:
        if line.strip() and not line.startswith("=") and not line.startswith("-"):
            return line.strip()[:120]
    return ""

# ==========================================================================
# Parsing sub-checker untuk enterprise_audit dan enterprise_checker
# ==========================================================================

def parse_enterprise_audit_report(report_path: Path) -> list[CheckerRun]:
    sub_runs = []
    if not report_path.exists():
        return sub_runs
    try:
        with open(report_path, encoding="utf-8") as f:
            data = json.load(f)
        results = data.get("results", [])
        for item in results:
            name = item.get("name", "unknown")
            passed = item.get("passed", False)
            severity = item.get("severity", "INFO")
            duration = item.get("duration_seconds", 0.0)
            error = item.get("error")
            suggested_fix = item.get("suggested_fix")
            score = 100.0 if passed else 0.0
            status = "PASS" if passed else ("ERROR" if error else "FAIL")
            run = CheckerRun(
                module=f"  └─ {name}",
                category=CATEGORY_ENTERPRISE_AUDIT_DETAIL,
                supports_json=False,
                external=False,
                ok=True,
                returncode=0,
                score=score,
                binary_score=False,
                duration_sec=duration,
                error=error if error else None,
                status=status,
                details="",
                extra_info=f"severity={severity}" + (f" fix={suggested_fix}" if suggested_fix else "")
            )
            sub_runs.append(run)
    except Exception:
        pass
    return sub_runs

def parse_enterprise_checker_output(output: str) -> list[CheckerRun]:
    """Parse output dari enterprise_checker (32 tes)."""
    sub_runs = []
    lines = output.splitlines()
    patterns = [
        re.compile(r"^(?P<icon>[✅❌⚠️])\s*(?:\[[^\]]+\]\s*)?(?P<name>.+?)\s*\((?P<duration>[\d.]+)s\)", re.I),
        re.compile(r"^(?P<status>PASS|FAIL|ERROR)\s+(?P<name>.+?)\s+\((?P<duration>[\d.]+)s\)", re.I),
        re.compile(r"^(?P<name>.+?):\s*(?P<status>PASS|FAIL|ERROR)", re.I),
    ]
    seen_names = set()
    for line in lines:
        for pat in patterns[:2]:
            m = pat.search(line)
            if m:
                name = m.group("name").strip()
                if name in seen_names:
                    continue
                seen_names.add(name)
                duration = float(m.group("duration")) if "duration" in m.groupdict() else 0.0
                if "icon" in m.groupdict():
                    icon = m.group("icon")
                    status = "PASS" if icon == "✅" else ("FAIL" if icon == "❌" else "ERROR")
                else:
                    status = m.group("status").upper()
                score = 100.0 if status == "PASS" else 0.0
                sc = re.search(r"skor=([\d.]+)", line)
                if sc:
                    score = float(sc.group(1))
                run = CheckerRun(
                    module=f"  └─ {name}",
                    category=CATEGORY_ENTERPRISE_CHECKER_DETAIL,
                    supports_json=False,
                    external=False,
                    ok=True,
                    returncode=0,
                    score=score,
                    binary_score=False,
                    duration_sec=duration,
                    error=None,
                    status=status,
                    details="",
                    extra_info=""
                )
                sub_runs.append(run)
                break
        else:
            m = patterns[2].search(line)
            if m:
                name = m.group("name").strip()
                if name in seen_names:
                    continue
                seen_names.add(name)
                status = m.group("status").upper()
                score = 100.0 if status == "PASS" else 0.0
                dur = re.search(r"\(([\d.]+)s\)", line)
                duration = float(dur.group(1)) if dur else 0.0
                run = CheckerRun(
                    module=f"  └─ {name}",
                    category=CATEGORY_ENTERPRISE_CHECKER_DETAIL,
                    supports_json=False,
                    external=False,
                    ok=True,
                    returncode=0,
                    score=score,
                    binary_score=False,
                    duration_sec=duration,
                    error=None,
                    status=status,
                    details="",
                    extra_info=""
                )
                sub_runs.append(run)
    return sub_runs

# ==========================================================================
# Menjalankan satu checker
# ==========================================================================

def run_one_checker(row: dict, project_root: Path, package_name: str, timeout: int) -> tuple[CheckerRun, list[CheckerRun]]:
    module = row["module"]
    run = CheckerRun(
        module=module,
        category=row["category"],
        supports_json=row["json"],
        external=row.get("external", False)
    )
    sub_runs: list[CheckerRun] = []

    is_external = run.external
    script_path = None
    if is_external:
        candidates = [
            project_root / "checker" / f"{module}.py",
            project_root / f"{module}.py"
        ]
        for cand in candidates:
            if cand.exists():
                script_path = cand
                break
        if not script_path:
            run.error = f"File {module}.py tidak ditemukan"
            run.status = "ERROR"
            return run, sub_runs
        cmd = [sys.executable, str(script_path)]
        # Tambahkan argumen tambahan jika ada
        if "args" in row:
            cmd.extend(row["args"])
        cwd = str(project_root)
    else:
        cmd = [sys.executable, "-m", f"{package_name}.{module}"]
        json_path = None
        if row["json"]:
            fd, json_path = tempfile.mkstemp(prefix=f"mc_{module}_", suffix=".json")
            os.close(fd)
            cmd.append("--json")
            cmd.append(json_path)
        cwd = str(project_root)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    start = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, env=env,
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace"
        )
        run.ok = True
        run.returncode = proc.returncode

        output = proc.stdout + "\n" + proc.stderr
        run.details = output[:3000]
        run.extra_info = extract_extra_info(output)

        score = None
        binary = True

        if is_external:
            if module == "enterprise_audit_checker":
                report_file = project_root / "enterprise_audit_report.json"
                if report_file.exists():
                    try:
                        with open(report_file, encoding="utf-8") as f:
                            data = json.load(f)
                        if "summary" in data and "score_percent" in data["summary"]:
                            score = float(data["summary"]["score_percent"])
                            binary = False
                        sub_runs = parse_enterprise_audit_report(report_file)
                    except Exception as e:
                        run.error = f"Gagal baca JSON audit: {e}"
                else:
                    run.error = "File enterprise_audit_report.json tidak ditemukan"
            elif module == "enterprise_checker":
                m = re.search(r"Total:\s*(\d+)\s*\|\s*Passed:\s*(\d+)", output)
                if m:
                    total = int(m.group(1))
                    passed = int(m.group(2))
                    if total > 0:
                        score = (passed / total) * 100.0
                        binary = False
                    else:
                        score = 0.0
                else:
                    score = 100.0 if proc.returncode == 0 else 0.0
                    binary = True
                sub_runs = parse_enterprise_checker_output(output)
            else:
                # External checker lain (pytest_checker_1, pytest_checker_2)
                # Mereka biasanya tidak menghasilkan JSON, fallback ke exit code
                score = 100.0 if proc.returncode == 0 else 0.0
                binary = True
                # Coba parse output untuk mendapatkan skor (jika ada)
                # Misal pytest_checker_2 menampilkan "Quality Score : 75.00%"
                m = re.search(r"Quality Score\s*:\s*([\d.]+)%", output, re.I)
                if m:
                    score = float(m.group(1))
                    binary = False
                # Atau "SKOR KUALITAS: 75.00%"
                m = re.search(r"SKOR KUALITAS\s*:\s*([\d.]+)%", output, re.I)
                if m:
                    score = float(m.group(1))
                    binary = False
        else:
            # Checker standar
            if row["json"] and json_path and os.path.exists(json_path) and os.path.getsize(json_path) > 0:
                try:
                    with open(json_path, encoding="utf-8") as f:
                        data = json.load(f)
                    found = find_score(data)
                    if found:
                        score, binary = found[0], not found[1]
                    else:
                        score = 100.0 if proc.returncode == 0 else 0.0
                        binary = True
                except Exception as e:
                    run.error = f"Gagal baca JSON: {e}"
                    score = 100.0 if proc.returncode == 0 else 0.0
                    binary = True
            else:
                score = 100.0 if proc.returncode == 0 else 0.0
                binary = True
                if row["json"]:
                    run.error = "File JSON tidak dihasilkan"

        if score is not None:
            run.score = max(0.0, min(100.0, score))
            run.binary_score = binary
            run.status = "PASS" if run.score >= 80 else "FAIL"
        else:
            run.status = "ERROR"

        if proc.returncode != 0 and not run.error:
            run.error = f"Exit code {proc.returncode}"

    except subprocess.TimeoutExpired:
        run.status = "ERROR"
        run.error = f"Timeout > {timeout}s"
    except Exception as e:
        run.status = "ERROR"
        run.error = f"{e.__class__.__name__}: {e}"
    finally:
        run.duration_sec = time.time() - start
        if not is_external and row["json"] and json_path and os.path.exists(json_path):
            try:
                os.remove(json_path)
            except:
                pass

    return run, sub_runs

# ==========================================================================
# Tampilan laporan
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
    return {"PASS": c.GREEN, "FAIL": c.RED, "ERROR": c.YELLOW}.get(status, "")

def print_report(runs: list[CheckerRun], c: Colors, fail_under: float, elapsed: float) -> dict[str, Any]:
    by_category: dict[str, list[CheckerRun]] = {}
    for r in runs:
        by_category.setdefault(r.category, []).append(r)

    print(f"\n{c.BOLD}{'=' * 80}{c.RESET}")
    print(f"{c.BOLD}  LAPORAN GABUNGAN SELURUH CHECKER  ({len(runs)} checker dijalankan){c.RESET}")
    print(f"{c.BOLD}{'=' * 80}{c.RESET}")

    main_cats = [CATEGORY_ARCH, CATEGORY_ACCOUNTING, CATEGORY_SECURITY, CATEGORY_RUNTIME, CATEGORY_GOVERNANCE]
    detail_cats = [CATEGORY_ENTERPRISE_AUDIT_DETAIL, CATEGORY_ENTERPRISE_CHECKER_DETAIL]
    for cat in main_cats + detail_cats:
        items = by_category.get(cat, [])
        if not items:
            continue
        print(f"\n{c.CYAN}{c.BOLD}## {cat}{c.RESET}")
        for r in sorted(items, key=lambda x: x.module):
            if cat.startswith("Enterprise"):
                tag = f"{status_color(c, r.status)}{r.status:<5}{c.RESET}"
                score_txt = "   -  " if r.score is None else f"{r.score:5.1f}"
                err_txt = f"  {c.DIM}{r.error}{c.RESET}" if r.error else ""
                extra = f"  {c.DIM}{r.extra_info}{c.RESET}" if r.extra_info else ""
                print(f"  {r.module:<42} skor={score_txt} ({r.duration_sec:5.1f}s){err_txt}{extra}")
            else:
                tag = f"{status_color(c, r.status)}{r.status:<5}{c.RESET}"
                score_txt = "   -  " if r.score is None else f"{r.score:5.1f}"
                bin_tag = f"{c.DIM}[BINARY]{c.RESET}" if r.binary_score else "        "
                err_txt = f"  {c.DIM}{r.error}{c.RESET}" if r.error else ""
                extra = f"  {c.DIM}{r.extra_info}{c.RESET}" if r.extra_info else ""
                print(f"  [{tag}] {r.module:<42} skor={score_txt} {bin_tag} ({r.duration_sec:5.1f}s){err_txt}{extra}")

    scored = [r.score for r in runs if r.score is not None]
    n_pass = sum(1 for r in runs if r.status == "PASS")
    n_fail = sum(1 for r in runs if r.status == "FAIL")
    n_error = sum(1 for r in runs if r.status == "ERROR")
    overall = round(statistics.mean(scored), 2) if scored else 0.0

    print(f"\n{c.BOLD}{'-' * 80}{c.RESET}")
    print(f"{c.BOLD}RINGKASAN PER KATEGORI (rata-rata skor proporsional){c.RESET}")
    for cat in main_cats:
        items = by_category.get(cat, [])
        cat_scores = [r.score for r in items if r.score is not None]
        cat_avg = round(statistics.mean(cat_scores), 1) if cat_scores else 0.0
        print(f"  - {cat:<32} : {cat_avg:5.1f} / 100  ({len(items)} checker)")
    for cat in detail_cats:
        items = by_category.get(cat, [])
        if items:
            cat_scores = [r.score for r in items if r.score is not None]
            cat_avg = round(statistics.mean(cat_scores), 1) if cat_scores else 0.0
            print(f"  - {cat:<32} : {cat_avg:5.1f} / 100  ({len(items)} sub-checker)")

    print(f"\n{c.BOLD}TOTAL{c.RESET}")
    print(f"  PASS  : {c.GREEN}{n_pass}{c.RESET}")
    print(f"  FAIL  : {c.RED}{n_fail}{c.RESET}")
    print(f"  ERROR : {c.YELLOW}{n_error}{c.RESET}")
    print(f"  Waktu total : {elapsed:.1f}s")

    final_color = c.GREEN if overall >= fail_under else c.RED
    print(f"\n{c.BOLD}SKOR AKHIR PROPORSIONAL : {final_color}{overall:.2f} / 100{c.RESET}")
    verdict = "LULUS" if (overall >= fail_under and n_error == 0) else "TIDAK LULUS"
    verdict_color = c.GREEN if verdict == "LULUS" else c.RED
    print(f"VERDICT                  : {verdict_color}{c.BOLD}{verdict}{c.RESET}")
    print(f"{c.BOLD}{'=' * 80}{c.RESET}\n")

    return {
        "overall_score": overall,
        "verdict": verdict,
        "total_checkers": len(runs),
        "pass": n_pass,
        "fail": n_fail,
        "error": n_error,
        "elapsed_sec": round(elapsed, 2),
        "by_category": {
            cat: round(statistics.mean([r.score for r in by_category.get(cat, []) if r.score is not None]), 1)
            if any(r.score is not None for r in by_category.get(cat, [])) else 0.0
            for cat in main_cats + detail_cats
        },
        "checkers": [asdict(r) for r in runs],
    }

# ==========================================================================
# Auto-detect
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
# Main
# ==========================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="Master Checker")
    parser.add_argument("--only", type=str, help="Comma-separated checker names")
    parser.add_argument("--exclude", type=str, help="Comma-separated checker names to exclude")
    parser.add_argument("--workers", type=int, default=8, help="Parallel workers (default 8)")
    parser.add_argument("--timeout", type=int, default=None, help="Global timeout per checker")
    parser.add_argument("--json", type=str, help="Save combined report to JSON")
    parser.add_argument("--fail-under", type=float, default=80.0, help="Passing threshold (default 80)")
    parser.add_argument("--no-color", action="store_true", help="Disable colors")
    parser.add_argument("--list", action="store_true", help="List all checkers")
    parser.add_argument("--project-root", type=str, help="Override project root")
    parser.add_argument("--package-name", type=str, help="Override package name")
    parser.add_argument("--skip-heavy", action="store_true", help="Skip heavy checkers")
    args = parser.parse_args()

    auto_root, auto_package = detect_project_root_and_package(Path(__file__))
    project_root = Path(args.project_root).resolve() if args.project_root else auto_root
    package_name = args.package_name if args.package_name else auto_package

    registry = CHECKER_REGISTRY
    if args.only:
        wanted = {m.strip() for m in args.only.split(",") if m.strip()}
        registry = [r for r in registry if r["module"] in wanted]
    if args.exclude:
        excluded = {m.strip() for m in args.exclude.split(",") if m.strip()}
        registry = [r for r in registry if r["module"] not in excluded]
    if args.skip_heavy:
        registry = [r for r in registry if not r.get("heavy", False)]

    if args.list:
        for r in CHECKER_REGISTRY:
            mode = "json " if r["json"] else "binary"
            heavy = " HEAVY" if r.get("heavy") else ""
            ext = " EXTERNAL" if r.get("external") else ""
            print(f"[{mode}] {r['category']:<32} {r['module']}{heavy}{ext}")
        print(f"\nTotal: {len(CHECKER_REGISTRY)} checker terdaftar.")
        return 0

    c = Colors(enabled=not args.no_color and sys.stdout.isatty())

    print(f"{c.BOLD}Project root  : {project_root}{c.RESET}")
    print(f"{c.BOLD}Package       : {package_name}{c.RESET}")
    print(f"{c.BOLD}Menjalankan {len(registry)} checker secara paralel (workers={args.workers})...{c.RESET}")

    start = time.time()
    all_runs: list[CheckerRun] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {}
        for row in registry:
            timeout = args.timeout if args.timeout is not None else TIMEOUT_OVERRIDES.get(row["module"], TIMEOUT_DEFAULT)
            futures[executor.submit(run_one_checker, row, project_root, package_name, timeout)] = row

        done = 0
        for future in concurrent.futures.as_completed(futures):
            row = futures[future]
            done += 1
            try:
                main_run, sub_runs = future.result()
            except Exception as exc:
                main_run = CheckerRun(
                    module=row["module"],
                    category=row["category"],
                    supports_json=row["json"],
                    external=row.get("external", False),
                    ok=False,
                    status="ERROR",
                    error=f"Unhandled: {exc}"
                )
                sub_runs = []
            all_runs.append(main_run)
            if sub_runs:
                all_runs.extend(sub_runs)
            print(f"  {c.DIM}[{done}/{len(registry)}]{c.RESET} selesai: {main_run.module} -> {main_run.status} ({main_run.duration_sec:.1f}s)")

    elapsed = time.time() - start
    result = print_report(all_runs, c, args.fail_under, elapsed)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"Laporan JSON disimpan ke: {args.json}")

    return 0 if (result["overall_score"] >= args.fail_under and result["error"] == 0) else 1

if __name__ == "__main__":
    sys.exit(main())
