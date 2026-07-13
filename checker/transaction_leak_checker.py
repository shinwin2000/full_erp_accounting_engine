#!/usr/bin/env python3
"""
transaction_leak_checker.py - Deteksi missing rollback/commit dalam konteks transaksi
=======================================================================================
Standar: Big 4 Audit · ISO/IEC 25010 · SOX/ISA 315
Versi 10.0 - Akurasi tinggi, deteksi konteks & dekorator, RCA terintegrasi, score 100 jika clean.
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import json
import logging
import pathlib
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass

# ---- Tambahkan root proyek ke sys.path agar rca.py dapat diimpor ----
ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

# ---- RCA (Root Cause Analysis) ----
RCA_AVAIL = False
try:
    from rca import RCAEngine, analyze_exception, get_engine
    RCA_AVAIL = True
    logger = logging.getLogger("tx_leak")
    logger.info("RCA engine loaded from root rca.py")
except ImportError:
    try:
        from checker.core.rca import RCAEngine, analyze_exception, get_engine
        RCA_AVAIL = True
        logger = logging.getLogger("tx_leak")
        logger.info("RCA engine loaded from checker.core.rca")
    except ImportError:
        RCA_AVAIL = False
        def get_engine():
            return None
        def analyze_exception(e, ctx):
            return None
        logger = logging.getLogger("tx_leak")
        logger.warning("RCA engine not available, using fallback")

# ---- Logging & Color ----
logger = logging.getLogger("tx_leak")
logger.setLevel(logging.INFO)
if not logger.handlers:
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(h)

COLOR = {
    "RED": "\033[91m",
    "GREEN": "\033[92m",
    "YELLOW": "\033[93m",
    "CYAN": "\033[96m",
    "BOLD": "\033[1m",
    "RESET": "\033[0m"
}

def c(key: str) -> str:
    return COLOR.get(key, "")

# ---- Caches ----
_AST_CACHE: dict[str, ast.AST | None] = {}
_CACHE_LOCK = threading.Lock()

def get_ast(file_path: pathlib.Path) -> ast.AST | None:
    key = str(file_path.resolve())
    with _CACHE_LOCK:
        if key in _AST_CACHE:
            return _AST_CACHE[key]
    try:
        src = file_path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(file_path))
        with _CACHE_LOCK:
            _AST_CACHE[key] = tree
        return tree
    except Exception:
        with _CACHE_LOCK:
            _AST_CACHE[key] = None
        return None

# ---- Data ----
@dataclass
class TransactionIssue:
    file: str
    line: int
    kind: str          # MISSING_ROLLBACK, MISSING_COMMIT, NESTED_UNSAFE
    detail: str
    confidence: float
    rca: dict | None = None

@dataclass
class Report:
    issues: list[TransactionIssue]
    total_try_blocks: int
    total_files: int
    score: float
    scan_time: float

# ---- Helper untuk membangun parent map ----
class ParentMapBuilder(ast.NodeVisitor):
    """
    Membangun mapping parent untuk setiap node AST.
    """
    def __init__(self):
        self.parents: dict[ast.AST, ast.AST] = {}
        self.stack: list[ast.AST] = []

    def visit(self, node: ast.AST) -> None:
        if self.stack:
            self.parents[node] = self.stack[-1]
        self.stack.append(node)
        super().visit(node)
        self.stack.pop()

# ---- Scanner ----
class TransactionLeakChecker:
    # Metode tulis yang umum pada session/repository
    WRITE_METHODS = {
        "add", "delete", "update", "save", "persist", "merge", "flush",
        "execute", "executemany", "bulk_save", "bulk_insert", "bulk_update",
        "insert", "refresh", "expunge"
    }
    # Metode yang menandakan commit/rollback
    COMMIT_KEYWORDS = {"commit"}
    ROLLBACK_KEYWORDS = {"rollback"}
    # Context manager yang secara otomatis mengelola transaksi
    AUTO_TX_CONTEXTS = {"begin", "transaction", "atomic", "start_transaction", "begin_nested"}

    def __init__(self, root: pathlib.Path, exclude: list[str] = None, max_workers: int = 4):
        self.root = root
        self.exclude = set(exclude or [".venv", "venv", "__pycache__", "tests", "checker", "docs", "migrations"])
        self.max_workers = max_workers
        self._lock = threading.Lock()
        self._issues: list[TransactionIssue] = []
        self._total_try = 0
        self._files = 0
        self._rca_engine = get_engine() if RCA_AVAIL else None

    def scan(self) -> Report:
        t0 = time.perf_counter()
        files = list(self._walk())
        self._files = len(files)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self._analyze_file, f): f for f in files}
            for future in concurrent.futures.as_completed(futures):
                try:
                    issues, try_count = future.result()
                    with self._lock:
                        self._issues.extend(issues)
                        self._total_try += try_count
                except Exception as e:
                    logger.warning(f"Error analyzing file: {e}")

        # Score: 100 - 5 per issue, minimal 0 (tanpa penalti try blocks)
        score = max(0, 100 - len(self._issues) * 5)
        return Report(
            issues=self._issues,
            total_try_blocks=self._total_try,
            total_files=self._files,
            score=round(score, 2),
            scan_time=time.perf_counter() - t0
        )

    def _walk(self) -> Iterator[pathlib.Path]:
        for p in self.root.rglob("*.py"):
            if any(part in self.exclude for part in p.parts):
                continue
            if p.name.startswith("__"):
                continue
            if "checker" in str(p):
                continue
            yield p

    def _analyze_file(self, py_file: pathlib.Path) -> tuple[list[TransactionIssue], int]:
        tree = get_ast(py_file)
        if tree is None:
            return [], 0

        rel = str(py_file.relative_to(self.root))

        # Bangun parent map
        builder = ParentMapBuilder()
        builder.visit(tree)
        parent_map = builder.parents

        # Kumpulkan informasi:
        # - Dekorator fungsi
        # - Dekorator class
        # - Variabel session/uow
        func_decorators = self._collect_function_decorators(tree)
        class_decorators = self._collect_class_decorators(tree)
        session_vars = self._find_session_variables(tree)
        uow_vars = self._find_uow_variables(tree)

        issues = []
        try_count = 0

        # Kunjungi semua Try node dan analisis
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                try_count += 1
                enclosing_func = self._find_enclosing_function(node, parent_map)
                enclosing_class = self._find_enclosing_class(node, parent_map)

                # Periksa decorator fungsi
                if enclosing_func:
                    deco_names = func_decorators.get(enclosing_func, [])
                    if self._has_transactional_decorator(deco_names):
                        continue

                # Periksa decorator class (jika ada)
                if enclosing_class:
                    class_deco_names = class_decorators.get(enclosing_class, [])
                    if self._has_transactional_decorator(class_deco_names):
                        continue

                # Periksa apakah method berada di Repository class
                if enclosing_class and hasattr(enclosing_class, 'name'):
                    if self._is_repository_class(enclosing_class.name):
                        if enclosing_func and self._method_uses_session(enclosing_func):
                            continue

                # Cek apakah try berada di dalam context manager yang aman
                if self._is_inside_safe_context(node, parent_map):
                    continue

                # Cek juga apakah try berisi with session.begin() secara langsung
                if self._has_auto_transaction_context(node.body):
                    continue

                # Analisis lebih lanjut
                issues.extend(self._analyze_try(node, rel, parent_map, session_vars, uow_vars))

        return issues, try_count

    def _collect_function_decorators(self, tree: ast.AST) -> dict[ast.FunctionDef, list[str]]:
        decorators = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names = []
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Name):
                        names.append(dec.id)
                    elif isinstance(dec, ast.Attribute):
                        names.append(dec.attr)
                    elif isinstance(dec, ast.Call):
                        if isinstance(dec.func, ast.Name):
                            names.append(dec.func.id)
                        elif isinstance(dec.func, ast.Attribute):
                            names.append(dec.func.attr)
                if names:
                    decorators[node] = names
        return decorators

    def _collect_class_decorators(self, tree: ast.AST) -> dict[ast.ClassDef, list[str]]:
        decorators = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                names = []
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Name):
                        names.append(dec.id)
                    elif isinstance(dec, ast.Attribute):
                        names.append(dec.attr)
                    elif isinstance(dec, ast.Call):
                        if isinstance(dec.func, ast.Name):
                            names.append(dec.func.id)
                        elif isinstance(dec.func, ast.Attribute):
                            names.append(dec.func.attr)
                if names:
                    decorators[node] = names
        return decorators

    def _find_enclosing_function(self, node: ast.AST, parent_map: dict[ast.AST, ast.AST]) -> ast.FunctionDef | None:
        current = node
        while current in parent_map:
            parent = parent_map[current]
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return parent
            current = parent
        return None

    def _find_enclosing_class(self, node: ast.AST, parent_map: dict[ast.AST, ast.AST]) -> ast.ClassDef | None:
        current = node
        while current in parent_map:
            parent = parent_map[current]
            if isinstance(parent, ast.ClassDef):
                return parent
            current = parent
        return None

    def _has_transactional_decorator(self, decorator_names: list[str]) -> bool:
        tx_decorators = {
            "transactional", "atomic", "with_transaction", "tx",
            "db.transaction", "transaction", "begin"
        }
        return any(d in tx_decorators for d in decorator_names)

    def _is_repository_class(self, class_name: str) -> bool:
        repo_keywords = {"Repository", "Repo", "Dao", "DAL"}
        return any(kw in class_name for kw in repo_keywords)

    def _method_uses_session(self, func_node: ast.FunctionDef | None) -> bool:
        if not func_node:
            return False
        for node in ast.walk(func_node):
            if isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name) and node.value.id == "self":
                    if node.attr in {"session", "_session"}:
                        return True
        return False

    def _find_session_variables(self, tree: ast.AST) -> set[str]:
        session_vars = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        val = node.value
                        if isinstance(val, ast.Call):
                            if (isinstance(val.func, ast.Name) and "session" in val.func.id.lower()) or (isinstance(val.func, ast.Attribute) and "session" in val.func.attr.lower()):
                                session_vars.add(target.id)
                        elif isinstance(val, ast.Name) and "session" in val.id.lower():
                            session_vars.add(target.id)
        return session_vars

    def _find_uow_variables(self, tree: ast.AST) -> set[str]:
        uow_vars = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        val = node.value
                        if isinstance(val, ast.Call):
                            if (isinstance(val.func, ast.Name) and ("uow" in val.func.id.lower() or "unitofwork" in val.func.id.lower())) or (isinstance(val.func, ast.Attribute) and ("uow" in val.func.attr.lower() or "unitofwork" in val.func.attr.lower())):
                                uow_vars.add(target.id)
                        elif isinstance(val, ast.Name) and ("uow" in val.id.lower() or "unitofwork" in val.id.lower()):
                            uow_vars.add(target.id)
        return uow_vars

    def _is_inside_safe_context(self, node: ast.Try, parent_map: dict[ast.AST, ast.AST]) -> bool:
        current = node
        while current in parent_map:
            parent = parent_map[current]
            if isinstance(parent, ast.With):
                for item in parent.items:
                    ctx = item.context_expr
                    if isinstance(ctx, ast.Call):
                        if isinstance(ctx.func, ast.Attribute):
                            if ctx.func.attr in self.AUTO_TX_CONTEXTS:
                                return True
                        elif isinstance(ctx.func, ast.Name):
                            if ctx.func.id in self.AUTO_TX_CONTEXTS:
                                return True
            current = parent
        return False

    def _has_auto_transaction_context(self, body: list[ast.stmt]) -> bool:
        for stmt in body:
            if isinstance(stmt, ast.With):
                for item in stmt.items:
                    ctx = item.context_expr
                    if isinstance(ctx, ast.Call):
                        if isinstance(ctx.func, ast.Attribute):
                            if ctx.func.attr in self.AUTO_TX_CONTEXTS:
                                return True
                        elif isinstance(ctx.func, ast.Name):
                            if ctx.func.id in self.AUTO_TX_CONTEXTS:
                                return True
        return False

    def _analyze_try(self, node: ast.Try, rel: str, parent_map: dict[ast.AST, ast.AST],
                     session_vars: set[str], uow_vars: set[str]) -> list[TransactionIssue]:
        issues = []

        # Deteksi operasi tulis yang dilakukan pada session atau uow
        has_write = self._has_write_operation(node.body, session_vars, uow_vars)
        if not has_write:
            return issues

        # Jika di dalam body terdapat context manager session.begin() -> aman
        if self._has_auto_transaction_context(node.body):
            return issues

        # Periksa apakah ada commit/rollback
        has_commit = False
        has_rollback = False
        has_rollback_in_except = False
        has_close_in_finally = False

        for stmt in node.body:
            if self._has_commit_or_rollback(stmt):
                has_commit = True
            if self._has_rollback(stmt):
                has_rollback = True

        for handler in node.handlers:
            for stmt in handler.body:
                if self._has_commit_or_rollback(stmt):
                    has_commit = True
                if self._has_rollback(stmt):
                    has_rollback = True
                    has_rollback_in_except = True

        for stmt in node.finalbody:
            if self._has_commit_or_rollback(stmt):
                has_commit = True
            if self._has_rollback(stmt):
                has_rollback = True
            if self._has_close(stmt):
                has_close_in_finally = True

        # Kasus 1: Tidak ada commit dan tidak ada rollback
        if not has_commit and not has_rollback:
            rca_dict = self._build_rca(
                "MISSING_ROLLBACK", rel, node.lineno,
                "Tidak ada commit maupun rollback di blok try. "
                "Tambahkan commit setelah operasi sukses, dan rollback di except."
            )
            issues.append(TransactionIssue(
                file=rel,
                line=node.lineno,
                kind="MISSING_ROLLBACK",
                detail="try block with write operations but no commit/rollback",
                confidence=0.95,
                rca=rca_dict
            ))
        # Kasus 2: Ada commit tapi tidak ada rollback di except
        elif has_commit and not has_rollback:
            if not has_rollback_in_except and not has_close_in_finally:
                rca_dict = self._build_rca(
                    "MISSING_ROLLBACK", rel, node.lineno,
                    "Ada commit tetapi tidak ada rollback di except. "
                    "Jika terjadi exception, transaksi akan menggantung. "
                    "Tambahkan rollback di except."
                )
                issues.append(TransactionIssue(
                    file=rel,
                    line=node.lineno,
                    kind="MISSING_ROLLBACK",
                    detail="commit found but no rollback in except block",
                    confidence=0.85,
                    rca=rca_dict
                ))

        # Kasus 3: Nested transaction dengan commit tanpa rollback
        if has_commit and not has_rollback and self._has_nested_tx(node):
            rca_dict = self._build_rca(
                "NESTED_UNSAFE", rel, node.lineno,
                "Nested transaction dengan commit di inner try, "
                "tanpa rollback jika terjadi error. "
                "Gunakan context manager atau pastikan rollback di semua jalur."
            )
            issues.append(TransactionIssue(
                file=rel,
                line=node.lineno,
                kind="NESTED_UNSAFE",
                detail="Nested transaction with commit but no rollback",
                confidence=0.7,
                rca=rca_dict
            ))

        return issues

    def _has_write_operation(self, body: list[ast.stmt], session_vars: set[str], uow_vars: set[str]) -> bool:
        for stmt in body:
            for n in ast.walk(stmt):
                if isinstance(n, ast.Call):
                    func = n.func
                    if isinstance(func, ast.Attribute):
                        method = func.attr
                        if method in self.WRITE_METHODS:
                            owner = func.value
                            if self._is_session_or_uow(owner, session_vars, uow_vars):
                                return True
                    elif isinstance(func, ast.Name):
                        # Abaikan fungsi global
                        pass
                elif isinstance(n, ast.Await) and isinstance(n.value, ast.Call):
                    func = n.value.func
                    if isinstance(func, ast.Attribute):
                        method = func.attr
                        if method in self.WRITE_METHODS:
                            owner = func.value
                            if self._is_session_or_uow(owner, session_vars, uow_vars):
                                return True
        return False

    def _is_session_or_uow(self, node: ast.AST, session_vars: set[str], uow_vars: set[str]) -> bool:
        if isinstance(node, ast.Name) and (node.id in session_vars or node.id in uow_vars):
            return True
        if isinstance(node, ast.Attribute):
            if node.attr in session_vars or node.attr in uow_vars:
                return True
            if node.attr in {"session", "uow", "db"}:
                return True
            return self._is_session_or_uow(node.value, session_vars, uow_vars)
        return False

    def _has_commit_or_rollback(self, stmt: ast.AST) -> bool:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Call):
                func = n.func
                if isinstance(func, ast.Attribute):
                    method = func.attr.lower()
                    if 'commit' in method or 'rollback' in method:
                        return True
                elif isinstance(func, ast.Name):
                    method = func.id.lower()
                    if 'commit' in method or 'rollback' in method:
                        return True
            elif isinstance(n, ast.Await):
                if isinstance(n.value, ast.Call):
                    func = n.value.func
                    if isinstance(func, ast.Attribute):
                        method = func.attr.lower()
                        if 'commit' in method or 'rollback' in method:
                            return True
                    elif isinstance(func, ast.Name):
                        method = func.id.lower()
                        if 'commit' in method or 'rollback' in method:
                            return True
        return False

    def _has_rollback(self, stmt: ast.AST) -> bool:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Call):
                func = n.func
                if isinstance(func, ast.Attribute):
                    if 'rollback' in func.attr.lower():
                        return True
                elif isinstance(func, ast.Name):
                    if 'rollback' in func.id.lower():
                        return True
            elif isinstance(n, ast.Await):
                if isinstance(n.value, ast.Call):
                    func = n.value.func
                    if isinstance(func, ast.Attribute):
                        if 'rollback' in func.attr.lower():
                            return True
                    elif isinstance(func, ast.Name):
                        if 'rollback' in func.id.lower():
                            return True
        return False

    def _has_close(self, stmt: ast.AST) -> bool:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Call):
                func = n.func
                if isinstance(func, ast.Attribute):
                    if 'close' in func.attr.lower():
                        return True
                elif isinstance(func, ast.Name):
                    if 'close' in func.id.lower():
                        return True
        return False

    def _has_nested_tx(self, node: ast.Try) -> bool:
        for n in ast.walk(node):
            if isinstance(n, ast.Try) and n is not node:
                return True
        return False

    def _build_rca(self, kind: str, file: str, line: int, detail: str) -> dict:
        rca_dict = {
            "root_cause": detail,
            "suggested_fix": "",
            "severity": "HIGH",
            "confidence": 0.9,
        }
        if kind == "MISSING_ROLLBACK":
            rca_dict["suggested_fix"] = (
                "Tambahkan commit setelah semua operasi sukses, "
                "dan rollback pada except block.\n"
                "Contoh:\n"
                "try:\n"
                "    session.add(obj)\n"
                "    session.commit()\n"
                "except Exception:\n"
                "    session.rollback()\n"
                "    raise\n"
                "Atau gunakan context manager: with session.begin(): ..."
            )
        elif kind == "NESTED_UNSAFE":
            rca_dict["suggested_fix"] = (
                "Hindari nested transaction manual. "
                "Gunakan savepoint jika perlu, atau gunakan @transactional "
                "yang menangani rollback secara otomatis."
            )

        if self._rca_engine is not None:
            try:
                exc = RuntimeError(f"Transaction leak: {kind} at {file}:{line}")
                ctx = {"file": file, "line": line, "code": detail}
                result = analyze_exception(exc, ctx)
                if result:
                    eng_dict = result.to_dict()
                    if eng_dict.get("root_cause") and "Unhandled" not in eng_dict["root_cause"]:
                        rca_dict["root_cause"] = eng_dict["root_cause"] + " (from RCA engine)"
                    if eng_dict.get("suggested_fix") and "Tambahkan rule" not in eng_dict["suggested_fix"]:
                        rca_dict["suggested_fix"] = eng_dict["suggested_fix"] + " (from RCA engine)"
                    if eng_dict.get("severity"):
                        rca_dict["severity"] = eng_dict["severity"]
            except Exception:
                pass
        return rca_dict

# ---- Reporters ----
def print_report(report: Report, verbose: bool = False):
    print(f"\n{c('CYAN')}{'='*70}{c('RESET')}")
    print(f"{c('BOLD')}TRANSACTION LEAK CHECKER{c('RESET')}")
    print(f"{'='*70}")
    print(f"  Files scanned     : {report.total_files}")
    print(f"  Try blocks found  : {report.total_try_blocks}")
    print(f"  Issues detected   : {len(report.issues)}")
    print(f"  RCA Engine        : {'✅ Active' if RCA_AVAIL else '⚠️ Fallback'}")
    print(f"  Score             : {c('GREEN') if report.score >= 90 else c('YELLOW')}{report.score}/100{c('RESET')}")
    print(f"  Scan time         : {report.scan_time:.2f}s")

    if report.issues:
        print(f"\n{c('RED')}Issues:{c('RESET')}")
        for i in report.issues[:20]:
            color = c("RED") if i.kind == "MISSING_ROLLBACK" else c("YELLOW")
            print(f"  {color}[{i.kind}]{c('RESET')} {i.file}:{i.line}  (conf:{i.confidence:.2f})")
            print(f"      {i.detail}")
            if verbose and i.rca:
                rc = i.rca.get('root_cause', '')[:200]
                if rc:
                    print(f"      RCA: {rc}")
                fix = i.rca.get('suggested_fix', '')[:200]
                if fix:
                    print(f"      Fix: {fix}")
    else:
        print(f"\n  {c('GREEN')}✅ No transaction leaks detected.{c('RESET')}")

def save_json(report: Report, path: pathlib.Path):
    data = {
        "score": report.score,
        "total_try_blocks": report.total_try_blocks,
        "total_files": report.total_files,
        "scan_time": report.scan_time,
        "issues": [
            {
                "file": i.file,
                "line": i.line,
                "kind": i.kind,
                "detail": i.detail,
                "confidence": i.confidence
            }
            for i in report.issues
        ]
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  JSON saved to {path}")

def save_html(report: Report, path: pathlib.Path):
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Transaction Leak Report</title>
<style>body{{font-family:sans-serif;padding:2rem}}
.issue{{margin:0.5rem 0;padding:0.5rem;border-left:4px solid #dc3545}}
.error{{border-color:#dc3545}} .warning{{border-color:#ffc107}}
</style></head><body>
<h1>Transaction Leak Report</h1>
<p>Score: <span style="font-size:2rem">{report.score}/100</span></p>
<p>Files: {report.total_files} | Try blocks: {report.total_try_blocks}</p>
<h2>Issues ({len(report.issues)})</h2>
"""
    for i in report.issues[:50]:
        cls = "error" if i.kind == "MISSING_ROLLBACK" else "warning"
        html += f'<div class="issue {cls}"><strong>{i.kind}</strong> {i.file}:{i.line}<br><small>{i.detail}</small></div>'
    html += "</body></html>"
    with open(path, "w") as f:
        f.write(html)
    print(f"  HTML saved to {path}")

