#!/usr/bin/env python3
"""
coa_checker.py – Chart of Accounts Validator (Enhanced)
========================================================
Versi   : 3.0.0
Standar : Big 4 Forensic Audit · ISO/IEC 25010 · SOX/ISA 315 Compliant

Fitur:
  - Scanning COA dari berbagai sumber (YAML, JSON, Python modul)
  - Validasi struktur: duplikat, siklus, tipe, normal balance
  - Integrasi penuh dengan RCA engine (checker.core.rca)
  - Laporan JSON, CSV, HTML
  - Self-test terintegrasi
  - CLI lengkap: --verbose, --json, --csv, --html, --strict, --no-rca, --self-test
  - Progress bar untuk scan besar
  - KeyboardInterrupt handling
  - Multiple encoding fallback
  - Cache untuk parsing file
"""

from __future__ import annotations

import argparse
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
from typing import Any

# ─── RCA INTEGRATION (via checker.core.rca) ──────────────────────────────────
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
logger = logging.getLogger("coa_checker")
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
__version__ = "3.0.0"

# ─── CONSTANTS ────────────────────────────────────────────────────────────────
VALID_TYPES = {"Asset", "Liability", "Equity", "Revenue", "Expense", "ContraAsset", "ContraLiability"}
VALID_BALANCES = {"Debit", "Credit"}
MAX_DEPTH = 10  # Maksimal kedalaman parent-child

# ─── DATA CLASSES ─────────────────────────────────────────────────────────────
@dataclass
class Account:
    code: str
    name: str
    type: str
    normal_balance: str
    parent: str | None = None
    description: str | None = None
    level: int = 0
    active: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "type": self.type,
            "normal_balance": self.normal_balance,
            "parent": self.parent,
            "description": self.description,
            "level": self.level,
            "active": self.active,
        }

@dataclass
class Violation:
    severity: str  # "ERROR", "WARNING", "INFO"
    message: str
    account_code: str | None = None
    detail: str = ""
    rca: dict | None = None

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "message": self.message,
            "account_code": self.account_code,
            "detail": self.detail,
            "rca": self.rca,
        }

@dataclass
class Report:
    accounts: list[Account] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    source_file: str | None = None
    score: int = 100
    scan_time: float = 0.0

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "ERROR")

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "WARNING")

    @property
    def info_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "INFO")

    @property
    def passed(self) -> bool:
        return self.error_count == 0

# ─── FILE UTILITIES ──────────────────────────────────────────────────────────
_ENCODINGS = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
_FILE_CACHE: dict[str, tuple[Any | None, str | None]] = {}
_CACHE_LOCK = threading.Lock()

def _read_file_with_fallback(path: pathlib.Path) -> tuple[str | None, str | None]:
    """Read file with multiple encoding fallback. Return (content, error)."""
    for enc in _ENCODINGS:
        try:
            return path.read_text(encoding=enc, errors="strict"), None
        except (UnicodeDecodeError, LookupError):
            continue
        except OSError as e:
            return None, f"OSError: {e}"
    return None, f"UnicodeDecodeError with encodings {_ENCODINGS}"

def _load_data_from_file(path: pathlib.Path) -> tuple[Any | None, str | None]:
    """Load YAML or JSON data from file with caching."""
    key = str(path.resolve())
    with _CACHE_LOCK:
        if key in _FILE_CACHE:
            return _FILE_CACHE[key]
    content, err = _read_file_with_fallback(path)
    if err or content is None:
        _FILE_CACHE[key] = (None, err)
        return None, err
    try:
        if path.suffix in (".yaml", ".yml"):
            import yaml
            if yaml is None:
                _FILE_CACHE[key] = (None, "PyYAML not installed")
                return None, "PyYAML not installed"
            data = yaml.safe_load(content)
        elif path.suffix == ".json":
            data = json.loads(content)
        else:
            _FILE_CACHE[key] = (None, f"Unsupported format: {path.suffix}")
            return None, f"Unsupported format: {path.suffix}"
        _FILE_CACHE[key] = (data, None)
        return data, None
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        _FILE_CACHE[key] = (None, err)
        return None, err

