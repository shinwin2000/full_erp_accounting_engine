#!/usr/bin/env python3
"""
uow_checker.py - Unit of Work Pattern Validator (Final)
========================================================
Memeriksa kepatuhan terhadap Unit of Work (UoW) pattern.

Fitur:
- Mendeteksi async method (AsyncFunctionDef)
- Skip Factory/Builder/Provider classes
- Fleksibel terhadap context manager (__enter__/__exit__ atau __aenter__/__aexit__)
- Validasi isi __exit__: mendeteksi commit/rollback baik sync maupun async (await)
- Jika class memiliki method commit() dan rollback(), __exit__ tidak wajib memanggil commit (explicit commit pattern)
- Menggunakan NodeVisitor untuk analisis branch error tanpa error parent

Cara pakai:
  python checker/uow_checker.py
  python checker/uow_checker.py --verbose
  python checker/uow_checker.py --json report.json
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
from dataclasses import dataclass, field
from typing import List, Set, Optional, Tuple

# =============================================================================
# Root Project
# =============================================================================
ROOT = pathlib.Path(__file__).resolve().parent.parent

# =============================================================================
# Warna
# =============================================================================
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

# =============================================================================
# Data Classes
# =============================================================================
@dataclass
class Finding:
    file: str
    line: int
    severity: str       # ERROR / WARNING / INFO
    category: str       # port / implementation / usage / bypass
    message: str
    detail: str = ""

@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    score: int = 100

# =============================================================================
# HELPERS
# =============================================================================

def is_exception_class(cls_node: ast.ClassDef) -> bool:
    name = cls_node.name
    if "Error" in name or "Exception" in name:
        return True
    for base in cls_node.bases:
        if isinstance(base, ast.Name) and ("Error" in base.id or "Exception" in base.id):
            return True
    return False

def is_factory_class(cls_node: ast.ClassDef) -> bool:
    name = cls_node.name
    if name.endswith(("Factory", "Builder", "Provider", "Registry")):
        return True
    if "Factory" in name or "Builder" in name or "Provider" in name:
        return True
    return False

def get_methods(cls_node: ast.ClassDef) -> Set[str]:
    methods = set()
    for item in cls_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.add(item.name)
    return methods

def has_method(cls_node: ast.ClassDef, method_name: str) -> bool:
    for item in cls_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name == method_name:
                return True
    return False

def has_context_manager(methods: Set[str]) -> bool:
    return ("__enter__" in methods and "__exit__" in methods) or \
           ("__aenter__" in methods and "__aexit__" in methods)

def find_exit_method(cls_node: ast.ClassDef) -> Optional[ast.FunctionDef | ast.AsyncFunctionDef]:
    for item in cls_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name in ("__exit__", "__aexit__"):
                return item
    return None

def analyze_exit_method(exit_node: ast.FunctionDef | ast.AsyncFunctionDef) -> Tuple[bool, bool, bool]:
    """
    Menganalisis method __exit__ atau __aexit__.
    Returns: (has_commit, has_rollback, has_rollback_on_error)
    Mendeteksi baik pemanggilan sync maupun async (await).
    Menggunakan NodeVisitor untuk melacak branch error.
    """
    has_commit = False
    has_rollback = False
    has_rollback_on_error = False

    class ErrorBranchVisitor(ast.NodeVisitor):
        def __init__(self):
            self.in_error_branch = False

        def visit_If(self, node):
            # Cek apakah ini if yang mengecek exception
            is_exception_check = False
            test = node.test
            if isinstance(test, ast.Name) and test.id in ("exc_type", "exc_val", "exc_tb"):
                is_exception_check = True
            elif isinstance(test, ast.Call) and isinstance(test.func, ast.Name) and test.func.id == "isinstance":
                is_exception_check = True
            elif isinstance(test, ast.Compare):
                is_exception_check = True

            if is_exception_check:
                # Masuk ke branch if (error branch)
                old_in_error = self.in_error_branch
                self.in_error_branch = True
                self.generic_visit(node)
                self.in_error_branch = old_in_error
                # Kunjungi else jika ada
                if node.orelse:
                    for stmt in node.orelse:
                        self.visit(stmt)
                return
            # Jika bukan exception check, kunjungi normal
            self.generic_visit(node)

        def visit_Call(self, node):
            func = node.func
            if isinstance(func, ast.Attribute):
                attr = func.attr.lower()
                if attr == "commit":
                    nonlocal has_commit
                    has_commit = True
                elif attr == "rollback":
                    nonlocal has_rollback
                    has_rollback = True
                    if self.in_error_branch:
                        nonlocal has_rollback_on_error
                        has_rollback_on_error = True
                # Cek juga melalui self._transaction_manager.commit()
                if isinstance(func.value, ast.Attribute) and isinstance(func.value.value, ast.Name) and func.value.value.id == "self":
                    if func.value.attr in ("_transaction_manager", "_session", "_uow"):
                        if attr == "commit":
                            has_commit = True
                        elif attr == "rollback":
                            has_rollback = True
                            if self.in_error_branch:
                                has_rollback_on_error = True
                # self.commit() atau self.rollback()
                if isinstance(func.value, ast.Name) and func.value.id == "self":
                    if attr == "commit":
                        has_commit = True
                    elif attr == "rollback":
                        has_rollback = True
                        if self.in_error_branch:
                            has_rollback_on_error = True
            self.generic_visit(node)

        def visit_Await(self, node):
            # Proses value dari await
            self.visit(node.value)

    visitor = ErrorBranchVisitor()
    visitor.visit(exit_node)
    return has_commit, has_rollback, has_rollback_on_error

def is_factory_function(func_name: str) -> bool:
    return func_name.startswith(('create_', 'build_', 'make_', 'new_', 'get_', 'setup_'))

def is_wrapper_function(func_node: ast.FunctionDef) -> bool:
    if len(func_node.body) > 3:
        return False
    for stmt in ast.walk(func_node):
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            if isinstance(stmt.value.func, ast.Attribute):
                if 'service' in ast.unparse(stmt.value.func.value).lower():
                    return True
    return False

def has_direct_repo_call(func_node: ast.FunctionDef) -> bool:
    for stmt in ast.walk(func_node):
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            if isinstance(stmt.value.func, ast.Attribute):
                attr = stmt.value.func.attr.lower()
                if attr in ('save', 'add', 'update', 'delete', 'persist', 'remove', 'commit', 'flush'):
                    if isinstance(stmt.value.func.value, ast.Name):
                        obj_name = stmt.value.func.value.id.lower()
                        if 'repo' in obj_name or 'repository' in obj_name:
                            return True
    return False

def has_uow_parameter(func_node: ast.FunctionDef) -> bool:
    for arg in func_node.args.args:
        if arg.arg in ('uow', 'unit_of_work'):
            return True
    return False

def has_uow_self_assign(func_node: ast.FunctionDef) -> bool:
    if func_node.name != '__init__':
        return False
    for stmt in ast.walk(func_node):
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Attribute):
                    if isinstance(target.value, ast.Name) and target.value.id == 'self' and target.attr == '_uow':
                        return True
    return False

def has_uow_commit_call(func_node: ast.FunctionDef) -> bool:
    for stmt in ast.walk(func_node):
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            call = stmt.value
            if isinstance(call.func, ast.Attribute):
                if call.func.attr in ('commit', 'rollback'):
                    if isinstance(call.func.value, ast.Name) and call.func.value.id in ('uow', 'unit_of_work'):
                        return True
                    if isinstance(call.func.value, ast.Attribute):
                        if isinstance(call.func.value.value, ast.Name) and call.func.value.value.id == 'self' and call.func.value.attr == '_uow':
                            return True
    return False

def has_uow_with_context(func_node: ast.FunctionDef) -> bool:
    for stmt in ast.walk(func_node):
        if isinstance(stmt, ast.With):
            for item in stmt.items:
                context_expr = ast.unparse(item.context_expr)
                if 'uow' in context_expr.lower() or 'unit_of_work' in context_expr.lower():
                    return True
    return False

def has_transactional_decorator(func_node: ast.FunctionDef) -> bool:
    for dec in func_node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == 'transactional':
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == 'transactional':
            return True
        if isinstance(dec, ast.Call):
            if isinstance(dec.func, ast.Name) and dec.func.id == 'transactional':
                return True
            if isinstance(dec.func, ast.Attribute) and dec.func.attr == 'transactional':
                return True
    return False

# =============================================================================
# 1. Port Checker
# =============================================================================
def check_uow_port() -> List[Finding]:
    findings = []
    port_file = ROOT / "ports" / "primary" / "unit_of_work_port.py"
    if not port_file.exists():
        findings.append(Finding(
            file=str(port_file),
            line=0,
            severity="ERROR",
            category="port",
            message="File unit_of_work_port.py tidak ditemukan di ports/primary/",
            detail="Buat file ports/primary/unit_of_work_port.py dengan interface UoW."
        ))
        return findings

    try:
        src = port_file.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(port_file))
    except SyntaxError as e:
        findings.append(Finding(
            file=str(port_file),
            line=e.lineno or 0,
            severity="ERROR",
            category="port",
            message=f"Syntax error di port file: {e.msg}",
            detail="Perbaiki syntax error."
        ))
        return findings

    uow_classes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if 'unit' in node.name.lower() and 'work' in node.name.lower():
                uow_classes.append(node)

    if not uow_classes:
        findings.append(Finding(
            file=str(port_file),
            line=0,
            severity="ERROR",
            category="port",
            message="Tidak ditemukan class UnitOfWork di port file",
            detail="Tambahkan class UnitOfWork (atau UnitOfWorkPort) dengan method commit, rollback, begin/context manager."
        ))
        return findings

    for cls in uow_classes:
        methods = get_methods(cls)
        has_cm = has_context_manager(methods)

        if has_cm:
            findings.append(Finding(
                file=str(port_file),
                line=cls.lineno,
                severity="INFO",
                category="port",
                message=f"✅ Port UoW '{cls.name}' memiliki context manager (__enter__/__exit__ atau __aenter__/__aexit__)",
                detail=""
            ))
        else:
            required = {'begin', 'commit', 'rollback'}
            missing = required - methods
            if missing:
                findings.append(Finding(
                    file=str(port_file),
                    line=cls.lineno,
                    severity="ERROR",
                    category="port",
                    message=f"Class '{cls.name}' kekurangan method: {', '.join(missing)}",
                    detail=f"Implementasikan method {', '.join(missing)} atau gunakan context manager."
                ))
            else:
                findings.append(Finding(
                    file=str(port_file),
                    line=cls.lineno,
                    severity="INFO",
                    category="port",
                    message=f"✅ Port UoW '{cls.name}' lengkap (begin, commit, rollback)",
                    detail=""
                ))

    return findings

# =============================================================================
# 2. Implementation Checker
# =============================================================================
def check_uow_implementation() -> List[Finding]:
    findings = []
    impl_dir = ROOT / "adapters" / "secondary_impl"
    if not impl_dir.exists():
        findings.append(Finding(
            file=str(impl_dir),
            line=0,
            severity="ERROR",
            category="implementation",
            message="Direktori adapters/secondary_impl/ tidak ditemukan",
            detail="Buat direktori adapters/secondary_impl/ untuk implementasi UoW."
        ))
        return findings

    impl_files = list(impl_dir.glob("*unit_of_work*.py")) + list(impl_dir.glob("*uow*.py"))
    if not impl_files:
        findings.append(Finding(
            file=str(impl_dir),
            line=0,
            severity="ERROR",
            category="implementation",
            message="Tidak ditemukan implementasi UoW di adapters/secondary_impl/",
            detail="Buat file misalnya sqlalchemy_unit_of_work_impl.py"
        ))
        return findings

    for impl_file in impl_files:
        try:
            src = impl_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(impl_file))
        except SyntaxError as e:
            findings.append(Finding(
                file=str(impl_file),
                line=e.lineno or 0,
                severity="ERROR",
                category="implementation",
                message=f"Syntax error di {impl_file.name}: {e.msg}",
                detail="Perbaiki syntax error."
            ))
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if is_exception_class(node):
                continue
            if is_factory_class(node):
                continue
            if 'unit' not in node.name.lower() or 'work' not in node.name.lower():
                continue

            methods = get_methods(node)
            has_cm = has_context_manager(methods)

            if has_cm:
                exit_method = find_exit_method(node)
                if exit_method is not None:
                    has_commit, has_rollback, has_rollback_on_error = analyze_exit_method(exit_method)
                    has_commit_method_defined = has_method(node, "commit")
                    has_rollback_method_defined = has_method(node, "rollback")

                    if has_commit or has_rollback:
                        findings.append(Finding(
                            file=str(impl_file),
                            line=node.lineno,
                            severity="INFO",
                            category="implementation",
                            message=f"✅ Implementasi UoW '{node.name}' menggunakan context manager dan __exit__ memanggil commit/rollback",
                            detail=""
                        ))
                    elif has_commit_method_defined and has_rollback_method_defined:
                        if has_rollback_on_error:
                            findings.append(Finding(
                                file=str(impl_file),
                                line=node.lineno,
                                severity="INFO",
                                category="implementation",
                                message=f"✅ Implementasi UoW '{node.name}' menggunakan explicit commit pattern (__exit__ hanya rollback error)",
                                detail="commit dipanggil secara eksplisit oleh pengguna."
                            ))
                        else:
                            findings.append(Finding(
                                file=str(impl_file),
                                line=exit_method.lineno,
                                severity="WARNING",
                                category="implementation",
                                message=f"Implementasi '{node.name}' memiliki __exit__ tetapi tidak memanggil commit/rollback di branch error",
                                detail="Pastikan error branch memanggil rollback, atau abaikan warning ini jika desain sudah benar."
                            ))
                    else:
                        findings.append(Finding(
                            file=str(impl_file),
                            line=exit_method.lineno,
                            severity="WARNING",
                            category="implementation",
                            message=f"Implementasi '{node.name}' memiliki __exit__ tetapi tidak memanggil commit atau rollback",
                            detail="Pastikan __exit__ memanggil session.commit() atau session.rollback() (termasuk melalui _transaction_manager), atau gunakan explicit commit pattern dengan method commit() dan rollback()."
                        ))
                else:
                    findings.append(Finding(
                        file=str(impl_file),
                        line=node.lineno,
                        severity="ERROR",
                        category="implementation",
                        message=f"Implementasi '{node.name}' memiliki context manager tetapi tidak ditemukan __exit__",
                        detail="Implementasikan __exit__ atau __aexit__"
                    ))
            else:
                required = {'begin', 'commit', 'rollback'}
                missing = required - methods
                if missing:
                    findings.append(Finding(
                        file=str(impl_file),
                        line=node.lineno,
                        severity="ERROR",
                        category="implementation",
                        message=f"Implementasi '{node.name}' kekurangan method: {', '.join(missing)}",
                        detail=f"Implementasikan method {', '.join(missing)} atau gunakan context manager."
                    ))
                else:
                    findings.append(Finding(
                        file=str(impl_file),
                        line=node.lineno,
                        severity="INFO",
                        category="implementation",
                        message=f"✅ Implementasi UoW '{node.name}' lengkap",
                        detail=""
                    ))

    return findings

# =============================================================================
# 3. Usage Checker
# =============================================================================
def check_uow_usage() -> List[Finding]:
    findings = []
    target_dirs = [
        ROOT / "application" / "use_cases",
        ROOT / "application" / "service_layer",
    ]

    for dir_path in target_dirs:
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if py_file.name.startswith("__") or py_file.name.startswith("uow_checker"):
                continue
            if py_file.name in ("registry.py", "handlers.py"):
                continue
            try:
                src = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=str(py_file))
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue

                func_name = node.name
                if is_factory_function(func_name):
                    continue

                if not has_direct_repo_call(node):
                    continue

                uses_uow = (
                    has_transactional_decorator(node) or
                    has_uow_with_context(node) or
                    has_uow_commit_call(node) or
                    has_uow_parameter(node) or
                    is_wrapper_function(node)
                )

                if not uses_uow:
                    findings.append(Finding(
                        file=str(py_file),
                        line=node.lineno,
                        severity="ERROR",
                        category="usage",
                        message=f"Fungsi '{func_name}' memanggil repository method tanpa UoW",
                        detail="Tambahkan dekorator @transactional atau gunakan 'with uow:'"
                    ))

    return findings

# =============================================================================
# 4. Bypass Checker
# =============================================================================
def check_bypass_uow() -> List[Finding]:
    findings = []
    target_dirs = [
        ROOT / "application" / "use_cases",
        ROOT / "application" / "service_layer",
    ]
    exclude = {'.venv', 'venv', '__pycache__', '.git', 'node_modules', 'dist', 'build', 'migrations', 'deployment', 'docs', 'tests', 'checker'}

    for dir_path in target_dirs:
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            if any(part in exclude for part in py_file.parts):
                continue
            if py_file.name.startswith("__") or py_file.name.startswith("uow_checker"):
                continue
            if py_file.name in ("registry.py", "handlers.py"):
                continue
            try:
                src = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=str(py_file))
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                    call = node.value
                    if isinstance(call.func, ast.Attribute):
                        attr = call.func.attr.lower()
                        if attr in ('save', 'add', 'update', 'delete', 'persist', 'remove'):
                            if isinstance(call.func.value, ast.Name):
                                obj_name = call.func.value.id.lower()
                                if 'repo' in obj_name or 'repository' in obj_name:
                                    parent_func = None
                                    for parent in ast.walk(tree):
                                        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                            if node in ast.walk(parent):
                                                parent_func = parent
                                                break
                                    if parent_func and not is_factory_function(parent_func.name):
                                        uses_uow = (
                                            has_transactional_decorator(parent_func) or
                                            has_uow_with_context(parent_func) or
                                            has_uow_commit_call(parent_func) or
                                            has_uow_parameter(parent_func) or
                                            is_wrapper_function(parent_func)
                                        )
                                        if not uses_uow:
                                            findings.append(Finding(
                                                file=str(py_file),
                                                line=node.lineno,
                                                severity="WARNING",
                                                category="bypass",
                                                message=f"Pemanggilan {call.func.attr}() tanpa UoW di {parent_func.name}",
                                                detail="Gunakan UoW untuk operasi write ke repository."
                                            ))

    return findings

# =============================================================================
# Main
# =============================================================================
def scan_uow() -> Report:
    report = Report()
    report.findings.extend(check_uow_port())
    report.findings.extend(check_uow_implementation())
    report.findings.extend(check_uow_usage())
    report.findings.extend(check_bypass_uow())

    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    warnings = sum(1 for f in report.findings if f.severity == "WARNING")
    report.score = max(0, 100 - errors * 10 - warnings * 2)
    return report

# =============================================================================
# Output
# =============================================================================
def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}UNIT OF WORK (UoW) CHECKER REPORT (FINAL){c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")

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
        cat_labels = {
            'port': 'UoW Port Definition',
            'implementation': 'UoW Implementation',
            'usage': 'UoW Usage in Use Cases',
            'bypass': 'Bypass Detection',
        }
        for cat, items in categories.items():
            label = cat_labels.get(cat, cat)
            err_cnt = sum(1 for i in items if i.severity == "ERROR")
            warn_cnt = sum(1 for i in items if i.severity == "WARNING")
            color = c["RED"] if err_cnt > 0 else c["YELLOW"] if warn_cnt > 0 else c["GREEN"]
            print(f"  {label}: {color}{err_cnt} errors, {warn_cnt} warnings{c['RESET']}")

        print(f"\n{c['RED'] if errors else c['YELLOW']}Details:{c['RESET']}")
        for f in report.findings[:30]:
            color = c["RED"] if f.severity == "ERROR" else c["YELLOW"]
            print(f"  {color}[{f.severity}]{c['RESET']} [{f.category}] {f.file}:{f.line}")
            print(f"     {f.message}")
            if verbose and f.detail:
                print(f"     {c['CYAN']}→ {f.detail}{c['RESET']}")
        if len(report.findings) > 30:
            print(f"  ... and {len(report.findings)-30} more findings")

def save_json(report: Report, filepath: str):
    c = COLOR
    data = {
        "findings": [
            {"file": f.file, "line": f.line, "severity": f.severity,
             "category": f.category, "message": f.message, "detail": f.detail}
            for f in report.findings
        ],
        "score": report.score,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{c['CYAN']}JSON saved to {filepath}{c['RESET']}")

# =============================================================================
# CLI
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="Unit of Work (UoW) Pattern Checker")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    args = parser.parse_args()

    report = scan_uow()
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)

    errors = sum(1 for f in report.findings if f.severity == "ERROR")
    sys.exit(0 if errors == 0 else 1)

if __name__ == "__main__":
    main()