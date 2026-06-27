#!/usr/bin/env python3
"""
posting_flow_checker.py - Posting Flow Integrity Validator
===========================================================
Memeriksa kelengkapan dan konsistensi alur posting jurnal:
1. Capture / Intent → 2. Validation → 3. Approval (Four-Eyes) → 4. Posting → 5. GL Update → 6. Audit Trail

Cara pakai:
  python posting_flow_checker.py
  python posting_flow_checker.py --verbose
  python posting_flow_checker.py --json report.json
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
from dataclasses import dataclass, field

# Warna
COLOR = {"RED": "", "GREEN": "", "YELLOW": "", "CYAN": "", "RESET": ""}
try:
    import colorama
    colorama.init(autoreset=True)
    COLOR["RED"] = colorama.Fore.RED
    COLOR["GREEN"] = colorama.Fore.GREEN
    COLOR["YELLOW"] = colorama.Fore.YELLOW
    COLOR["CYAN"] = colorama.Fore.CYAN
    COLOR["RESET"] = colorama.Style.RESET_ALL
except ImportError:
    pass

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent

@dataclass
class FlowStep:
    step: str              # capture, validate, approve, post, gl_update, audit
    file: str
    line: int
    function: str
    implemented: bool

@dataclass
class FlowCheck:
    entity: str            # Journal, AR, AP, etc.
    steps: list[FlowStep]
    complete: bool
    missing_steps: list[str]

@dataclass
class Finding:
    file: str
    line: int
    severity: str
    message: str
    detail: str = ""

@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    flow_checks: list[FlowCheck] = field(default_factory=list)
    score: int = 100

# ----------------------------------------------------------------------
# Step 1: Capture / Intent
# ----------------------------------------------------------------------
def find_capture_functions(file_path: pathlib.Path) -> list[tuple[str, int]]:
    """Cari fungsi yang menangani capture/intent journal."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    results = []
    capture_keywords = {'capture', 'intent', 'create', 'record', 'initiate', 'draft'}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_name = node.name.lower()
            # Cek apakah fungsi ada di domain/intent atau capture_service
            if 'intent' in str(file_path).lower() or 'capture' in str(file_path).lower():
                if any(k in fn_name for k in capture_keywords):
                    results.append((fn_name, node.lineno))
            elif any(k in fn_name for k in capture_keywords):
                # Check if function uses domain events or creates immutable record
                has_domain_event = False
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                        if isinstance(stmt.value.func, ast.Name):
                            if 'event' in stmt.value.func.id.lower():
                                has_domain_event = True
                                break
                        elif isinstance(stmt.value.func, ast.Attribute):
                            if 'event' in stmt.value.func.attr.lower():
                                has_domain_event = True
                                break
                if has_domain_event:
                    results.append((fn_name, node.lineno))
    return results

# ----------------------------------------------------------------------
# Step 2: Validation
# ----------------------------------------------------------------------
def find_validation_functions(file_path: pathlib.Path) -> list[tuple[str, int]]:
    """Cari fungsi validasi journal."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    results = []
    validation_keywords = {'validate', 'check', 'verify', 'ensure', 'assert', 'is_valid'}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_name = node.name.lower()
            if any(k in fn_name for k in validation_keywords):
                # Cek apakah ada validasi double-entry, account, period
                body = ast.unparse(node)
                has_balance_check = 'debit' in body.lower() and 'credit' in body.lower()
                has_account_check = 'account' in body.lower() and ('valid' in body.lower() or 'exists' in body.lower())
                has_period_check = 'period' in body.lower() and ('open' in body.lower() or 'closed' in body.lower())
                if has_balance_check or has_account_check or has_period_check:
                    results.append((fn_name, node.lineno))
    return results

# ----------------------------------------------------------------------
# Step 3: Approval (Four-Eyes)
# ----------------------------------------------------------------------
def find_approval_functions(file_path: pathlib.Path) -> list[tuple[str, int]]:
    """Cari fungsi approval (four-eyes)."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    results = []
    approval_keywords = {'approve', 'authorize', 'sign_off', 'confirm', 'verify_approval'}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_name = node.name.lower()
            if any(k in fn_name for k in approval_keywords):
                # Cek apakah ada logika approval (status, roles)
                body = ast.unparse(node)
                has_status = 'status' in body.lower() or 'approved' in body.lower()
                has_role = 'role' in body.lower() or 'user' in body.lower()
                if has_status and has_role:
                    results.append((fn_name, node.lineno))
    return results

