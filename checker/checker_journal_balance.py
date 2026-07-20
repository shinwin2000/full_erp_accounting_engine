#!/usr/bin/env python3
"""
JOURNAL BALANCE CHECKER v3.1 — PRECISION ARCHITECTURAL VALIDATOR WITH RCA
========================================================================
Memeriksa implementasi jurnal memastikan debit == kredit.
Integrasi dengan RCAEngine untuk rekomendasi perbaikan.

v3:
- Skip GraphQL types (strawberry) agar tidak salah deteksi
- Perbaikan deteksi class jurnal lebih akurat

v3.1 (bugfix performa, ditemukan lewat benchmark nyata):
- FIX BUG PERFORMA UTAMA: setiap file di-parse ulang (read_text + ast.parse)
  SEBANYAK 3 KALI — sekali per step analisis (kumpulkan class jurnal,
  analisis fungsi pembuat entitas, analisis repository). Parsing AST adalah
  bagian termahal dari static analysis, jadi ini menyebabkan waktu proses
  3x lebih lama dari seharusnya. Sekarang setiap file di-parse sekali,
  hasil AST-nya di-cache, lalu dipakai ulang di ketiga step.

Cara pakai:
    python checker/checker_journal_balance.py [--json report.json] [--rca]

Exit code: 0 jika tidak ada critical, 1 jika ada critical.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# ============================================================
# Import RCA (jika ada)
# ============================================================
ROOT = Path(__file__).resolve().parent.parent
CHECKER_CORE = ROOT / "checker" / "core"
if str(CHECKER_CORE) not in sys.path:
    sys.path.insert(0, str(CHECKER_CORE))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from rca import Category, ErrorCode, RCAEngine, RCAResult, Severity, analyze_exception
    RCA_AVAILABLE = True
except ImportError:
    try:
        from checker.core.rca import (
            Category,
            ErrorCode,
            RCAEngine,
            RCAResult,
            Severity,
            analyze_exception,
        )
        RCA_AVAILABLE = True
    except ImportError:
        RCA_AVAILABLE = False
        RCAEngine = None
        Severity = None
        RCAResult = None
        Category = None
        ErrorCode = None
        print("WARNING: RCAEngine not found. RCA analysis disabled.", file=sys.stderr)

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

# ─── Konfigurasi ──────────────────────────────────────────────────────────────
SKIP_DIRS = {
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".git", ".venv", "node_modules", ".tox", ".cache", "dist", "build",
    "docs", "deployment", "scripts", "monitoring",
    "migrations", "tests", "helm", "reports", "event_gateway",
    "dto_objects", "commands_cqrs", "mappers", "checker",
}


@dataclass
class Finding:
    severity: str  # CRITICAL, ERROR, WARNING
    file: str
    line: int
    message: str
    suggestion: str = ""
    rca_severity: str = ""
    rca_root_cause: str = ""


@dataclass
class JournalClassInfo:
    name: str
    file: Path
    line: int
    has_is_balanced: bool = False
    has_validate: bool = False
    has_post_init_check: bool = False
    is_valid: bool = False
    has_lines_field: bool = False
    has_total_debit: bool = False
    has_total_credit: bool = False


@dataclass
class ObjectCreation:
    var_name: str
    class_name: str
    line: int
    file_path: Path
    func_name: str


@dataclass
class MethodCall:
    var_name: str
    method: str
    line: int
    file_path: Path


# ─── AST Helpers ──────────────────────────────────────────────────────────────

def get_ast_tree(path: Path) -> ast.AST | None:
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


def is_graphql_type(class_node: ast.ClassDef) -> bool:
    """
    Deteksi apakah class adalah GraphQL type dari strawberry.
    Cek decorator: @strawberry.type, @strawberry.input, @strawberry.interface, dll.
    """
    for deco in class_node.decorator_list:
        # Kasus: @strawberry.type
        if isinstance(deco, ast.Attribute):
            if isinstance(deco.value, ast.Name) and deco.value.id == "strawberry":
                if deco.attr in ("type", "input", "interface", "union", "enum"):
                    return True
        # Kasus: @strawberry.type(...)
        elif isinstance(deco, ast.Call):
            if isinstance(deco.func, ast.Attribute):
                if isinstance(deco.func.value, ast.Name) and deco.func.value.id == "strawberry":
                    if deco.func.attr in ("type", "input", "interface", "union", "enum"):
                        return True
    return False


def is_journal_class(class_node: ast.ClassDef, file_path: Path) -> bool:
    """Deteksi class yang merupakan entitas jurnal dengan kriteria lebih luas."""
    name = class_node.name

    # Skip GraphQL types (strawberry)
    if is_graphql_type(class_node):
        return False

    # Skip enum
    if is_enum_class(class_node):
        return False

    # Skip file mapper
    if "_mapper.py" in file_path.name or file_path.name.endswith("mapper.py"):
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
        "Mapped", "MapperOutput",
        "GraphQL", "Schema", "Query", "Mutation", "Subscription",
    )
    for pattern in skip_patterns:
        if pattern in name:
            return False

    # HARUS mengandung kata Journal atau Ledger atau Entry (dengan konteks)
    journal_keywords = ("Journal", "Ledger", "Entry")
    if not any(kw in name for kw in journal_keywords):
        return False

    # Periksa struktur internal
    has_lines = False
    has_total_debit = False
    has_total_credit = False
    has_is_balanced = False

    for item in class_node.body:
        if isinstance(item, (ast.Assign, ast.AnnAssign)):
            targets = item.targets if isinstance(item, ast.Assign) else [item.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    if target.id in ("lines", "line_items", "journal_lines", "entries"):
                        has_lines = True
                    if target.id == "total_debit":
                        has_total_debit = True
                    if target.id == "total_credit":
                        has_total_credit = True

        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fname = item.name.lower()
            if fname == "is_balanced":
                has_is_balanced = True

    # Jika class memiliki lines dan total_debit/total_credit → kemungkinan jurnal
    if has_lines and has_total_debit and has_total_credit:
        return True
    if has_is_balanced:
        return True
    if has_lines and any(kw in name for kw in ("Journal", "Ledger")):
        return True

    return False


def analyze_journal_class(class_node: ast.ClassDef, file_path: Path) -> JournalClassInfo:
    info = JournalClassInfo(
        name=class_node.name,
        file=file_path,
        line=class_node.lineno,
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

        # Cek field
        if isinstance(item, (ast.Assign, ast.AnnAssign)):
            targets = item.targets if isinstance(item, ast.Assign) else [item.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    if target.id in ("lines", "line_items", "journal_lines", "entries"):
                        info.has_lines_field = True
                    if target.id == "total_debit":
                        info.has_total_debit = True
                    if target.id == "total_credit":
                        info.has_total_credit = True

    if info.has_is_balanced:
        info.is_valid = True

    return info


class BalanceCheckVisitor(ast.NodeVisitor):
    def __init__(self):
        self.has_check = False

    def visit_Assert(self, node):
        if isinstance(node.test, ast.Compare):
            left = ast.unparse(node.test.left)
            right = ast.unparse(node.test.comparators[0]) if node.test.comparators else ""
            if ("debit" in left.lower() and "credit" in right.lower()) or ("credit" in left.lower() and "debit" in right.lower()):
                self.has_check = True
        self.generic_visit(node)

    def visit_If(self, node):
        if isinstance(node.test, ast.Compare):
            left = ast.unparse(node.test.left)
            right = ast.unparse(node.test.comparators[0]) if node.test.comparators else ""
            if ("debit" in left.lower() and "credit" in right.lower()) or ("credit" in left.lower() and "debit" in right.lower()):
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


def is_journal_constructor(call_node: ast.Call, class_names: set[str]) -> str | None:
    if isinstance(call_node.func, ast.Name):
        if call_node.func.id in class_names:
            return call_node.func.id
    return None


def extract_object_creations(
    func_node: ast.FunctionDef,
    journal_class_names: set[str],
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
                                file_path=file_path,
                                func_name=func_node.name
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
                            file_path=file_path,
                            func_name=func_node.name
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
    body = func_node.body
    if len(body) != 1:
        return False
    stmt = body[0]
    if isinstance(stmt, ast.Raise):
        if isinstance(stmt.exc, ast.Call):
            if isinstance(stmt.exc.func, ast.Name) and stmt.exc.func.id == "NotImplementedError":
                return True
        return False
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Expr):
        if isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis:
            return True
    return False


# ─── RCA Integration ──────────────────────────────────────────────────────────

def get_rca_analysis_for_finding(finding: Finding) -> tuple[str, str]:
    """Gunakan RCAEngine untuk menganalisis temuan dan beri rekomendasi."""
    if not RCA_AVAILABLE:
        return "", ""

    # Buat exception dummy dengan pesan temuan
    dummy_exc = RuntimeError(f"Journal Balance Violation: {finding.message}")
    try:
        result = analyze_exception(dummy_exc)
        if result:
            return result.severity.value, result.suggested_fix or result.root_cause
    except Exception:
        pass
    return "", ""


# ─── Main Orchestrator ──────────────────────────────────────────────────────

def run_checker(verbose: bool = False, json_out: str | None = None, use_rca: bool = True) -> int:
    print(f"{BOLD}{CYAN}╔{'═'*78}╗{RESET}")
    print(f"{BOLD}{CYAN}║{' '*20}JOURNAL BALANCE CHECKER v3.1 (RCA-ENABLED){' '*20}║{RESET}")
    print(f"{BOLD}{CYAN}╚{'═'*78}╝{RESET}")
    print(f"  Root: {ROOT}")
    print(f"  RCA Enabled: {RCA_AVAILABLE and use_rca}")
    print()

    # Scan semua file Python di seluruh proyek (kecuali skip dirs)
    all_files = []
    for p in ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.name.startswith("__") and p.name != "__init__.py":
            continue
        if p.name in ("checker_journal_balance.py", "rca.py", "rca_project_rules.py", "test_rca.py"):
            continue
        all_files.append(p)

    print(f"🔍 Scanning {len(all_files)} Python files...")

    findings: list[Finding] = []
    journal_classes: list[JournalClassInfo] = []
    journal_class_names: set[str] = set()

    # FIX v3.1.0 — BUG PERFORMA UTAMA:
    # Versi lama memanggil get_ast_tree(file_path) — yaitu read_text() + ast.parse() —
    # SATU KALI PER STEP untuk SETIAP file, dan ada 3 step (kumpulkan class jurnal,
    # analisis fungsi pembuat entitas, analisis repository). Artinya setiap file
    # dibaca dari disk dan di-parse ulang 3x. Pada codebase besar, parsing AST
    # adalah bagian termahal dari static analysis, jadi ini yang membuat checker
    # terasa lama. Sekarang setiap file di-parse SEKALI, tree-nya di-cache, lalu
    # dipakai ulang di ketiga step.
    file_trees: dict[Path, ast.AST] = {}
    for file_path in all_files:
        tree = get_ast_tree(file_path)
        if tree is not None:
            file_trees[file_path] = tree

    # ─── Step 1: Kumpulkan semua class jurnal ────────────────────────────────
    for file_path, tree in file_trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if is_journal_class(node, file_path):
                    info = analyze_journal_class(node, file_path)
                    journal_classes.append(info)
                    journal_class_names.add(info.name)

                    if not info.is_valid:
                        findings.append(Finding(
                            severity="CRITICAL",
                            file=str(file_path.relative_to(ROOT)),
                            line=node.lineno,
                            message=f"Journal class '{info.name}' tidak memiliki validasi balance (is_balanced / __post_init__).",
                            suggestion="Tambahkan metode is_balanced() atau __post_init__ yang membandingkan total_debit == total_credit."
                        ))

    # ─── Step 2: Analisis semua fungsi yang membuat dan menyimpan entitas jurnal ──
    for file_path, tree in file_trees.items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                creations = extract_object_creations(node, journal_class_names, file_path)
                if not creations:
                    continue

                calls = extract_method_calls(node, file_path)

                for creation in creations:
                    # Cek apakah ada method save/persist yang dipanggil pada object ini
                    save_calls = [c for c in calls if c.var_name == creation.var_name and c.method in ("save", "add", "persist", "store", "create")]
                    if not save_calls:
                        continue

                    # Cek apakah ada validasi balance sebelum save
                    validate_calls = [c for c in calls if c.var_name == creation.var_name and c.method in ("validate", "is_balanced", "ensure_balanced")]
                    if validate_calls:
                        continue

                    # Cek apakah class memiliki __post_init__ yang validasi
                    class_info = next((ci for ci in journal_classes if ci.name == creation.class_name), None)
                    if class_info and class_info.has_post_init_check:
                        continue

                    # Cek apakah class memiliki is_balanced
                    if class_info and class_info.has_is_balanced:
                        # Jika ada is_balanced tapi tidak dipanggil sebelum save, tetap warning
                        findings.append(Finding(
                            severity="ERROR",
                            file=str(file_path.relative_to(ROOT)),
                            line=creation.line,
                            message=f"Fungsi '{node.name}' membuat entitas jurnal ({creation.class_name}) tetapi tidak memanggil .is_balanced() sebelum save.",
                            suggestion=f"Panggil {creation.var_name}.is_balanced() sebelum menyimpan untuk memastikan debit == kredit."
                        ))
                    else:
                        findings.append(Finding(
                            severity="CRITICAL",
                            file=str(file_path.relative_to(ROOT)),
                            line=creation.line,
                            message=f"Fungsi '{node.name}' membuat entitas jurnal ({creation.class_name}) tanpa validasi balance.",
                            suggestion=f"Panggil {creation.var_name}.validate() atau {creation.var_name}.is_balanced() sebelum menyimpan, atau tambahkan __post_init__ dengan validasi."
                        ))

    # ─── Step 3: Analisis Repository (JournalRepository, LedgerRepository) ──
    for file_path, tree in file_trees.items():
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
                        if is_abstract_method(item):
                            continue

                        args = item.args.args
                        if len(args) > 1:
                            entity_var = args[1].arg
                            if entity_var.endswith("_id"):
                                continue

                            # Cek apakah entity_var adalah entitas jurnal (cek class_names)
                            if entity_var not in journal_class_names and entity_var.title() not in journal_class_names:
                                continue

                            calls = extract_method_calls(item, file_path)
                            validate_calls = [c for c in calls if c.var_name == entity_var and c.method in ("validate", "is_balanced", "ensure_balanced")]

                            class_info = next((ci for ci in journal_classes if ci.name == entity_var or ci.name == entity_var.title()), None)
                            if class_info and class_info.has_post_init_check:
                                continue

                            if not validate_calls:
                                findings.append(Finding(
                                    severity="ERROR",
                                    file=str(file_path.relative_to(ROOT)),
                                    line=item.lineno,
                                    message=f"Repository '{node.name}.{item.name}' menyimpan {entity_var} tanpa validasi balance.",
                                    suggestion=f"Panggil {entity_var}.validate() atau {entity_var}.is_balanced() sebelum commit."
                                ))

    # ─── Step 4: Analisis RCA ──────────────────────────────────────────────
    if use_rca and RCA_AVAILABLE:
        for f in findings:
            sev, suggestion = get_rca_analysis_for_finding(f)
            f.rca_severity = sev
            if suggestion:
                f.suggestion = suggestion if not f.suggestion else f.suggestion + " " + suggestion

    # ─── Report ──────────────────────────────────────────────────────────────
    critical = [f for f in findings if f.severity == "CRITICAL"]
    errors = [f for f in findings if f.severity == "ERROR"]
    warnings = [f for f in findings if f.severity == "WARNING"]

    print("\n" + "═" * 80)
    print(f"{BOLD}📊 SUMMARY{RESET}")
    print(f"  Journal classes found:    {len(journal_classes)}")
    if verbose:
        for jc in journal_classes:
            print(f"    - {jc.name} ({jc.file.relative_to(ROOT)}:{jc.line}) {'✅' if jc.is_valid else '❌'}")
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
            if f.rca_severity:
                print(f"      🧠 RCA Severity: {f.rca_severity}")
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
            "journal_classes": [
                {"name": jc.name, "file": str(jc.file.relative_to(ROOT)), "line": jc.line, "valid": jc.is_valid}
                for jc in journal_classes
            ],
            "issues": {
                "critical": [{"file": f.file, "line": f.line, "message": f.message, "suggestion": f.suggestion, "rca_severity": f.rca_severity} for f in critical],
                "errors": [{"file": f.file, "line": f.line, "message": f.message, "suggestion": f.suggestion, "rca_severity": f.rca_severity} for f in errors],
                "warnings": [{"file": f.file, "line": f.line, "message": f.message, "suggestion": f.suggestion, "rca_severity": f.rca_severity} for f in warnings],
            }
        }
        Path(json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\n{CYAN}📁 JSON report saved to {json_out}{RESET}")

    return exit_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan detail class jurnal")
    parser.add_argument("--json", metavar="FILE", help="Simpan laporan ke JSON")
    parser.add_argument("--no-rca", action="store_true", help="Nonaktifkan RCA analysis")
    args = parser.parse_args()

    sys.exit(run_checker(verbose=args.verbose, json_out=args.json, use_rca=not args.no_rca))
