#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tax_checker.py – Tax Implementation Validator (Forensic)
========================================================
Versi   : 3.0.0
Standar : Big 4 Forensic Audit · ISO/IEC 25010 · SOX/ISA 315 Compliant

Fitur:
  - Scan semua calculator di policy_engine/tax_indonesia/, infrastructure/tax/, adapters/tax/, domain/tax/
  - Validasi method calculate, validate, get_rate
  - Deteksi penggunaan Decimal
  - Deteksi hardcoded rates
  - Signature checking (parameter count)
  - Return type checking (Decimal recommended)
  - Integrasi RCA engine
  - Laporan JSON, CSV, HTML
  - Self-test
  - CLI lengkap: --verbose, --json, --csv, --html, --strict, --no-rca, --self-test, --exclude
"""

from __future__ import annotations

import argparse
import ast
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

# ─── RCA INTEGRATION (via checker.core.rca) ──────────────────────────────────
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
logger = logging.getLogger("tax_checker")
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
EXPECTED_CALCULATORS = {
    "ppn_calculator": "PPN 11%",
    "pph_21_calculator": "PPh Pasal 21 (progresif)",
    "pph_22_calculator": "PPh Pasal 22 (0.1%-7.5%)",
    "pph_23_calculator": "PPh Pasal 23 (2%-15%)",
    "pph_25_calculator": "PPh Pasal 25 (angsuran 25%)",
    "pph_26_calculator": "PPh Pasal 26 (20%)",
    "pph_4_ayat_2_calculator": "PPh Pasal 4 ayat 2 (0.5%-10%)",
    "pph_badan_calculator": "PPh Badan (22%)",
    "bea_meterai_calculator": "Bea Meterai (Rp10.000)",
    "withholding_engine": "Engine pemotongan pajak",
    "penalty_interest_engine": "Engine denda & bunga",
    "rate_registry_dynamic": "Registry tarif dinamis",
}

SKIP_CLASS_PATTERNS = {
    "Registry", "Type", "State", "Table", "Config", "Constants",
    "Data", "Model", "Schema", "Exception", "Error", "Base", "Mixin",
}

SKIP_FILE_PATTERNS = {
    "__init__", "exception", "constant", "util", "model", "schema",
    "saga", "state", "table", "router", "adapter", "repository", "service",
}

# ─── DATA CLASSES ─────────────────────────────────────────────────────────────
@dataclass
class CalculatorInfo:
    file: str
    name: str
    class_name: str
    has_calculate: bool
    has_validate: bool
    has_get_rate: bool
    uses_decimal: bool
    hardcoded_rates: List[str]
    methods: List[str]
    is_calculator_class: bool
    has_correct_signature: bool
    has_decimal_return: bool

@dataclass
class Violation:
    severity: str  # ERROR, WARNING, INFO
    file: str
    line: int
    message: str
    detail: str = ""
    rca: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {
            "severity": self.severity,
            "file": self.file,
            "line": self.line,
            "message": self.message,
            "detail": self.detail,
            "rca": self.rca,
        }

@dataclass
class Report:
    calculators: List[CalculatorInfo] = field(default_factory=list)
    violations: List[Violation] = field(default_factory=list)
    score: int = 100
    total_files_scanned: int = 0
    total_calculators_found: int = 0
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

def _is_calculator_file(filename: str) -> bool:
    name_lower = filename.lower()
    keywords = ["calculator", "withholding", "rate", "tax_", "ppn", "pph", "bea_meterai", "penalty"]
    has_keyword = any(kw in name_lower for kw in keywords)
    if not has_keyword:
        return False
    for pattern in SKIP_FILE_PATTERNS:
        if pattern in name_lower:
            return False
    return True

def _is_calculator_class(cls_node: ast.ClassDef) -> bool:
    class_name = cls_node.name
    if not (class_name.endswith("Calculator") or class_name.endswith("Engine")):
        return False
    for pattern in SKIP_CLASS_PATTERNS:
        if pattern in class_name:
            return False
    for base in cls_node.bases:
        if isinstance(base, ast.Name) and base.id in ("Exception", "BaseException"):
            return False
        if isinstance(base, ast.Attribute) and base.attr in ("Exception", "BaseException"):
            return False
    return True

def _find_calculator_class(tree: ast.AST) -> Optional[ast.ClassDef]:
    candidates = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and _is_calculator_class(node):
            methods = [item.name for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]
            has_calculate = any('calculate' in m.lower() for m in methods)
            candidates.append((node, has_calculate))
    # Prioritaskan yang punya calculate
    for node, has_calc in candidates:
        if has_calc:
            return node
    return candidates[0][0] if candidates else None

def _extract_methods(cls_node: ast.ClassDef) -> List[str]:
    methods = []
    for item in cls_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(item.name)
    return methods

def _has_method(cls_node: ast.ClassDef, method_name: str) -> bool:
    for item in cls_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name == method_name:
                return True
    return False

def _get_method_node(cls_node: ast.ClassDef, method_name: str) -> Optional[Union[ast.FunctionDef, ast.AsyncFunctionDef]]:
    for item in cls_node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name == method_name:
                return item
    return None

def _count_required_params(method_node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> int:
    args = method_node.args
    total = len(args.args)
    defaults = len(args.defaults)
    # Exclude self/cls
    offset = 1 if total > 0 and args.args[0].arg in ("self", "cls") else 0
    required = max(0, total - defaults - offset)
    return required

def _has_decimal_import(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "decimal":
            for alias in node.names:
                if alias.name == "Decimal":
                    return True
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "decimal":
                    return True
    return False

def _is_decimal_return(method_node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> bool:
    # Check return annotation
    if method_node.returns:
        # Simple check: 'Decimal' or 'decimal.Decimal'
        if isinstance(method_node.returns, ast.Name) and method_node.returns.id == "Decimal":
            return True
        if isinstance(method_node.returns, ast.Attribute) and method_node.returns.attr == "Decimal":
            return True
    # Check if any return statement returns Decimal(...)
    for node in ast.walk(method_node):
        if isinstance(node, ast.Return) and node.value:
            # Check if return value is Decimal(...)
            if isinstance(node.value, ast.Call):
                func = node.value.func
                if isinstance(func, ast.Name) and func.id == "Decimal":
                    return True
                if isinstance(func, ast.Attribute) and func.attr == "Decimal":
                    return True
            # Check if return value is a variable assigned Decimal(...)
            if isinstance(node.value, ast.Name):
                # We need to look for assignment
                for sub in ast.walk(method_node):
                    if isinstance(sub, ast.Assign):
                        for target in sub.targets:
                            if isinstance(target, ast.Name) and target.id == node.value.id:
                                if isinstance(sub.value, ast.Call):
                                    func = sub.value.func
                                    if isinstance(func, ast.Name) and func.id == "Decimal":
                                        return True
                                    if isinstance(func, ast.Attribute) and func.attr == "Decimal":
                                        return True
    return False

def _extract_hardcoded_rates(cls_node: ast.ClassDef) -> List[str]:
    rates = []
    for node in ast.walk(cls_node):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and ('rate' in target.id.lower() or 'tarif' in target.id.lower()):
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, (int, float)):
                        rates.append(f"{target.id}={node.value.value}")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            for operand in (node.left, node.right):
                if isinstance(operand, ast.Constant) and isinstance(operand.value, (int, float)):
                    rates.append(f"Multiplication with {operand.value} at line {node.lineno}")
        # Check dict literals
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    if 'rate' in key.value.lower() or 'tarif' in key.value.lower():
                        if isinstance(node.values[node.keys.index(key)], ast.Constant):
                            rates.append(f"dict {key.value}={node.values[node.keys.index(key)].value}")
    return rates

# ─── PARSER ──────────────────────────────────────────────────────────────────
def parse_calculator_file(file_path: pathlib.Path) -> Optional[CalculatorInfo]:
    tree, err = _get_ast(file_path)
    if err or tree is None:
        return None

    cls = _find_calculator_class(tree)
    if cls is None:
        return None

    class_name = cls.name
    methods = _extract_methods(cls)
    has_calculate = _has_method(cls, "calculate") or any('calculate' in m.lower() for m in methods)
    has_validate = _has_method(cls, "validate") or any('validate' in m.lower() for m in methods)
    has_get_rate = _has_method(cls, "get_rate") or any('get_rate' in m.lower() for m in methods)

    # Check signature: calculate should have at least 1 parameter (excluding self/cls)
    has_correct_signature = False
    calc_node = _get_method_node(cls, "calculate")
    if calc_node is not None:
        required = _count_required_params(calc_node)
        if required >= 1:
            has_correct_signature = True

    has_decimal_return = False
    if calc_node is not None:
        has_decimal_return = _is_decimal_return(calc_node)

    uses_decimal = _has_decimal_import(tree)
    for node in ast.walk(cls):
        if isinstance(node, ast.Name) and node.id == "Decimal":
            uses_decimal = True
        if isinstance(node, ast.Attribute) and node.attr == "Decimal":
            uses_decimal = True

    hardcoded_rates = _extract_hardcoded_rates(cls)

    return CalculatorInfo(
        file=str(file_path),
        name=file_path.stem,
        class_name=class_name,
        has_calculate=has_calculate,
        has_validate=has_validate,
        has_get_rate=has_get_rate,
        uses_decimal=uses_decimal,
        hardcoded_rates=hardcoded_rates,
        methods=methods,
        is_calculator_class=True,
        has_correct_signature=has_correct_signature,
        has_decimal_return=has_decimal_return,
    )

# ─── VALIDATOR ──────────────────────────────────────────────────────────────
def validate_calculator(info: CalculatorInfo, strict: bool = False) -> List[Violation]:
    violations = []
    exc_context = {"calculator": info.name, "class": info.class_name, "file": info.file}

    if not info.has_calculate:
        msg = f"Calculator {info.name} lacks 'calculate' method in class {info.class_name}"
        exc = ValueError(msg)
        rca = _rca_analyze(exc, exc_context)
        violations.append(Violation(
            severity="ERROR",
            file=info.file,
            line=0,
            message=msg,
            detail="Method 'calculate' is mandatory for all calculators.",
            rca=rca,
        ))
    else:
        if not info.has_correct_signature:
            msg = f"Calculator {info.name} calculate method missing required parameters (need at least 1 parameter besides self/cls)"
            exc = ValueError(msg)
            rca = _rca_analyze(exc, exc_context)
            violations.append(Violation(
                severity="ERROR",
                file=info.file,
                line=0,
                message=msg,
                detail="Calculate method must accept at least one parameter (e.g., amount, value, or context).",
                rca=rca,
            ))
        if not info.has_decimal_return:
            if strict:
                severity = "ERROR"
            else:
                severity = "WARNING"
            msg = f"Calculator {info.name} calculate method does not return Decimal (recommended for accuracy)"
            exc = ValueError(msg)
            rca = _rca_analyze(exc, exc_context)
            violations.append(Violation(
                severity=severity,
                file=info.file,
                line=0,
                message=msg,
                detail="Use Decimal for monetary values to avoid floating-point errors.",
                rca=rca,
            ))

    if not info.uses_decimal:
        violations.append(Violation(
            severity="WARNING",
            file=info.file,
            line=0,
            message=f"Calculator {info.name} does not import or use Decimal (recommended for monetary values)",
            detail="Add 'from decimal import Decimal' and use Decimal for all monetary calculations.",
        ))

    if not info.has_validate:
        violations.append(Violation(
            severity="INFO",
            file=info.file,
            line=0,
            message=f"Calculator {info.name} lacks 'validate' method (optional for input validation)",
            detail="Consider adding a validate method to check input parameters.",
        ))
    if not info.has_get_rate:
        violations.append(Violation(
            severity="INFO",
            file=info.file,
            line=0,
            message=f"Calculator {info.name} lacks 'get_rate' method (optional for rate retrieval)",
            detail="Consider adding a get_rate method to separate rate logic from calculation.",
        ))

    if info.hardcoded_rates:
        for rate in info.hardcoded_rates[:5]:
            violations.append(Violation(
                severity="WARNING",
                file=info.file,
                line=0,
                message=f"Hardcoded rate in {info.name}: {rate} (prefer configuration-based rates)",
                detail="Move rates to configuration (YAML, DB, or dynamic registry) for maintainability.",
            ))

    return violations

# ─── SCAN ────────────────────────────────────────────────────────────────────
def scan_tax_implementations(
    project_root: pathlib.Path,
    extra_excludes: Set[str],
    strict: bool = False,
    run_rca: bool = True,
    progress_callback: Optional[Callable] = None,
) -> Report:
    t0 = time.monotonic()
    report = Report()

    search_dirs = [
        project_root / "policy_engine" / "tax_indonesia",
        project_root / "infrastructure" / "tax",
        project_root / "adapters" / "tax",
        project_root / "domain" / "tax",
        project_root / "application" / "service_layer" / "tax",
    ]

    candidate_files: List[pathlib.Path] = []
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for f in search_dir.glob("*.py"):
            if _is_calculator_file(f.name):
                candidate_files.append(f)

    # Also search root for *calculator*.py
    for f in project_root.glob("*calculator*.py"):
        if f not in candidate_files and _is_calculator_file(f.name):
            candidate_files.append(f)
    for f in project_root.glob("*withholding*.py"):
        if f not in candidate_files and _is_calculator_file(f.name):
            candidate_files.append(f)

    # Filter excludes
    candidate_files = [f for f in candidate_files if not any(ex in str(f) for ex in extra_excludes)]

    report.total_files_scanned = len(candidate_files)

    total = len(candidate_files)
    for idx, file_path in enumerate(candidate_files):
        if progress_callback:
            progress_callback(idx + 1, total)
        info = parse_calculator_file(file_path)
        if info is None:
            continue
        report.calculators.append(info)
        report.total_calculators_found += 1
        violations = validate_calculator(info, strict=strict)
        # Enrich with RCA if enabled
        if run_rca:
            for v in violations:
                if v.rca is None:
                    try:
                        exc = ValueError(v.message)
                        rca = _rca_analyze(exc, {"calculator": info.name, "class": info.class_name, "file": info.file})
                        if rca:
                            v.rca = rca
                    except Exception:
                        pass
        report.violations.extend(violations)

    # Check for missing expected calculators
    expected_files = set(EXPECTED_CALCULATORS.keys())
    found_files = {info.name for info in report.calculators}
    missing = expected_files - found_files
    for m in missing:
        report.violations.append(Violation(
            severity="INFO",
            file=m,
            line=0,
            message=f"Expected calculator file {m}.py not found ({EXPECTED_CALCULATORS.get(m, '')})",
            detail="This may be intentional if the calculator is not yet implemented.",
        ))

    errors = report.error_count
    warnings = report.warning_count
    report.score = max(0, min(100, 100 - errors * 15 - warnings * 2))
    report.scan_time = time.monotonic() - t0
    return report

# ─── REPORT ──────────────────────────────────────────────────────────────────
def print_report(report: Report, verbose: bool = False, show_rca: bool = False):
    c = COLOR
    _safe_print(f"\n{c['CYAN']}{'='*72}{c['RESET']}")
    _safe_print(f"{c['BOLD']}TAX IMPLEMENTATION CHECKER REPORT v{__version__}{c['RESET']}")
    _safe_print(f"{c['CYAN']}{'='*72}{c['RESET']}")
    _safe_print(f"  Files scanned: {report.total_files_scanned}")
    _safe_print(f"  Calculators  : {report.total_calculators_found}")
    _safe_print(f"  Violations   : {len(report.violations)}")
    _safe_print(f"    Errors     : {c['RED']}{report.error_count}{c['RESET']}")
    _safe_print(f"    Warnings   : {c['YELLOW']}{report.warning_count}{c['RESET']}")
    _safe_print(f"    Infos      : {c['DIM']}{report.info_count}{c['RESET']}")
    _safe_print(f"  Score        : {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")
    _safe_print(f"  RCA          : {'✅ Active' if _RCA_AVAILABLE else '⚠️ Fallback'}")
    _safe_print(f"  Time         : {report.scan_time:.3f}s")

    if verbose and report.calculators:
        _safe_print(f"\n{c['CYAN']}Calculator details:{c['RESET']}")
        for calc in report.calculators:
            _safe_print(f"\n  {calc.name} ({calc.class_name})")
            _safe_print(f"    calculate: {'✅' if calc.has_calculate else '❌'}")
            _safe_print(f"    validate: {'✅' if calc.has_validate else '❌'}")
            _safe_print(f"    get_rate: {'✅' if calc.has_get_rate else '❌'}")
            _safe_print(f"    Decimal: {'✅' if calc.uses_decimal else '❌'}")
            _safe_print(f"    Signature: {'✅' if calc.has_correct_signature else '❌'}")
            _safe_print(f"    Decimal return: {'✅' if calc.has_decimal_return else '❌'}")
            if calc.hardcoded_rates:
                _safe_print(f"    Hardcoded: {', '.join(calc.hardcoded_rates)}")

    if report.violations:
        _safe_print(f"\n{c['RED'] if report.error_count else c['YELLOW']}Violations:{c['RESET']}")
        for v in report.violations[:50]:
            color = c["RED"] if v.severity == "ERROR" else c["YELLOW"] if v.severity == "WARNING" else c["DIM"]
            _safe_print(f"  {color}[{v.severity}]{c['RESET']} {v.file}:{v.line}")
            _safe_print(f"     {v.message}")
            if verbose and v.detail:
                _safe_print(f"     {c['CYAN']}→ {v.detail}{c['RESET']}")
            if show_rca and v.rca:
                rc = v.rca.get("root_cause", "")
                fix = v.rca.get("suggested_fix", "")
                if rc:
                    _safe_print(f"     {c['MAGENTA']}RCA: {rc[:120]}{c['RESET']}")
                if fix:
                    _safe_print(f"     {c['MAGENTA']}Fix: {fix[:120]}{c['RESET']}")
        if len(report.violations) > 50:
            _safe_print(f"  ... and {len(report.violations)-50} more")
    else:
        _safe_print(f"\n{c['GREEN']}✅ No tax implementation violations found!{c['RESET']}")

    _safe_print(f"\n{c['CYAN']}{'─'*72}{c['RESET']}")
    if report.passed:
        _safe_print(f"  {c['GREEN']}✅ PASS — All tax calculators properly implemented.{c['RESET']}")
    else:
        _safe_print(f"  {c['RED']}❌ FAIL — {report.error_count} error(s) need fixing.{c['RESET']}")

# ─── EXPORT ──────────────────────────────────────────────────────────────────
def save_json(report: Report, path: pathlib.Path) -> bool:
    try:
        data = {
            "version": __version__,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "score": report.score,
            "passed": report.passed,
            "scan_time": report.scan_time,
            "files_scanned": report.total_files_scanned,
            "calculators_found": report.total_calculators_found,
            "calculators": [
                {
                    "file": c.file,
                    "name": c.name,
                    "class_name": c.class_name,
                    "has_calculate": c.has_calculate,
                    "has_validate": c.has_validate,
                    "has_get_rate": c.has_get_rate,
                    "uses_decimal": c.uses_decimal,
                    "hardcoded_rates": c.hardcoded_rates,
                    "methods": c.methods,
                    "has_correct_signature": c.has_correct_signature,
                    "has_decimal_return": c.has_decimal_return,
                }
                for c in report.calculators
            ],
            "violations": [v.to_dict() for v in report.violations],
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
            writer.writerow(["severity", "file", "line", "message", "detail"])
            for v in report.violations:
                writer.writerow([v.severity, v.file, v.line, v.message, v.detail])
        _safe_print(f"{_c('GREEN')}✅ CSV saved: {path}{_c('RESET')}")
        return True
    except Exception as e:
        _safe_print(f"{_c('RED')}❌ Failed to save CSV: {e}{_c('RESET')}")
        return False

def save_html(report: Report, path: pathlib.Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Tax Checker Report</title>
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
</style></head>
<body>
<h1>Tax Checker Report</h1>
<div class="summary">
  <div class="card"><div class="value">{len(report.calculators)}</div><div class="label">Calculators</div></div>
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
            if v.detail:
                html += f' <small>{v.detail}</small>'
            if v.rca:
                rc = v.rca.get("root_cause", "")[:120]
                if rc:
                    html += f'<br><small>RCA: {rc}</small>'
            html += f'<br><small>{v.file}:{v.line}</small></div>'
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

    if verbose: _safe_print(f"\nTax Checker self-test v{__version__}…\n")

    # Test _is_calculator_file
    check("_is_calculator_file ppn_calculator.py", _is_calculator_file("ppn_calculator.py"))
    check("_is_calculator_file __init__.py", not _is_calculator_file("__init__.py"))

    # Test _is_calculator_class
    code = """
