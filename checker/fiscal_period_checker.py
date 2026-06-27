#!/usr/bin/env python3
"""
fiscal_period_checker.py - Fiscal Period Rules & Lifecycle Validator (Conservative)
===================================================================================
Memeriksa kepatuhan fiscal period dengan pendekatan konservatif.
Hanya periksa file di domain/fiscal_period/, domain/shared_value_objects/,
application/service_layer/service_fiscal_period, application/use_cases/*period*.

Cara pakai:
  python checker/fiscal_period_checker.py [--verbose] [--json report.json]
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
from dataclasses import dataclass, field

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

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


@dataclass
class Finding:
    file: str
    line: int
    severity: str
    category: str
    message: str
    detail: str = ""


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    score: int = 100


# =============================================================================
# FILE FILTER
# =============================================================================
def get_relevant_files() -> list[pathlib.Path]:
    relevant = []
    skip_dirs = {
        ".venv", "venv", "__pycache__", ".git", "node_modules",
        "dist", "build", "migrations", "deployment", "docs",
        "monitoring", "config_files", "logs", "tests", "checker",
        "scripts", "tools", "adapters", "infrastructure",
        "domain/financial_statement",
    }
    skip_stems = {
        "main_checker", "fix_bom", "fix", "asgi", "wsgi", "manage",
        "setup", "conftest", "pytest", "__init__", "tax_checker",
        "layer_checker", "fiscal_period_checker"
    }

    allowed_prefixes = (
        "domain/fiscal_period/",
        "domain/shared_value_objects/",
        "application/service_layer/service_fiscal_period",
        "application/use_cases/",
    )

    for path in PROJECT_ROOT.rglob("*.py"):
        rel = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        if any(rel.startswith(d) for d in skip_dirs):
            continue
        if path.stem in skip_stems:
            continue

        is_allowed = False
        for prefix in allowed_prefixes:
            if rel.startswith(prefix):
                is_allowed = True
                break
        if not is_allowed:
            continue

        if rel.startswith("application/use_cases/"):
            stem = path.stem.lower()
            if not any(k in stem for k in ("period", "fiscal", "closing", "year_end")):
                continue

        relevant.append(path)

    return relevant


def is_service_file(path: pathlib.Path) -> bool:
    return "service" in path.stem.lower()


def is_use_case_file(path: pathlib.Path) -> bool:
    return "use_case" in path.stem.lower() or "handler" in path.stem.lower()


def is_domain_file(path: pathlib.Path) -> bool:
    rel = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    return rel.startswith("domain/")


# =============================================================================
# AST HELPERS (Semantic Detection)
# =============================================================================
VALIDATION_NAMES = {
    "ensure_open", "ensure_can_close", "ensure_closed", "validate_period",
    "can_post", "can_close", "is_open", "is_closed", "check_period_open",
    "check_period_closed", "assert_open", "assert_closed",
    "ensure_period_open", "ensure_period_closed", "validate_period_status",
    "period_guard", "ensure_can_post", "can_reopen", "ensure_can_reopen",
    "validate_can_reopen_period", "can_reopen_period", "validate_can_close_period",
    "validate_can_lock_period", "validate_period_before_close", "validate_period_before_lock",
    "validate_status_transition"
}


def is_property_method(node: ast.FunctionDef) -> bool:
    for deco in node.decorator_list:
        if isinstance(deco, ast.Name):
            if deco.id in ("property", "cached_property"):
                return True
        elif isinstance(deco, ast.Attribute):
            if deco.attr in ("property", "cached_property"):
                return True
    return False


def has_validation_call(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            if isinstance(sub.func, ast.Name) and sub.func.id.lower() in VALIDATION_NAMES:
                return True
            if isinstance(sub.func, ast.Attribute):
                attr = sub.func.attr.lower()
                if attr in VALIDATION_NAMES:
                    return True
                if isinstance(sub.func.value, ast.Attribute) and sub.func.value.attr == "self":
                    if attr in ("open", "close", "lock", "unlock", "reopen"):
                        return True
                if isinstance(sub.func.value, ast.Name) and sub.func.value.id.lower() in ("period", "self"):
                    if attr in ("open", "close", "lock", "unlock", "reopen"):
                        return True
                # Deteksi delegasi ke validator: self._validator.xxx()
                if isinstance(sub.func.value, ast.Attribute):
                    if sub.func.value.attr in ("_validator", "validator", "_invariant_enforcer", "invariant_enforcer"):
                        if attr in VALIDATION_NAMES:
                            return True
    return False


def has_if_status_check(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.If):
            cond = ast.unparse(sub.test).lower()
            if "period" in cond:
                if "status" in cond or "open" in cond or "closed" in cond or "locked" in cond:
                    return True
                if "is_open" in cond or "is_closed" in cond or "is_locked" in cond:
                    return True
                if "can_reopen" in cond or "can_close" in cond or "can_post" in cond:
                    return True
        if isinstance(sub, ast.Assert):
            cond = ast.unparse(sub.test).lower()
            if "period" in cond and ("open" in cond or "closed" in cond or "locked" in cond):
                return True
            if "status" in cond and ("open" in cond or "closed" in cond or "locked" in cond):
                return True
    return False


def has_method_call(node: ast.AST, names: list[str]) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            if isinstance(sub.func, ast.Name) and sub.func.id.lower() in names:
                return True
            if isinstance(sub.func, ast.Attribute) and sub.func.attr.lower() in names:
                return True
            # Delegasi ke validator
            if isinstance(sub.func, ast.Attribute) and isinstance(sub.func.value, ast.Attribute):
                if sub.func.value.attr in ("_validator", "validator", "_invariant_enforcer", "invariant_enforcer"):
                    if sub.func.attr.lower() in names:
                        return True
    return False


def is_getter_or_validator(func_name: str) -> bool:
    lower = func_name.lower()
    return lower.startswith(("is_", "has_", "get_", "can_", "validate_"))


# =============================================================================
# 1. STATUS LIFECYCLE
# =============================================================================
def find_period_status_enum() -> tuple[pathlib.Path | None, set[str]]:
    search_dirs = [
        PROJECT_ROOT / "domain" / "fiscal_period",
        PROJECT_ROOT / "domain" / "shared_value_objects",
        PROJECT_ROOT / "axioms",
    ]
    for base in search_dirs:
        if not base.exists():
            continue
        for py_file in base.glob("*.py"):
            try:
                src = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src)
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    is_enum = False
                    for base_node in node.bases:
                        if isinstance(base_node, ast.Name) and base_node.id in ("Enum", "StrEnum"):
                            is_enum = True
                            break
                        if isinstance(base_node, ast.Attribute) and base_node.attr in ("Enum", "StrEnum"):
                            is_enum = True
                            break
                    if not is_enum:
                        continue
                    name = node.name.lower()
                    if "period" in name or "status" in name:
                        found = set()
                        for item in node.body:
                            if isinstance(item, ast.Assign):
                                for target in item.targets:
                                    if isinstance(target, ast.Name):
                                        found.add(target.id.upper())
                            elif isinstance(item, ast.AnnAssign):
                                if isinstance(item.target, ast.Name):
                                    found.add(item.target.id.upper())
                        if found:
                            return py_file, found
    return None, set()


# =============================================================================
# 2. PERIOD VALIDATION
# =============================================================================
def check_period_validation(tree: ast.AST, file_path: pathlib.Path) -> list[Finding]:
    findings = []
    if not (is_service_file(file_path) or is_use_case_file(file_path)):
        return findings

    post_funcs = {
        "post_journal", "post_entry", "post_transaction", "post_to_ledger",
        "post_journal_entry", "post", "save_journal", "create_journal"
    }

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if is_property_method(node):
            continue
        fname = node.name.lower()
        if is_getter_or_validator(fname):
            continue
        if not any(p in fname for p in post_funcs):
            continue

        if has_validation_call(node) or has_if_status_check(node):
            continue

        findings.append(Finding(
            file=str(file_path),
            line=node.lineno,
            severity="ERROR",
            category="period_validation",
            message=f"Fungsi '{node.name}' tidak memvalidasi status period",
            detail="Tambahkan panggilan ensure_open() atau cek period.status == OPEN."
        ))
    return findings


# =============================================================================
# 3. FISCAL YEAR
# =============================================================================
def check_fiscal_year(tree: ast.AST, file_path: pathlib.Path) -> list[Finding]:
    findings = []
    if not is_domain_file(file_path):
        return findings

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        name = node.name
        if name not in ("FiscalPeriod", "AccountingPeriod", "Period", "FiscalYear"):
            continue

        has_start = False
        has_end = False
        has_year = False
        has_month = False

        for item in node.body:
            if isinstance(item, (ast.Assign, ast.AnnAssign)):
                targets = []
                if isinstance(item, ast.Assign):
                    targets = [t.id for t in item.targets if isinstance(t, ast.Name)]
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    targets = [item.target.id]
                for t in targets:
                    if "start" in t.lower() and "date" in t.lower():
                        has_start = True
                    if "end" in t.lower() and "date" in t.lower():
                        has_end = True
                    if "year" in t.lower():
                        has_year = True
                    if "month" in t.lower():
                        has_month = True
            if isinstance(item, ast.FunctionDef):
                fname = item.name.lower()
                if "start_date" in fname or "get_start_date" in fname:
                    has_start = True
                if "end_date" in fname or "get_end_date" in fname:
                    has_end = True

        if not (has_start or has_year):
            findings.append(Finding(
                file=str(file_path),
                line=node.lineno,
                severity="WARNING",
                category="fiscal_year",
                message=f"Class '{name}' tidak memiliki start_date atau year",
                detail="Tambahkan atribut start_date/end_date atau year/month."
            ))
        elif not (has_end or has_month):
            findings.append(Finding(
                file=str(file_path),
                line=node.lineno,
                severity="WARNING",
                category="fiscal_year",
                message=f"Class '{name}' tidak memiliki end_date atau month",
                detail="Tambahkan atribut start_date/end_date atau year/month."
            ))
    return findings


# =============================================================================
# 4. CLOSURE CONSTRAINTS
# =============================================================================
def check_closure_constraints(tree: ast.AST, file_path: pathlib.Path) -> list[Finding]:
    findings = []
    if not (is_service_file(file_path) or is_use_case_file(file_path) or is_domain_file(file_path)):
        return findings

    close_funcs = {"close_period", "lock_period", "close", "lock"}
    reopen_funcs = {"reopen_period", "unlock_period", "reopen", "unlock"}

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if is_property_method(node):
            continue
        fname = node.name.lower()
        if is_getter_or_validator(fname):
            continue

        # Close / lock
        if any(c in fname for c in close_funcs):
            if has_validation_call(node) or has_if_status_check(node):
                continue

            has_status_check = False
            for sub in ast.walk(node):
                if isinstance(sub, ast.If):
                    cond = ast.unparse(sub.test).lower()
                    if "_status" in cond and "open" in cond:
                        has_status_check = True
                        break
                    if "is_closed" in cond or "is_locked" in cond:
                        has_status_check = True
                        break
                    if "can_close" in cond or "validate_can_close" in cond:
                        has_status_check = True
                        break
                if isinstance(sub, ast.Assert):
                    cond = ast.unparse(sub.test).lower()
                    if "_status" in cond and "open" in cond:
                        has_status_check = True
                        break
            if has_status_check:
                continue

            findings.append(Finding(
                file=str(file_path),
                line=node.lineno,
                severity="WARNING",
                category="closure_constraint",
                message=f"Fungsi '{node.name}' tidak memeriksa status sebelum close",
                detail="Tambahkan ensure_can_close() atau cek period.status == OPEN."
            ))

        # Reopen / unlock
        if any(r in fname for r in reopen_funcs):
            has_closed_check = False
            for sub in ast.walk(node):
                if isinstance(sub, ast.If):
                    cond = ast.unparse(sub.test).lower()
                    if "closed" in cond:
                        has_closed_check = True
                        break
                    if "can_reopen" in cond or "is_closed" in cond:
                        has_closed_check = True
                        break
                    if "validate_can_reopen" in cond or "validate_status_transition" in cond:
                        has_closed_check = True
                        break
                if isinstance(sub, ast.Assert):
                    cond = ast.unparse(sub.test).lower()
                    if "closed" in cond:
                        has_closed_check = True
                        break
            if not has_closed_check and not has_method_call(
                node,
                ["ensure_closed", "is_closed", "can_reopen", "validate_can_reopen_period", "can_reopen_period"]
            ):
                findings.append(Finding(
                    file=str(file_path),
                    line=node.lineno,
                    severity="ERROR",
                    category="closure_constraint",
                    message=f"Fungsi '{node.name}' tidak memvalidasi period sudah CLOSED",
                    detail="Tambahkan validasi period.status == CLOSED sebelum reopen."
                ))
    return findings


# =============================================================================
# 5. YEAR-END CLOSING
# =============================================================================
def check_year_end(tree: ast.AST, file_path: pathlib.Path) -> list[Finding]:
    findings = []
    if not (is_service_file(file_path) or is_use_case_file(file_path)):
        return findings

    closing_keywords = {"year_end", "year_close", "close_books", "perform_closing", "year_end_closing"}

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if is_property_method(node):
            continue
        fname = node.name.lower()
        if is_getter_or_validator(fname):
            continue
        if not any(k in fname for k in closing_keywords):
            continue

        body = ast.unparse(node)
        has_retained = "retained" in body.lower() and "earnings" in body.lower()
        has_journal = "journal" in body.lower() or "entry" in body.lower()

        if not has_retained or not has_journal:
            findings.append(Finding(
                file=str(file_path),
                line=node.lineno,
                severity="WARNING",
                category="year_end",
                message=f"Fungsi '{node.name}' tidak memiliki prosedur year-end closing lengkap",
                detail="Pastikan mencakup retained earnings adjustment dan closing journal entries."
            ))
    return findings


# =============================================================================
# SCANNER
# =============================================================================
def scan_project() -> Report:
    report = Report()
    py_files = get_relevant_files()

    enum_file, statuses = find_period_status_enum()
    expected = {"DRAFT", "OPEN", "CLOSED", "LOCKED"}
    if enum_file:
        missing = expected - statuses
        if missing:
            report.findings.append(Finding(
                file=str(enum_file),
                line=1,
                severity="ERROR",
                category="status_lifecycle",
                message=f"Status period tidak lengkap: {', '.join(missing)}",
                detail="Enum PeriodStatus harus memiliki DRAFT, OPEN, CLOSED, LOCKED."
            ))

    for py_file in py_files:
        try:
            src = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            continue

        report.findings.extend(check_period_validation(tree, py_file))
        report.findings.extend(check_fiscal_year(tree, py_file))
        report.findings.extend(check_closure_constraints(tree, py_file))
        report.findings.extend(check_year_end(tree, py_file))

    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")
    report.score = max(0, 100 - errors * 10 - warnings * 3)
    return report


# =============================================================================
# OUTPUT
# =============================================================================
def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*72}{c['RESET']}")
    print(f"{c['CYAN']}FISCAL PERIOD CHECKER (Conservative){c['RESET']}")
    print(f"{c['CYAN']}{'='*72}{c['RESET']}")
    print(f"\n  Total findings: {len(report.findings)}")
    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")
    print(f"  Errors: {c['RED']}{errors}{c['RESET']}, Warnings: {c['YELLOW']}{warnings}{c['RESET']}")
    print(f"  Score: {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    if report.findings:
        categories = {}
        for f in report.findings:
            categories.setdefault(f.category, []).append(f)

        print(f"\n{c['CYAN']}By Category:{c['RESET']}")
        for cat, items in categories.items():
            label = {
                "status_lifecycle": "Status Lifecycle",
                "period_validation": "Period Validation",
                "fiscal_year": "Fiscal Year",
                "closure_constraint": "Closure Constraints",
                "year_end": "Year-End Closing",
            }.get(cat, cat)
            err = sum(1 for i in items if i.severity == "ERROR")
            warn = sum(1 for i in items if i.severity == "WARNING")
            color = c["RED"] if err else c["YELLOW"] if warn else c["GREEN"]
            print(f"  {label}: {color}{err} errors, {warn} warnings{c['RESET']}")

        print(f"\n{c['RED'] if errors else c['YELLOW']}Details (first 30):{c['RESET']}")
        for f in report.findings[:30]:
            color = c["RED"] if f.severity == "ERROR" else c["YELLOW"]
            print(f"  {color}[{f.severity}]{c['RESET']} [{f.category}] {f.file}:{f.line}")
            print(f"     {f.message}")
            if verbose and f.detail:
                print(f"     {c['CYAN']}→ {f.detail}{c['RESET']}")
        if len(report.findings) > 30:
            print(f"  ... and {len(report.findings)-30} more")
    else:
        print(f"\n{c['GREEN']}✅ Tidak ada pelanggaran fiscal period ditemukan!{c['RESET']}")


def save_json(report: Report, filepath: str):
    data = {
        "score": report.score,
        "findings": [{"file": f.file, "line": f.line, "severity": f.severity,
                      "category": f.category, "message": f.message, "detail": f.detail}
                     for f in report.findings]
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{COLOR['CYAN']}JSON saved to {filepath}{COLOR['RESET']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE")
    args = parser.parse_args()

    report = scan_project()
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)

    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    sys.exit(0 if errors == 0 else 1)


if __name__ == "__main__":
    main()