# ----------------------------------------------------------------------
# Step 4: Posting
# ----------------------------------------------------------------------
def find_posting_functions(file_path: pathlib.Path) -> list[tuple[str, int]]:
    """Cari fungsi posting journal."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    results = []
    posting_keywords = {'post', 'record', 'save', 'commit', 'persist', 'execute'}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_name = node.name.lower()
            if any(k in fn_name for k in posting_keywords):
                # Cek apakah ada transaksi/UoW
                body = ast.unparse(node)
                has_transaction = 'transaction' in body.lower() or 'uow' in body.lower() or 'unit_of_work' in body.lower()
                if has_transaction:
                    results.append((fn_name, node.lineno))
    return results

# ----------------------------------------------------------------------
# Step 5: GL Update
# ----------------------------------------------------------------------
def find_gl_update_functions(file_path: pathlib.Path) -> list[tuple[str, int]]:
    """Cari fungsi update GL."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    results = []
    gl_keywords = {'general_ledger', 'gl', 'ledger', 'post_to_gl', 'update_gl'}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_name = node.name.lower()
            if any(k in fn_name for k in gl_keywords):
                results.append((fn_name, node.lineno))
            # Cek juga fungsi yang menggunakan GL repository
            body = ast.unparse(node)
            if 'gl' in body.lower() and ('save' in body.lower() or 'update' in body.lower() or 'insert' in body.lower()):
                results.append((fn_name, node.lineno))
    return results

# ----------------------------------------------------------------------
# Step 6: Audit Trail
# ----------------------------------------------------------------------
def find_audit_functions(file_path: pathlib.Path) -> list[tuple[str, int]]:
    """Cari fungsi audit trail."""
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    results = []
    audit_keywords = {'audit', 'event', 'log', 'record', 'hash', 'immutable'}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_name = node.name.lower()
            if any(k in fn_name for k in audit_keywords):
                # Cek apakah ada logging/publishing
                body = ast.unparse(node)
                has_publish = 'publish' in body.lower() or 'append' in body.lower() or 'write' in body.lower()
                if has_publish:
                    results.append((fn_name, node.lineno))
    return results

# ----------------------------------------------------------------------
# Main Checker
# ----------------------------------------------------------------------
def analyze_posting_flow() -> Report:
    report = Report()
    # Direktori yang diperiksa
    target_dirs = [
        PROJECT_ROOT / "domain" / "journal",
        PROJECT_ROOT / "domain" / "intent",
        PROJECT_ROOT / "domain" / "reality",
        PROJECT_ROOT / "application" / "use_cases",
        PROJECT_ROOT / "application" / "service_layer",
        PROJECT_ROOT / "application" / "commands_cqrs",
        PROJECT_ROOT / "adapters" / "secondary_impl",
        PROJECT_ROOT / "audit",
        PROJECT_ROOT / "infrastructure" / "event_store",
    ]
    # Tambahkan semua folder domain yang mengandung 'journal', 'entry', 'post'
    domain_dir = PROJECT_ROOT / "domain"
    if domain_dir.exists():
        for sub in domain_dir.iterdir():
            if sub.is_dir() and any(k in sub.name.lower() for k in ('journal', 'entry', 'post', 'intent', 'reality')):
                target_dirs.append(sub)

    exclude = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', 'dist', 'build', 'migrations', 'deployment', 'docs', 'tests'}

    # Kumpulkan semua fungsi per step
    capture_funcs = []
    validate_funcs = []
    approve_funcs = []
    post_funcs = []
    gl_funcs = []
    audit_funcs = []

    for dir_path in target_dirs:
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if any(part in exclude for part in py_file.parts):
                continue
            if py_file.name.startswith("__") or py_file.name.startswith("posting_flow_checker"):
                continue

            capture_funcs.extend([(str(py_file), f, line) for f, line in find_capture_functions(py_file)])
            validate_funcs.extend([(str(py_file), f, line) for f, line in find_validation_functions(py_file)])
            approve_funcs.extend([(str(py_file), f, line) for f, line in find_approval_functions(py_file)])
            post_funcs.extend([(str(py_file), f, line) for f, line in find_posting_functions(py_file)])
            gl_funcs.extend([(str(py_file), f, line) for f, line in find_gl_update_functions(py_file)])
            audit_funcs.extend([(str(py_file), f, line) for f, line in find_audit_functions(py_file)])

    # Periksa kelengkapan flow
    steps_defined = {
        'capture': len(capture_funcs) > 0,
        'validate': len(validate_funcs) > 0,
        'approve': len(approve_funcs) > 0,
        'post': len(post_funcs) > 0,
        'gl_update': len(gl_funcs) > 0,
        'audit': len(audit_funcs) > 0,
    }

    missing_steps = [s for s, defined in steps_defined.items() if not defined]

    # Buat flow check per entity
    entities = {
        'Journal': {'capture': capture_funcs, 'validate': validate_funcs,
                    'approve': approve_funcs, 'post': post_funcs,
                    'gl_update': gl_funcs, 'audit': audit_funcs}
    }

    # Periksa apakah ada step yang missing
    for entity, steps in entities.items():
        step_list = []
        complete = True
        missing = []
        for step_name, funcs in steps.items():
            if funcs:
                for file, func, line in funcs[:3]:  # ambil max 3 per step
                    step_list.append(FlowStep(
                        step=step_name,
                        file=file,
                        line=line,
                        function=func,
                        implemented=True
                    ))
            else:
                missing.append(step_name)
                complete = False
                step_list.append(FlowStep(
                    step=step_name,
                    file="",
                    line=0,
                    function="",
                    implemented=False
                ))
        report.flow_checks.append(FlowCheck(
            entity=entity,
            steps=step_list,
            complete=complete,
            missing_steps=missing
        ))

    # Buat findings untuk missing steps
    for entity, steps in entities.items():
        for step_name, funcs in steps.items():
            if not funcs:
                report.findings.append(Finding(
                    file="",
                    line=0,
                    severity="ERROR",
                    message=f"Missing '{step_name}' step in {entity} posting flow",
                    detail=f"Implementasi {step_name} tidak ditemukan di kode sumber."
                ))

    # Tambahkan findings untuk step yang ditemukan di lokasi tidak tepat
    # (misal capture di application/service_layer padahal seharusnya di domain/intent)
    for file, func, line in capture_funcs:
        if 'intent' not in file.lower() and 'capture' not in file.lower():
            report.findings.append(Finding(
                file=file,
                line=line,
                severity="WARNING",
                message=f"Capture function '{func}' berada di lokasi non-intent: {file}",
                detail="Sebaiknya capture logic berada di domain/intent atau domain/reality."
            ))

    # Periksa apakah ada fungsi posting di application/use_cases
    post_found = False
    for file, func, line in post_funcs:
        if 'use_cases' in file or 'service_layer' in file:
            post_found = True
            break
    if not post_found:
        report.findings.append(Finding(
            file="application/use_cases",
            line=0,
            severity="WARNING",
            message="Tidak ada fungsi posting di application/use_cases",
            detail="Fungsi posting sebaiknya berada di use case layer."
        ))

    # Score: setiap ERROR -10, WARNING -3
    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")
    report.score = max(0, 100 - errors * 10 - warnings * 3)

    return report

