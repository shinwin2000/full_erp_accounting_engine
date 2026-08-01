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
    "runtime_exhaustive_checker": 900,    # <-- timeout dinaikkan
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
    is_detail: bool = False
    ok: bool = False
    returncode: int | None = None
    score: float | None = None
    binary_score: bool = False
    duration_sec: float = 0.0
    error: str | None = None
    status: str = "ERROR"
    execution_status: str = "NOT_RUN"
    score_source: str = ""
    details: str = ""
    extra_info: str = ""

# ==========================================================================
# Fungsi bantu
# ==========================================================================

def find_score(data: Any) -> tuple[float, bool] | None:
    """
    Ekstrak skor dari struktur JSON.

    Returns:
        (score_0_to_100, is_authoritative_numeric_score)
    """
    if not isinstance(data, dict):
        return None

    # Prioritaskan skor yang paling eksplisit.
    for key in SCORE_KEY_CANDIDATES:
        if key not in data or not isinstance(data[key], (int, float)):
            continue

        val = float(data[key])
        if not 0.0 <= val <= 100.0:
            continue

        # Banyak checker mengembalikan skor ter-normalisasi 0..1.
        # Semua key skor diperlakukan konsisten: <= 1 berarti proporsi.
        if 0.0 <= val <= 1.0:
            val *= 100.0

        return (val, True)

    # Cari nested result setelah top-level.
    for container in NESTED_CONTAINERS:
        child = data.get(container)
        if isinstance(child, dict):
            found = find_score(child)
            if found is not None:
                return found

    # Fallback binary status bila tidak ada skor numerik.
    for key in PASSED_KEY_CANDIDATES:
        if key in data and isinstance(data[key], bool):
            return (100.0 if data[key] else 0.0, False)

    for container in NESTED_CONTAINERS:
        child = data.get(container)
        if not isinstance(child, dict):
            continue
        for key in PASSED_KEY_CANDIDATES:
            if key in child and isinstance(child[key], bool):
                return (100.0 if child[key] else 0.0, False)

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

def parse_score_from_output(output: str) -> tuple[float, str] | None:
    """
    Ekstrak skor dari output teks secara konservatif.

    Prioritas:
      1. skor final / overall
      2. quality score
      3. generic score/skor
      4. explicit success/failure wording

    Returns:
        (score_0_to_100, source) atau None.
    """
    patterns = [
        (
            r"(?:SKOR AKHIR(?:\s+PROPORSIONAL)?|FINAL SCORE|FINAL QUALITY SCORE)"
            r"\s*[:=]\s*([\d.]+)",
            "final_score",
        ),
        (
            r"(?:SKOR KUALITAS|QUALITY SCORE)\s*[:=]\s*([\d.]+)",
            "quality_score",
        ),
        (
            r"(?:OVERALL SCORE|OVERALL|HEALTH SCORE)\s*[:=]\s*([\d.]+)",
            "overall_score",
        ),
        (r"score\s*[:=]\s*([\d.]+)", "generic_score"),
        (r"skor\s*[:=]\s*([\d.]+)", "generic_skor"),
    ]

    for pattern, source in patterns:
        matches = list(re.finditer(pattern, output, re.I))
        if not matches:
            continue
        value = float(matches[-1].group(1))
        if 0.0 <= value <= 1.0:
            value *= 100.0
        if 0.0 <= value <= 100.0:
            return value, source

    success_patterns = [
        r"(?:Overall\s+Status|STATUS)\s*:\s*(?:PASSED|LULUS|SUCCESS)\b",
        r"DEPLOYMENT GUARD\s*:\s*PASSED\b",
        r"All\s+checks?\s+passed\b",
        r"Semua\s+modul\s+dapat\s+diimpor\b",
    ]
    failure_patterns = [
        r"(?:Overall\s+Status|STATUS|VERDICT)\s*:\s*"
        r"(?:FAILED|FAIL|TIDAK\s+LULUS|ERROR)\b",
        r"DEPLOYMENT GUARD\s*:\s*(?:FAILED|BLOCKED)\b",
    ]

    for pattern in success_patterns:
        if re.search(pattern, output, re.I):
            return 100.0, "explicit_success"

    for pattern in failure_patterns:
        if re.search(pattern, output, re.I):
            return 0.0, "explicit_failure"

    return None

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
                is_detail=True,
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
                # Lewati entri tidak berguna seperti "DETAIL"
                if name.lower() == "detail" or name == "":
                    continue
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
                if name.lower() == "detail" or name == "":
                    continue
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

