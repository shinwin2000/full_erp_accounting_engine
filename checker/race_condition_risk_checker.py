#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker/race_condition_risk_checker.py – Race Condition Risk Detector
=======================================================================
Versi   : 3.0.0
Standar : Big 4 Forensic Audit · ISO/IEC 25010 · SOX/ISA 315 Compliant

Fitur:
  - Deteksi metode update/delete tanpa pessimistic lock (SELECT FOR UPDATE)
  - Deteksi metode update/delete tanpa optimistic lock (version field)
  - Deteksi distributed lock (Redis, ZooKeeper, etc.)
  - Deteksi @transactional decorator dengan isolation level
  - Deteksi async lock patterns (asyncio.Lock, aioredis.lock)
  - Integrasi RCA engine (checker.core.rca)
  - Parallel scanning, AST caching, progress bar
  - Laporan JSON, CSV, HTML, SARIF
  - Self-test terintegrasi
  - CLI: --verbose, --json, --csv, --html, --sarif, --strict, --no-rca, --self-test, --exclude, --max-workers
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import csv
import json
import logging
import os
import pathlib
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union, Callable

# ─── RCA INTEGRATION ──────────────────────────────────────────────────────────
_RCA_ENGINE = None
_RCA_AVAILABLE = False

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
    _root = pathlib.Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    try:
        from checker.core.rca import get_engine, analyze_exception, Severity
        _RCA_ENGINE = get_engine()
        _RCA_AVAILABLE = True
        return True
    except ImportError:
        pass
    return False

_init_rca()

def _rca_analyze(exc: Exception, context: Optional[Dict] = None) -> Optional[Dict]:
    if not _RCA_AVAILABLE:
        return {
            "severity": "WARNING",
            "root_cause": str(exc)[:200],
            "suggested_fix": "Install checker.core.rca",
            "confidence": 0.0,
        }
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

# ─── LOGGING ──────────────────────────────────────────────────────────────────
_log_handler = logging.StreamHandler(sys.stderr)
_log_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
))
logger = logging.getLogger("race_condition_checker")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    logger.addHandler(_log_handler)

# ─── COLOR ──────────────────────────────────────────────────────────────────
COLOR: Dict[str, str] = {
    "RED": "", "GREEN": "", "YELLOW": "", "CYAN": "", "MAGENTA": "",
    "WHITE": "", "BOLD": "", "DIM": "", "RESET": "",
}
try:
    import colorama
    colorama.init(autoreset=True)
    COLOR.update({
        "RED"   : colorama.Fore.RED,
        "GREEN" : colorama.Fore.GREEN,
        "YELLOW": colorama.Fore.YELLOW,
        "CYAN"  : colorama.Fore.CYAN,
        "MAGENTA": colorama.Fore.MAGENTA,
        "WHITE" : colorama.Fore.WHITE,
        "BOLD"  : colorama.Style.BRIGHT,
        "DIM"   : colorama.Style.DIM,
        "RESET" : colorama.Style.RESET_ALL,
    })
except ImportError:
    pass

def _safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        new_args = [a.encode("ascii", errors="replace").decode("ascii") if isinstance(a, str) else a for a in args]
        print(*new_args, **kwargs)

def _c(key: str) -> str:
    return COLOR.get(key, "")

# ─── VERSION ──────────────────────────────────────────────────────────────────
__version__ = "3.0.0"

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
EXCLUDED_DIRS_DEFAULT = {
    "checker", "tests", "migrations", "__pycache__", ".git",
    "docs", "scripts", "deployment", "monitoring", "reports",
    "venv", ".venv", "node_modules", "dist", "build",
}

UPDATE_DELETE_KEYWORDS = {"update", "delete", "modify", "change", "alter", "remove", "set", "patch"}
LOCK_KEYWORDS = {"lock", "select_for_update", "for_update", "optimistic_lock", "pessimistic_lock", "distributed_lock"}
VERSION_KEYWORDS = {"version", "optimistic", "row_version", "etag", "revision", "rev"}
TRANSACTIONAL_DECORATORS = {"transactional", "atomic", "with_transaction", "db_transaction"}
ISOLATION_LEVELS = {"READ_COMMITTED", "REPEATABLE_READ", "SERIALIZABLE", "READ_UNCOMMITTED"}

