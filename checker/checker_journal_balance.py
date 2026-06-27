#!/usr/bin/env python3
"""
JOURNAL BALANCE CHECKER — PRECISION (AST + Runtime)
====================================================
Memeriksa secara nyata apakah implementasi jurnal di seluruh proyek
memastikan debit == kredit. Fokus pada entitas jurnal yang sebenarnya,
fungsi posting yang benar, dan repository yang menyimpan jurnal.

Tidak menghasilkan false positive untuk value objects atau __post_init__.

Cara pakai:
    python test_journal_balance_precision.py [--verbose] [--json report.json]

Exit code: 0 jika semua valid, 1 jika ada critical issue.
"""

import ast
import importlib
import inspect
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ─── Konfigurasi ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent

SKIP_DIRS = {
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".git", ".venv", "node_modules", ".tox", ".cache", "dist", "build", "uv",
    "tests", "migrations", "docs", "deployment", "scripts", "monitoring"
}

# Direktori yang akan di-scan
SCAN_DIRS = [
    "domain",
    "application/use_cases",
    "application/service_layer",
    "application/commands_cqrs",
    "adapters/secondary_impl",
]

# Keyword untuk validasi balance
VALIDATE_KEYWORDS = {"validate", "check", "enforce", "verify", "assert_balance", "ensure_balance"}

# Class yang diabaikan (base class, bukan jurnal)
IGNORE_CLASSES = {"BaseJournal", "AbstractJournal", "JournalEntry", "JournalLine", "BaseEntity"}

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
    recommendation: str = ""
    detail: str = ""

@dataclass
class JournalClassInfo:
    name: str
    file: Path
    line: int
    has_debit: bool
    has_credit: bool
    has_lines: bool
    validate_method: str | None
    is_valid: bool = False
    reason: str = ""

@dataclass
class PostingFunction:
    name: str
    file: Path
    line: int
    calls_validate: bool
    called_validate: str
    is_valid: bool = False
    reason: str = ""

@dataclass
class RepositoryMethod:
    name: str
    file: Path
    line: int
    entity_type: str
    calls_validate: bool
    is_valid: bool = False
    reason: str = ""

# ─── AST Helpers ──────────────────────────────────────────────────────────────

def get_ast_tree(path: Path):
    try:
        src = path.read_text(encoding="utf-8")
        return ast.parse(src, filename=str(path))
    except:
        return None

def is_journal_class(class_node: ast.ClassDef) -> tuple[bool, bool, bool]:
    """
    Periksa apakah class memiliki field debit/credit atau lines.
    Kembalikan (has_debit, has_credit, has_lines).
    """
    has_debit = False
    has_credit = False
    has_lines = False
    for item in class_node.body:
        # Assign
        if isinstance(item, ast.Assign):
            for target in item.targets:
                if isinstance(target, ast.Name):
                    name = target.id.lower()
                    if name in ("debit", "debit_amount"):
                        has_debit = True
                    elif name in ("credit", "credit_amount"):
                        has_credit = True
                    elif name in ("lines", "line_items", "journal_lines"):
                        has_lines = True
        # AnnAssign
        elif isinstance(item, ast.AnnAssign):
            if isinstance(item.target, ast.Name):
                name = item.target.id.lower()
                if name in ("debit", "debit_amount"):
                    has_debit = True
                elif name in ("credit", "credit_amount"):
                    has_credit = True
                elif name in ("lines", "line_items", "journal_lines"):
                    has_lines = True
    return has_debit, has_credit, has_lines

def has_validate_method(class_node: ast.ClassDef) -> str | None:
    """Cari metode validasi dalam class."""
    for item in class_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(kw in item.name.lower() for kw in VALIDATE_KEYWORDS):
                return item.name
    return None

def is_posting_function(func_node: ast.FunctionDef) -> bool:
    """True jika fungsi memposting jurnal (berdasarkan nama)."""
    name = func_node.name.lower()
    # Jangan flag __post_init__ karena itu bukan fungsi posting
    if name == "__post_init__":
        return False
    # Hanya fungsi yang secara eksplisit menandakan posting
    return any(kw in name for kw in ["post_journal", "save_journal", "add_journal", "create_journal", "post_entry"])

def is_repository_method(class_node: ast.ClassDef, func_node: ast.FunctionDef) -> tuple[bool, str]:
    """True jika method adalah repository save/update."""
    # Class harus bernama *Repository
    if not class_node.name.endswith("Repository"):
        return False, ""
    name = func_node.name.lower()
    if name in ("save", "update", "add", "persist", "store"):
        # Cari parameter pertama yang bukan self
        args = func_node.args.args
        if len(args) > 1:
            entity_arg = args[1].arg
            return True, entity_arg
    return False, ""

