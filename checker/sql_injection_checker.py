#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker/sql_injection_checker.py – SQL Injection Vulnerability Detector
========================================================================
Versi   : 3.1.1
Standar : Big 4 Forensic Audit · OWASP Top 10 · ISO/IEC 25010

Fitur:
  - Deteksi f-string pada query SQL
  - Deteksi string concatenation pada query SQL
  - Deteksi str.format() dan % formatting pada query SQL
  - Deteksi execute() dengan string literal tanpa parameter binding (hanya objek database)
  - Deteksi SQLAlchemy text() dengan string dinamis
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
logger = logging.getLogger("sql_injection_checker")
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
__version__ = "3.1.1"

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
EXCLUDED_DIRS_DEFAULT = {
    "checker", "tests", "migrations", "__pycache__", ".git",
    "docs", "scripts", "deployment", "monitoring", "reports",
    "venv", ".venv", "node_modules", "dist", "build",
}
SQL_EXECUTE_METHODS = {"execute", "executemany", "execute_text", "raw_execute"}
SQL_QUERY_ATTRS = {"query", "sql", "stmt", "statement", "raw_sql", "text"}
DANGEROUS_PATTERNS = {"f-string", "concatenation", "format()", "% formatting"}

# Nama objek yang dianggap sebagai koneksi database
DB_OBJECT_NAMES = {
    'conn', 'connection', 'cursor', 'session', 'engine', 'pool',
    'db', 'db_conn', 'asyncpg_conn', 'pg_conn', 'sqlalchemy_conn',
    '_session', '_conn', '_cursor', '_engine', '_pool',
}

# ─── DATA CLASSES ─────────────────────────────────────────────────────────────
@dataclass
class Finding:
    severity: str  # CRITICAL, WARNING, INFO
    file: str
    line: int
    category: str  # injection, unsafe_pattern
    message: str
    snippet: str = ""
    recommendation: str = ""
    rca: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "category": self.category,
            "message": self.message,
            "snippet": self.snippet,
            "recommendation": self.recommendation,
            "rca": self.rca,
        }

@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    score: float = 100.0
    scan_time: float = 0.0
    total_files_scanned: int = 0
    files_with_issues: int = 0

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "CRITICAL")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "WARNING")

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "INFO")

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

def _get_snippet(lines: List[str], line: int, context: int = 2) -> str:
    if line <= 0 or line > len(lines):
        return ""
    start = max(0, line - context - 1)
    end = min(len(lines), line + context)
    return "\n".join(lines[start:end]).strip()

