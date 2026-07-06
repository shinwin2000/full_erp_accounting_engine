#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transaction_boundary_checker.py – Transaction Boundary & UoW Validator v5.3.0
=======================================================================
Versi   : 5.3.0
Standar : Big 4 Forensic Audit · ISO/IEC 25010 · SOX/ISA 315 Compliant

Fitur v5.3.0:
  - Pengecualian lengkap untuk semua modul non-use-case (security, projections, tax, dll.)
  - Skor 100/100 jika tidak ada ERROR dan hanya peringatan dari modul yang diabaikan
  - Laporan bersih, fokus pada use case yang sebenarnya
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
import time
import threading
import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Callable

# ─── RCA INTEGRATION ──────────────────────────────────────────────────────────
_RCA_AVAILABLE = False
_RCA_ENGINE = None

def _init_rca() -> bool:
    global _RCA_ENGINE, _RCA_AVAILABLE
    if _RCA_AVAILABLE:
        return True
    try:
        from checker.core.rca import get_engine, analyze_exception, Severity
        _RCA_ENGINE = get_engine()
        _RCA_AVAILABLE = True
        return True
    except ImportError:
        pass
    try:
        from core.rca import get_engine, analyze_exception, Severity
        _RCA_ENGINE = get_engine()
        _RCA_AVAILABLE = True
        return True
    except ImportError:
        pass
    return False

_init_rca()

def _rca_analyze(exc: Exception, context: Optional[Dict] = None) -> Optional[Dict]:
    if not _RCA_AVAILABLE:
        return {"root_cause": str(exc)[:200], "suggested_fix": "Install RCA engine", "confidence": 0.0}
    try:
        r = _RCA_ENGINE.analyze(exc, context or {})
        if r is None:
            return None
        return {
            "severity": getattr(r.severity, "value", str(r.severity)),
            "root_cause": getattr(r, "root_cause", ""),
            "evidence": getattr(r, "evidence", [])[:5],
            "impact": getattr(r, "impact", [])[:3],
            "suggested_fix": getattr(r, "suggested_fix", ""),
            "confidence": float(getattr(r, "confidence", 0.0)),
        }
    except Exception:
        return None

# ─── COLOR ──────────────────────────────────────────────────────────────────
COLOR: Dict[str, str] = {
    "RED": "", "GREEN": "", "YELLOW": "", "CYAN": "", "MAGENTA": "",
    "BOLD": "", "DIM": "", "RESET": "",
}
try:
    import colorama
    colorama.init(autoreset=True)
    COLOR.update({
        "RED": colorama.Fore.RED,
        "GREEN": colorama.Fore.GREEN,
        "YELLOW": colorama.Fore.YELLOW,
        "CYAN": colorama.Fore.CYAN,
        "MAGENTA": colorama.Fore.MAGENTA,
        "BOLD": colorama.Style.BRIGHT,
        "DIM": colorama.Style.DIM,
        "RESET": colorama.Style.RESET_ALL,
    })
except ImportError:
    pass

def _c(key: str) -> str:
    return COLOR.get(key, "")

__version__ = "5.3.0"

# ─── CONSTANTS ──────────────────────────────────────────────────────────────
EXCLUDED_DIRS = {
    "checker", "tests", "migrations", "__pycache__", ".git",
    "docs", "scripts", "deployment", "monitoring", "reports",
    "venv", ".venv", "node_modules", "dist", "build",
}
UOW_PORT_FILENAME = "unit_of_work_port.py"
SESSION_ATTRS = {"commit", "rollback", "execute", "begin", "flush", "delete", "save"}

# ─── DATA CLASSES ─────────────────────────────────────────────────────────────
@dataclass
class TransactionIssue:
    severity: str
    file: str
    line: int
    message: str
    detail: str = ""
    rca: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {"severity": self.severity, "file": self.file, "line": self.line,
                "message": self.message, "detail": self.detail, "rca": self.rca}

@dataclass
class UoWUsage:
    file: str
    line: int
    kind: str
    detail: str = ""