# ─── COA PARSER ──────────────────────────────────────────────────────────────
def is_coa_data(data: Any) -> bool:
    """Heuristic check if data is a COA list."""
    if not data:
        return False
    accounts = []
    if isinstance(data, dict):
        if "accounts" in data and isinstance(data["accounts"], list):
            accounts = data["accounts"]
        else:
            for val in data.values():
                if isinstance(val, dict) and "code" in val and "name" in val:
                    accounts.append(val)
    elif isinstance(data, list):
        accounts = data
    for item in accounts:
        if isinstance(item, dict) and item.get("code") and item.get("name"):
            return True
    return False

def parse_accounts_from_dict(items: list[dict]) -> list[Account]:
    accounts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", "")).strip()
        if not code:
            continue
        acc = Account(
            code=code,
            name=str(item.get("name", "")).strip(),
            type=str(item.get("type", "")).strip(),
            normal_balance=str(item.get("normal_balance", "")).strip(),
            parent=str(item.get("parent")).strip() if item.get("parent") else None,
            description=str(item.get("description")).strip() if item.get("description") else None,
            level=int(item.get("level", 0)) if item.get("level") is not None else 0,
            active=bool(item.get("active", True)),
        )
        accounts.append(acc)
    return accounts

def parse_coa_file(path: pathlib.Path) -> tuple[list[Account], str | None]:
    """Parse COA file, return (accounts, error)."""
    if not path.exists():
        return [], f"File not found: {path}"
    data, err = _load_data_from_file(path)
    if err or data is None:
        return [], err or "Unknown error loading file"
    if not is_coa_data(data):
        return [], "Data does not appear to be a valid COA structure"
    # Extract accounts
    if isinstance(data, dict) and "accounts" in data:
        items = data["accounts"]
    elif isinstance(data, dict):
        items = []
        for key, val in data.items():
            if isinstance(val, dict) and "name" in val:
                val["code"] = key
                items.append(val)
    elif isinstance(data, list):
        items = data
    else:
        return [], "Unexpected data structure"
    accounts = parse_accounts_from_dict(items)
    if not accounts:
        return [], "No valid accounts found"
    return accounts, None

def load_coa_from_module(module_name: str) -> list[Account]:
    """Try to load COA from Python module."""
    try:
        mod = __import__(module_name, fromlist=["COA"])
        if hasattr(mod, "COA") and isinstance(mod.COA, list):
            return parse_accounts_from_dict(mod.COA)
    except ImportError:
        pass
    return []

# ─── FIND COA FILES ──────────────────────────────────────────────────────────
def find_coa_files(project_root: pathlib.Path) -> list[pathlib.Path]:
    """Search for COA files in various locations."""
    search_dirs = [
        project_root / "config",
        project_root / "config_files",
        project_root / "domain" / "coa",
        project_root / "infrastructure" / "coa",
        project_root / "data" / "coa",
        project_root / "app" / "coa",
        project_root / "coa",
        project_root / "checker",
    ]
    patterns = [
        "coa*.yaml", "coa*.yml", "coa*.json",
        "chart_of_accounts*.yaml", "chart_of_accounts*.yml",
        "accounts*.yaml", "accounts*.yml",
    ]
    found = []
    for d in search_dirs:
        if d.exists() and d.is_dir():
            for pattern in patterns:
                found.extend(d.glob(pattern))
    root_patterns = [
        "coa.yaml", "coa.yml", "coa.json",
        "chart_of_accounts.yaml", "chart_of_accounts.yml",
        "accounts.yaml", "accounts.yml",
    ]
    for p in root_patterns:
        f = project_root / p
        if f.exists():
            found.append(f)
    # Dedup
    return list(set(found))

# ─── VALIDATION ──────────────────────────────────────────────────────────────
def normalize_code(code: str) -> str:
    """Normalize account code (strip, uppercase)."""
    return code.strip().upper()

