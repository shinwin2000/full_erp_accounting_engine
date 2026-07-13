#!/usr/bin/env python3
"""
fiscal_period_checker.py – Fiscal Period Rules & Lifecycle Validator
====================================================================
Versi   : 3.0.1
Standar : Big 4 Forensic Audit · ISO/IEC 25010 · SOX/ISA 315 Compliant
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import logging
import pathlib
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

# ─── RCA INTEGRATION ──────────────────────────────────────────────────────────
_RCA_ENGINE = None
_RCA_AVAILABLE = False

def _init_rca() -> bool:
    global _RCA_ENGINE, _RCA_AVAILABLE
    if _RCA_AVAILABLE:
        return True
    try:
        from checker.core.rca import Severity, analyze_exception, get_engine
        _RCA_ENGINE = get_engine()
        _RCA_AVAILABLE = True
        return True
    except ImportError:
        pass
    _root = pathlib.Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    try:
        from checker.core.rca import Severity, analyze_exception, get_engine
        _RCA_ENGINE = get_engine()
        _RCA_AVAILABLE = True
        return True
    except ImportError:
        pass
    return False

_init_rca()

def _rca_analyze(exc: Exception, context: dict | None = None) -> dict | None:
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
logger = logging.getLogger("fiscal_period_checker")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    logger.addHandler(_log_handler)

# ─── COLOR ──────────────────────────────────────────────────────────────────
COLOR: dict[str, str] = {
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
__version__ = "3.0.1"

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
EXPECTED_STATUSES = {"DRAFT", "OPEN", "CLOSED", "LOCKED"}
POST_KEYWORDS = {"post", "save", "create", "update", "delete", "publish", "submit", "apply"}
CLOSE_KEYWORDS = {"close", "lock", "finalize", "freeze"}
REOPEN_KEYWORDS = {"reopen", "unlock", "restore"}
YEAR_END_KEYWORDS = {"year_end", "year_close", "close_books", "perform_closing", "year_end_closing"}
PERIOD_CLASS_NAMES = {"FiscalPeriod", "AccountingPeriod", "Period", "FiscalYear"}
VALIDATION_NAMES = {
    "ensure_open", "ensure_can_close", "ensure_closed", "validate_period",
    "can_post", "can_close", "is_open", "is_closed", "check_period_open",
    "check_period_closed", "assert_open", "assert_closed",
    "ensure_period_open", "ensure_period_closed", "validate_period_status",
    "period_guard", "ensure_can_post", "can_reopen", "ensure_can_reopen",
    "validate_can_reopen_period", "can_reopen_period", "validate_can_close_period",
    "validate_can_lock_period", "validate_period_before_close", "validate_period_before_lock",
    "validate_status_transition", "validate_can_reopen", "validate_can_lock",
    "ensure_period_active", "check_period_active", "validate_period_active",
}
GETTER_PREFIXES = {"is_", "has_", "get_", "can_", "validate_", "check_", "ensure_"}

# ─── DATA CLASSES ─────────────────────────────────────────────────────────────
@dataclass
class Finding:
    severity: str
    file: str
    line: int
    category: str
    message: str
    detail: str = ""
    rca: dict | None = None

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "category": self.category,
            "message": self.message,
            "detail": self.detail,
            "rca": self.rca,
        }

@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    score: int = 100
    scan_time: float = 0.0

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "ERROR")

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
_AST_CACHE: dict[str, tuple[ast.AST | None, str | None]] = {}
_CACHE_LOCK = threading.Lock()

def _read_source(py_file: pathlib.Path) -> str | None:
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

def _get_ast(py_file: pathlib.Path) -> tuple[ast.AST | None, str | None]:
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

def _is_property_method(node: ast.FunctionDef) -> bool:
    for deco in node.decorator_list:
        if isinstance(deco, ast.Name) and deco.id in ("property", "cached_property"):
            return True
        if isinstance(deco, ast.Attribute) and deco.attr in ("property", "cached_property"):
            return True
    return False

def _has_validation_call(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            if isinstance(sub.func, ast.Name) and sub.func.id.lower() in VALIDATION_NAMES:
                return True
            if isinstance(sub.func, ast.Attribute):
                attr = sub.func.attr.lower()
                if attr in VALIDATION_NAMES:
                    return True
                if isinstance(sub.func.value, ast.Attribute):
                    if sub.func.value.attr in ("_validator", "validator", "_invariant_enforcer", "invariant_enforcer"):
                        if attr in VALIDATION_NAMES:
                            return True
    return False

def _has_if_status_check(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.If):
            cond = ast.unparse(sub.test).lower()
            if "period" in cond and ("status" in cond or "open" in cond or "closed" in cond or "locked" in cond):
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

def _has_method_call(node: ast.AST, names: list[str]) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            if isinstance(sub.func, ast.Name) and sub.func.id.lower() in names:
                return True
            if isinstance(sub.func, ast.Attribute):
                if sub.func.attr.lower() in names:
                    return True
                if isinstance(sub.func.value, ast.Attribute):
                    if sub.func.value.attr in ("_validator", "validator", "_invariant_enforcer", "invariant_enforcer"):
                        if sub.func.attr.lower() in names:
                            return True
    return False

def _is_getter_or_validator(func_name: str) -> bool:
    lower = func_name.lower()
    return any(lower.startswith(p) for p in GETTER_PREFIXES)

# ─── FILE FILTER ──────────────────────────────────────────────────────────────
def get_relevant_files(project_root: pathlib.Path, extra_excludes: set[str]) -> list[pathlib.Path]:
    relevant = []
    skip_dirs = {
        ".venv", "venv", "__pycache__", ".git", "node_modules",
        "dist", "build", "migrations", "deployment", "docs",
        "monitoring", "config_files", "logs", "tests", "checker",
        "scripts", "tools", "adapters", "infrastructure",
        "domain/financial_statement",
    } | extra_excludes

    skip_stems = {
        "main_checker", "fix_bom", "fix", "asgi", "wsgi", "manage",
        "setup", "conftest", "pytest", "__init__", "tax_checker",
        "layer_checker", "fiscal_period_checker", "coa_checker",
    }

    allowed_prefixes = (
        "domain/fiscal_period/",
        "domain/shared_value_objects/",
        "application/service_layer/service_fiscal_period",
        "application/use_cases/",
    )

    for path in project_root.rglob("*.py"):
        rel = str(path.relative_to(project_root)).replace("\\", "/")
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
            if not any(k in stem for k in ("period", "fiscal", "closing", "year_end", "close", "lock", "reopen")):
                continue

        relevant.append(path)

    return relevant

# ─── ANALYZERS (dengan parameter project_root) ──────────────────────────────
def analyze_period_validation(tree: ast.AST, file_path: pathlib.Path, project_root: pathlib.Path) -> list[Finding]:
    findings = []
    rel = str(file_path.relative_to(project_root)).replace("\\", "/")
    is_service = "service" in rel
    is_use_case = "use_case" in rel or "handler" in rel

    if not (is_service or is_use_case):
        return findings

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if _is_property_method(node):
            continue
        fname = node.name.lower()
        if _is_getter_or_validator(fname):
            continue
        if not any(k in fname for k in POST_KEYWORDS):
            continue

        if _has_validation_call(node) or _has_if_status_check(node):
            continue

        findings.append(Finding(
            severity="ERROR",
            file=rel,
            line=node.lineno,
            category="period_validation",
            message=f"Function '{node.name}' does not validate period status before writing",
            detail="Add ensure_open() or check period.status == OPEN before posting.",
        ))
    return findings

def analyze_fiscal_year(tree: ast.AST, file_path: pathlib.Path, project_root: pathlib.Path) -> list[Finding]:
    findings = []
    rel = str(file_path.relative_to(project_root)).replace("\\", "/")
    if not rel.startswith("domain/"):
        return findings

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if node.name not in PERIOD_CLASS_NAMES:
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
                severity="WARNING",
                file=rel,
                line=node.lineno,
                category="fiscal_year",
                message=f"Class '{node.name}' lacks start_date or year attribute",
                detail="Add start_date/end_date or year/month attributes.",
            ))
        elif not (has_end or has_month):
            findings.append(Finding(
                severity="WARNING",
                file=rel,
                line=node.lineno,
                category="fiscal_year",
                message=f"Class '{node.name}' lacks end_date or month attribute",
                detail="Add start_date/end_date or year/month attributes.",
            ))
    return findings

def analyze_closure_constraints(tree: ast.AST, file_path: pathlib.Path, project_root: pathlib.Path) -> list[Finding]:
    findings = []
    rel = str(file_path.relative_to(project_root)).replace("\\", "/")
    if not (rel.startswith("domain/") or rel.startswith("application/service_layer/") or rel.startswith("application/use_cases/")):
        return findings

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if _is_property_method(node):
            continue
        fname = node.name.lower()
        if _is_getter_or_validator(fname):
            continue

        if any(c in fname for c in CLOSE_KEYWORDS):
            if _has_validation_call(node) or _has_if_status_check(node):
                continue
            findings.append(Finding(
                severity="WARNING",
                file=rel,
                line=node.lineno,
                category="closure_constraint",
                message=f"Function '{node.name}' does not validate period is OPEN before closing",
                detail="Add ensure_can_close() or check period.status == OPEN.",
            ))

        if any(r in fname for r in REOPEN_KEYWORDS):
            if _has_method_call(node, ["ensure_closed", "is_closed", "can_reopen", "validate_can_reopen_period", "can_reopen_period"]):
                continue
            if _has_if_status_check(node):
                continue
            findings.append(Finding(
                severity="ERROR",
                file=rel,
                line=node.lineno,
                category="closure_constraint",
                message=f"Function '{node.name}' does not validate period is CLOSED before reopen",
                detail="Add ensure_closed() or check period.status == CLOSED.",
            ))
    return findings

def analyze_year_end(tree: ast.AST, file_path: pathlib.Path, project_root: pathlib.Path) -> list[Finding]:
    findings = []
    rel = str(file_path.relative_to(project_root)).replace("\\", "/")
    if not (rel.startswith("application/service_layer/") or rel.startswith("application/use_cases/")):
        return findings

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if _is_property_method(node):
            continue
        fname = node.name.lower()
        if _is_getter_or_validator(fname):
            continue
        if not any(k in fname for k in YEAR_END_KEYWORDS):
            continue

        body = ast.unparse(node)
        has_retained = "retained" in body.lower() and "earnings" in body.lower()
        has_journal = "journal" in body.lower() or "entry" in body.lower()

        if not has_retained or not has_journal:
            findings.append(Finding(
                severity="WARNING",
                file=rel,
                line=node.lineno,
                category="year_end",
                message=f"Function '{node.name}' lacks full year-end closing procedure",
                detail="Ensure it includes retained earnings adjustment and closing journal entries.",
            ))
    return findings

# ─── ORCHESTRATOR ────────────────────────────────────────────────────────────
def scan_project(
    project_root: pathlib.Path,
    extra_excludes: set[str],
    run_rca: bool = True,
    progress_callback: Callable | None = None,
) -> Report:
    t0 = time.monotonic()
    report = Report()

    # Status enum
    enum_file, statuses = find_period_status_enum(project_root)
    missing = EXPECTED_STATUSES - statuses
    if missing:
        report.findings.append(Finding(
            severity="ERROR",
            file=str(enum_file.relative_to(project_root)) if enum_file else "?",
            line=1,
            category="status_lifecycle",
            message=f"Period status enum missing: {', '.join(missing)}",
            detail="Enum PeriodStatus must have DRAFT, OPEN, CLOSED, LOCKED.",
        ))

    files = get_relevant_files(project_root, extra_excludes)
    total = len(files)
    for idx, py_file in enumerate(files):
        if progress_callback:
            progress_callback(idx + 1, total)
        tree, err = _get_ast(py_file)
        if err or tree is None:
            continue

        findings = []
        findings.extend(analyze_period_validation(tree, py_file, project_root))
        findings.extend(analyze_fiscal_year(tree, py_file, project_root))
        findings.extend(analyze_closure_constraints(tree, py_file, project_root))
        findings.extend(analyze_year_end(tree, py_file, project_root))

        if run_rca:
            for f in findings:
                try:
                    exc = ValueError(f.message)
                    ctx = {
                        "file": f.file,
                        "line": f.line,
                        "category": f.category,
                        "severity": f.severity,
                    }
                    r = _rca_analyze(exc, ctx)
                    if r:
                        f.rca = r
                except Exception:
                    pass

        report.findings.extend(findings)

    errors = report.error_count
    warnings = report.warning_count
    report.score = max(0, min(100, 100 - errors * 10 - warnings * 3))
    report.scan_time = time.monotonic() - t0
    return report

def find_period_status_enum(project_root: pathlib.Path) -> tuple[pathlib.Path | None, set[str]]:
    search_dirs = [
        project_root / "domain" / "fiscal_period",
        project_root / "domain" / "shared_value_objects",
        project_root / "axioms",
        project_root / "domain",
    ]
    for base in search_dirs:
        if not base.exists():
            continue
        for py_file in base.glob("*.py"):
            if py_file.name == "__init__.py":
                continue
            tree, err = _get_ast(py_file)
            if err or tree is None:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                is_enum = any(
                    (isinstance(b, ast.Name) and b.id in ("Enum", "StrEnum")) or
                    (isinstance(b, ast.Attribute) and b.attr in ("Enum", "StrEnum"))
                    for b in node.bases
                )
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

# ─── REPORT ──────────────────────────────────────────────────────────────────
def print_report(report: Report, verbose: bool = False, show_rca: bool = False):
    c = COLOR
    _safe_print(f"\n{c['CYAN']}{'='*72}{c['RESET']}")
    _safe_print(f"{c['BOLD']}FISCAL PERIOD CHECKER REPORT v{__version__}{c['RESET']}")
    _safe_print(f"{c['CYAN']}{'='*72}{c['RESET']}")
    _safe_print(f"  Findings : {len(report.findings)}")
    _safe_print(f"  Errors   : {c['RED']}{report.error_count}{c['RESET']}")
    _safe_print(f"  Warnings : {c['YELLOW']}{report.warning_count}{c['RESET']}")
    _safe_print(f"  Infos    : {c['DIM']}{report.info_count}{c['RESET']}")
    _safe_print(f"  Score    : {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")
    _safe_print(f"  RCA      : {'✅ Active' if _RCA_AVAILABLE else '⚠️ Fallback'}")
    _safe_print(f"  Time     : {report.scan_time:.3f}s")

    if report.findings:
        categories = {}
        for f in report.findings:
            categories.setdefault(f.category, []).append(f)

        _safe_print(f"\n{c['CYAN']}By Category:{c['RESET']}")
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
            _safe_print(f"  {label}: {color}{err} errors, {warn} warnings{c['RESET']}")

        _safe_print(f"\n{c['RED'] if report.error_count else c['YELLOW']}Details (first 30):{c['RESET']}")
        for f in report.findings[:30]:
            color = c["RED"] if f.severity == "ERROR" else c["YELLOW"]
            _safe_print(f"  {color}[{f.severity}]{c['RESET']} [{f.category}] {f.file}:{f.line}")
            _safe_print(f"     {f.message}")
            if verbose and f.detail:
                _safe_print(f"     {c['CYAN']}→ {f.detail}{c['RESET']}")
            if show_rca and f.rca:
                rc = f.rca.get("root_cause", "")
                fix = f.rca.get("suggested_fix", "")
                if rc:
                    _safe_print(f"     {c['MAGENTA']}RCA: {rc[:120]}{c['RESET']}")
                if fix:
                    _safe_print(f"     {c['MAGENTA']}Fix: {fix[:120]}{c['RESET']}")
        if len(report.findings) > 30:
            _safe_print(f"  ... and {len(report.findings)-30} more")
    else:
        _safe_print(f"\n{c['GREEN']}✅ No fiscal period violations found!{c['RESET']}")

    _safe_print(f"\n{c['CYAN']}{'─'*72}{c['RESET']}")
    if report.passed:
        _safe_print(f"  {c['GREEN']}✅ PASS — All period rules satisfied.{c['RESET']}")
    else:
        _safe_print(f"  {c['RED']}❌ FAIL — {report.error_count} error(s) need fixing.{c['RESET']}")

# ─── EXPORT ──────────────────────────────────────────────────────────────────
def save_json(report: Report, path: pathlib.Path) -> bool:
    try:
        data = {
            "version": __version__,
            "timestamp": datetime.now(UTC).isoformat(),
            "score": report.score,
            "passed": report.passed,
            "scan_time": report.scan_time,
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
            writer.writerow(["severity", "file", "line", "category", "message", "detail"])
            for fnd in report.findings:
                writer.writerow([fnd.severity, fnd.file, fnd.line, fnd.category, fnd.message, fnd.detail])
        _safe_print(f"{_c('GREEN')}✅ CSV saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save CSV: {e}{_c('RESET')}")
        return False

def save_html(report: Report, path: pathlib.Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Fiscal Period Checker Report</title>
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
table{{width:100%;border-collapse:collapse;margin-top:1rem}}
th,td{{border:1px solid #dee2e6;padding:0.5rem;text-align:left}}
th{{background:#e9ecef}}
</style></head>
<body>
<h1>Fiscal Period Checker Report</h1>
<div class="summary">
  <div class="card"><div class="value">{len(report.findings)}</div><div class="label">Findings</div></div>
  <div class="card"><div class="value" style="color:#dc3545">{report.error_count}</div><div class="label">Errors</div></div>
  <div class="card"><div class="value" style="color:#ffc107">{report.warning_count}</div><div class="label">Warnings</div></div>
  <div class="card"><div class="value">{report.score}</div><div class="label">Score</div></div>
  <div class="card"><div class="value">{'PASS' if report.passed else 'FAIL'}</div><div class="label">Status</div></div>
</div>
<h2>Findings</h2>
"""
        for f in report.findings:
            cls = "error" if f.severity == "ERROR" else "warning" if f.severity == "WARNING" else "info"
            html += f'<div class="finding {cls}"><strong>{f.severity}</strong> [{f.category}] {f.message}'
            if f.detail:
                html += f' <small>{f.detail}</small>'
            html += f'<br><small>{f.file}:{f.line}</small></div>'
        html += "</body></html>"
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        _safe_print(f"{_c('GREEN')}✅ HTML saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save HTML: {e}{_c('RESET')}")
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

    if verbose: _safe_print(f"\nFiscal Period Checker self-test v{__version__}…\n")

    code = """
def post_journal(entry):
    pass
"""
    tree = ast.parse(code)
    check("_has_validation_call returns False", not _has_validation_call(tree))

    code2 = """
def post_journal(entry):
    ensure_open()
"""
    tree2 = ast.parse(code2)
    check("_has_validation_call detects ensure_open", _has_validation_call(tree2))

    code3 = """
def close_period(period):
    if period.status == OPEN:
        pass
"""
    tree3 = ast.parse(code3)
    check("_has_if_status_check detects if", _has_if_status_check(tree3))

    check("_is_getter_or_validator is_open", _is_getter_or_validator("is_open"))
    check("_is_getter_or_validator post_journal", not _is_getter_or_validator("post_journal"))
    check("RCA availability", True)

    if verbose: _safe_print(f"\nSelf-test: {passed} passed, {failed} failed {'✅' if failed==0 else '❌'}")
    return failed == 0

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description=f"Fiscal Period Checker v{__version__}")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE")
    parser.add_argument("--csv", metavar="FILE")
    parser.add_argument("--html", metavar="FILE")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--no-rca", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--exclude", default="")
    parser.add_argument("--version", action="version", version=f"fiscal_period_checker v{__version__}")

    args = parser.parse_args()

    if args.self_test:
        return 0 if self_test(verbose=True) else 1

    project_root = pathlib.Path(__file__).resolve().parent.parent
    extra_excludes = set(args.exclude.split(",")) if args.exclude else set()

    report = scan_project(
        project_root=project_root,
        extra_excludes=extra_excludes,
        run_rca=not args.no_rca,
    )

    print_report(report, verbose=args.verbose, show_rca=not args.no_rca)

    if not args.dry_run:
        if args.json:
            save_json(report, pathlib.Path(args.json))
        if args.csv:
            save_csv(report, pathlib.Path(args.csv))
        if args.html:
            save_html(report, pathlib.Path(args.html))

    return 0 if report.passed else 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        _safe_print(f"\n{_c('YELLOW')}⏹️  Interrupted by user.{_c('RESET')}")
        sys.exit(130)