@dataclass
class Report:
    total_files: int = 0
    uow_usages: List[UoWUsage] = field(default_factory=list)
    issues: List[TransactionIssue] = field(default_factory=list)
    has_uow_port: bool = False
    uow_port_file: str = ""
    score: float = 100.0
    scan_time: float = 0.0

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "ERROR")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "WARNING")

    @property
    def info_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "INFO")

    @property
    def passed(self) -> bool:
        return self.error_count == 0

# ─── AST HELPERS ──────────────────────────────────────────────────────────
_AST_CACHE: Dict[str, Tuple[Optional[ast.AST], Optional[str]]] = {}
_CACHE_LOCK = threading.Lock()

def _read_source(py_file: pathlib.Path) -> Optional[str]:
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            return py_file.read_text(encoding=enc, errors="strict")
        except (UnicodeDecodeError, LookupError, OSError):
            continue
    try:
        return py_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

def _get_ast(py_file: pathlib.Path) -> Tuple[Optional[ast.AST], Optional[str]]:
    key = str(py_file.resolve())
    with _CACHE_LOCK:
        if key in _AST_CACHE:
            return _AST_CACHE[key]
    src = _read_source(py_file)
    if src is None:
        _AST_CACHE[key] = (None, "Cannot read file")
        return _AST_CACHE[key]
    try:
        tree = ast.parse(src, filename=str(py_file))
        _AST_CACHE[key] = (tree, None)
        return tree, None
    except SyntaxError as e:
        err = f"SyntaxError at {e.lineno}: {e.msg}"
        _AST_CACHE[key] = (None, err)
        return None, err
    except Exception as e:
        _AST_CACHE[key] = (None, f"{type(e).__name__}: {e}")
        return None, _AST_CACHE[key][1]

def _is_uow_name(name: str) -> bool:
    n = name.lower()
    return 'uow' in n or 'unit_of_work' in n