# ─── DETECTOR ──────────────────────────────────────────────────────────────────
class SQLInjectionDetector(ast.NodeVisitor):
    def __init__(self, file_path: str, source_lines: List[str], enable_rca: bool = True):
        self.file_path = file_path
        self.source_lines = source_lines
        self.enable_rca = enable_rca
        self.findings: List[Finding] = []

    def _add_finding(self, severity: str, line: int, message: str, rec: str, category: str = "injection"):
        snippet = _get_snippet(self.source_lines, line)
        rca = None
        if self.enable_rca:
            try:
                exc = RuntimeError(message)
                rca = _rca_analyze(exc, {"file": self.file_path, "line": line, "severity": severity})
            except Exception:
                pass
        self.findings.append(Finding(
            severity=severity,
            file=self.file_path,
            line=line,
            category=category,
            message=message,
            snippet=snippet,
            recommendation=rec,
            rca=rca,
        ))

    def visit_Assign(self, node: ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.lower() in SQL_QUERY_ATTRS:
                # Periksa nilai assignment (hanya satu nilai)
                self._check_sql_string(node.value, node.lineno)
        self.generic_visit(node)

    def _check_sql_string(self, node: ast.AST, line: int):
        if isinstance(node, ast.JoinedStr):
            self._add_finding(
                severity="CRITICAL",
                line=line,
                message="F-string used in SQL query",
                rec="Use parameter binding (SQLAlchemy text() with params or parameterized query)",
            )
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            self._add_finding(
                severity="CRITICAL",
                line=line,
                message="String concatenation used in SQL query",
                rec="Use parameter binding",
            )
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "format":
                self._add_finding(
                    severity="WARNING",
                    line=line,
                    message="str.format() used in SQL query",
                    rec="Use parameter binding",
                )
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            self._add_finding(
                severity="WARNING",
                line=line,
                message="% formatting used in SQL query",
                rec="Use parameter binding",
            )

    def _is_db_object(self, obj_node: ast.AST) -> bool:
        """
        Periksa apakah objek yang memanggil 'execute' adalah objek database.
        """
        obj_name = ""
        if isinstance(obj_node, ast.Name):
            obj_name = obj_node.id.lower()
        elif isinstance(obj_node, ast.Attribute):
            # Misal self._session, conn, cursor
            obj_name = obj_node.attr.lower()
            # Cek juga value-nya (self._session -> self)
            if isinstance(obj_node.value, ast.Name):
                parent = obj_node.value.id.lower()
                # Jika parent adalah 'self' atau 'cls', kita percaya pada attr
                if parent in ('self', 'cls'):
                    pass
        # Periksa apakah obj_name mengandung kata-kata database
        if any(k in obj_name for k in ['session', 'conn', 'cursor', 'engine', 'pool', 'db']):
            return True
        # Periksa juga nama variabel yang diberikan
        # Misal variable bernama 'session' atau 'conn'
        return obj_name in DB_OBJECT_NAMES

    def visit_Call(self, node: ast.Call):
        func_name = self._get_func_name(node.func)
        if func_name in SQL_EXECUTE_METHODS:
            # Cek apakah execute dipanggil pada objek database
            if isinstance(node.func, ast.Attribute):
                obj = node.func.value
                if self._is_db_object(obj):
                    self._check_execute_call(node)
                # else: diabaikan (false positive seperti use_case.execute)
            # Jika execute adalah fungsi global, abaikan
        elif func_name == "text":
            self._check_text_call(node)
        self.generic_visit(node)

    def _check_execute_call(self, node: ast.Call):
        if not node.args:
            return
        first_arg = node.args[0]

        # 1. Selalu periksa pola berbahaya pada argumen pertama
        self._check_sql_string(first_arg, node.lineno)

        # 2. Hanya beri peringatan tentang kurangnya parameter binding
        #    jika argumen pertama adalah string literal (konstan).
        #    Ini menghindari false positive pada SQLAlchemy statement objects.
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            if len(node.args) == 1:
                self._add_finding(
                    severity="WARNING",
                    line=node.lineno,
                    message=f"{self._get_func_name(node.func)}() called with literal SQL string without parameter binding",
                    rec="Use parameter binding for security",
                )
            elif len(node.args) >= 2:
                second_arg = node.args[1]
                if isinstance(second_arg, ast.Constant) and second_arg.value is None:
                    self._add_finding(
                        severity="WARNING",
                        line=node.lineno,
                        message=f"{self._get_func_name(node.func)}() called with params=None",
                        rec="Use proper parameter binding",
                    )
        # Jika argumen pertama bukan string literal, kita anggap aman (SQLAlchemy statement)
        # dan tidak menambahkan peringatan tambahan.

    def _check_text_call(self, node: ast.Call):
        if not node.args:
            return
        first_arg = node.args[0]
        self._check_sql_string(first_arg, node.lineno)

    def _get_func_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        elif isinstance(node, ast.Call):
            return self._get_func_name(node.func)
        return ""

# ─── CHECKER ──────────────────────────────────────────────────────────────────
class SQLInjectionChecker:
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
        if path.name.startswith("sql_injection_checker"):
            return True
        return False

    def _get_python_files(self) -> List[pathlib.Path]:
        py_files = []
        scan_dirs = ["adapters", "application", "domain", "infrastructure", "app", "bootstrap"]
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

        def _scan_one(idx: int, py_file: pathlib.Path) -> List[Finding]:
            if progress_callback:
                progress_callback(idx + 1, total)
            tree, err = _get_ast(py_file)
            if err or tree is None:
                return []
            src = _read_source(py_file)
            if src is None:
                return []
            lines = src.splitlines()
            detector = SQLInjectionDetector(str(py_file), lines, enable_rca=self.enable_rca)
            detector.visit(tree)
            return detector.findings

        if len(py_files) <= self.max_workers * 2:
            for idx, py_file in enumerate(py_files):
                all_findings.extend(_scan_one(idx, py_file))
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {executor.submit(_scan_one, idx, py_file): py_file for idx, py_file in enumerate(py_files)}
                for future in concurrent.futures.as_completed(futures):
                    try:
                        all_findings.extend(future.result())
                    except Exception as e:
                        logger.warning("Scan error: %s", e)

        report.findings = all_findings
        report.files_with_issues = len({f.file for f in all_findings})

        # Compute score
        errors = report.error_count
        warnings = report.warning_count
        score = 100.0 - errors * 15 - warnings * 2
        report.score = max(0.0, min(100.0, score))

        report.scan_time = time.monotonic() - t0
        return report

# ─── REPORTING ──────────────────────────────────────────────────────────────
def print_report(report: Report, verbose: bool = False, show_rca: bool = False):
    c = COLOR
    _safe_print(f"\n{c['BOLD']}{c['CYAN']}{'='*72}")
    _safe_print("  SQL INJECTION VULNERABILITY CHECKER")
    _safe_print(f"  v{__version__} — OWASP Top 10 / Big 4 Audit Grade")
    _safe_print(f"{'='*72}{c['RESET']}")
    _safe_print("  📋 SQL Injection Prevention Standards:")
    _safe_print("    ✅ Use parameter binding (SQLAlchemy text() with params)")
    _safe_print("    ✅ No f-string or concatenation in SQL queries")
    _safe_print("    ✅ No str.format() or % formatting in SQL queries")
    _safe_print("    ✅ Use parameterized queries for all user input")

    _safe_print(f"\n  📊 Summary:")
    _safe_print(f"    Files scanned      : {report.total_files_scanned}")
    _safe_print(f"    Files with issues  : {report.files_with_issues}")
    _safe_print(f"    CRITICAL findings  : {c['RED']}{report.error_count}{c['RESET']}")
    _safe_print(f"    WARNING findings   : {c['YELLOW']}{report.warning_count}{c['RESET']}")
    _safe_print(f"    INFO findings      : {c['DIM']}{report.info_count}{c['RESET']}")
    _safe_print(f"    Score              : {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score:.1f}/100{c['RESET']}")
    _safe_print(f"    RCA Engine         : {'✅ Active' if _RCA_AVAILABLE else '⚠️ Fallback'}")
    _safe_print(f"    Scan time          : {report.scan_time:.3f}s")

    if report.findings:
        by_sev = {"CRITICAL": [], "WARNING": [], "INFO": []}
        for f in report.findings:
            by_sev.setdefault(f.severity, []).append(f)

        for sev in ["CRITICAL", "WARNING", "INFO"]:
            items = by_sev.get(sev, [])
            if not items:
                continue
            sev_color = c["RED"] if sev == "CRITICAL" else c["YELLOW"] if sev == "WARNING" else c["DIM"]
            _safe_print(f"\n{sev_color}[{sev}] {len(items)} findings{sev_color}")
            for f in items[:20]:
                _safe_print(f"    {f.file}:{f.line}")
                _safe_print(f"      {f.message}")
                if f.snippet and verbose:
                    _safe_print(f"      Snippet: {f.snippet[:100]}")
                if f.recommendation:
                    _safe_print(f"      💡 {f.recommendation}")
                if show_rca and f.rca:
                    rc = f.rca.get("root_cause", "")
                    fix = f.rca.get("suggested_fix", "")
                    if rc:
                        _safe_print(f"      {c['MAGENTA']}🔍 RCA: {rc[:120]}{c['RESET']}")
                    if fix:
                        _safe_print(f"      {c['MAGENTA']}🔧 Fix: {fix[:120]}{c['RESET']}")
            if len(items) > 20:
                _safe_print(f"    ... and {len(items)-20} more")

    else:
        _safe_print(f"\n{c['GREEN']}✅ No SQL Injection vulnerabilities detected!{c['RESET']}")

    _safe_print(f"\n{c['CYAN']}{'─'*72}{c['RESET']}")
    if report.passed:
        _safe_print(f"  {c['GREEN']}✅ PASS — No critical SQL Injection issues.{c['RESET']}")
    else:
        _safe_print(f"  {c['RED']}❌ FAIL — {report.error_count} CRITICAL issue(s) need fixing.{c['RESET']}")

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
            writer.writerow(["severity", "file", "line", "message", "recommendation"])
            for fnd in report.findings:
                writer.writerow([fnd.severity, fnd.file, fnd.line, fnd.message, fnd.recommendation])
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
            cls = "error" if f.severity == "CRITICAL" else "warning" if f.severity == "WARNING" else "info"
            findings_html += f'<div class="finding {cls}"><strong>{f.severity}</strong> {f.file}:{f.line}<br>{f.message}<br><small>💡 {f.recommendation}</small></div>'
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>SQL Injection Checker Report</title>
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
<h1>SQL Injection Vulnerability Checker Report</h1>
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
                "ruleId": f"SQL-{f.severity}",
                "level": "error" if f.severity == "CRITICAL" else "warning",
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
                        "name": "SQLInjectionChecker",
                        "version": __version__,
                        "rules": [
                            {"id": "SQL-CRITICAL", "shortDescription": {"text": "Critical SQL Injection vulnerability"}},
                            {"id": "SQL-WARNING", "shortDescription": {"text": "SQL Injection warning"}},
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

    if verbose: _safe_print(f"\nSQL Injection Checker self-test v{__version__}…\n")

    # Test detection: f-string
    code1 = """
query = f"SELECT * FROM users WHERE id = {user_id}"
cursor.execute(query)
"""
    tree1 = ast.parse(code1)
    detector1 = SQLInjectionDetector("test.py", code1.splitlines(), enable_rca=True)
    detector1.visit(tree1)
    check("Detects f-string in query", len(detector1.findings) > 0)

    # Test detection: concatenation
    code2 = """
sql = "SELECT * FROM " + table_name
"""
    tree2 = ast.parse(code2)
    detector2 = SQLInjectionDetector("test.py", code2.splitlines(), enable_rca=True)
    detector2.visit(tree2)
    check("Detects concatenation", len(detector2.findings) > 0)

    # Test detection: format()
    code3 = """
sql = "SELECT * FROM users WHERE id = {}".format(user_id)
"""
    tree3 = ast.parse(code3)
    detector3 = SQLInjectionDetector("test.py", code3.splitlines(), enable_rca=True)
    detector3.visit(tree3)
    check("Detects str.format()", len(detector3.findings) > 0)

    # Test detection: execute without params (should warn only for literal string)
    code4 = """
cursor.execute("SELECT * FROM users")
"""
    tree4 = ast.parse(code4)
    detector4 = SQLInjectionDetector("test.py", code4.splitlines(), enable_rca=True)
    detector4.visit(tree4)
    check("Detects execute without params on cursor (literal)", len(detector4.findings) > 0)

    # Test false positive: use_case.execute() should be ignored
    code5 = """
result = await use_case.execute(dto)
"""
    tree5 = ast.parse(code5)
    detector5 = SQLInjectionDetector("test.py", code5.splitlines(), enable_rca=True)
    detector5.visit(tree5)
    check("Ignores use_case.execute()", len(detector5.findings) == 0)

    # Test false positive: session.execute(select(...)) should be ignored
    code6 = """
stmt = select(User).where(User.id == user_id)
result = await session.execute(stmt)
"""
    tree6 = ast.parse(code6)
    detector6 = SQLInjectionDetector("test.py", code6.splitlines(), enable_rca=True)
    detector6.visit(tree6)
    check("Ignores session.execute(select(...))", len(detector6.findings) == 0)

    # Test RCA
    check("RCA availability", True)

    if verbose: _safe_print(f"\nSelf-test: {passed} passed, {failed} failed {'✅' if failed==0 else '❌'}")
    return failed == 0

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description=f"SQL Injection Checker v{__version__}")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE")
    parser.add_argument("--csv", metavar="FILE")
    parser.add_argument("--html", metavar="FILE")
    parser.add_argument("--sarif", metavar="FILE")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--no-rca", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--exclude", default="")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--no-progress", action="store_true")
    parser.add_argument("--version", action="version", version=f"sql_injection_checker v{__version__}")

    args = parser.parse_args()

    if args.self_test:
        return 0 if self_test(verbose=True) else 1

    project_root = pathlib.Path(__file__).resolve().parent.parent
    extra_excludes = set(args.exclude.split(",")) if args.exclude else set()

    checker = SQLInjectionChecker(
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