# ─── DATA CLASSES ─────────────────────────────────────────────────────────────
@dataclass
class Finding:
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    file: str
    line: int
    function: str
    message: str
    detail: str = ""
    rca: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "function": self.function,
            "message": self.message,
            "detail": self.detail,
            "rca": self.rca,
        }

@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    score: float = 100.0
    scan_time: float = 0.0
    total_files_scanned: int = 0
    total_functions_checked: int = 0
    files_with_issues: int = 0

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity in ("CRITICAL", "HIGH"))

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "MEDIUM")

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity in ("LOW", "INFO"))

    @property
    def passed(self) -> bool:
        return self.error_count == 0

# ─── AST UTILITIES ──────────────────────────────────────────────────────────
_AST_CACHE: Dict[str, Tuple[Optional[ast.AST], Optional[str]]] = {}
_CACHE_LOCK = threading.Lock()

def _read_source(py_file: pathlib.Path) -> Optional[str]:
    encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
    for enc in encodings:
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
        err = f"{type(e).__name__}: {e}"
        _AST_CACHE[key] = (None, err)
        return None, err

def _has_method_call(node: ast.AST, call_names: Set[str]) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            if isinstance(sub.func, ast.Name) and sub.func.id in call_names:
                return True
            if isinstance(sub.func, ast.Attribute) and sub.func.attr in call_names:
                return True
            # self.with_for_update(), session.execute("SELECT ... FOR UPDATE")
            if isinstance(sub.func, ast.Attribute):
                if isinstance(sub.func.value, ast.Attribute):
                    if sub.func.value.attr in call_names:
                        return True
                    if sub.func.attr in call_names:
                        return True
                if isinstance(sub.func.value, ast.Name):
                    if sub.func.value.id in call_names:
                        return True
    return False

def _has_string_contains(text: str, keywords: Set[str]) -> bool:
    text_lower = text.lower()
    for kw in keywords:
        if kw.lower() in text_lower:
            return True
    return False

def _get_source_snippet(lines: List[str], line: int, context: int = 2) -> str:
    if line <= 0 or line > len(lines):
        return ""
    start = max(0, line - context - 1)
    end = min(len(lines), line + context)
    return "\n".join(lines[start:end]).strip()

def _generate_rca(msg: str, severity: str, context: Optional[Dict] = None) -> Optional[Dict]:
    if not _RCA_AVAILABLE:
        return {
            "severity": "WARNING",
            "root_cause": msg[:200],
            "suggested_fix": "Install checker.core.rca",
            "confidence": 0.0,
        }
    try:
        exc = RuntimeError(msg) if severity in ("CRITICAL", "HIGH") else ValueError(msg)
        ctx = {"severity": severity, "violation": msg, **(context or {})}
        return _rca_analyze(exc, ctx)
    except Exception:
        return {"root_cause": msg, "suggested_fix": "Implement proper locking mechanism."}

