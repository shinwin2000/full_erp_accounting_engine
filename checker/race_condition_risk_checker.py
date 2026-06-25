#!/usr/bin/env python3
"""
race_condition_risk_checker.py - Race Condition Risk Detector
==============================================================
Mendeteksi potensi race condition pada operasi update/delete.

Cara pakai:
  python race_condition_risk_checker.py
  python race_condition_risk_checker.py --verbose
  python race_condition_risk_checker.py --json report.json
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
from dataclasses import dataclass, field
from typing import List

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
class Finding:
    file: str
    line: int
    severity: str
    message: str
    detail: str = ""

@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    score: int = 100

def check_file(file_path: pathlib.Path) -> List[Finding]:
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    findings = []
    # Cari method update atau delete
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not any(k in node.name.lower() for k in ('update', 'delete', 'modify', 'change')):
                continue

            has_lock = False
            has_version_check = False

            # Cek apakah ada parameter lock atau version
            for arg in node.args.args:
                if 'lock' in arg.arg.lower():
                    has_lock = True
                if 'version' in arg.arg.lower():
                    has_version_check = True

            # Cek dalam body: with lock, select for update, version check
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.With):
                    for item in stmt.items:
                        if isinstance(item.context_expr, ast.Call):
                            if isinstance(item.context_expr.func, ast.Name) and 'lock' in item.context_expr.func.id.lower():
                                has_lock = True
                                break
                            if isinstance(item.context_expr.func, ast.Attribute) and 'lock' in item.context_expr.func.attr.lower():
                                has_lock = True
                                break
                if isinstance(stmt, ast.If):
                    cond = ast.unparse(stmt.test).lower()
                    if 'version' in cond or 'optimistic' in cond:
                        has_version_check = True
                if isinstance(stmt, ast.Assert):
                    cond = ast.unparse(stmt.test).lower()
                    if 'version' in cond:
                        has_version_check = True

            if not has_lock and not has_version_check:
                findings.append(Finding(
                    file=str(file_path),
                    line=node.lineno,
                    severity="WARNING",
                    message=f"Fungsi '{node.name}' berpotensi race condition (no lock/version check)",
                    detail="Tambahkan pessimistic lock (SELECT FOR UPDATE) atau optimistic locking (version field)."
                ))
    return findings

def scan_project() -> Report:
    report = Report()
    # Scan domain, application, infrastructure
    target_dirs = [
        PROJECT_ROOT / "domain",
        PROJECT_ROOT / "application",
        PROJECT_ROOT / "infrastructure",
    ]
    for d in target_dirs:
        if d.exists():
            for py_file in d.rglob("*.py"):
                if any(part in {'.venv', 'venv', '__pycache__', '.git', 'node_modules'} for part in py_file.parts):
                    continue
                if py_file.name.startswith("race_condition"):
                    continue
                report.findings.extend(check_file(py_file))

    report.score = max(0, 100 - len(report.findings) * 5)
    return report

def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}RACE CONDITION RISK CHECKER REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"\n  Findings: {len(report.findings)}")
    print(f"  Score: {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    for f in report.findings:
        print(f"  {c['YELLOW']}[WARNING]{c['RESET']} {f.file}:{f.line}")
        print(f"     {f.message}")
        if verbose and f.detail:
            print(f"     {c['CYAN']}{f.detail}{c['RESET']}")

def save_json(report: Report, filepath: str):
    data = {"findings": [{"file": f.file, "line": f.line, "severity": f.severity, "message": f.message, "detail": f.detail} for f in report.findings], "score": report.score}
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{c['CYAN']}JSON saved to {filepath}{c['RESET']}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", metavar="FILE")
    args = parser.parse_args()

    report = scan_project()
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)
    sys.exit(0 if len(report.findings) == 0 else 1)

if __name__ == "__main__":
    main()