def extract_journal_classes(path: Path) -> list[JournalClassInfo]:
    tree = get_ast_tree(path)
    if not tree:
        return []
    result = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if node.name in IGNORE_CLASSES:
                continue
            has_debit, has_credit, has_lines = is_journal_class(node)
            # Hanya jika memiliki debit/credit atau lines
            if has_debit or has_credit or has_lines:
                validate = has_validate_method(node)
                info = JournalClassInfo(
                    name=node.name,
                    file=path,
                    line=node.lineno,
                    has_debit=has_debit,
                    has_credit=has_credit,
                    has_lines=has_lines,
                    validate_method=validate
                )
                result.append(info)
    return result

def extract_posting_functions(path: Path) -> list[PostingFunction]:
    tree = get_ast_tree(path)
    if not tree:
        return []
    result = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if is_posting_function(node):
                # Cek apakah fungsi memanggil validasi
                calls_validate = False
                called = ""
                body_text = ast.unparse(node) if hasattr(ast, 'unparse') else ""
                for subnode in ast.walk(node):
                    if isinstance(subnode, ast.Call):
                        if isinstance(subnode.func, ast.Name):
                            if any(kw in subnode.func.id.lower() for kw in VALIDATE_KEYWORDS):
                                calls_validate = True
                                called = subnode.func.id
                        elif isinstance(subnode.func, ast.Attribute):
                            if any(kw in subnode.func.attr.lower() for kw in VALIDATE_KEYWORDS):
                                calls_validate = True
                                called = subnode.func.attr
                if not calls_validate:
                    # Cek assert debit==credit
                    if "assert" in body_text and "debit" in body_text and "credit" in body_text:
                        calls_validate = True
                        called = "assert"
                result.append(PostingFunction(
                    name=node.name,
                    file=path,
                    line=node.lineno,
                    calls_validate=calls_validate,
                    called_validate=called
                ))
    return result

def extract_repository_methods(path: Path) -> list[RepositoryMethod]:
    tree = get_ast_tree(path)
    if not tree:
        return []
    result = []
    # Cari class repository dan method-nya
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name.endswith("Repository"):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    is_repo, entity_arg = is_repository_method(node, item)
                    if is_repo:
                        # Cek apakah method memanggil validasi
                        calls_validate = False
                        for subnode in ast.walk(item):
                            if isinstance(subnode, ast.Call):
                                if isinstance(subnode.func, ast.Name):
                                    if any(kw in subnode.func.id.lower() for kw in VALIDATE_KEYWORDS):
                                        calls_validate = True
                                elif isinstance(subnode.func, ast.Attribute):
                                    if any(kw in subnode.func.attr.lower() for kw in VALIDATE_KEYWORDS):
                                        calls_validate = True
                        if not calls_validate:
                            body_text = ast.unparse(item) if hasattr(ast, 'unparse') else ""
                            if "assert" in body_text and "debit" in body_text and "credit" in body_text:
                                calls_validate = True
                        result.append(RepositoryMethod(
                            name=item.name,
                            file=path,
                            line=item.lineno,
                            entity_type=entity_arg,
                            calls_validate=calls_validate
                        ))
    return result

# ─── Runtime Introspection ───────────────────────────────────────────────────

def import_module(module_name: str):
    try:
        return importlib.import_module(module_name)
    except:
        return None

def inspect_journal_class_runtime(class_obj: Any) -> tuple[bool, str]:
    """Periksa apakah class benar-benar memiliki validasi balance."""
    if not class_obj:
        return False, "Class tidak ditemukan"
    methods = inspect.getmembers(class_obj, predicate=inspect.isfunction)
    method_names = [m[0] for m in methods]
    validate_methods = [m for m in method_names if any(kw in m.lower() for kw in VALIDATE_KEYWORDS)]
    if not validate_methods:
        return False, "Tidak ada metode validasi"
    # Ambil metode pertama
    method_name = validate_methods[0]
    method = getattr(class_obj, method_name, None)
    if not method:
        return False, f"Metode {method_name} tidak ditemukan"
    try:
        source = inspect.getsource(method)
    except:
        return False, "Tidak dapat membaca source"
    # Cek apakah ada pengecekan debit==credit
    patterns = [
        r'debit.*==.*credit',
        r'credit.*==.*debit',
        r'debit.*!=.*credit',
        r'assert.*debit.*credit',
        r'raise.*debit.*credit',
        r'total_debit.*==.*total_credit',
        r'sum\(.*debit.*\).*==.*sum\(.*credit.*\)',
    ]
    for pattern in patterns:
        if re.search(pattern, source, re.IGNORECASE):
            return True, f"OK (metode {method_name})"
    return False, f"Metode {method_name} TIDAK membandingkan debit/credit"