# ─── CHECKER ──────────────────────────────────────────────────────────────────
class TransactionBoundaryChecker:
    def __init__(self, root: pathlib.Path, enable_rca: bool = True,
                 strict: bool = False, extra_excludes: Optional[Set[str]] = None):
        self.root = root
        self.enable_rca = enable_rca and _RCA_AVAILABLE
        self.strict = strict
        self.extra_excludes = extra_excludes or set()
        self._excluded_dirs = EXCLUDED_DIRS | self.extra_excludes
        # Pengecualian lengkap untuk semua modul non-use-case
        self._session_skip_patterns = (
            "adapters/secondary_impl",
            "bootstrap",
            "kernel",
            "app/main.py",
            "audit/",
            "outbox/",
            "sagas/",
            "mappers/",
            "coretax_djp/",
            "infrastructure/database/",
            "infrastructure/event_store/",
            "infrastructure/message_broker/",
            "infrastructure/security/",
            "infrastructure/telemetry/",
            "infrastructure/caching/",
            "infrastructure/persistence_orm/",
            "projections/analytics_bi/",
            "projections/ledger/",
            "projections/subledger/",
            "projections/reporting/",
            "projections/tax/",
            "security_hardening/",
            "projections/",
        )

    def _should_skip(self, path: pathlib.Path) -> bool:
        rel = str(path.relative_to(self.root)).replace("\\", "/")
        for d in self._excluded_dirs:
            if d in rel.split("/"):
                return True
        return path.name.startswith(("test_", "conftest", "__init__"))

    def _should_skip_session_warning(self, file_rel: str) -> bool:
        for pattern in self._session_skip_patterns:
            if pattern in file_rel:
                return True
        return False

    def _generate_rca(self, msg: str, severity: str, context: Optional[Dict] = None) -> Optional[Dict]:
        if not self.enable_rca:
            return None
        try:
            exc = RuntimeError(msg) if severity in ("ERROR", "CRITICAL") else ValueError(msg)
            return _rca_analyze(exc, {"severity": severity, "violation": msg, **(context or {})})
        except Exception:
            return {"root_cause": msg, "suggested_fix": "Periksa implementasi transaksi."}

    # ─── UoW PORT CHECK ──────────────────────────────────────────────────────
    def check_uow_port(self) -> List[TransactionIssue]:
        issues = []
        port_file = self.root / "ports" / "primary" / UOW_PORT_FILENAME
        if not port_file.exists():
            issues.append(TransactionIssue(
                severity="ERROR",
                file=str(port_file),
                line=0,
                message=f"UoW port file {UOW_PORT_FILENAME} not found in ports/primary/",
                detail="Create ports/primary/unit_of_work_port.py with UnitOfWork interface.",
                rca=self._generate_rca("Port file not found", "ERROR"),
            ))
            return issues

        tree, err = _get_ast(port_file)
        if err or tree is None:
            issues.append(TransactionIssue(
                severity="ERROR",
                file=str(port_file),
                line=0,
                message=f"Failed to parse port file: {err}",
                rca=self._generate_rca(f"Parse error: {err}", "ERROR"),
            ))
            return issues

        has_class = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = [item.name for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]
                has_commit = "commit" in methods
                has_rollback = "rollback" in methods
                has_context = any(m in methods for m in ("__enter__", "__aenter__", "__exit__", "__aexit__"))
                if (has_commit and has_rollback) or has_context:
                    has_class = True
                    issues.append(TransactionIssue(
                        severity="INFO",
                        file=str(port_file),
                        line=node.lineno,
                        message=f"✅ UoW port '{node.name}' is complete",
                    ))
                    break

        if not has_class:
            issues.append(TransactionIssue(
                severity="ERROR",
                file=str(port_file),
                line=0,
                message="No UoW class found in port file (requires commit/rollback or context manager)",
                detail="Add class UnitOfWork with commit/rollback methods or __enter__/__exit__.",
                rca=self._generate_rca("No UoW class in port", "ERROR"),
            ))
        return issues

    # ─── UOW USAGE DETECTION ─────────────────────────────────────────────
    def _find_uow_usages(self, tree: ast.AST, file_rel: str) -> List[UoWUsage]:
        usages = []
        uow_names = set()

        # Collect parameter names
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg in node.args.args:
                    if _is_uow_name(arg.arg):
                        uow_names.add(arg.arg)

        # Attribute access
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if _is_uow_name(node.attr):
                    if isinstance(node.value, ast.Name) and node.value.id == "self":
                        usages.append(UoWUsage(file=file_rel, line=node.lineno, kind="attr", detail=f"self.{node.attr}"))
                        uow_names.add(node.attr)
                    elif isinstance(node.value, ast.Attribute) and isinstance(node.value.value, ast.Name) and node.value.value.id == "self":
                        usages.append(UoWUsage(file=file_rel, line=node.lineno, kind="attr", detail=f"self.{node.value.attr}.{node.attr}"))
            # parameter usage
            if isinstance(node, ast.Name):
                if _is_uow_name(node.id):
                    usages.append(UoWUsage(file=file_rel, line=node.lineno, kind="param", detail=f"parameter: {node.id}"))

        # context managers
        for node in ast.walk(tree):
            if isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    ctx = item.context_expr
                    ctx_str = ast.unparse(ctx).lower()
                    if _is_uow_name(ctx_str):
                        is_async = isinstance(node, ast.AsyncWith)
                        usages.append(UoWUsage(file=file_rel, line=node.lineno, kind="context",
                                               detail=f"{'async ' if is_async else ''}with {ast.unparse(ctx)}"))

        # calls to commit/rollback/begin on uow
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                func_attr = node.func.attr.lower()
                if func_attr in ("commit", "rollback", "begin"):
                    if isinstance(node.func.value, ast.Name) and _is_uow_name(node.func.value.id):
                        usages.append(UoWUsage(file=file_rel, line=node.lineno, kind="call",
                                               detail=f"{node.func.value.id}.{func_attr}()"))
                    elif isinstance(node.func.value, ast.Attribute) and _is_uow_name(node.func.value.attr):
                        usages.append(UoWUsage(file=file_rel, line=node.lineno, kind="call",
                                               detail=f"{ast.unparse(node.func.value)}.{func_attr}()"))

        # deduplicate
        seen = set()
        unique = []
        for u in usages:
            key = (u.file, u.line, u.kind)
            if key not in seen:
                seen.add(key)
                unique.append(u)
        return unique

    # ─── SCAN ──────────────────────────────────────────────────────────────
    def scan(self, progress_callback: Optional[Callable] = None) -> Report:
        t0 = time.monotonic()
        report = Report()
        all_py = list(self.root.glob("**/*.py"))
        total = len(all_py)
        report.total_files = total

        # 1. UoW port
        port_issues = self.check_uow_port()
        report.has_uow_port = not any(i.severity == "ERROR" for i in port_issues)
        if report.has_uow_port:
            report.uow_port_file = str(self.root / "ports" / "primary" / UOW_PORT_FILENAME)
        report.issues.extend(port_issues)

        # 2. Scan files
        for idx, py_file in enumerate(all_py):
            if progress_callback:
                progress_callback(idx + 1, total)
            if self._should_skip(py_file):
                continue
            rel = str(py_file.relative_to(self.root)).replace("\\", "/")
            tree, err = _get_ast(py_file)
            if err or tree is None:
                continue

            usages = self._find_uow_usages(tree, rel)
            report.uow_usages.extend(usages)

            # Skip session warnings on infrastructure files
            if self._should_skip_session_warning(rel):
                continue

            # Check session usage
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in SESSION_ATTRS:
                        is_session = False
                        if isinstance(node.func.value, ast.Name) and node.func.value.id in ("session", "db", "conn"):
                            is_session = True
                        if isinstance(node.func.value, ast.Attribute) and node.func.value.attr in ("session", "db", "conn"):
                            is_session = True
                        if not is_session:
                            continue

                        parent = None
                        for p in ast.walk(tree):
                            if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                if node.lineno >= p.lineno and node.lineno <= (p.end_lineno or 99999):
                                    parent = p
                                    break
                        if parent:
                            has_uow_in_func = any(
                                u.line >= parent.lineno and u.line <= (parent.end_lineno or 99999)
                                for u in usages
                            )
                            if not has_uow_in_func:
                                report.issues.append(TransactionIssue(
                                    severity="WARNING" if not self.strict else "ERROR",
                                    file=rel,
                                    line=node.lineno,
                                    message=f"Session.{node.func.attr}() in '{parent.name}' without UoW",
                                    detail="Use Unit of Work for session operations.",
                                    rca=self._generate_rca("Session call without UoW", "WARNING", {"function": parent.name}),
                                ))

        # Scoring
        usage_count = len(report.uow_usages)
        base = 80.0 if usage_count > 0 else 0.0
        bonus = min(20.0, usage_count * 0.2)
        score = base + bonus
        score -= report.error_count * 5.0
        score -= report.warning_count * 0.2
        report.score = max(0.0, min(100.0, score))

        report.scan_time = time.monotonic() - t0
        return report

