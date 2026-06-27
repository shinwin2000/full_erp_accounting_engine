#!/usr/bin/env python3
"""
coa_checker.py - Chart of Accounts Validator (Enhanced)
========================================================
Memeriksa struktur COA (Chart of Accounts) dari berbagai sumber.

Cara pakai:
  python checker/coa_checker.py
  python checker/coa_checker.py --verbose
  python checker/coa_checker.py --coa-file config/coa.yaml
  python checker/coa_checker.py --generate-sample
  python checker/coa_checker.py --json report.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set

# --- Dependensi opsional ---
try:
    import yaml
except ImportError:
    yaml = None

# --- Warna terminal ---
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


# --- Data Classes ---
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
    source_file: Optional[str] = None


# --- Pencarian file COA ---
def find_coa_files(project_root: pathlib.Path) -> List[pathlib.Path]:
    """Cari file COA di berbagai lokasi."""
    search_dirs = [
        project_root / "config",
        project_root / "config_files",
        project_root / "domain" / "coa",
        project_root / "infrastructure" / "coa",
        project_root / "data" / "coa",
        project_root / "app" / "coa",
        project_root / "coa",
        project_root / "checker",  # fallback jika checker punya sample
    ]
    patterns = ["coa*.yaml", "coa*.yml", "coa*.json", 
                "chart_of_accounts*.yaml", "chart_of_accounts*.yml"]
    found = []
    for d in search_dirs:
        if d.exists() and d.is_dir():
            for pattern in patterns:
                found.extend(d.glob(pattern))
    # Cari di root dengan nama spesifik
    root_patterns = ["coa.yaml", "coa.yml", "coa.json", 
                     "chart_of_accounts.yaml", "chart_of_accounts.yml"]
    for p in root_patterns:
        f = project_root / p
        if f.exists():
            found.append(f)
    return list(set(found))


def is_coa_likely(data: Any) -> bool:
    """Periksa apakah data kemungkinan adalah daftar COA yang valid."""
    if not data:
        return False
    accounts = []
    if isinstance(data, dict):
        if "accounts" in data and isinstance(data["accounts"], list):
            accounts = data["accounts"]
        else:
            for val in data.values():
                if isinstance(val, dict) and "name" in val and "code" in val:
                    accounts.append(val)
    elif isinstance(data, list):
        accounts = data
    for item in accounts:
        if isinstance(item, dict) and item.get("code") and item.get("name"):
            return True
    return False


def parse_coa_file(file_path: pathlib.Path) -> List[Account]:
    """Parse file COA (YAML/JSON) menjadi list Account."""
    data: Dict[str, Any] = {}
    try:
        with open(file_path, encoding="utf-8") as f:
            if file_path.suffix in (".yaml", ".yml"):
                if yaml is None:
                    return []
                data = yaml.safe_load(f) or {}
            elif file_path.suffix == ".json":
                data = json.load(f)
            else:
                return []
    except Exception:
        return []

    if not is_coa_likely(data):
        return []

    accounts = []
    if isinstance(data, dict):
        if "accounts" in data and isinstance(data["accounts"], list):
            items = data["accounts"]
        else:
            items = []
            for key, val in data.items():
                if isinstance(val, dict) and "name" in val:
                    val["code"] = key
                    items.append(val)
    elif isinstance(data, list):
        items = data
    else:
        return []

    for item in items:
        if not isinstance(item, dict):
            continue
        acc = Account(
            code=str(item.get("code", "")).strip(),
            name=str(item.get("name", "")).strip(),
            type=str(item.get("type", "")).strip(),
            normal_balance=str(item.get("normal_balance", "")).strip(),
            parent=str(item.get("parent")).strip() if item.get("parent") else None,
            description=str(item.get("description")).strip() if item.get("description") else None,
        )
        if acc.code:
            accounts.append(acc)
    return accounts


def load_coa_from_module(module_name: str) -> List[Account]:
    """Coba load COA dari modul Python."""
    try:
        mod = __import__(module_name, fromlist=["COA"])
        if hasattr(mod, "COA") and isinstance(mod.COA, list):
            accounts = []
            for item in mod.COA:
                if isinstance(item, dict):
                    acc = Account(
                        code=str(item.get("code", "")).strip(),
                        name=str(item.get("name", "")).strip(),
                        type=str(item.get("type", "")).strip(),
                        normal_balance=str(item.get("normal_balance", "")).strip(),
                        parent=str(item.get("parent")).strip() if item.get("parent") else None,
                        description=str(item.get("description")).strip() if item.get("description") else None,
                    )
                    if acc.code:
                        accounts.append(acc)
            return accounts
    except ImportError:
        pass
    return []


# --- Validasi ---
def validate_coa(accounts: List[Account]) -> List[Violation]:
    violations = []
    codes: Set[str] = set()
    code_map = {acc.code: acc for acc in accounts}

    for acc in accounts:
        if not acc.code:
            violations.append(Violation("Kode akun kosong", None))
            continue
        if acc.code in codes:
            violations.append(Violation(f"Kode akun duplikat: {acc.code}", acc.code))
        codes.add(acc.code)

        if not acc.name:
            violations.append(Violation(f"Akun {acc.code} tidak memiliki nama", acc.code))

        valid_types = {"Asset", "Liability", "Equity", "Revenue", "Expense"}
        if acc.type not in valid_types:
            violations.append(Violation(f"Akun {acc.code} memiliki tipe tidak valid: {acc.type}", acc.code))

        valid_balances = {"Debit", "Credit"}
        if acc.normal_balance not in valid_balances:
            violations.append(Violation(f"Akun {acc.code} memiliki normal balance tidak valid: {acc.normal_balance}", acc.code))

        if acc.parent:
            if acc.parent not in codes:
                violations.append(Violation(f"Akun {acc.code} merujuk parent {acc.parent} yang tidak ada", acc.code))
            elif acc.parent == acc.code:
                violations.append(Violation(f"Akun {acc.code} memiliki parent sendiri (siklus)", acc.code))

    # Cek siklus parent-child
    for acc in accounts:
        if acc.parent and acc.parent in code_map:
            visited = set()
            current = acc.code
            while current and current in code_map:
                if current in visited:
                    violations.append(Violation(f"Siklus parent-child terdeteksi pada akun {current}", current))
                    break
                visited.add(current)
                current = code_map[current].parent

    return violations


def scan_coa(project_root: pathlib.Path, coa_file: Optional[str] = None) -> Report:
    report = Report()
    if coa_file:
        file_path = pathlib.Path(coa_file)
        if not file_path.exists():
            report.violations.append(Violation(f"File COA tidak ditemukan: {coa_file}"))
            return report
        accounts = parse_coa_file(file_path)
        if not accounts:
            report.violations.append(Violation(f"Tidak ada akun ditemukan di file {coa_file} atau file bukan COA"))
            return report
        report.accounts = accounts
        report.source_file = str(file_path)
    else:
        files = find_coa_files(project_root)
        if not files:
            accounts = load_coa_from_module("domain.coa.chart_of_accounts")
            if accounts:
                report.accounts = accounts
                report.source_file = "domain.coa.chart_of_accounts (Python module)"
            else:
                report.violations.append(Violation(
                    "Tidak ditemukan file COA (coa.yaml/yml/json) maupun modul Python.\n"
                    "Gunakan --generate-sample untuk membuat contoh file COA."
                ))
                return report
        else:
            for f in files:
                accounts = parse_coa_file(f)
                if accounts:
                    report.accounts = accounts
                    report.source_file = str(f)
                    break
            if not report.accounts:
                report.violations.append(Violation("Tidak ada akun ditemukan dalam file COA yang ditemukan"))
                return report

    report.violations.extend(validate_coa(report.accounts))
    report.score = max(0, 100 - len(report.violations) * 5)
    return report


def generate_sample_coa(project_root: pathlib.Path) -> None:
    """Buat file contoh COA di config/coa.yaml jika tidak ada."""
    sample = {
        "accounts": [
            {"code": "1000", "name": "Kas", "type": "Asset", "normal_balance": "Debit"},
            {"code": "1100", "name": "Piutang Usaha", "type": "Asset", "normal_balance": "Debit"},
            {"code": "2000", "name": "Utang Usaha", "type": "Liability", "normal_balance": "Credit"},
            {"code": "3000", "name": "Modal", "type": "Equity", "normal_balance": "Credit"},
            {"code": "4000", "name": "Pendapatan", "type": "Revenue", "normal_balance": "Credit"},
            {"code": "5000", "name": "Beban", "type": "Expense", "normal_balance": "Debit"},
        ]
    }
    target = project_root / "config" / "coa.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        if yaml:
            yaml.dump(sample, f, default_flow_style=False, allow_unicode=True)
        else:
            json.dump(sample, f, indent=2)
    print(f"{COLOR['GREEN']}✅ Contoh COA dibuat di: {target}{COLOR['RESET']}")
    print(f"{COLOR['CYAN']}Silakan edit file tersebut untuk menambahkan akun yang sesuai.{COLOR['RESET']}")


def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}COA CHECKER REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")
    if report.source_file:
        print(f"\n  Sumber: {report.source_file}")
    print(f"  Total accounts: {len(report.accounts)}")
    print(f"  Violations: {len(report.violations)}")
    print(f"  Score: {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    if verbose and report.accounts:
        print("\n  Account list (first 20):")
        for acc in report.accounts[:20]:
            parent = f" (parent: {acc.parent})" if acc.parent else ""
            print(f"    {acc.code} - {acc.name} ({acc.type}){parent}")
        if len(report.accounts) > 20:
            print(f"    ... and {len(report.accounts)-20} more")

    if report.violations:
        print(f"\n{c['RED']}❌ Violations:{c['RESET']}")
        for v in report.violations:
            if v.account_code:
                print(f"  {v.account_code}: {v.message}")
            else:
                print(f"  {v.message}")


def save_json(report: Report, filepath: str):
    data = {
        "source": report.source_file,
        "accounts": [{"code": a.code, "name": a.name, "type": a.type, "normal_balance": a.normal_balance,
                      "parent": a.parent, "description": a.description} for a in report.accounts],
        "violations": [{"account_code": v.account_code, "message": v.message} for v in report.violations],
        "score": report.score,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{c['CYAN']}✅ JSON saved to {filepath}{c['RESET']}")


def main():
    parser = argparse.ArgumentParser(description="Chart of Accounts Validator")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail akun")
    parser.add_argument("--json", metavar="FILE", help="Simpan laporan ke file JSON")
    parser.add_argument("--coa-file", metavar="FILE", help="Tentukan file COA secara manual")
    parser.add_argument("--generate-sample", action="store_true", help="Buat file contoh COA jika tidak ada")
    args = parser.parse_args()

    project_root = pathlib.Path(__file__).resolve().parent.parent

    if args.generate_sample:
        generate_sample_coa(project_root)
        return

    report = scan_coa(project_root, args.coa_file)
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)

    sys.exit(0 if len(report.violations) == 0 else 1)


if __name__ == "__main__":
    main()