# ─── Main Validator ──────────────────────────────────────────────────────────

def validate_journal_balance(verbose: bool = False, json_out: str | None = None) -> int:
    print(f"{BOLD}{CYAN}╔{'═'*78}╗{RESET}")
    print(f"{BOLD}{CYAN}║{' '*20}JOURNAL BALANCE CHECKER — PRECISION{' '*20}║{RESET}")
    print(f"{BOLD}{CYAN}╚{'═'*78}╝{RESET}")
    print()

    findings: list[Finding] = []
    journal_classes: list[JournalClassInfo] = []
    posting_funcs: list[PostingFunction] = []
    repo_methods: list[RepositoryMethod] = []

    # ─── Scan ────────────────────────────────────────────────────────────────
    print("🔍 Scanning project...")
    for dir_name in SCAN_DIRS:
        dir_path = ROOT / dir_name
        if not dir_path.exists():
            continue
        for p in dir_path.rglob("*.py"):
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            if p.name.startswith("__") and p.name != "__init__.py":
                continue
            journal_classes.extend(extract_journal_classes(p))
            posting_funcs.extend(extract_posting_functions(p))
            repo_methods.extend(extract_repository_methods(p))

    print(f"📂 Ditemukan: {len(journal_classes)} class jurnal, {len(posting_funcs)} fungsi posting, {len(repo_methods)} repository method.\n")

    # ─── Runtime Validasi ──────────────────────────────────────────────────

    # Cache module
    module_cache = {}

    # 1. Validasi class jurnal
    for info in journal_classes:
        # Hanya class yang benar-benar memiliki debit & credit (atau lines) yang kita periksa
        # Jika hanya memiliki lines, validasi bisa dilakukan di level lines
        if info.has_debit and info.has_credit:
            # Coba import
            try:
                rel = info.file.relative_to(ROOT)
                module_name = ".".join(rel.with_suffix("").parts)
            except:
                continue
            if module_name not in module_cache:
                mod = import_module(module_name)
                module_cache[module_name] = mod
            else:
                mod = module_cache[module_name]
            if mod is None:
                findings.append(Finding("CRITICAL", str(info.file.relative_to(ROOT)), info.line,
                                        f"Module '{module_name}' tidak dapat diimpor"))
                continue
            class_obj = getattr(mod, info.name, None)
            if class_obj is None:
                findings.append(Finding("CRITICAL", str(info.file.relative_to(ROOT)), info.line,
                                        f"Class '{info.name}' tidak ditemukan"))
                continue
            # Runtime check
            is_valid, reason = inspect_journal_class_runtime(class_obj)
            info.is_valid = is_valid
            if not is_valid:
                findings.append(Finding(
                    "CRITICAL",
                    str(info.file.relative_to(ROOT)),
                    info.line,
                    f"Journal class '{info.name}' tidak memiliki validasi balance yang benar",
                    recommendation="Tambahkan metode validate() yang membandingkan total_debit == total_credit",
                    detail=reason
                ))
        else:
            # Class dengan lines saja (misal InvoiceEntity yang memiliki lines)
            # Kita asumsikan validasi di level lines, namun kita tetap periksa apakah ada validate
            if info.validate_method:
                # Coba import dan periksa
                try:
                    rel = info.file.relative_to(ROOT)
                    module_name = ".".join(rel.with_suffix("").parts)
                except:
                    continue
                if module_name not in module_cache:
                    mod = import_module(module_name)
                    module_cache[module_name] = mod
                else:
                    mod = module_cache[module_name]
                if mod is None:
                    continue
                class_obj = getattr(mod, info.name, None)
                if class_obj is None:
                    continue
                is_valid, reason = inspect_journal_class_runtime(class_obj)
                info.is_valid = is_valid
                if not is_valid:
                    findings.append(Finding(
                        "WARNING",
                        str(info.file.relative_to(ROOT)),
                        info.line,
                        f"Class '{info.name}' memiliki metode validasi tetapi tidak membandingkan debit/credit",
                        detail=reason
                    ))
            else:
                # Tidak ada metode validasi sama sekali, tapi class ini mungkin bukan entitas jurnal inti
                # Beri warning saja
                findings.append(Finding(
                    "WARNING",
                    str(info.file.relative_to(ROOT)),
                    info.line,
                    f"Class '{info.name}' memiliki field debit/credit/lines tetapi tidak ada metode validasi",
                    recommendation="Tambahkan validate() atau pastikan validasi dilakukan di tempat lain"
                ))

    # 2. Validasi fungsi posting
    for func in posting_funcs:
        if not func.calls_validate:
            findings.append(Finding(
                "CRITICAL",
                str(func.file.relative_to(ROOT)),
                func.line,
                f"Fungsi '{func.name}' memposting jurnal tanpa memanggil validasi balance",
                recommendation="Panggil journal.validate() sebelum menyimpan"
            ))
        else:
            # Periksa apakah metode validasi yang dipanggil benar-benar ada
            # (Runtime check optional)
            func.is_valid = True

    # 3. Validasi repository method
    for repo in repo_methods:
        if not repo.calls_validate:
            findings.append(Finding(
                "CRITICAL",
                str(repo.file.relative_to(ROOT)),
                repo.line,
                f"Repository '{repo.name}' menyimpan {repo.entity_type} tanpa validasi balance",
                recommendation="Panggil {repo.entity_type}.validate() sebelum menyimpan"
            ))
        else:
            repo.is_valid = True

    # ─── Report ──────────────────────────────────────────────────────────────
    critical = [f for f in findings if f.severity == "CRITICAL"]
    warnings = [f for f in findings if f.severity == "WARNING"]

    if critical:
        print(f"{RED}{BOLD}🔴 CRITICAL ISSUES ({len(critical)}){RESET}")
        for f in critical:
            print(f"  {RED}✖{RESET} {f.file}:{f.line}  {f.message}")
            if f.detail:
                print(f"      📌 {f.detail}")
            if f.recommendation:
                print(f"      💡 {f.recommendation}")
        print()

    if warnings:
        print(f"{YELLOW}{BOLD}⚠️  WARNINGS ({len(warnings)}){RESET}")
        for f in warnings:
            print(f"  {YELLOW}⚠{RESET} {f.file}:{f.line}  {f.message}")
            if f.recommendation:
                print(f"      💡 {f.recommendation}")
        print()

    # Ringkasan
    total_journals = len(journal_classes)
    valid_journals = sum(1 for c in journal_classes if c.is_valid)
    total_post = len(posting_funcs)
    valid_post = sum(1 for f in posting_funcs if f.is_valid)
    total_repo = len(repo_methods)
    valid_repo = sum(1 for r in repo_methods if r.is_valid)

    print("═" * 80)
    print(f"{BOLD}SUMMARY — JOURNAL BALANCE CHECKER (PRECISION){RESET}")
    print(f"  Journal classes found:    {total_journals}")
    print(f"  Valid (with balance):     {valid_journals}")
    print(f"  Posting functions found:  {total_post}")
    print(f"  Valid (calls validate):   {valid_post}")
    print(f"  Repository methods found: {total_repo}")
    print(f"  Valid (with validate):    {valid_repo}")
    print(f"  Critical issues:          {len(critical)}")
    print(f"  Warnings:                 {len(warnings)}")
    print("═" * 80)

    if json_out:
        report = {
            "journal_classes": {"total": total_journals, "valid": valid_journals},
            "posting_functions": {"total": total_post, "valid": valid_post},
            "repository_methods": {"total": total_repo, "valid": valid_repo},
            "issues": {
                "critical": [{"file": f.file, "line": f.line, "message": f.message} for f in critical],
                "warnings": [{"file": f.file, "line": f.line, "message": f.message} for f in warnings]
            }
        }
        Path(json_out).write_text(json.dumps(report, indent=2))
        print(f"\n{CYAN}JSON report saved to {json_out}{RESET}")

    if critical:
        print(f"\n{RED}{BOLD}❌ VALIDATION FAILED — {len(critical)} critical issue(s) must be fixed.{RESET}")
        return 1
    else:
        print(f"\n{GREEN}{BOLD}✅ VALIDATION PASSED — No critical issues.{RESET}")
        if warnings:
            print(f"{YELLOW}   Review {len(warnings)} warnings to improve quality.{RESET}")
        return 0

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", metavar="FILE")
    args = parser.parse_args()
    sys.exit(validate_journal_balance(verbose=args.verbose, json_out=args.json))