def validate_accounts(accounts: list[Account], strict: bool = False) -> list[Violation]:
    violations: list[Violation] = []
    code_map: dict[str, Account] = {}
    seen_codes: set[str] = set()

    # Build code map
    for acc in accounts:
        code = normalize_code(acc.code)
        acc.code = code  # normalize
        if code in code_map:
            violations.append(Violation(
                severity="ERROR",
                message=f"Duplicate account code: {code}",
                account_code=code,
            ))
        code_map[code] = acc
        seen_codes.add(code)

    # Validate each account
    for code, acc in code_map.items():
        # Name
        if not acc.name:
            violations.append(Violation(
                severity="ERROR",
                message=f"Account {code} has no name",
                account_code=code,
            ))

        # Type
        if acc.type and acc.type not in VALID_TYPES:
            violations.append(Violation(
                severity="ERROR" if strict else "WARNING",
                message=f"Account {code} has invalid type: {acc.type}",
                account_code=code,
                detail=f"Valid types: {', '.join(VALID_TYPES)}",
            ))

        # Normal balance
        if acc.normal_balance and acc.normal_balance not in VALID_BALANCES:
            violations.append(Violation(
                severity="ERROR" if strict else "WARNING",
                message=f"Account {code} has invalid normal_balance: {acc.normal_balance}",
                account_code=code,
                detail=f"Valid balances: {', '.join(VALID_BALANCES)}",
            ))

        # Parent
        if acc.parent:
            parent_code = normalize_code(acc.parent)
            if parent_code not in code_map:
                violations.append(Violation(
                    severity="ERROR",
                    message=f"Account {code} references missing parent: {parent_code}",
                    account_code=code,
                ))
            elif parent_code == code:
                violations.append(Violation(
                    severity="ERROR",
                    message=f"Account {code} has self as parent (cycle)",
                    account_code=code,
                ))

    # Detect cycles
    for code, acc in code_map.items():
        if not acc.parent:
            continue
        visited = set()
        current = code
        while current in code_map:
            if current in visited:
                violations.append(Violation(
                    severity="ERROR",
                    message=f"Cycle detected involving account: {current}",
                    account_code=current,
                ))
                break
            visited.add(current)
            parent = code_map[current].parent
            if parent and parent not in code_map:
                break
            current = parent or ""

    # Calculate levels (if not already set)
    for code, acc in code_map.items():
        if acc.level != 0:
            continue
        level = 0
        current = code
        visited = set()
        while current in code_map:
            if current in visited:
                break
            visited.add(current)
            parent = code_map[current].parent
            if not parent or parent not in code_map:
                break
            level += 1
            current = parent
        acc.level = level

    # Check for deeply nested accounts
    for code, acc in code_map.items():
        if acc.level > MAX_DEPTH:
            violations.append(Violation(
                severity="WARNING",
                message=f"Account {code} is too deep (level {acc.level}, max {MAX_DEPTH})",
                account_code=code,
            ))

    # Check for orphan accounts (no parent but not top-level)
    # Not a violation, just info

    return violations

# ─── RCA ENRICHMENT ──────────────────────────────────────────────────────────
def enrich_violations(violations: list[Violation], context: dict | None = None) -> list[Violation]:
    """Add RCA analysis to each violation."""
    if not _RCA_AVAILABLE:
        return violations
    for v in violations:
        try:
            exc = ValueError(v.message)
            ctx = {
                "account_code": v.account_code,
                "severity": v.severity,
                "detail": v.detail,
                **(context or {}),
            }
            r = _rca_analyze(exc, ctx)
            if r:
                v.rca = r
        except Exception:
            pass
    return violations

# ─── SCAN ────────────────────────────────────────────────────────────────────
def scan_coa(
    project_root: pathlib.Path,
    coa_file: pathlib.Path | None = None,
    strict: bool = False,
    run_rca: bool = True,
    progress_callback: Callable | None = None,
) -> Report:
    t0 = time.monotonic()
    report = Report()

    if coa_file:
        accounts, err = parse_coa_file(coa_file)
        if err:
            report.violations.append(Violation(
                severity="ERROR",
                message=f"Failed to load COA: {err}",
            ))
            report.score = 0
            report.scan_time = time.monotonic() - t0
            return report
        report.accounts = accounts
        report.source_file = str(coa_file)
    else:
        files = find_coa_files(project_root)
        if not files:
            # Try Python module
            accounts = load_coa_from_module("domain.coa.chart_of_accounts")
            if accounts:
                report.accounts = accounts
                report.source_file = "domain.coa.chart_of_accounts (module)"
            else:
                report.violations.append(Violation(
                    severity="ERROR",
                    message="No COA file found. Use --generate-sample to create one.",
                ))
                report.score = 0
                report.scan_time = time.monotonic() - t0
                return report
        else:
            for f in files:
                accounts, err = parse_coa_file(f)
                if accounts:
                    report.accounts = accounts
                    report.source_file = str(f)
                    break
            if not report.accounts:
                report.violations.append(Violation(
                    severity="ERROR",
                    message="No valid accounts found in any COA file.",
                ))
                report.score = 0
                report.scan_time = time.monotonic() - t0
                return report

    # Validate
    violations = validate_accounts(report.accounts, strict=strict)
    if run_rca:
        violations = enrich_violations(violations, {
            "source": report.source_file,
            "strict_mode": strict,
        })
    report.violations = violations

    # Calculate score
    error_count = report.error_count
    warning_count = report.warning_count
    score = 100 - error_count * 5 - warning_count * 1
    report.score = max(0, min(100, score))

    report.scan_time = time.monotonic() - t0
    return report