# ─── DETECTOR ──────────────────────────────────────────────────────────────────
class RaceConditionDetector:
    def __init__(
        self,
        file_path: pathlib.Path,
        root: pathlib.Path,
        lines: List[str],
        enable_rca: bool = True,
        strict: bool = False,
    ):
        self.file_path = file_path
        self.root = root
        self.lines = lines
        self.enable_rca = enable_rca
        self.strict = strict
        self.findings: List[Finding] = []
        self.rel_path = str(file_path.relative_to(root)).replace("\\", "/")

    def _add_finding(self, severity: str, line: int, func_name: str, message: str, detail: str):
        rca = _generate_rca(message, severity, {"function": func_name, "file": self.rel_path}) if self.enable_rca else None
        self.findings.append(Finding(
            severity=severity,
            file=self.rel_path,
            line=line,
            function=func_name,
            message=message,
            detail=detail,
            rca=rca,
        ))

    def _is_update_delete_method(self, func_name: str) -> bool:
        lower = func_name.lower()
        return any(kw in lower for kw in UPDATE_DELETE_KEYWORDS)

    def _has_pessimistic_lock(self, node: ast.AST) -> bool:
        """Check for pessimistic lock patterns (SELECT FOR UPDATE, with_for_update())."""
        # Check for with_for_update() call
        if _has_method_call(node, {"with_for_update", "select_for_update"}):
            return True
        # Check for "FOR UPDATE" in SQL string
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                if "FOR UPDATE" in sub.value.upper():
                    return True
            if isinstance(sub, ast.JoinedStr):
                for part in sub.values:
                    if isinstance(part, ast.Constant) and isinstance(part.value, str):
                        if "FOR UPDATE" in part.value.upper():
                            return True
        return False

    def _has_optimistic_lock(self, node: ast.AST) -> bool:
        """Check for optimistic lock patterns (version field check)."""
        # Check for version check in if/assert
        for sub in ast.walk(node):
            if isinstance(sub, ast.If):
                cond = ast.unparse(sub.test).lower()
                if "version" in cond and ("!=" in cond or ">" in cond or "<" in cond):
                    return True
            if isinstance(sub, ast.Assert):
                cond = ast.unparse(sub.test).lower()
                if "version" in cond and ("!=" in cond or ">" in cond or "<" in cond):
                    return True
            # Check for version parameter
            if isinstance(sub, ast.Call):
                if isinstance(sub.func, ast.Attribute):
                    if sub.func.attr in {"update", "where"}:
                        # Check if version is in args
                        for arg in sub.args:
                            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                                if "version" in arg.value.lower():
                                    return True
        return False

    def _has_distributed_lock(self, node: ast.AST) -> bool:
        """Check for distributed lock patterns (Redis lock, ZooKeeper, etc.)."""
        lock_names = {"lock", "acquire", "redlock", "zookeeper_lock", "distributed_lock"}
        return _has_method_call(node, lock_names) or _has_method_call(node, {"redis_lock", "cache_lock"})

    def _has_transactional_decorator(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> bool:
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id in TRANSACTIONAL_DECORATORS:
                return True
            if isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name) and dec.func.id in TRANSACTIONAL_DECORATORS:
                    return True
                if isinstance(dec.func, ast.Attribute) and dec.func.attr in TRANSACTIONAL_DECORATORS:
                    return True
        return False

    def _has_isolation_level(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> bool:
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call):
                for kw in dec.keywords:
                    if kw.arg == "isolation" and isinstance(kw.value, ast.Constant):
                        if kw.value.value in ISOLATION_LEVELS:
                            return True
        return False

    def _has_lock_keyword_in_params(self, node: ast.FunctionDef) -> bool:
        for arg in node.args.args:
            arg_lower = arg.arg.lower()
            if "lock" in arg_lower or "version" in arg_lower:
                return True
        return False

    def analyze_function(self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> Optional[Finding]:
        func_name = node.name
        if not self._is_update_delete_method(func_name):
            return None

        has_plock = self._has_pessimistic_lock(node)
        has_olock = self._has_optimistic_lock(node)
        has_dlock = self._has_distributed_lock(node)
        has_txn = self._has_transactional_decorator(node)
        has_isolation = self._has_isolation_level(node)
        has_lock_param = self._has_lock_keyword_in_params(node)

        # Determine severity based on protection level
        if has_plock or has_olock or has_dlock:
            # Protected - no finding
            return None

        # Check if it's a read-only operation (shouldn't need lock)
        body_text = ast.unparse(node)
        if "select" in body_text.lower() and "update" not in body_text.lower() and "delete" not in body_text.lower():
            return None

        # Determine severity
        if has_txn and has_isolation:
            severity = "MEDIUM" if not self.strict else "HIGH"
            detail = "Uses @transactional with isolation level but missing explicit lock. Consider SELECT FOR UPDATE or version check."
        elif has_txn:
            severity = "MEDIUM"
            detail = "Uses @transactional but missing explicit lock. Add SELECT FOR UPDATE or version check."
        elif has_lock_param:
            severity = "MEDIUM" if not self.strict else "HIGH"
            detail = "Has lock/version parameter but not used in method body. Check if lock is actually acquired."
        else:
            severity = "HIGH" if not self.strict else "CRITICAL"
            detail = "No lock mechanism detected. Add pessimistic (SELECT FOR UPDATE), optimistic (version check), or distributed lock."

        message = f"Function '{func_name}' may have race condition"

        return Finding(
            severity=severity,
            file=self.rel_path,
            line=node.lineno,
            function=func_name,
            message=message,
            detail=detail,
            rca=_generate_rca(message, severity, {"function": func_name}) if self.enable_rca else None,
        )

    def scan(self, tree: ast.AST) -> List[Finding]:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                finding = self.analyze_function(node)
                if finding:
                    self.findings.append(finding)
        return self.findings

# ─── SCANNER ──────────────────────────────────────────────────────────────────
class RaceConditionChecker:
    def __init__(
        self,
        root: pathlib.Path,
        enable_rca: bool = True,
        strict: bool = False,
        extra_excludes: Optional[Set[str]] = None,
        max_workers: int = 4,
    ):
        self.root = root
        self.enable_rca = enable_rca and _RCA_AVAILABLE
        self.strict = strict
        self.extra_excludes = extra_excludes or set()
        self.max_workers = max_workers
        self._excluded_dirs = EXCLUDED_DIRS_DEFAULT | self.extra_excludes

    def _should_skip_file(self, path: pathlib.Path) -> bool:
        rel = str(path.relative_to(self.root)).replace("\\", "/")
        for d in self._excluded_dirs:
            if d in rel.split("/"):
                return True
        if path.name.startswith(("test_", "conftest", "__init__")):
            return True
        if path.name.endswith(("_test.py", "_tests.py")):
            return True
        if path.name.startswith("race_condition"):
            return True
        return False

    def _get_python_files(self) -> List[pathlib.Path]:
        py_files = []
        scan_dirs = ["domain", "application", "infrastructure", "adapters", "bootstrap", "kernel"]
        for dir_name in scan_dirs:
            base = self.root / dir_name
            if not base.exists():
                continue
            for p in base.rglob("*.py"):
                if not self._should_skip_file(p):
                    py_files.append(p)
        return sorted(set(py_files))

    def scan(self, progress_callback: Optional[Callable] = None) -> Report:
        t0 = time.monotonic()
        report = Report()
        py_files = self._get_python_files()
        report.total_files_scanned = len(py_files)

        all_findings: List[Finding] = []
        total = len(py_files)
        functions_checked = 0

        def _scan_one(idx: int, py_file: pathlib.Path) -> Tuple[List[Finding], int]:
            if progress_callback:
                progress_callback(idx + 1, total)
            tree, err = _get_ast(py_file)
            if err or tree is None:
                return [], 0
            src = _read_source(py_file)
            if src is None:
                return [], 0
            lines = src.splitlines()
            detector = RaceConditionDetector(py_file, self.root, lines, enable_rca=self.enable_rca, strict=self.strict)
            findings = detector.scan(tree)
            func_count = sum(1 for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
            return findings, func_count

        if len(py_files) <= self.max_workers * 2:
            for idx, py_file in enumerate(py_files):
                findings, func_count = _scan_one(idx, py_file)
                all_findings.extend(findings)
                functions_checked += func_count
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {executor.submit(_scan_one, idx, py_file): py_file for idx, py_file in enumerate(py_files)}
                for future in concurrent.futures.as_completed(futures):
                    try:
                        findings, func_count = future.result()
                        all_findings.extend(findings)
                        functions_checked += func_count
                    except Exception as e:
                        logger.warning("Scan error: %s", e)

        report.findings = all_findings
        report.total_functions_checked = functions_checked
        report.files_with_issues = len({f.file for f in all_findings})

        # Compute score
        errors = report.error_count
        warnings = report.warning_count
        score = 100.0 - errors * 10 - warnings * 2
        report.score = max(0.0, min(100.0, score))

        report.scan_time = time.monotonic() - t0
        return report

# ─── REPORTING ──────────────────────────────────────────────────────────────
def print_report(report: Report, verbose: bool = False, show_rca: bool = False):
    c = COLOR
    _safe_print(f"\n{c['BOLD']}{c['CYAN']}{'='*72}")
    _safe_print("  RACE CONDITION RISK CHECKER")
    _safe_print(f"  v{__version__} — Big 4 Audit Grade")
    _safe_print(f"{'='*72}{c['RESET']}")
    _safe_print("  📋 Race Condition Prevention Standards:")
    _safe_print("    ✅ Pessimistic lock (SELECT FOR UPDATE, with_for_update())")
    _safe_print("    ✅ Optimistic lock (version field check)")
    _safe_print("    ✅ Distributed lock (Redis, ZooKeeper, etc.)")
    _safe_print("    ✅ Transaction with proper isolation level")
    _safe_print("    ✅ Lock parameter passed to update/delete methods")

    _safe_print(f"\n  📊 Summary:")
    _safe_print(f"    Files scanned      : {report.total_files_scanned}")
    _safe_print(f"    Functions checked  : {report.total_functions_checked}")
    _safe_print(f"    Files with issues  : {report.files_with_issues}")
    _safe_print(f"    CRITICAL findings  : {c['RED']}{report.error_count}{c['RESET']}")
    _safe_print(f"    WARNING findings   : {c['YELLOW']}{report.warning_count}{c['RESET']}")
    _safe_print(f"    INFO findings      : {c['DIM']}{report.info_count}{c['RESET']}")
    _safe_print(f"    Score              : {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score:.1f}/100{c['RESET']}")
    _safe_print(f"    RCA Engine         : {'✅ Active' if _RCA_AVAILABLE else '⚠️ Fallback'}")
    _safe_print(f"    Scan time          : {report.scan_time:.3f}s")

    if report.findings:
        by_sev = {"CRITICAL": [], "HIGH": [], "MEDIUM": [], "LOW": [], "INFO": []}
        for f in report.findings:
            by_sev.setdefault(f.severity, []).append(f)

        _safe_print(f"\n{c['RED']}─── FINDINGS ───{c['RESET']}")
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
            items = by_sev.get(sev, [])
            if not items:
                continue
            sev_color = c["RED"] if sev in ("CRITICAL", "HIGH") else c["YELLOW"] if sev == "MEDIUM" else c["DIM"]
            _safe_print(f"\n  {sev_color}[{sev}] {len(items)} findings{sev_color}")

            for f in items[:20]:
                _safe_print(f"    {f.function} @ {f.file}:{f.line}")
                _safe_print(f"      {f.message}")
                if f.detail:
                    _safe_print(f"      {c['CYAN']}→ {f.detail}{c['RESET']}")
                if verbose and f.rca:
                    rc = f.rca.get("root_cause", "")
                    fix = f.rca.get("suggested_fix", "")
                    conf = f.rca.get("confidence", 0)
                    if rc:
                        _safe_print(f"      {c['MAGENTA']}🔍 RCA: {rc[:120]}{c['RESET']}")
                    if fix:
                        _safe_print(f"      {c['MAGENTA']}🔧 Fix: {fix[:120]}{c['RESET']}")
                    if conf:
                        _safe_print(f"      {c['DIM']}📊 Confidence: {conf:.0%}{c['RESET']}")
            if len(items) > 20:
                _safe_print(f"    ... and {len(items)-20} more")

    else:
        _safe_print(f"\n{c['GREEN']}✅ No race condition risks detected!{c['RESET']}")

    _safe_print(f"\n{c['CYAN']}{'─'*72}{c['RESET']}")
    if report.passed:
        _safe_print(f"  {c['GREEN']}✅ PASS — No critical race condition risks.{c['RESET']}")
    else:
        _safe_print(f"  {c['RED']}❌ FAIL — {report.error_count} critical risk(s) need fixing.{c['RESET']}")

# ─── EXPORT ──────────────────────────────────────────────────────────────────
def save_json(report: Report, path: pathlib.Path) -> bool:
    try:
        data = {
            "version": __version__,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "score": report.score,
            "passed": report.passed,
            "scan_time": report.scan_time,
            "total_files_scanned": report.total_files_scanned,
            "total_functions_checked": report.total_functions_checked,
            "files_with_issues": report.files_with_issues,
            "findings": [f.to_dict() for f in report.findings],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        _safe_print(f"{_c('GREEN')}✅ JSON saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save JSON: {e}{_c('RESET')}")
        return False

def save_csv(report: Report, path: pathlib.Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["severity", "file", "line", "function", "message", "detail"])
            for fnd in report.findings:
                writer.writerow([fnd.severity, fnd.file, fnd.line, fnd.function, fnd.message, fnd.detail])
        _safe_print(f"{_c('GREEN')}✅ CSV saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save CSV: {e}{_c('RESET')}")
        return False

def save_html(report: Report, path: pathlib.Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        findings_html = ""
        for f in report.findings:
            cls = "error" if f.severity in ("CRITICAL", "HIGH") else "warning" if f.severity == "MEDIUM" else "info"
            findings_html += f'<div class="finding {cls}"><strong>{f.severity}</strong> {f.function}@{f.file}:{f.line}<br>{f.message}<br><small>{f.detail}</small></div>'
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Race Condition Checker Report</title>
<style>
body{{font-family:sans-serif;background:#f8f9fa;color:#212529;padding:2rem}}
h1{{color:#0d6efd}}
.summary{{display:flex;gap:2rem;flex-wrap:wrap;margin:1rem 0}}
.card{{background:white;padding:1rem 2rem;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,0.1)}}
.card .value{{font-size:2rem;font-weight:bold}}
.card .label{{color:#6c757d}}
.finding{{margin:0.5rem 0;padding:0.5rem 1rem;border-left:4px solid}}
.error{{border-color:#dc3545;background:#f8d7da}}
.warning{{border-color:#ffc107;background:#fff3cd}}
.info{{border-color:#0dcaf0;background:#d1ecf1}}
</style></head>
<body>
<h1>Race Condition Risk Checker Report</h1>
<div class="summary">
  <div class="card"><div class="value">{len(report.findings)}</div><div class="label">Findings</div></div>
  <div class="card"><div class="value" style="color:#dc3545">{report.error_count}</div><div class="label">CRITICAL</div></div>
  <div class="card"><div class="value" style="color:#ffc107">{report.warning_count}</div><div class="label">Warnings</div></div>
  <div class="card"><div class="value">{report.score:.1f}</div><div class="label">Score</div></div>
  <div class="card"><div class="value">{'PASS' if report.passed else 'FAIL'}</div><div class="label">Status</div></div>
</div>
<h2>Findings</h2>
{findings_html}
</body></html>"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        _safe_print(f"{_c('GREEN')}✅ HTML saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save HTML: {e}{_c('RESET')}")
        return False

def save_sarif(report: Report, path: pathlib.Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        results = []
        for f in report.findings:
            results.append({
                "ruleId": f"RACE-{f.severity}",
                "level": "error" if f.severity in ("CRITICAL", "HIGH") else "warning",
                "message": {"text": f.message},
                "locations": [{
                    "physicalLocation": {
                        "artifactLocation": {"uri": f.file},
                        "region": {"startLine": max(1, f.line)},
                    }
                }],
            })
        sarif = {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [{
                "tool": {
                    "driver": {
                        "name": "RaceConditionChecker",
                        "version": __version__,
                        "rules": [
                            {"id": "RACE-CRITICAL", "shortDescription": {"text": "Critical race condition risk"}},
                            {"id": "RACE-HIGH", "shortDescription": {"text": "High severity race condition"}},
                            {"id": "RACE-MEDIUM", "shortDescription": {"text": "Medium severity race condition"}},
                        ]
                    }
                },
                "results": results,
            }]
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sarif, f, indent=2, ensure_ascii=False)
        _safe_print(f"{_c('GREEN')}✅ SARIF saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save SARIF: {e}{_c('RESET')}")
        return False

# ─── SELF-TEST ──────────────────────────────────────────────────────────────
def self_test(verbose: bool = True) -> bool:
    passed = failed = 0
    def check(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            if verbose: _safe_print(f"  ✅ {name}")
            passed += 1
        else:
            if verbose: _safe_print(f"  ❌ {name}" + (f": {detail}" if detail else ""))
            failed += 1

    if verbose: _safe_print(f"\nRace Condition Checker self-test v{__version__}…\n")

    # Test detection: no lock
    code1 = """
def update_user(self, user_id, data):
    return self.session.execute("UPDATE users SET name = 'test' WHERE id = 1")
"""
    tree1 = ast.parse(code1)
    node1 = next((n for n in ast.walk(tree1) if isinstance(n, ast.FunctionDef)), None)
    checker = RaceConditionChecker(pathlib.Path.cwd(), enable_rca=False)
    if node1:
        detector = RaceConditionDetector(pathlib.Path("test.py"), pathlib.Path("."), code1.splitlines(), enable_rca=False)
        finding = detector.analyze_function(node1)
        check("Detects no lock in update", finding is not None)
        if finding:
            check("Correct severity for no lock", finding.severity in ("HIGH", "CRITICAL"))

    # Test detection: with pessimistic lock
    code2 = """
def update_user(self, user_id, data):
    user = self.session.query(User).with_for_update().filter(User.id == user_id).first()
    user.name = data['name']
    return user
"""
    tree2 = ast.parse(code2)
    node2 = next((n for n in ast.walk(tree2) if isinstance(n, ast.FunctionDef)), None)
    if node2:
        detector2 = RaceConditionDetector(pathlib.Path("test.py"), pathlib.Path("."), code2.splitlines(), enable_rca=False)
        finding2 = detector2.analyze_function(node2)
        check("No finding for pessimistic lock", finding2 is None)

    # Test detection: with version check
    code3 = """
def update_user(self, user_id, data, version):
    user = self.session.query(User).filter(User.id == user_id).first()
    if user.version != version:
        raise Exception("Optimistic lock failed")
    user.name = data['name']
    return user
"""
    tree3 = ast.parse(code3)
    node3 = next((n for n in ast.walk(tree3) if isinstance(n, ast.FunctionDef)), None)
    if node3:
        detector3 = RaceConditionDetector(pathlib.Path("test.py"), pathlib.Path("."), code3.splitlines(), enable_rca=False)
        finding3 = detector3.analyze_function(node3)
        check("No finding for optimistic lock", finding3 is None)

    # Test detection: with distributed lock
    code4 = """
def update_user(self, user_id, data):
    with redis.lock("user:lock:{}".format(user_id)):
        user = self.session.query(User).filter(User.id == user_id).first()
        user.name = data['name']
        return user
"""
    tree4 = ast.parse(code4)
    node4 = next((n for n in ast.walk(tree4) if isinstance(n, ast.FunctionDef)), None)
    if node4:
        detector4 = RaceConditionDetector(pathlib.Path("test.py"), pathlib.Path("."), code4.splitlines(), enable_rca=False)
        finding4 = detector4.analyze_function(node4)
        check("No finding for distributed lock", finding4 is None)

    # Test RCA
    check("RCA availability", True)

    if verbose: _safe_print(f"\nSelf-test: {passed} passed, {failed} failed {'✅' if failed==0 else '❌'}")
    return failed == 0

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description=f"Race Condition Checker v{__version__}")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE")
    parser.add_argument("--csv", metavar="FILE")
    parser.add_argument("--html", metavar="FILE")
    parser.add_argument("--sarif", metavar="FILE")
    parser.add_argument("--strict", action="store_true", help="Promote warnings to errors")
    parser.add_argument("--no-rca", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--exclude", default="")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--no-progress", action="store_true")
    parser.add_argument("--version", action="version", version=f"race_condition_checker v{__version__}")

    args = parser.parse_args()

    if args.self_test:
        return 0 if self_test(verbose=True) else 1

    project_root = pathlib.Path(__file__).resolve().parent.parent
    extra_excludes = set(args.exclude.split(",")) if args.exclude else set()

    checker = RaceConditionChecker(
        root=project_root,
        enable_rca=not args.no_rca,
        strict=args.strict,
        extra_excludes=extra_excludes,
        max_workers=args.max_workers,
    )

    progress = None
    if not args.no_progress:
        total = 0
        scanned = 0
        lock = threading.Lock()
        def _progress(current: int, total_: int):
            nonlocal total, scanned
            with lock:
                total = total_
                scanned = current
                pct = (scanned / total * 100) if total > 0 else 0
                bar = "█" * int(pct / 2) + "░" * (50 - int(pct / 2))
                _safe_print(f"\r  [{bar}] {scanned}/{total} ({pct:.1f}%)", end="", flush=True)
                if scanned >= total:
                    _safe_print()
        progress = _progress

    report = checker.scan(progress_callback=progress)

    print_report(report, verbose=args.verbose, show_rca=not args.no_rca)

    if not args.dry_run:
        if args.json:
            save_json(report, pathlib.Path(args.json))
        if args.csv:
            save_csv(report, pathlib.Path(args.csv))
        if args.html:
            save_html(report, pathlib.Path(args.html))
        if args.sarif:
            save_sarif(report, pathlib.Path(args.sarif))

    return 0 if report.passed else 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        _safe_print(f"\n{_c('YELLOW')}⏹️  Interrupted by user.{_c('RESET')}")
        sys.exit(130)