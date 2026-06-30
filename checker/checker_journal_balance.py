#!/usr/bin/env python3
"""
JOURNAL BALANCE CHECKER v1 — PRECISION ARCHITECTURAL VALIDATOR
================================================================
Memeriksa apakah implementasi jurnal memastikan debit == kredit.

V1 PERBAIKAN:
- Skip file *_mapper.py dan *mapper.py
- Skip class dengan nama Mapped* atau *MapperOutput
- Hanya class dengan kata Journal/Ledger yang diperiksa

Cara pakai:
    python checker/checker_journal_balance.py [--json report.json]

Exit code: 0 jika tidak ada critical, 1 jika ada critical.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Set

# ─── Konfigurasi ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SKIP_DIRS = {
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".git", ".venv", "node_modules", ".tox", ".cache", "dist", "build",
    "docs", "deployment", "scripts", "monitoring", "checker",
    "migrations", "tests", "helm", "reports", "event_gateway",
    "dto_objects", "commands_cqrs", "mappers",
}

SCAN_DIRS = [
    "domain",
    "application/service_layer",
    "application/use_cases",
]

# ─── Color ──────────────────────────────────────────────────────────────────
try:
    import colorama
    colorama.init(autoreset=True)
    RED = colorama.Fore.RED
    GREEN = colorama.Fore.GREEN
    YELLOW = colorama.Fore.YELLOW
    CYAN = colorama.Fore.CYAN
    BOLD = colorama.Style.BRIGHT
    RESET = colorama.Style.RESET_ALL
except ImportError:
    RED = GREEN = YELLOW = CYAN = BOLD = RESET = ""


@dataclass
class Finding:
    severity: str
    file: str
    line: int
    message: str
    suggestion: str = ""


@dataclass
class JournalClassInfo:
    name: str
    file: Path
    line: int
    has_is_balanced: bool = False
    has_validate: bool = False
    has_post_init_check: bool = False
    is_valid: bool = False
    is_journal: bool = False


@dataclass
class ObjectCreation:
    var_name: str
    class_name: str
    line: int
    file_path: Path


@dataclass
class MethodCall:
    var_name: str
    method: str
    line: int
    file_path: Path


# ─── AST Helpers ──────────────────────────────────────────────────────────────

def get_ast_tree(path: Path) -> Optional[ast.AST]:
    try:
        src = path.read_text(encoding="utf-8")
        return ast.parse(src, filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return None


def is_enum_class(class_node: ast.ClassDef) -> bool:
    for base in class_node.bases:
        if isinstance(base, ast.Name) and base.id == "Enum":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "Enum":
            return True
    return False


def is_mapper_file(file_path: Path) -> bool:
    """Cek apakah file adalah mapper file."""
    name = file_path.name
    return "_mapper.py" in name or name.endswith("mapper.py")


def is_mapped_class(class_name: str) -> bool:
    """Cek apakah class adalah hasil mapping."""
    return class_name.startswith("Mapped") or class_name.endswith("MapperOutput")


def is_journal_class(class_node: ast.ClassDef, file_path: Path) -> bool:
    """Deteksi class yang benar-benar merupakan entitas jurnal."""
    name = class_node.name

    # Skip mapper file
    if is_mapper_file(file_path):
        return False

    # Skip mapped class
    if is_mapped_class(name):
        return False

    if is_enum_class(class_node):
        return False

    # Skip class dengan kata yang jelas bukan jurnal
    skip_patterns = (
        "Invariants", "StateMachine", "Validator", "Helper", "Manager",
        "Config", "Factory", "Repository", "Service", "Controller",
        "Router", "Middleware", "Handler", "Listener", "Consumer",
        "Producer", "Wrapper", "Adapter", "Transformer",
        "Error", "Exception", "Event", "Response", "Request", "DTO",
        "Command", "Query", "Envelope", "Notification", "Snapshot",
        "Projection", "ViewModel", "Mixin", "Protocol", "Port",
        "VO", "ValueObject", "Type", "Side", "Status", "Entry",
        "TimeEntry", "Transaction", "Invoice", "Receipt", "Disbursement",
        "Payment", "Purchase", "Sales", "Budget", "Forex", "Line",
    )
    for pattern in skip_patterns:
        if pattern in name:
            return False

    # HARUS mengandung kata Journal atau Ledger
    if "Journal" not in name and "Ledger" not in name:
        return False

    # Class jurnal harus memiliki total_debit/total_credit atau is_balanced atau lines
    has_total_debit = False
    has_total_credit = False
    has_is_balanced = False
    has_lines = False

    for item in class_node.body:
        if isinstance(item, (ast.Assign, ast.AnnAssign)):
            targets = item.targets if isinstance(item, ast.Assign) else [item.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in ("lines", "line_items", "journal_lines"):
                    has_lines = True

        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fname = item.name.lower()
            if fname == "is_balanced":
                has_is_balanced = True
            if fname == "total_debit":
                has_total_debit = True
            if fname == "total_credit":
                has_total_credit = True

    if has_is_balanced:
        return True
    if has_lines and has_total_debit and has_total_credit:
        return True
    if has_lines and "Journal" in name:
        return True

    return False


def analyze_journal_class(class_node: ast.ClassDef, file_path: Path) -> JournalClassInfo:
    info = JournalClassInfo(
        name=class_node.name,
        file=file_path,
        line=class_node.lineno,
        is_journal="Journal" in class_node.name or "Ledger" in class_node.name,
    )

    def has_balance_check(node: ast.AST) -> bool:
        visitor = BalanceCheckVisitor()
        visitor.visit(node)
        return visitor.has_check

    for item in class_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fname = item.name.lower()
            if fname == "is_balanced":
                info.has_is_balanced = True
            if fname == "validate":
                info.has_validate = True
                if has_balance_check(item):
                    info.is_valid = True
        if isinstance(item, ast.FunctionDef) and item.name == "__post_init__":
            if has_balance_check(item):
                info.has_post_init_check = True
                info.is_valid = True

    if info.has_is_balanced:
        info.is_valid = True

    return info


class BalanceCheckVisitor(ast.NodeVisitor):
    def __init__(self):
        self.has_check = False

    def visit_Assert(self, node):
        if isinstance(node.test, ast.Compare):
            left = ast.unparse(node.test.left) if hasattr(ast, 'unparse') else ""
            for comp in node.test.comparators:
                right = ast.unparse(comp) if hasattr(ast, 'unparse') else ""
                if ("debit" in left and "credit" in right) or ("credit" in left and "debit" in right):
                    self.has_check = True
        self.generic_visit(node)

    def visit_If(self, node):
        if isinstance(node.test, ast.Compare):
            left = ast.unparse(node.test.left) if hasattr(ast, 'unparse') else ""
            for comp in node.test.comparators:
                right = ast.unparse(comp) if hasattr(ast, 'unparse') else ""
                if ("debit" in left and "credit" in right) or ("credit" in left and "debit" in right):
                    self.has_check = True
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in ("is_balanced", "ensure_balanced", "check_balance", "validate"):
                self.has_check = True
        if isinstance(node.func, ast.Name):
            if node.func.id in ("is_balanced", "ensure_balanced", "check_balance", "validate"):
                self.has_check = True
        self.generic_visit(node)


def is_journal_constructor(call_node: ast.Call, class_names: Set[str]) -> Optional[str]:
    if isinstance(call_node.func, ast.Name):
        if call_node.func.id in class_names:
            return call_node.func.id
    return None


def extract_object_creations(
    func_node: ast.FunctionDef,
    journal_class_names: Set[str],
    file_path: Path
) -> list[ObjectCreation]:
    creations = []

    for node in ast.walk(func_node):
        if isinstance(node, ast.Assign):
            if isinstance(node.value, ast.Call):
                class_name = is_journal_constructor(node.value, journal_class_names)
                if class_name:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            creations.append(ObjectCreation(
                                var_name=target.id,
                                class_name=class_name,
                                line=node.lineno,
                                file_path=file_path
                            ))
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.value, ast.Call):
                class_name = is_journal_constructor(node.value, journal_class_names)
                if class_name:
                    if isinstance(node.target, ast.Name):
                        creations.append(ObjectCreation(
                            var_name=node.target.id,
                            class_name=class_name,
                            line=node.lineno,
                            file_path=file_path
                        ))

    return creations


def extract_method_calls(
    func_node: ast.FunctionDef,
    file_path: Path
) -> list[MethodCall]:
    calls = []

    for node in ast.walk(func_node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                calls.append(MethodCall(
                    var_name=node.func.value.id,
                    method=node.func.attr,
                    line=node.lineno,
                    file_path=file_path
                ))

    return calls


def is_abstract_method(func_node: ast.FunctionDef) -> bool:
    """Cek apakah method adalah abstract (raise NotImplementedError, pass, atau ...)."""
    body = func_node.body
    if len(body) != 1:
        return False

    stmt = body[0]
    if isinstance(stmt, ast.Raise):
        # Cek apakah raise NotImplementedError
        if isinstance(stmt.exc, ast.Call):
            if isinstance(stmt.exc.func, ast.Name) and stmt.exc.func.id == "NotImplementedError":
                return True
        return False
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Expr):
        if isinstance(stmt.value, ast.Constant):
            if stmt.value.value is Ellipsis:
                return True
    return False


def is_journal_entity_name(name: str) -> bool:
    skip_patterns = (
        "Event", "Response", "Request", "DTO", "Command", "Query",
        "Envelope", "Notification", "Snapshot", "Projection", "ViewModel",
        "Mixin", "Protocol", "Port", "VO", "ValueObject", "Type", "Side",
        "Status", "Entry", "TimeEntry", "Transaction", "Invoice",
        "Receipt", "Disbursement", "Payment", "Purchase", "Sales",
        "Budget", "Forex", "Line", "Invariants", "StateMachine",
        "Validator", "Helper", "Manager", "Config", "Factory",
        "Repository", "Service", "Controller", "Router", "Middleware",
        "Handler", "Listener", "Consumer", "Producer", "Wrapper",
        "Adapter", "Transformer", "Mapper", "Error", "Exception",
        "Mapped", "MapperOutput",
    )
    for pattern in skip_patterns:
        if pattern in name:
            return False
    return "Journal" in name or "Ledger" in name


# ─── Main Orchestrator ──────────────────────────────────────────────────────

def run_checker(verbose: bool = False, json_out: Optional[str] = None) -> int:
    print(f"{BOLD}{CYAN}╔{'═'*78}╗{RESET}")
    print(f"{BOLD}{CYAN}║{' '*20}JOURNAL BALANCE CHECKER v1 (PRECISION){' '*20}║{RESET}")
    print(f"{BOLD}{CYAN}╚{'═'*78}╝{RESET}")
    print(f"  Root: {ROOT}")
    print()

    all_files = []
    for dir_name in SCAN_DIRS:
        target = ROOT / dir_name
        if not target.exists():
            continue
        for p in target.rglob("*.py"):
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            if p.name.startswith("__") and p.name != "__init__.py":
                continue
            if p.name == "checker_journal_balance.py":
                continue
            all_files.append(p)

    print(f"🔍 Scanning {len(all_files)} Python files...")

    findings: list[Finding] = []
    journal_classes: list[JournalClassInfo] = []
    journal_class_names: Set[str] = set()

    # ─── Step 1: Kumpulkan semua class jurnal ────────────────────────────────
    for file_path in all_files:
        tree = get_ast_tree(file_path)
        if tree is None:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if is_journal_class(node, file_path):
                    info = analyze_journal_class(node, file_path)
                    journal_classes.append(info)
                    if info.is_journal:
                        journal_class_names.add(info.name)

                    if not info.is_valid and info.is_journal:
                        findings.append(Finding(
                            severity="CRITICAL",
                            file=str(file_path.relative_to(ROOT)),
                            line=node.lineno,
                            message=f"Journal class '{info.name}' tidak memiliki validasi balance.",
                            suggestion="Tambahkan metode is_balanced() atau __post_init__ yang membandingkan total_debit == total_credit."
                        ))

    # ─── Step 2: Analisis fungsi service/use_case ─────────────────────────────
    for file_path in all_files:
        tree = get_ast_tree(file_path)
        if tree is None:
            continue

        rel_path = str(file_path.relative_to(ROOT))
        if "service_layer" not in rel_path and "use_cases" not in rel_path:
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                creations = extract_object_creations(node, journal_class_names, file_path)
                if not creations:
                    continue

                calls = extract_method_calls(node, file_path)

                for creation in creations:
                    save_calls = [c for c in calls if c.var_name == creation.var_name and c.method in ("save", "add", "persist", "store")]
                    if not save_calls:
                        continue

                    validate_calls = [c for c in calls if c.var_name == creation.var_name and c.method in ("validate", "is_balanced", "ensure_balanced")]

                    if not validate_calls:
                        class_info = next((ci for ci in journal_classes if ci.name == creation.class_name), None)
                        if class_info and class_info.has_post_init_check:
                            continue

                        findings.append(Finding(
                            severity="CRITICAL",
                            file=str(file_path.relative_to(ROOT)),
                            line=creation.line,
                            message=f"Fungsi posting '{node.name}' membuat entitas jurnal ({creation.class_name}) tanpa memanggil .validate() atau .is_balanced() sebelum save.",
                            suggestion=f"Panggil {creation.var_name}.validate() atau {creation.var_name}.is_balanced() sebelum menyimpan."
                        ))

    # ─── Step 3: Repository (hanya JournalRepository/LedgerRepository) ──────
    for file_path in all_files:
        tree = get_ast_tree(file_path)
        if tree is None:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if not node.name.endswith("Repository"):
                    continue
                if "Journal" not in node.name and "Ledger" not in node.name:
                    continue

                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if item.name.lower() not in ("save", "update", "add", "persist", "store"):
                            continue

                        # Skip abstract method
                        if is_abstract_method(item):
                            continue

                        args = item.args.args
                        if len(args) > 1:
                            entity_var = args[1].arg
                            if entity_var.endswith("_id"):
                                continue

                            if not is_journal_entity_name(entity_var.title()) and not is_journal_entity_name(entity_var):
                                continue

                            calls = extract_method_calls(item, file_path)
                            validate_calls = [c for c in calls if c.var_name == entity_var and c.method in ("validate", "is_balanced", "ensure_balanced")]

                            class_info = next((ci for ci in journal_classes if ci.name == entity_var.title() or ci.name == entity_var), None)
                            if class_info and class_info.has_post_init_check:
                                continue

                            if not validate_calls:
                                findings.append(Finding(
                                    severity="CRITICAL",
                                    file=str(file_path.relative_to(ROOT)),
                                    line=item.lineno,
                                    message=f"Repository '{node.name}.{item.name}' menyimpan {entity_var} tanpa validasi balance.",
                                    suggestion=f"Panggil {entity_var}.validate() atau {entity_var}.is_balanced() sebelum commit."
                                ))

    # ─── Report ──────────────────────────────────────────────────────────────
    critical = [f for f in findings if f.severity == "CRITICAL"]
    errors = [f for f in findings if f.severity == "ERROR"]
    warnings = [f for f in findings if f.severity == "WARNING"]

    print("\n" + "═" * 80)
    print(f"{BOLD}📊 SUMMARY{RESET}")
    print(f"  Journal classes found:    {len(journal_classes)}")
    print(f"  ❌ Critical issues:       {len(critical)}")
    print(f"  ⚠️  Errors:                {len(errors)}")
    print(f"  ℹ️  Warnings:              {len(warnings)}")

    if critical or errors:
        print("\n" + f"{RED}{BOLD}🔴 DETAIL ISSUES{RESET}")
        for f in critical + errors:
            print(f"  [{f.severity}] {f.file}:{f.line}")
            print(f"      {f.message}")
            if f.suggestion:
                print(f"      💡 {f.suggestion}")
        print("\n" + f"{RED}{BOLD}❌ VALIDATION FAILED — Perbaiki critical/error issues.{RESET}")
        exit_code = 1
    else:
        print("\n" + f"{GREEN}{BOLD}✅ VALIDATION PASSED — Tidak ada critical/error issues.{RESET}")
        if warnings:
            print(f"{YELLOW}   {len(warnings)} warnings tersedia, gunakan --verbose untuk detail.{RESET}")
        exit_code = 0

    if json_out:
        report = {
            "summary": {
                "journal_classes": len(journal_classes),
                "critical": len(critical),
                "errors": len(errors),
                "warnings": len(warnings),
            },
            "issues": {
                "critical": [{"file": f.file, "line": f.line, "message": f.message, "suggestion": f.suggestion} for f in critical],
                "errors": [{"file": f.file, "line": f.line, "message": f.message, "suggestion": f.suggestion} for f in errors],
                "warnings": [{"file": f.file, "line": f.line, "message": f.message, "suggestion": f.suggestion} for f in warnings],
            }
        }
        Path(json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\n{CYAN}📁 JSON report saved to {json_out}{RESET}")

    return exit_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE")
    args = parser.parse_args()
    sys.exit(run_checker(verbose=args.verbose, json_out=args.json))