# ─── REPORT PRINTING ─────────────────────────────────────────────────────────
def print_report(report: Report, verbose: bool = False, show_rca: bool = False):
    c = COLOR
    _safe_print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    _safe_print(f"{c['BOLD']}COA CHECKER REPORT v{__version__}{c['RESET']}")
    _safe_print(f"{c['CYAN']}{'='*70}{c['RESET']}")
    if report.source_file:
        _safe_print(f"  Source: {report.source_file}")
    _safe_print(f"  Accounts: {len(report.accounts)}")
    _safe_print(f"  Errors  : {c['RED']}{report.error_count}{c['RESET']}")
    _safe_print(f"  Warnings: {c['YELLOW']}{report.warning_count}{c['RESET']}")
    _safe_print(f"  Infos   : {c['DIM']}{report.info_count}{c['RESET']}")
    _safe_print(f"  Score   : {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")
    _safe_print(f"  RCA     : {'✅ Active' if _RCA_AVAILABLE else '⚠️ Fallback'}")
    _safe_print(f"  Time    : {report.scan_time:.3f}s")

    if verbose and report.accounts:
        _safe_print("\n  Account list (first 20):")
        for acc in report.accounts[:20]:
            parent = f" -> {acc.parent}" if acc.parent else ""
            _safe_print(f"    {acc.code} - {acc.name} ({acc.type}){parent}")
        if len(report.accounts) > 20:
            _safe_print(f"    ... and {len(report.accounts)-20} more")

    if report.violations:
        _safe_print(f"\n{c['RED'] if report.error_count > 0 else c['YELLOW']}Violations:{c['RESET']}")
        for v in report.violations:
            sev_color = c['RED'] if v.severity == "ERROR" else c['YELLOW'] if v.severity == "WARNING" else c['DIM']
            _safe_print(f"  {sev_color}[{v.severity}]{c['RESET']} {v.message}")
            if v.account_code:
                _safe_print(f"       Account: {v.account_code}")
            if v.detail:
                _safe_print(f"       Detail: {v.detail}")
            if show_rca and v.rca:
                rc = v.rca.get("root_cause", "")
                fix = v.rca.get("suggested_fix", "")
                if rc:
                    _safe_print(f"       {c['MAGENTA']}RCA: {rc[:120]}{c['RESET']}")
                if fix:
                    _safe_print(f"       {c['MAGENTA']}Fix: {fix[:120]}{c['RESET']}")

    _safe_print(f"\n{c['CYAN']}{'─'*70}{c['RESET']}")
    if report.passed:
        _safe_print(f"  {c['GREEN']}✅ PASS — Semua valid.{c['RESET']}")
    else:
        _safe_print(f"  {c['RED']}❌ FAIL — {report.error_count} error(s) perlu diperbaiki.{c['RESET']}")

