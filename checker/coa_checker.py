#!/usr/bin/env python3
"""
coa_checker.py - Chart of Accounts Validator
=============================================
Memeriksa struktur COA (Chart of Accounts) di file YAML atau Python.

Cara pakai:
  python coa_checker.py
  python coa_checker.py --verbose
  python coa_checker.py --json report.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

try:
    import yaml
except ImportError:
    yaml = None

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
class Account:
    code: str
    name: str
    type: str
    normal_balance: str
    parent: Optional[str] = None
    description: Optional[str] = None

@dataclass
class Violation:
    message: str
    account_code: Optional[str] = None

@dataclass
class Report:
    accounts: List[Account] = field(default_factory=list)
    violations: List[Violation] = field(default_factory=list)
    score: int = 100

def parse_yaml_coa(file_path: pathlib.Path) -> List[Account]:
    if yaml is None:
        return []
    try:
        with open(file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:
        return []

    accounts = []
    if isinstance(data, dict) and 'accounts' in data:
        for item in data['accounts']:
            acc = Account(
                code=item.get('code', ''),
                name=item.get('name', ''),
                type=item.get('type', ''),
                normal_balance=item.get('normal_balance', ''),
                parent=item.get('parent'),
                description=item.get('description'),
            )
            accounts.append(acc)
    return accounts

def validate_coa(accounts: List[Account]) -> List[Violation]:
    violations = []
    codes = set()
    for acc in accounts:
        if not acc.code:
            violations.append(Violation("Kode akun kosong", None))
        elif acc.code in codes:
            violations.append(Violation(f"Kode akun duplikat: {acc.code}", acc.code))
        codes.add(acc.code)

        if not acc.name:
            violations.append(Violation(f"Akun {acc.code} tidak memiliki nama", acc.code))

        valid_types = {'Asset', 'Liability', 'Equity', 'Revenue', 'Expense', 'Asset', 'Liability', 'Equity', 'Revenue', 'Expense'}
        if acc.type not in valid_types:
            violations.append(Violation(f"Akun {acc.code} memiliki tipe tidak valid: {acc.type}", acc.code))

        valid_balances = {'Debit', 'Credit'}
        if acc.normal_balance not in valid_balances:
            violations.append(Violation(f"Akun {acc.code} memiliki normal balance tidak valid: {acc.normal_balance}", acc.code))

        # Cek parent exist
        if acc.parent and acc.parent not in codes:
            violations.append(Violation(f"Akun {acc.code} merujuk parent {acc.parent} yang tidak ada", acc.code))

    return violations

def scan_coa() -> Report:
    report = Report()
    coa_files = list(PROJECT_ROOT.glob("config_files/coa*.yaml")) + list(PROJECT_ROOT.glob("config_files/*coa*.yml"))
    if not coa_files:
        # Coba cari di domain/coa
        coa_files = list(PROJECT_ROOT.glob("domain/coa/*.yaml"))
    if not coa_files:
        report.violations.append(Violation("Tidak ditemukan file COA (coa.yaml / coa.yml)"))
        return report

    accounts = []
    for f in coa_files:
        accounts.extend(parse_yaml_coa(f))

    if not accounts:
        report.violations.append(Violation("Tidak ada akun ditemukan dalam file COA"))
        return report

    report.accounts = accounts
    report.violations.extend(validate_coa(accounts))

    report.score = max(0, 100 - len(report.violations) * 10)
    return report

def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}COA CHECKER REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"\n  Total accounts: {len(report.accounts)}")
    print(f"  Violations: {len(report.violations)}")
    print(f"  Score: {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    if verbose and report.accounts:
        print("\n  Account list:")
        for acc in report.accounts[:10]:
            print(f"    {acc.code} - {acc.name} ({acc.type})")
        if len(report.accounts) > 10:
            print(f"    ... and {len(report.accounts)-10} more")

    if report.violations:
        print(f"\n{c['RED']}❌ Violations:{c['RESET']}")
        for v in report.violations:
            if v.account_code:
                print(f"  {v.account_code}: {v.message}")
            else:
                print(f"  {v.message}")

def save_json(report: Report, filepath: str):
    data = {
        "accounts": [{"code": a.code, "name": a.name, "type": a.type, "normal_balance": a.normal_balance,
                      "parent": a.parent, "description": a.description} for a in report.accounts],
        "violations": [{"account_code": v.account_code, "message": v.message} for v in report.violations],
        "score": report.score,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{c['CYAN']}JSON saved to {filepath}{c['RESET']}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", metavar="FILE")
    args = parser.parse_args()

    report = scan_coa()
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)
    sys.exit(0 if len(report.violations) == 0 else 1)

if __name__ == "__main__":
    main()