class PPNCalculator:
    def calculate(self, amount):
        pass
"""
    tree = ast.parse(code)
    cls = _find_calculator_class(tree)
    check("_find_calculator_class finds PPNCalculator", cls is not None and cls.name == "PPNCalculator")

    # Test _has_decimal_import
    code2 = "from decimal import Decimal\nclass TaxCalc:\n    pass"
    tree2 = ast.parse(code2)
    check("_has_decimal_import detects import", _has_decimal_import(tree2))

    # Test _count_required_params
    code3 = """
class Calc:
    def calculate(self, amount, rate=0.1):
        pass
"""
    tree3 = ast.parse(code3)
    cls3 = _find_calculator_class(tree3)
    calc_node = _get_method_node(cls3, "calculate")
    req = _count_required_params(calc_node)
    check("_count_required_params (self, amount, rate=0.1) -> 1", req == 1)

    # Test _is_decimal_return
    code4 = """
from decimal import Decimal
class Calc:
    def calculate(self, amount):
        return Decimal(amount * 0.1)
"""
    tree4 = ast.parse(code4)
    cls4 = _find_calculator_class(tree4)
    calc_node4 = _get_method_node(cls4, "calculate")
    check("_is_decimal_return detects Decimal return", _is_decimal_return(calc_node4))

    # Test RCA availability
    check("RCA availability", True)

    if verbose: _safe_print(f"\nSelf-test: {passed} passed, {failed} failed {'✅' if failed==0 else '❌'}")
    return failed == 0

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description=f"Tax Implementation Checker v{__version__}")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE")
    parser.add_argument("--csv", metavar="FILE")
    parser.add_argument("--html", metavar="FILE")
    parser.add_argument("--strict", action="store_true", help="Make Decimal return type an ERROR")
    parser.add_argument("--no-rca", action="store_true")
    parser.add_argument("--self-test", action="store_true", dest="self_test")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--exclude", default="")
    parser.add_argument("--version", action="version", version=f"tax_checker v{__version__}")

    args = parser.parse_args()

    if args.self_test:
        return 0 if self_test(verbose=True) else 1

    project_root = pathlib.Path(__file__).resolve().parent.parent
    extra_excludes = set(args.exclude.split(",")) if args.exclude else set()

    report = scan_tax_implementations(
        project_root=project_root,
        extra_excludes=extra_excludes,
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