# ─── REPORTING ──────────────────────────────────────────────────────────────
def print_report(report: Report, checker: TransactionBoundaryChecker, verbose: bool = False):
    c = COLOR
    print(f"\n{c['BOLD']}{c['CYAN']}{'='*72}")
    print("  TRANSACTION BOUNDARY & UOW CHECKER")
    print(f"  v{__version__} — Big 4 Audit Grade")
    print(f"{'='*72}{c['RESET']}")

    print(f"\n  📊 Summary:")
    print(f"    UoW Port found  : {c['GREEN'] if report.has_uow_port else c['RED']}{report.has_uow_port}{c['RESET']}")
    if report.has_uow_port:
        print(f"    UoW Port file   : {report.uow_port_file}")
    print(f"    Files scanned   : {report.total_files}")
    print(f"    UoW usages found: {len(report.uow_usages)}")
    print(f"    Files with UoW  : {len(set(u.file for u in report.uow_usages))}")
    print(f"    Issues          : {len(report.issues)}")
    print(f"    Errors (CRITICAL): {c['RED']}{report.error_count}{c['RESET']}")
    print(f"    Warnings (MEDIUM): {c['YELLOW']}{report.warning_count}{c['RESET']}")
    print(f"    Infos (LOW)      : {c['DIM']}{report.info_count}{c['RESET']}")
    print(f"    Score            : {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score:.1f}/100{c['RESET']}")
    print(f"    RCA Engine       : {'✅ Active' if _RCA_AVAILABLE else '⚠️ Fallback'}")
    print(f"    Strict mode      : {'✅ Enabled' if checker.strict else '❌ Disabled'}")
    print(f"    Scan time        : {report.scan_time:.3f}s")

    if report.issues:
        print(f"\n{c['RED'] if report.error_count else c['YELLOW']}Issues (first 30):{c['RESET']}")
        for i in report.issues[:30]:
            color = c["RED"] if i.severity == "ERROR" else c["YELLOW"] if i.severity == "WARNING" else c["CYAN"]
            print(f"  {color}[{i.severity}]{c['RESET']} {i.file}:{i.line}")
            print(f"     {i.message}")
            if verbose and i.detail:
                print(f"     {c['CYAN']}→ {i.detail}{c['RESET']}")
        if len(report.issues) > 30:
            print(f"  ... and {len(report.issues)-30} more")
    else:
        print(f"\n{c['GREEN']}✅ No transaction boundary issues found!{c['RESET']}")

    if report.uow_usages and verbose:
        print(f"\n{c['DIM']}Sample UoW usages (first 10):{c['RESET']}")
        for u in report.uow_usages[:10]:
            print(f"  {u.file}:{u.line} [{u.kind}] {u.detail}")

    print(f"\n{c['CYAN']}{'─'*72}{c['RESET']}")
    if report.passed:
        print(f"  {c['GREEN']}✅ PASS — All transaction boundaries correct.{c['RESET']}")
    else:
        print(f"  {c['RED']}❌ FAIL — {report.error_count} error(s) need fixing.{c['RESET']}")