def save_sarif(report: Report, path: pathlib.Path):
    sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "TransactionLeakChecker", "version": "1.0"}},
            "results": [
                {
                    "ruleId": "TX-001",
                    "level": "error" if i.kind == "MISSING_ROLLBACK" else "warning",
                    "message": {"text": i.detail},
                    "locations": [{
                        "physicalLocation": {
                            "artifactLocation": {"uri": i.file},
                            "region": {"startLine": i.line}
                        }
                    }]
                }
                for i in report.issues
            ]
        }]
    }
    with open(path, "w") as f:
        json.dump(sarif, f, indent=2)
    print(f"  SARIF saved to {path}")

# ---- Main ----
def main():
    parser = argparse.ArgumentParser(description="Transaction Leak Checker")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE", help="Save JSON report")
    parser.add_argument("--html", metavar="FILE", help="Save HTML report")
    parser.add_argument("--sarif", metavar="FILE", help="Save SARIF report")
    parser.add_argument("--exclude", default=".venv,venv,__pycache__,tests,checker,docs,migrations")
    parser.add_argument("--max-workers", type=int, default=4)
    args = parser.parse_args()

    root = pathlib.Path(__file__).resolve().parent.parent
    checker = TransactionLeakChecker(root, args.exclude.split(","), args.max_workers)
    report = checker.scan()
    print_report(report, args.verbose)
    if args.json:
        save_json(report, pathlib.Path(args.json))
    if args.html:
        save_html(report, pathlib.Path(args.html))
    if args.sarif:
        save_sarif(report, pathlib.Path(args.sarif))

if __name__ == "__main__":
    main()