# ----------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------
def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}POSTING FLOW INTEGRITY CHECKER REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")

    print(f"\n  Entities checked: {len(report.flow_checks)}")
    for fc in report.flow_checks:
        status = f"{c['GREEN']}✅ Complete{c['RESET']}" if fc.complete else f"{c['RED']}❌ Incomplete{c['RESET']}"
        print(f"  {fc.entity}: {status}")

    print(f"\n  Total findings: {len(report.findings)}")
    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")
    print(f"  Errors: {c['RED']}{errors}{c['RESET']}, Warnings: {c['YELLOW']}{warnings}{c['RESET']}")
    print(f"  Score: {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    # Flow steps per entity
    print(f"\n{c['CYAN']}Flow Steps per Entity:{c['RESET']}")
    step_names = ['capture', 'validate', 'approve', 'post', 'gl_update', 'audit']
    step_labels = {
        'capture': '📝 Capture/Intent',
        'validate': '🔍 Validation',
        'approve': '✅ Approval (Four-Eyes)',
        'post': '📤 Posting',
        'gl_update': '📊 GL Update',
        'audit': '📋 Audit Trail'
    }
    for fc in report.flow_checks:
        print(f"\n  {c['CYAN']}{fc.entity}{c['RESET']}:")
        for step_name in step_names:
            step = next((s for s in fc.steps if s.step == step_name), None)
            if step:
                if step.implemented:
                    icon = f"{c['GREEN']}✔{c['RESET']}"
                    detail = f"{step.function} at {step.file}:{step.line}"
                else:
                    icon = f"{c['RED']}✖{c['RESET']}"
                    detail = "MISSING"
                print(f"    {step_labels.get(step_name, step_name)}: {icon}  {detail}")

    # Findings detail
    if report.findings:
        print(f"\n{c['RED'] if errors else c['YELLOW']}Findings:{c['RESET']}")
        for f in report.findings[:30]:
            color = c["RED"] if f.severity == "ERROR" else c["YELLOW"]
            location = f"{f.file}:{f.line}" if f.file else "GLOBAL"
            print(f"  {color}[{f.severity}]{c['RESET']} {location}")
            print(f"     {f.message}")
            if verbose and f.detail:
                print(f"     {c['CYAN']}→ {f.detail}{c['RESET']}")
        if len(report.findings) > 30:
            print(f"  ... and {len(report.findings)-30} more findings")

def save_json(report: Report, filepath: str):
    data = {
        "flow_checks": [
            {
                "entity": fc.entity,
                "complete": fc.complete,
                "missing_steps": fc.missing_steps,
                "steps": [
                    {"step": s.step, "function": s.function, "file": s.file, "line": s.line, "implemented": s.implemented}
                    for s in fc.steps
                ]
            }
            for fc in report.flow_checks
        ],
        "findings": [
            {"file": f.file, "line": f.line, "severity": f.severity, "message": f.message, "detail": f.detail}
            for f in report.findings
        ],
        "score": report.score
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{c['CYAN']}JSON saved to {filepath}{c['RESET']}")

# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Posting Flow Integrity Checker")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    args = parser.parse_args()

    report = analyze_posting_flow()
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)

    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    sys.exit(0 if errors == 0 else 1)

if __name__ == "__main__":
    main()