def _set_quality_status(run: CheckerRun, threshold: float) -> None:
    """Tetapkan status kualitas. Tidak ada lagi special-case 70%."""
    if run.score is None:
        run.status = "ERROR"
        return

    run.score = max(0.0, min(100.0, float(run.score)))
    run.status = "PASS" if run.score >= threshold else "FAIL"


def run_one_checker(
    row: dict,
    project_root: Path,
    package_name: str,
    timeout: int,
    fail_under: float,
) -> tuple[CheckerRun, list[CheckerRun]]:
    module = row["module"]
    run = CheckerRun(
        module=module,
        category=row["category"],
        supports_json=row["json"],
        external=row.get("external", False),
        is_detail=False,
    )
    sub_runs: list[CheckerRun] = []
    json_path: str | None = None

    is_external = run.external
    script_path: Path | None = None

    try:
        if is_external:
            candidates = [
                project_root / "checker" / f"{module}.py",
                project_root / f"{module}.py",
            ]
            for candidate in candidates:
                if candidate.exists():
                    script_path = candidate
                    break

            if script_path is None:
                run.execution_status = "ERROR"
                run.status = "ERROR"
                run.error = f"File {module}.py tidak ditemukan"
                return run, sub_runs

            cmd = [sys.executable, str(script_path)]
            cmd.extend(str(arg) for arg in row.get("args", []))
        else:
            cmd = [sys.executable, "-m", f"{package_name}.{module}"]
            if row["json"]:
                fd, json_path = tempfile.mkstemp(prefix=f"mc_{module}_", suffix=".json")
                os.close(fd)
                cmd.extend(["--json", json_path])

        env = os.environ.copy()
        env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"

        started = time.monotonic()
        proc = subprocess.run(
            cmd,
            cwd=str(project_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        run.duration_sec = time.monotonic() - started
        run.ok = True
        run.returncode = proc.returncode
        run.execution_status = "SUCCESS" if proc.returncode == 0 else "NONZERO_EXIT"

        output = (proc.stdout or "") + "\n" + (proc.stderr or "")
        run.details = output[:3000]
        run.extra_info = extract_extra_info(output)

        score: float | None = None
        binary = True
        score_source = ""

        if is_external and module == "enterprise_audit_checker":
            report_file = project_root / "enterprise_audit_report.json"
            if not report_file.exists():
                run.error = "File enterprise_audit_report.json tidak ditemukan"
                run.status = "ERROR"
                return run, sub_runs

            try:
                with open(report_file, encoding="utf-8") as handle:
                    data = json.load(handle)

                summary = data.get("summary", {})
                if isinstance(summary, dict) and isinstance(summary.get("score_percent"), (int, float)):
                    score = float(summary["score_percent"])
                    score_source = "enterprise_audit_report.summary.score_percent"
                    binary = False
                else:
                    found = find_score(data)
                    if found is not None:
                        score, authoritative = found
                        score_source = "enterprise_audit_report.json"
                        binary = not authoritative

                sub_runs = parse_enterprise_audit_report(report_file)
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                run.error = f"Gagal baca JSON audit: {exc}"
                run.status = "ERROR"
                return run, sub_runs

        elif is_external and module == "enterprise_checker":
            match = re.search(r"Total:\s*(\d+)\s*\|\s*Passed:\s*(\d+)", output, re.I)
            if match:
                total = int(match.group(1))
                passed = int(match.group(2))
                if total <= 0 or passed < 0 or passed > total:
                    run.error = f"Statistik enterprise_checker tidak valid: total={total}, passed={passed}"
                    run.status = "ERROR"
                    return run, sub_runs
                score = (passed / total) * 100.0
                binary = False
                score_source = "enterprise_checker.summary"
            else:
                parsed = parse_score_from_output(output)
                if parsed is not None:
                    score, score_source = parsed
                    binary = False
                else:
                    run.error = "Enterprise checker tidak menghasilkan skor/summary yang dapat diverifikasi"
                    run.status = "ERROR"
                    return run, sub_runs

            sub_runs = parse_enterprise_checker_output(output)

        elif is_external:
            parsed = parse_score_from_output(output)
            if parsed is not None:
                score, score_source = parsed
                binary = False
            elif proc.returncode == 0:
                score = 100.0
                score_source = "zero_exit_code_fallback"
                binary = True
            else:
                score = 0.0
                score_source = "nonzero_exit_code_fallback"
                binary = True

        else:
            if row["json"]:
                if not json_path or not os.path.exists(json_path) or os.path.getsize(json_path) == 0:
                    run.error = "Checker dikonfigurasi JSON tetapi file JSON tidak dihasilkan"
                    run.status = "ERROR"
                    return run, sub_runs

                try:
                    with open(json_path, encoding="utf-8") as handle:
                        data = json.load(handle)
                except (OSError, json.JSONDecodeError) as exc:
                    run.error = f"Gagal baca JSON checker: {exc}"
                    run.status = "ERROR"
                    return run, sub_runs

                found = find_score(data)
                if found is not None:
                    score, authoritative = found
                    score_source = "checker_json"
                    binary = not authoritative
                else:
                    parsed = parse_score_from_output(output)
                    if parsed is not None:
                        score, score_source = parsed
                        binary = False
                    elif proc.returncode == 0:
                        score = 100.0
                        score_source = "zero_exit_code_fallback"
                        binary = True
                    else:
                        score = 0.0
                        score_source = "nonzero_exit_code_fallback"
                        binary = True
            else:
                parsed = parse_score_from_output(output)
                if parsed is not None:
                    score, score_source = parsed
                    binary = False
                elif proc.returncode == 0:
                    score = 100.0
                    score_source = "zero_exit_code_fallback"
                    binary = True
                else:
                    score = 0.0
                    score_source = "nonzero_exit_code_fallback"
                    binary = True

        run.score = score
        run.binary_score = binary
        run.score_source = score_source
        _set_quality_status(run, fail_under)

        # Non-zero exit code tetap terlihat, tetapi tidak otomatis mengubah
        # QUALITY STATUS bila checker menghasilkan skor eksplisit yang valid.
        if proc.returncode != 0:
            note = f"exit_code={proc.returncode}"
            run.extra_info = f"{run.extra_info} | {note}".strip(" |")
            if run.status != "PASS" and not run.error:
                run.error = f"Exit code {proc.returncode}"

        # Sub-checker adalah bukti tambahan. Failure di dalamnya tidak boleh
        # diam-diam hilang bila parent mengklaim 100%.
        sub_failures = [s for s in sub_runs if s.status in {"FAIL", "ERROR"}]
        if sub_failures and run.status == "PASS":
            run.status = "FAIL"
            run.error = (
                f"{len(sub_failures)} sub-checker enterprise gagal/error; "
                "status parent dipaksa FAIL."
            )

    except subprocess.TimeoutExpired:
        run.duration_sec = time.monotonic() - started if "started" in locals() else 0.0
        run.execution_status = "TIMEOUT"
        run.status = "ERROR"
        run.error = f"Timeout > {timeout}s"
    except FileNotFoundError as exc:
        run.execution_status = "ERROR"
        run.status = "ERROR"
        run.error = f"Executable Python tidak ditemukan: {exc}"
    except Exception as exc:
        run.execution_status = "ERROR"
        run.status = "ERROR"
        run.error = f"{exc.__class__.__name__}: {exc}"
        if run.duration_sec == 0.0 and "started" in locals():
            run.duration_sec = time.monotonic() - started
    finally:
        if is_external is False and json_path and os.path.exists(json_path):
            try:
                os.remove(json_path)
            except OSError:
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

def _scope_is_complete(
    registry: list[dict[str, Any]],
    selected_registry: list[dict[str, Any]],
) -> bool:
    expected = {row["module"] for row in registry}
    actual = {row["module"] for row in selected_registry}
    return expected == actual


def _is_detail_run(run: CheckerRun) -> bool:
    return bool(run.is_detail or run.category in {
        CATEGORY_ENTERPRISE_AUDIT_DETAIL,
        CATEGORY_ENTERPRISE_CHECKER_DETAIL,
    })


def print_report(
    runs: list[CheckerRun],
    c: Colors,
    fail_under: float,
    elapsed: float,
    scope_complete: bool,
    expected_count: int,
    selected_count: int,
) -> dict[str, Any]:
    by_category: dict[str, list[CheckerRun]] = {}
    for result in runs:
        by_category.setdefault(result.category, []).append(result)

    top_level = [r for r in runs if not _is_detail_run(r)]
    details = [r for r in runs if _is_detail_run(r)]

    print(f"\n{c.BOLD}{'=' * 100}{c.RESET}")
    print(
        f"{c.BOLD}  LAPORAN GABUNGAN SELURUH CHECKER "
        f"({len(top_level)} top-level + {len(details)} detail = {len(runs)} hasil){c.RESET}"
    )
    print(f"{c.BOLD}{'=' * 100}{c.RESET}")

    main_cats = [
        CATEGORY_ARCH,
        CATEGORY_ACCOUNTING,
        CATEGORY_SECURITY,
        CATEGORY_RUNTIME,
        CATEGORY_GOVERNANCE,
    ]
    detail_cats = [
        CATEGORY_ENTERPRISE_AUDIT_DETAIL,
        CATEGORY_ENTERPRISE_CHECKER_DETAIL,
    ]

    for cat in main_cats + detail_cats:
        items = by_category.get(cat, [])
        if not items:
            continue

        print(f"\n{c.CYAN}{c.BOLD}## {cat}{c.RESET}")
        for result in sorted(items, key=lambda item: item.module):
            tag = (
                f"{status_color(c, result.status)}{result.status:<5}{c.RESET}"
            )
            score_txt = "  -   " if result.score is None else f"{result.score:5.1f}"
            err_txt = f"  {c.DIM}{result.error}{c.RESET}" if result.error else ""
            extra = f"  {c.DIM}{result.extra_info}{c.RESET}" if result.extra_info else ""
            source = (
                f" source={result.score_source}"
                if result.score_source
                else ""
            )
            source_txt = f"  {c.DIM}{source}{c.RESET}" if source else ""

            if _is_detail_run(result):
                print(
                    f"  {result.module:<42} "
                    f"status={tag} skor={score_txt} "
                    f"({result.duration_sec:5.1f}s){err_txt}{extra}"
                )
            else:
                bin_tag = f"{c.DIM}[BINARY]{c.RESET}" if result.binary_score else "        "
                print(
                    f"  [{tag}] {result.module:<42} "
                    f"skor={score_txt} {bin_tag} "
                    f"({result.duration_sec:5.1f}s)"
                    f"{source_txt}{err_txt}{extra}"
                )

    top_scores = [r.score for r in top_level if r.score is not None]
    detail_scores = [r.score for r in details if r.score is not None]

    n_pass = sum(1 for r in top_level if r.status == "PASS")
    n_fail = sum(1 for r in top_level if r.status == "FAIL")
    n_error = sum(1 for r in top_level if r.status == "ERROR")
    detail_fail = sum(1 for r in details if r.status == "FAIL")
    detail_error = sum(1 for r in details if r.status == "ERROR")

    # Skor utama hanya memakai top-level checker.
    # Sub-checker tetap dilaporkan, tetapi tidak boleh menggandakan bobot
    # enterprise_audit/enterprise_checker dalam skor akhir.
    overall = round(statistics.mean(top_scores), 2) if top_scores else 0.0
    detail_overall = round(statistics.mean(detail_scores), 2) if detail_scores else None

    blocking = [
        r for r in top_level
        if r.status in {"FAIL", "ERROR"}
    ]

    # "LULUS" hanya boleh terjadi bila:
    #   1) full registry dijalankan,
    #   2) semua top-level checker pass,
    #   3) tidak ada error,
    #   4) skor top-level melewati threshold.
    #
    # Ini sengaja berbeda dari implementasi lama yang hanya mengecek
    # overall_score + n_error, sehingga 1 FAIL masih bisa menghasilkan LULUS.
    if not scope_complete:
        verdict = "SCOPE TIDAK LENGKAP"
        exit_code = 2
    elif n_error > 0 or n_fail > 0 or overall < fail_under:
        verdict = "TIDAK LULUS"
        exit_code = 1
    else:
        verdict = "LULUS"
        exit_code = 0

    print(f"\n{c.BOLD}{'-' * 100}{c.RESET}")
    print(f"{c.BOLD}RINGKASAN PER KATEGORI (top-level checker){c.RESET}")
    for cat in main_cats:
        items = [r for r in by_category.get(cat, []) if not _is_detail_run(r)]
        cat_scores = [r.score for r in items if r.score is not None]
        cat_avg = round(statistics.mean(cat_scores), 1) if cat_scores else 0.0
        cat_fail = sum(1 for r in items if r.status == "FAIL")
        cat_error = sum(1 for r in items if r.status == "ERROR")
        flags = ""
        if cat_fail:
            flags += f" FAIL={cat_fail}"
        if cat_error:
            flags += f" ERROR={cat_error}"
        print(
            f"  - {cat:<32} : {cat_avg:5.1f} / 100"
            f"  ({len(items)} checker){flags}"
        )

    if details:
        print(f"\n{c.BOLD}DETAIL ENTERPRISE (diagnostik, tidak menggandakan bobot skor){c.RESET}")
        for cat in detail_cats:
            items = by_category.get(cat, [])
            if not items:
                continue
            scores = [r.score for r in items if r.score is not None]
            avg = round(statistics.mean(scores), 1) if scores else 0.0
            fails = sum(1 for r in items if r.status == "FAIL")
            errors = sum(1 for r in items if r.status == "ERROR")
            print(
                f"  - {cat:<32} : {avg:5.1f} / 100"
                f"  ({len(items)} sub-checker)"
                f"  FAIL={fails} ERROR={errors}"
            )

    print(f"\n{c.BOLD}GATE AUDIT{c.RESET}")
    print(
        f"  Scope                 : "
        f"{'FULL' if scope_complete else 'PARTIAL'} "
        f"({selected_count}/{expected_count} top-level checker)"
    )
    print(f"  Threshold             : {fail_under:.1f}")
    print(f"  Top-level PASS        : {n_pass}")
    print(f"  Top-level FAIL        : {n_fail}")
    print(f"  Top-level ERROR       : {n_error}")
    print(f"  Detail FAIL           : {detail_fail}")
    print(f"  Detail ERROR          : {detail_error}")
    print(f"  Waktu total           : {elapsed:.1f}s")

    if blocking:
        print(f"\n{c.BOLD}{c.RED}BLOCKING FINDINGS{c.RESET}")
        for result in sorted(blocking, key=lambda item: (item.status, item.module)):
            score_text = "-" if result.score is None else f"{result.score:.1f}"
            reason = result.error or "score di bawah threshold"
            print(
                f"  - {result.module}: status={result.status}, "
                f"score={score_text}, reason={reason}"
            )

    overall_color = c.GREEN if verdict == "LULUS" else c.RED
    if verdict == "SCOPE TIDAK LENGKAP":
        overall_color = c.YELLOW

    print(
        f"\n{c.BOLD}SKOR AKHIR TOP-LEVEL : "
        f"{overall_color}{overall:.2f} / 100{c.RESET}"
    )
    if detail_overall is not None:
        print(
            f"SKOR DETAIL ENTERPRISE: "
            f"{detail_overall:.2f} / 100"
        )
    print(
        f"VERDICT              : "
        f"{overall_color}{c.BOLD}{verdict}{c.RESET}"
    )
    print(f"{c.BOLD}{'=' * 100}{c.RESET}\n")

    return {
        "overall_score": overall,
        "detail_overall_score": detail_overall,
        "verdict": verdict,
        "exit_code": exit_code,
        "scope_complete": scope_complete,
        "expected_top_level_checkers": expected_count,
        "selected_top_level_checkers": selected_count,
        "total_results": len(runs),
        "top_level_results": len(top_level),
        "detail_results": len(details),
        "pass": n_pass,
        "fail": n_fail,
        "error": n_error,
        "detail_fail": detail_fail,
        "detail_error": detail_error,
        "elapsed_sec": round(elapsed, 2),
        "blocking_checkers": [asdict(r) for r in blocking],
        "by_category": {
            cat: (
                round(
                    statistics.mean(
                        [
                            r.score
                            for r in by_category.get(cat, [])
                            if not _is_detail_run(r) and r.score is not None
                        ]
                    ),
                    1,
                )
                if any(
                    not _is_detail_run(r) and r.score is not None
                    for r in by_category.get(cat, [])
                )
                else 0.0
            )
            for cat in main_cats
        },
        "detail_by_category": {
            cat: (
                round(
                    statistics.mean(
                        [r.score for r in by_category.get(cat, []) if r.score is not None]
                    ),
                    1,
                )
                if any(r.score is not None for r in by_category.get(cat, []))
                else 0.0
            )
            for cat in detail_cats
        },
        "checkers": [asdict(r) for r in runs],
    }

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
    parser = argparse.ArgumentParser(
        description="Master Checker — forensic quality gate"
    )
    parser.add_argument("--only", type=str, help="Comma-separated checker names")
    parser.add_argument("--exclude", type=str, help="Comma-separated checker names to exclude")
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Parallel workers (default 8)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Global timeout per checker; overrides per-checker timeout",
    )
    parser.add_argument("--json", type=str, help="Save combined report to JSON")
    parser.add_argument(
        "--fail-under",
        type=float,
        default=80.0,
        help="Minimum quality score for PASS (default 80)",
    )
    parser.add_argument("--no-color", action="store_true", help="Disable colors")
    parser.add_argument("--list", action="store_true", help="List all checkers")
    parser.add_argument("--project-root", type=str, help="Override project root")
    parser.add_argument("--package-name", type=str, help="Override package name")
    parser.add_argument(
        "--skip-heavy",
        action="store_true",
        help="Skip heavy checkers; resulting verdict is SCOPE TIDAK LENGKAP",
    )
    args = parser.parse_args()

    if args.workers < 1:
        parser.error("--workers harus >= 1")
    if args.fail_under < 0 or args.fail_under > 100:
        parser.error("--fail-under harus berada di antara 0 dan 100")
    if args.timeout is not None and args.timeout < 1:
        parser.error("--timeout harus >= 1")

    auto_root, auto_package = detect_project_root_and_package(Path(__file__))
    project_root = (
        Path(args.project_root).resolve()
        if args.project_root
        else auto_root
    )
    package_name = args.package_name if args.package_name else auto_package

    full_registry = list(CHECKER_REGISTRY)
    registry = full_registry

    if args.only:
        wanted = {m.strip() for m in args.only.split(",") if m.strip()}
        unknown = wanted - {r["module"] for r in full_registry}
        if unknown:
            parser.error(
                "Checker tidak dikenal pada --only: "
                + ", ".join(sorted(unknown))
            )
        registry = [r for r in registry if r["module"] in wanted]

    if args.exclude:
        excluded = {m.strip() for m in args.exclude.split(",") if m.strip()}
        unknown = excluded - {r["module"] for r in full_registry}
        if unknown:
            parser.error(
                "Checker tidak dikenal pada --exclude: "
                + ", ".join(sorted(unknown))
            )
        registry = [r for r in registry if r["module"] not in excluded]

    if args.skip_heavy:
        registry = [r for r in registry if not r.get("heavy", False)]

    if args.list:
        for row in full_registry:
            mode = "json " if row["json"] else "binary"
            heavy = " HEAVY" if row.get("heavy") else ""
            external = " EXTERNAL" if row.get("external") else ""
            print(
                f"[{mode}] {row['category']:<32} "
                f"{row['module']}{heavy}{external}"
            )
        print(f"\nTotal: {len(full_registry)} checker terdaftar.")
        return 0

    scope_complete = _scope_is_complete(full_registry, registry)
    c = Colors(enabled=not args.no_color and sys.stdout.isatty())

    print(f"{c.BOLD}Project root  : {project_root}{c.RESET}")
    print(f"{c.BOLD}Package       : {package_name}{c.RESET}")
    print(
        f"{c.BOLD}Menjalankan {len(registry)} checker secara paralel "
        f"(workers={args.workers})...{c.RESET}"
    )
    if not scope_complete:
        print(
            f"{c.YELLOW}{c.BOLD}PERINGATAN: scope tidak lengkap. "
            f"Verdict tidak boleh LULUS.{c.RESET}"
        )

    start = time.monotonic()
    all_runs: list[CheckerRun] = []

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=args.workers
    ) as executor:
        futures: dict[concurrent.futures.Future, dict[str, Any]] = {}
        for row in registry:
            timeout = (
                args.timeout
                if args.timeout is not None
                else TIMEOUT_OVERRIDES.get(row["module"], TIMEOUT_DEFAULT)
            )
            future = executor.submit(
                run_one_checker,
                row,
                project_root,
                package_name,
                timeout,
                args.fail_under,
            )
            futures[future] = row

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
                    is_detail=False,
                    ok=False,
                    status="ERROR",
                    execution_status="ERROR",
                    error=f"Unhandled future exception: {exc}",
                )
                sub_runs = []

            all_runs.append(main_run)
            all_runs.extend(sub_runs)

            color = status_color(c, main_run.status)
            print(
                f"  {c.DIM}[{done}/{len(registry)}]{c.RESET} "
                f"selesai: {main_run.module} -> "
                f"{color}{main_run.status}{c.RESET} "
                f"({main_run.duration_sec:.1f}s)"
            )

    elapsed = time.monotonic() - start

    # Deterministic output: as_completed order is nondeterministic, but the
    # final report is sorted by category/module.
    all_runs.sort(
        key=lambda r: (
            r.category,
            r.module,
        )
    )

    result = print_report(
        all_runs,
        c,
        args.fail_under,
        elapsed,
        scope_complete=scope_complete,
        expected_count=len(full_registry),
        selected_count=len(registry),
    )

    if args.json:
        output_path = Path(args.json).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, ensure_ascii=False)
        print(f"Laporan JSON disimpan ke: {output_path}")

    return int(result["exit_code"])

if __name__ == "__main__":
    sys.exit(main())