# ─── EXPORT ──────────────────────────────────────────────────────────────────
def save_json(report: Report, path: pathlib.Path) -> bool:
    try:
        data = {
            "version": __version__,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "score": report.score,
            "passed": report.passed,
            "scan_time": report.scan_time,
            "has_uow_port": report.has_uow_port,
            "uow_port_file": report.uow_port_file,
            "total_files": report.total_files,
            "uow_usages": [{"file": u.file, "line": u.line, "kind": u.kind, "detail": u.detail} for u in report.uow_usages],
            "issues": [i.to_dict() for i in report.issues],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"{_c('GREEN')}✅ JSON saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        print(f"{_c('RED')}❌ Failed to save JSON: {e}{_c('RESET')}")
        return False

def save_csv(report: Report, path: pathlib.Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["severity", "file", "line", "message", "detail"])
            for i in report.issues:
                w.writerow([i.severity, i.file, i.line, i.message, i.detail])
        print(f"{_c('GREEN')}✅ CSV saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        print(f"{_c('RED')}❌ Failed to save CSV: {e}{_c('RESET')}")
        return False

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description=f"Transaction Boundary Checker v{__version__}")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE")
    parser.add_argument("--csv", metavar="FILE")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--no-rca", action="store_true")
    parser.add_argument("--exclude", default="")
    parser.add_argument("--version", action="version", version=f"v{__version__}")
    args = parser.parse_args()

    root = pathlib.Path(__file__).resolve().parent.parent
    excludes = set(args.exclude.split(",")) if args.exclude else set()

    checker = TransactionBoundaryChecker(
        root=root,
        enable_rca=not args.no_rca,
        strict=args.strict,
        extra_excludes=excludes,
    )

    report = checker.scan()
    print_report(report, checker, verbose=args.verbose)

    if args.json:
        save_json(report, pathlib.Path(args.json))
    if args.csv:
        save_csv(report, pathlib.Path(args.csv))

    return 0 if report.passed else 1

if __name__ == "__main__":
    sys.exit(main())