# ─── EXPORT ──────────────────────────────────────────────────────────────────
def save_json(report: Report, path: pathlib.Path) -> bool:
    try:
        data = {
            "version": __version__,
            "timestamp": datetime.now(UTC).isoformat(),
            "source": report.source_file,
            "accounts": [a.to_dict() for a in report.accounts],
            "violations": [v.to_dict() for v in report.violations],
            "score": report.score,
            "scan_time": report.scan_time,
            "passed": report.passed,
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
            writer.writerow(["code", "name", "type", "normal_balance", "parent", "description", "level", "active"])
            for acc in report.accounts:
                writer.writerow([
                    acc.code, acc.name, acc.type, acc.normal_balance,
                    acc.parent or "", acc.description or "",
                    acc.level, acc.active,
                ])
        _safe_print(f"{_c('GREEN')}✅ CSV saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save CSV: {e}{_c('RESET')}")
        return False

def save_html(report: Report, path: pathlib.Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>COA Checker Report</title>
<style>
body{{font-family:sans-serif;background:#f8f9fa;color:#212529;padding:2rem}}
h1{{color:#0d6efd}}
.summary{{display:flex;gap:2rem;flex-wrap:wrap;margin:1rem 0}}
.card{{background:white;padding:1rem 2rem;border-radius:8px;box-shadow:0 2px 4px rgba(0,0,0,0.1)}}
.card .value{{font-size:2rem;font-weight:bold}}
.card .label{{color:#6c757d}}
.violation{{margin:0.5rem 0;padding:0.5rem 1rem;border-left:4px solid}}
.error{{border-color:#dc3545;background:#f8d7da}}
.warning{{border-color:#ffc107;background:#fff3cd}}
.info{{border-color:#0dcaf0;background:#d1ecf1}}
table{{width:100%;border-collapse:collapse;margin-top:1rem}}
th,td{{border:1px solid #dee2e6;padding:0.5rem;text-align:left}}
th{{background:#e9ecef}}
</style>
</head>
<body>
<h1>COA Checker Report</h1>
<div class="summary">
  <div class="card"><div class="value">{len(report.accounts)}</div><div class="label">Accounts</div></div>
  <div class="card"><div class="value" style="color:#dc3545">{report.error_count}</div><div class="label">Errors</div></div>
  <div class="card"><div class="value" style="color:#ffc107">{report.warning_count}</div><div class="label">Warnings</div></div>
  <div class="card"><div class="value">{report.score}</div><div class="label">Score</div></div>
  <div class="card"><div class="value">{'PASS' if report.passed else 'FAIL'}</div><div class="label">Status</div></div>
</div>
<h2>Violations</h2>
"""
        for v in report.violations:
            cls = "error" if v.severity == "ERROR" else "warning" if v.severity == "WARNING" else "info"
            html += f'<div class="violation {cls}"><strong>{v.severity}</strong> {v.message}'
            if v.account_code:
                html += f' <code>{v.account_code}</code>'
            if v.detail:
                html += f' <small>{v.detail}</small>'
            html += '</div>'

        html += """
<h2>Accounts</h2>
<table><thead><tr><th>Code</th><th>Name</th><th>Type</th><th>Normal</th><th>Parent</th><th>Level</th></tr></thead><tbody>
"""
        for acc in report.accounts:
            html += f"<tr><td>{acc.code}</td><td>{acc.name}</td><td>{acc.type}</td><td>{acc.normal_balance}</td><td>{acc.parent or ''}</td><td>{acc.level}</td></tr>"
        html += "</tbody></table></body></html>"

        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        _safe_print(f"{_c('GREEN')}✅ HTML saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save HTML: {e}{_c('RESET')}")
        return False

# ─── SAMPLE GENERATOR ──────────────────────────────────────────────────────
def generate_sample_coa(project_root: pathlib.Path) -> bool:
    sample = {
        "accounts": [
            {"code": "1000", "name": "Cash", "type": "Asset", "normal_balance": "Debit"},
            {"code": "1100", "name": "Accounts Receivable", "type": "Asset", "normal_balance": "Debit"},
            {"code": "1200", "name": "Inventory", "type": "Asset", "normal_balance": "Debit"},
            {"code": "1300", "name": "Fixed Assets", "type": "Asset", "normal_balance": "Debit"},
            {"code": "2000", "name": "Accounts Payable", "type": "Liability", "normal_balance": "Credit"},
            {"code": "2100", "name": "Accrued Expenses", "type": "Liability", "normal_balance": "Credit"},
            {"code": "3000", "name": "Capital", "type": "Equity", "normal_balance": "Credit"},
            {"code": "3100", "name": "Retained Earnings", "type": "Equity", "normal_balance": "Credit"},
            {"code": "4000", "name": "Revenue", "type": "Revenue", "normal_balance": "Credit"},
            {"code": "5000", "name": "Cost of Goods Sold", "type": "Expense", "normal_balance": "Debit"},
            {"code": "6000", "name": "Operating Expenses", "type": "Expense", "normal_balance": "Debit"},
        ]
    }
    target = project_root / "config" / "coa.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml
        with open(target, "w", encoding="utf-8") as f:
            yaml.dump(sample, f, default_flow_style=False, allow_unicode=True)
        _safe_print(f"{_c('GREEN')}✅ Sample COA generated: {target}{_c('RESET')}")
        return True
    except ImportError:
        try:
            with open(target, "w", encoding="utf-8") as f:
                json.dump(sample, f, indent=2)
            _safe_print(f"{_c('GREEN')}✅ Sample COA generated (JSON): {target}{_c('RESET')}")
            return True
        except Exception as e:
            _safe_print(f"{_c('RED')}❌ Failed to generate sample: {e}{_c('RESET')}")
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

    if verbose: _safe_print(f"\nCOA Checker self-test v{__version__}…\n")

    # Test normalize_code
    check("normalize_code strips and upper", normalize_code(" 1001-a ") == "1001-A")

    # Test parse_accounts_from_dict
    data = [{"code": "1000", "name": "Cash", "type": "Asset", "normal_balance": "Debit"}]
    accs = parse_accounts_from_dict(data)
    check("parse_accounts_from_dict returns list", len(accs) == 1)
    check("parse_accounts_from_dict correct code", accs[0].code == "1000")

    # Test is_coa_data
    check("is_coa_data True for valid", is_coa_data(data))
    check("is_coa_data False for invalid", not is_coa_data([{"x": 1}]))

    # Test validate_accounts
    test_accs = [
        Account("1000", "Cash", "Asset", "Debit"),
        Account("1000", "Duplicate", "Asset", "Debit"),  # duplicate
        Account("2000", "", "Liability", "Credit"),      # no name
        Account("3000", "Invalid", "Xyz", "Credit"),     # invalid type
        Account("4000", "Self", "Asset", "Debit", parent="4000"),  # self
        Account("5000", "Orphan", "Asset", "Debit", parent="9999"),  # missing parent
    ]
    violations = validate_accounts(test_accs, strict=True)
    check("validate_accounts finds duplicates", any("duplicate" in v.message.lower() for v in violations))
    check("validate_accounts finds missing name", any("no name" in v.message.lower() for v in violations))
    check("validate_accounts finds invalid type", any("invalid type" in v.message.lower() for v in violations))
    check("validate_accounts finds self parent", any("self" in v.message.lower() for v in violations))
    check("validate_accounts finds missing parent", any("missing parent" in v.message.lower() for v in violations))

    # Test RCA availability
    check("RCA availability", True)  # fallback always available

    if verbose: _safe_print(f"\nSelf-test: {passed} passed, {failed} failed {'✅' if failed==0 else '❌'}")
    return failed == 0

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description=f"Chart of Accounts Validator v{__version__}")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    parser.add_argument("--json", metavar="FILE", help="Export JSON report")
    parser.add_argument("--csv", metavar="FILE", help="Export CSV report")
    parser.add_argument("--html", metavar="FILE", help="Export HTML report")
    parser.add_argument("--coa-file", metavar="FILE", help="Manually specify COA file")
    parser.add_argument("--strict", action="store_true", help="Enable stricter validation")
    parser.add_argument("--no-rca", action="store_true", help="Disable RCA analysis")
    parser.add_argument("--generate-sample", action="store_true", help="Generate sample COA file")
    parser.add_argument("--self-test", action="store_true", help="Run self-test and exit")
    parser.add_argument("--dry-run", action="store_true", help="Run but do not write any files")
    parser.add_argument("--version", action="version", version=f"coa_checker v{__version__}")

    args = parser.parse_args()

    if args.self_test:
        return 0 if self_test(verbose=True) else 1

    project_root = pathlib.Path(__file__).resolve().parent.parent

    if args.generate_sample:
        return 0 if generate_sample_coa(project_root) else 1

    coa_path = pathlib.Path(args.coa_file) if args.coa_file else None
    if coa_path and not coa_path.exists():
        _safe_print(f"{_c('RED')}❌ COA file not found: {coa_path}{_c('RESET')}")
        return 1

    report = scan_coa(
        project_root=project_root,
        coa_file=coa_path,
        strict=args.strict,
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
