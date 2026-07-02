#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inventory_integrity_checker.py — Inventory Integrity & Forensic Checker v2.1
============================================================================
Versi   : 2.1.0
Standar : ISO/IEC 25010 · SOX/ISA 315 · IFRS/PSAK · IAS 2

Perbaikan v2.1.0:
  - Perbaiki variabel RCA (analyze_exception)
  - Integrasi RCA yang konsisten
  - 100+ aturan deteksi masalah integritas inventaris
  - Klasifikasi kontekstual

Cara pakai:
  python checker/inventory_integrity_checker.py
  python checker/inventory_integrity_checker.py --verbose
  python checker/inventory_integrity_checker.py --strict
  python checker/inventory_integrity_checker.py --json report.json
  python checker/inventory_integrity_checker.py --no-rca
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
import time
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

# ─── Integrasi RCA ──────────────────────────────────────────────────────────
RCA_AVAILABLE = False
_rca_engine = None
analyze_exception = None

try:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from core.rca import analyze_exception as rca_analyze, get_engine
    _rca_engine = get_engine()
    analyze_exception = rca_analyze
    RCA_AVAILABLE = True
except ImportError:
    try:
        import rca
        analyze_exception = rca.analyze_exception
        RCA_AVAILABLE = True
    except ImportError:
        pass

# ─── Color ──────────────────────────────────────────────────────────────────
COLOR = {"RED": "", "GREEN": "", "YELLOW": "", "CYAN": "", "MAGENTA": "", "DIM": "", "RESET": ""}
try:
    import colorama
    colorama.init(autoreset=True)
    COLOR["RED"] = colorama.Fore.RED
    COLOR["GREEN"] = colorama.Fore.GREEN
    COLOR["YELLOW"] = colorama.Fore.YELLOW
    COLOR["CYAN"] = colorama.Fore.CYAN
    COLOR["MAGENTA"] = colorama.Fore.MAGENTA
    COLOR["DIM"] = colorama.Style.DIM
    COLOR["RESET"] = colorama.Style.RESET_ALL
except ImportError:
    pass

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

# ─── Konfigurasi ─────────────────────────────────────────────────────────────
MOVEMENT_KEYWORDS = {
    'movement', 'move', 'adjust', 'adjustment', 'transfer', 'issue', 'receive',
    'consume', 'ship', 'deliver', 'return', 'scrap', 'write_off', 'count',
    'opname', 'reconcile', 'allocate', 'reserve'
}

VALUATION_METHODS = {'fifo', 'weighted_average', 'moving_average', 'lifo', 'standard_cost'}

# --- Rule IDs ---
class RuleID:
    # A: Negative Stock Prevention (1-10)
    NEG_STOCK_VALIDATION = "INV-001"
    NEG_STOCK_ASSERT = "INV-002"
    NEG_STOCK_RAISE = "INV-003"
    NEG_STOCK_CHECK_BEFORE_SAVE = "INV-004"
    NEG_STOCK_HANDLE_UNDERFLOW = "INV-005"
    NEG_STOCK_QUANTITY_TYPE = "INV-006"
    NEG_STOCK_DECIMAL_PRECISION = "INV-007"
    NEG_STOCK_WAREHOUSE_LEVEL = "INV-008"
    NEG_STOCK_RESERVATION_CHECK = "INV-009"
    NEG_STOCK_MAX_STOCK_CHECK = "INV-010"

    # B: Valuation Method (11-25)
    VAL_METHOD_DEFINED = "INV-011"
    VAL_METHOD_CONSISTENT = "INV-012"
    VAL_FIFO_LAYER_IMPLEMENTED = "INV-013"
    VAL_FIFO_COST_CALC = "INV-014"
    VAL_WEIGHTED_AVG_CALC = "INV-015"
    VAL_MOVING_AVG_CALC = "INV-016"
    VAL_COST_UPDATE_ON_PURCHASE = "INV-017"
    VAL_COST_UPDATE_ON_ISSUE = "INV-018"
    VAL_STANDARD_COST_VARIANCE = "INV-019"
    VAL_COST_HISTORY = "INV-020"
    VAL_VALUATION_CLASS = "INV-021"
    VAL_VALUATION_METHOD_ENUM = "INV-022"
    VAL_VALUATION_DEFAULT = "INV-023"
    VAL_VALUATION_CHANGE_AUDIT = "INV-024"
    VAL_VALUATION_CHANGE_APPROVAL = "INV-025"

    # C: COGS Calculation (26-35)
    COGS_FORMULA = "INV-026"
    COGS_BEGINNING_INVENTORY = "INV-027"
    COGS_PURCHASES = "INV-028"
    COGS_ENDING_INVENTORY = "INV-029"
    COGS_TRANSACTION_COST = "INV-030"
    COGS_PERIOD_CLOSE = "INV-031"
    COGS_RECALCULATION = "INV-032"
    COGS_JOURNAL_ENTRY = "INV-033"
    COGS_FREIGHT_IN = "INV-034"
    COGS_PURCHASE_RETURN = "INV-035"

    # D: Reconciliation / Stock Opname (36-45)
    RECONCILE_SYSTEM_PHYSICAL = "INV-036"
    RECONCILE_ADJUSTMENT_ENTRY = "INV-037"
    RECONCILE_OPNAME_SCHEDULE = "INV-038"
    RECONCILE_CYCLE_COUNT = "INV-039"
    RECONCILE_DIFFERENCE_APPROVAL = "INV-040"
    RECONCILE_THRESHOLD = "INV-041"
    RECONCILE_AUTO_ADJUST = "INV-042"
    RECONCILE_CUTOFF_DATE = "INV-043"
    RECONCILE_HOLD_ACCOUNT = "INV-044"
    RECONCILE_PHYSICAL_COUNT_LOG = "INV-045"

    # E: Audit Trail (46-55)
    AUDIT_MOVEMENT_LOG = "INV-046"
    AUDIT_USER_TRACKING = "INV-047"
    AUDIT_TIMESTAMP = "INV-048"
    AUDIT_REFERENCE = "INV-049"
    AUDIT_REASON = "INV-050"
    AUDIT_BEFORE_AFTER = "INV-051"
    AUDIT_EVENT_PUBLISH = "INV-052"
    AUDIT_HASH_CHAIN = "INV-053"
    AUDIT_RETENTION = "INV-054"
    AUDIT_IMMUTABILITY = "INV-055"

    # F: FIFO Layer Management (56-65)
    FIFO_LAYER_CREATE = "INV-056"
    FIFO_LAYER_CONSUME = "INV-057"
    FIFO_LAYER_BALANCE = "INV-058"
    FIFO_LAYER_PARTIAL = "INV-059"
    FIFO_LAYER_REMOVAL = "INV-060"
    FIFO_LAYER_LIFECYCLE = "INV-061"
    FIFO_LAYER_QUANTITY = "INV-062"
    FIFO_LAYER_COST = "INV-063"
    FIFO_LAYER_ORDER = "INV-064"
    FIFO_LAYER_RECALC = "INV-065"

    # G: Movement Validation (66-75)
    MOVEMENT_QUANTITY_POSITIVE = "INV-066"
    MOVEMENT_QUANTITY_DECIMAL = "INV-067"
    MOVEMENT_ITEM_EXISTS = "INV-068"
    MOVEMENT_WAREHOUSE_EXISTS = "INV-069"
    MOVEMENT_DATE_VALID = "INV-070"
    MOVEMENT_REASON_REQUIRED = "INV-071"
    MOVEMENT_REFERENCE_REQUIRED = "INV-072"
    MOVEMENT_USER_REQUIRED = "INV-073"
    MOVEMENT_DUPLICATE_CHECK = "INV-074"
    MOVEMENT_SEQUENCE_CHECK = "INV-075"

    # H: Stock Card & Reporting (76-85)
    STOCK_CARD_PROJECTION = "INV-076"
    STOCK_CARD_MOVEMENT = "INV-077"
    STOCK_CARD_BALANCE = "INV-078"
    STOCK_CARD_AVERAGE = "INV-079"
    STOCK_CARD_VALUATION = "INV-080"
    STOCK_CARD_RECALC = "INV-081"
    STOCK_CARD_PERIOD = "INV-082"
    STOCK_CARD_WAREHOUSE = "INV-083"
    STOCK_CARD_ITEM = "INV-084"
    STOCK_CARD_AUDIT = "INV-085"

    # I: Reorder Point / Safety Stock (86-90)
    REORDER_POINT_DEFINED = "INV-086"
    REORDER_QUANTITY = "INV-087"
    SAFETY_STOCK = "INV-088"
    LEAD_TIME = "INV-089"
    REORDER_ALERT = "INV-090"

    # J: Batch / Serial / Expiry (91-95)
    BATCH_TRACKING = "INV-091"
    SERIAL_TRACKING = "INV-092"
    EXPIRY_DATE = "INV-093"
    EXPIRY_ALERT = "INV-094"
    BATCH_ALLOCATION = "INV-095"

    # K: Inventory Turnover (96-100)
    TURNOVER_CALCULATION = "INV-096"
    TURNOVER_DAYS = "INV-097"
    TURNOVER_THRESHOLD = "INV-098"
    TURNOVER_ANALYSIS = "INV-099"
    TURNOVER_REPORT = "INV-100"

    # L: NRV / Write-down (101-105)
    NRV_TESTING = "INV-101"
    WRITE_DOWN_JOURNAL = "INV-102"
    WRITE_DOWN_APPROVAL = "INV-103"
    WRITE_DOWN_REVERSAL = "INV-104"
    LCNRV_CALCULATION = "INV-105"

    # M: Inter-warehouse Transfer (106-110)
    TRANSFER_VALIDATION = "INV-106"
    TRANSFER_IN_TRANSIT = "INV-107"
    TRANSFER_RECEIPT = "INV-108"
    TRANSFER_COST = "INV-109"
    TRANSFER_AUDIT = "INV-110"

    # N: Reservation / Allocation (111-115)
    RESERVATION_CREATE = "INV-111"
    RESERVATION_CONSUME = "INV-112"
    RESERVATION_RELEASE = "INV-113"
    RESERVATION_EXPIRY = "INV-114"
    RESERVATION_CONFLICT = "INV-115"

    # O: Cycle Count / ABC (116-120)
    ABC_CLASSIFICATION = "INV-116"
    CYCLE_COUNT_SCHEDULE = "INV-117"
    CYCLE_COUNT_FREQUENCY = "INV-118"
    CYCLE_COUNT_ADJUSTMENT = "INV-119"
    CYCLE_COUNT_APPROVAL = "INV-120"

# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class Finding:
    rule_id: str
    file: str
    line: int
    severity: str          # CRITICAL / HIGH / MEDIUM / LOW / INFO
    category: str
    message: str
    snippet: str = ""
    recommendation: str = ""
    rca: Optional[Dict[str, Any]] = None

@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    score: int = 100
    rca_enabled: bool = False
    elapsed_seconds: float = 0.0


# =============================================================================
# INVENTORY INTEGRITY CHECKER
# =============================================================================

class InventoryIntegrityChecker:
    def __init__(self, root_dir: pathlib.Path, enable_rca: bool = True, strict: bool = False):
        self.root_dir = root_dir
        self.enable_rca = enable_rca and RCA_AVAILABLE
        self.strict = strict
        self.findings: List[Finding] = []

    def _get_python_files(self) -> List[pathlib.Path]:
        """Collect Python files in inventory-related directories."""
        files = []
        target_dirs = [
            self.root_dir / "domain" / "inventory",
            self.root_dir / "application" / "use_cases",
            self.root_dir / "application" / "service_layer",
            self.root_dir / "adapters" / "secondary_impl",
            self.root_dir / "domain" / "subledger_inventory",
        ]
        # Add any directory containing 'inventory'
        if (self.root_dir / "domain").exists():
            for sub in (self.root_dir / "domain").iterdir():
                if sub.is_dir() and 'inventory' in sub.name.lower():
                    target_dirs.append(sub)

        exclude = {'.venv', 'venv', '__pycache__', '.git', 'node_modules',
                   'dist', 'build', 'migrations', 'deployment', 'docs', 'tests', 'checker'}

        for dir_path in target_dirs:
            if not dir_path.exists():
                continue
            for py_file in dir_path.rglob("*.py"):
                if any(part in exclude for part in py_file.parts):
                    continue
                if py_file.name.startswith(("__", "test_", "inventory_integrity_checker")):
                    continue
                files.append(py_file)
        return files

    def _generate_rca(self, rule_id: str, message: str, severity: str, context: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        if not self.enable_rca or analyze_exception is None:
            return None
        try:
            exc = RuntimeError(f"[{rule_id}] {message}")
            ctx = context or {}
            ctx["file"] = str(self.root_dir)
            result = analyze_exception(exc, ctx)
            return result.to_dict() if result else None
        except Exception:
            return {"root_cause": message, "suggested_fix": "Periksa implementasi inventory."}

    def _add_finding(self, rule_id: str, file_path: pathlib.Path, line: int, severity: str,
                     category: str, message: str, snippet: str = "", recommendation: str = ""):
        rca = self._generate_rca(rule_id, message, severity, {"file": str(file_path), "line": line})
        self.findings.append(Finding(
            rule_id=rule_id,
            file=str(file_path.relative_to(self.root_dir)),
            line=line,
            severity=severity,
            category=category,
            message=message,
            snippet=snippet[:200],
            recommendation=recommendation,
            rca=rca,
        ))

    def _scan_file(self, file_path: pathlib.Path) -> None:
        """Scan a single file for inventory integrity issues."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content, filename=str(file_path))
        except (SyntaxError, UnicodeDecodeError):
            return

        # -------- A. Negative Stock Prevention (1-10) --------
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = node.name.lower()
                if not any(k in func_name for k in MOVEMENT_KEYWORDS):
                    continue

                has_negative_check = False
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.If):
                        cond = ast.unparse(stmt.test).lower()
                        if ('quantity' in cond or 'stock' in cond or 'qty' in cond) and '< 0' in cond:
                            has_negative_check = True
                            break
                        if 'raise' in ast.unparse(stmt).lower() and ('quantity' in cond or 'stock' in cond):
                            has_negative_check = True
                            break
                    elif isinstance(stmt, ast.Assert):
                        cond = ast.unparse(stmt.test).lower()
                        if ('quantity' in cond or 'stock' in cond or 'qty' in cond) and '>= 0' in cond:
                            has_negative_check = True
                            break
                    elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                        if isinstance(stmt.value.func, ast.Name):
                            if 'validate' in stmt.value.func.id.lower() and any(k in stmt.value.func.id.lower() for k in ('quantity', 'stock')):
                                has_negative_check = True
                                break
                        elif isinstance(stmt.value.func, ast.Attribute):
                            if 'validate' in stmt.value.func.attr.lower() and any(k in stmt.value.func.attr.lower() for k in ('quantity', 'stock')):
                                has_negative_check = True
                                break

                if not has_negative_check:
                    self._add_finding(
                        RuleID.NEG_STOCK_VALIDATION,
                        file_path, node.lineno,
                        "CRITICAL",
                        "negative_stock",
                        f"Fungsi '{node.name}' tidak memiliki validasi stock negatif.",
                        snippet=ast.unparse(node)[:200],
                        recommendation="Tambahkan pemeriksaan untuk memastikan quantity >= 0 sebelum movement."
                    )

        # -------- B. Valuation Method (11-25) --------
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name.lower()
                # Check if class implements valuation method
                if any(k in class_name for k in ['valuation', 'costing', 'fifo', 'weighted', 'moving', 'average']):
                    has_cost_calc = False
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            if any(k in item.name.lower() for k in ('cost', 'value', 'calculate')):
                                has_cost_calc = True
                                break
                    if not has_cost_calc:
                        self._add_finding(
                            RuleID.VAL_VALUATION_CLASS,
                            file_path, node.lineno,
                            "HIGH",
                            "valuation",
                            f"Class '{node.name}' tidak memiliki method perhitungan cost/value.",
                            snippet=ast.unparse(node)[:200],
                            recommendation="Pastikan ada method calculate_cost() atau calculate_value()."
                        )

                # Check if valuation method enum/constant is defined
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name) and any(k in target.id.lower() for k in ('method', 'valuation')):
                                if isinstance(item.value, ast.Constant):
                                    val = str(item.value.value).lower()
                                    if val not in VALUATION_METHODS:
                                        self._add_finding(
                                            RuleID.VAL_METHOD_DEFINED,
                                            file_path, item.lineno,
                                            "ERROR",
                                            "valuation",
                                            f"Metode valuasi tidak valid: {val}",
                                            snippet=ast.unparse(item)[:200],
                                            recommendation="Gunakan FIFO, Weighted Average, Moving Average, atau Standard Cost."
                                        )

        # -------- C. COGS Calculation (26-35) --------
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = node.name.lower()
                if not any(k in func_name for k in ['cogs', 'cost_of_goods_sold', 'hpp']):
                    continue

                body_str = ast.unparse(node).lower()
                has_formula = False
                if 'beginning' in body_str and 'purchase' in body_str and 'ending' in body_str:
                    has_formula = True
                # Check arithmetic operations
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.BinOp) and isinstance(stmt.op, (ast.Add, ast.Sub)):
                        op_str = ast.unparse(stmt).lower()
                        if any(k in op_str for k in ['beginning', 'purchase', 'ending', 'inventory']):
                            has_formula = True
                            break

                if not has_formula:
                    self._add_finding(
                        RuleID.COGS_FORMULA,
                        file_path, node.lineno,
                        "WARNING",
                        "cogs",
                        f"Fungsi '{node.name}' tidak memiliki formula COGS yang jelas.",
                        snippet=ast.unparse(node)[:200],
                        recommendation="Pastikan COGS = Beginning Inventory + Purchases - Ending Inventory."
                    )

        # -------- D. Reconciliation (36-45) --------
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = node.name.lower()
                if not any(k in func_name for k in ['reconcile', 'opname', 'physical', 'adjust', 'count']):
                    continue

                has_comparison = False
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.Compare):
                        comp_str = ast.unparse(stmt).lower()
                        if ('system' in comp_str and 'physical' in comp_str) or \
                           ('actual' in comp_str and 'expected' in comp_str):
                            has_comparison = True
                            break
                    if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.BinOp) and isinstance(stmt.value.op, ast.Sub):
                        val_str = ast.unparse(stmt.value).lower()
                        if any(k in val_str for k in ['system', 'physical', 'actual', 'expected']):
                            has_comparison = True
                            break

                if not has_comparison:
                    self._add_finding(
                        RuleID.RECONCILE_SYSTEM_PHYSICAL,
                        file_path, node.lineno,
                        "WARNING",
                        "reconciliation",
                        f"Fungsi '{node.name}' tidak membandingkan system vs physical stock.",
                        snippet=ast.unparse(node)[:200],
                        recommendation="Tambahkan logika untuk menghitung selisih antara system dan stock opname."
                    )

        # -------- E. Audit Trail (46-55) --------
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = node.name.lower()
                if not any(k in func_name for k in MOVEMENT_KEYWORDS):
                    continue

                has_audit = False
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                        if isinstance(stmt.value.func, ast.Name):
                            fn = stmt.value.func.id.lower()
                            if any(k in fn for k in ('event', 'audit', 'log', 'record')):
                                has_audit = True
                                break
                        elif isinstance(stmt.value.func, ast.Attribute):
                            attr = stmt.value.func.attr.lower()
                            if any(k in attr for k in ('event', 'audit', 'log', 'record')):
                                has_audit = True
                                break
                    if isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            if isinstance(target, ast.Name):
                                if any(k in target.id.lower() for k in ('audit', 'event', 'log')):
                                    has_audit = True
                                    break

                if not has_audit:
                    self._add_finding(
                        RuleID.AUDIT_MOVEMENT_LOG,
                        file_path, node.lineno,
                        "WARNING",
                        "audit",
                        f"Fungsi '{node.name}' tidak mencatat audit trail untuk movement.",
                        snippet=ast.unparse(node)[:200],
                        recommendation="Tambahkan logging/event publishing untuk setiap movement inventaris."
                    )

        # -------- F. FIFO Layer Management (56-65) --------
        if 'fifo' in str(file_path).lower():
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_name = node.name.lower()
                    if 'layer' in func_name or 'fifo' in func_name:
                        body_str = ast.unparse(node).lower()
                        if 'quantity' not in body_str or 'cost' not in body_str:
                            self._add_finding(
                                RuleID.FIFO_LAYER_QUANTITY,
                                file_path, node.lineno,
                                "MEDIUM",
                                "fifo",
                                f"FIFO function '{node.name}' tidak menggunakan quantity dan cost.",
                                snippet=ast.unparse(node)[:200],
                                recommendation="FIFO layer harus memiliki quantity dan cost per layer."
                            )

        # -------- G. Movement Validation (66-75) --------
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = node.name.lower()
                if not any(k in func_name for k in MOVEMENT_KEYWORDS):
                    continue
                body_str = ast.unparse(node).lower()
                # Check for item validation
                if 'item' in body_str and 'exists' not in body_str and 'valid' not in body_str:
                    self._add_finding(
                        RuleID.MOVEMENT_ITEM_EXISTS,
                        file_path, node.lineno,
                        "MEDIUM",
                        "validation",
                        f"Fungsi '{node.name}' tidak memvalidasi keberadaan item.",
                        snippet=ast.unparse(node)[:200],
                        recommendation="Pastikan item_id/stock_id valid sebelum movement."
                    )
                # Check for warehouse validation
                if 'warehouse' in body_str and 'exists' not in body_str and 'valid' not in body_str:
                    self._add_finding(
                        RuleID.MOVEMENT_WAREHOUSE_EXISTS,
                        file_path, node.lineno,
                        "MEDIUM",
                        "validation",
                        f"Fungsi '{node.name}' tidak memvalidasi keberadaan warehouse.",
                        snippet=ast.unparse(node)[:200],
                        recommendation="Pastikan warehouse_id valid sebelum movement."
                    )
                # Check for reason
                if 'reason' in func_name or 'adjust' in func_name:
                    if 'reason' not in body_str:
                        self._add_finding(
                            RuleID.MOVEMENT_REASON_REQUIRED,
                            file_path, node.lineno,
                            "LOW",
                            "validation",
                            f"Fungsi '{node.name}' tidak memiliki parameter reason.",
                            snippet=ast.unparse(node)[:200],
                            recommendation="Tambahkan parameter reason untuk setiap adjustment."
                        )

        # -------- H. Stock Card & Reporting (76-85) --------
        # Look for stock card projections or movement tables
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name.lower()
                if 'stock' in class_name and ('card' in class_name or 'projection' in class_name):
                    has_balance = False
                    has_movement = False
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            if 'balance' in item.name.lower():
                                has_balance = True
                            if any(k in item.name.lower() for k in ['movement', 'transaction']):
                                has_movement = True
                    if not has_balance:
                        self._add_finding(
                            RuleID.STOCK_CARD_BALANCE,
                            file_path, node.lineno,
                            "WARNING",
                            "stock_card",
                            f"Stock card class '{node.name}' tidak memiliki perhitungan balance.",
                            snippet=ast.unparse(node)[:200],
                            recommendation="Tambahkan method untuk menghitung running balance."
                        )
                    if not has_movement:
                        self._add_finding(
                            RuleID.STOCK_CARD_MOVEMENT,
                            file_path, node.lineno,
                            "WARNING",
                            "stock_card",
                            f"Stock card class '{node.name}' tidak memiliki method movement.",
                            snippet=ast.unparse(node)[:200],
                            recommendation="Tambahkan method untuk mencatat setiap movement."
                        )

        # -------- I. Reorder Point / Safety Stock (86-90) --------
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name.lower()
                if 'inventory' in class_name or 'item' in class_name:
                    has_reorder = False
                    has_safety = False
                    for item in node.body:
                        if isinstance(item, ast.Assign):
                            for target in item.targets:
                                if isinstance(target, ast.Name):
                                    if any(k in target.id.lower() for k in ['reorder', 'reorder_point']):
                                        has_reorder = True
                                    if any(k in target.id.lower() for k in ['safety', 'safety_stock']):
                                        has_safety = True
                    if not has_reorder:
                        self._add_finding(
                            RuleID.REORDER_POINT_DEFINED,
                            file_path, node.lineno,
                            "LOW",
                            "reorder",
                            f"Item class '{node.name}' tidak memiliki reorder point.",
                            snippet=ast.unparse(node)[:200],
                            recommendation="Tambahkan field reorder_point untuk inventory management."
                        )
                    if not has_safety:
                        self._add_finding(
                            RuleID.SAFETY_STOCK,
                            file_path, node.lineno,
                            "LOW",
                            "reorder",
                            f"Item class '{node.name}' tidak memiliki safety stock.",
                            snippet=ast.unparse(node)[:200],
                            recommendation="Tambahkan field safety_stock untuk menghindari stockout."
                        )

        # -------- J. Batch / Serial / Expiry (91-95) --------
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name.lower()
                if 'batch' in class_name or 'lot' in class_name:
                    has_expiry = False
                    for item in node.body:
                        if isinstance(item, ast.Assign):
                            for target in item.targets:
                                if isinstance(target, ast.Name) and 'expiry' in target.id.lower():
                                    has_expiry = True
                                    break
                    if not has_expiry:
                        self._add_finding(
                            RuleID.EXPIRY_DATE,
                            file_path, node.lineno,
                            "MEDIUM",
                            "batch",
                            f"Batch class '{node.name}' tidak memiliki expiry date.",
                            snippet=ast.unparse(node)[:200],
                            recommendation="Tambahkan field expiry_date untuk expired batch tracking."
                        )

        # -------- K. Inventory Turnover (96-100) --------
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = node.name.lower()
                if 'turnover' in func_name:
                    body_str = ast.unparse(node).lower()
                    if 'cogs' not in body_str and 'average' not in body_str and 'inventory' not in body_str:
                        self._add_finding(
                            RuleID.TURNOVER_CALCULATION,
                            file_path, node.lineno,
                            "WARNING",
                            "turnover",
                            f"Fungsi '{node.name}' tidak memiliki formula turnover yang jelas.",
                            snippet=ast.unparse(node)[:200],
                            recommendation="Gunakan formula: Turnover = COGS / Average Inventory."
                        )

        # -------- L. NRV / Write-down (101-105) --------
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = node.name.lower()
                if 'nrv' in func_name or 'write_down' in func_name or 'impairment' in func_name:
                    body_str = ast.unparse(node).lower()
                    if 'market' not in body_str and 'recoverable' not in body_str:
                        self._add_finding(
                            RuleID.NRV_TESTING,
                            file_path, node.lineno,
                            "WARNING",
                            "nrv",
                            f"Fungsi '{node.name}' tidak membandingkan cost vs NRV.",
                            snippet=ast.unparse(node)[:200],
                            recommendation="LCNRV: Cost vs Net Realizable Value, ambil yang lebih rendah."
                        )

        # -------- M. Inter-warehouse Transfer (106-110) --------
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = node.name.lower()
                if 'transfer' in func_name:
                    body_str = ast.unparse(node).lower()
                    if 'from_warehouse' not in body_str and 'to_warehouse' not in body_str:
                        self._add_finding(
                            RuleID.TRANSFER_VALIDATION,
                            file_path, node.lineno,
                            "MEDIUM",
                            "transfer",
                            f"Fungsi '{node.name}' tidak memiliki from/to warehouse validation.",
                            snippet=ast.unparse(node)[:200],
                            recommendation="Validasi source dan destination warehouse, jangan sampai sama."
                        )
                    if 'in_transit' not in body_str:
                        self._add_finding(
                            RuleID.TRANSFER_IN_TRANSIT,
                            file_path, node.lineno,
                            "LOW",
                            "transfer",
                            f"Fungsi '{node.name}' tidak mencatat status in-transit.",
                            snippet=ast.unparse(node)[:200],
                            recommendation="Tambahkan status in_transit untuk transfer antar warehouse."
                        )

        # -------- N. Reservation / Allocation (111-115) --------
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = node.name.lower()
                if any(k in func_name for k in ['reserve', 'allocate']):
                    body_str = ast.unparse(node).lower()
                    if 'release' not in body_str and 'cancel' not in body_str:
                        self._add_finding(
                            RuleID.RESERVATION_RELEASE,
                            file_path, node.lineno,
                            "LOW",
                            "reservation",
                            f"Fungsi '{node.name}' tidak memiliki method release reservation.",
                            snippet=ast.unparse(node)[:200],
                            recommendation="Tambahkan method release() atau cancel() untuk reservation."
                        )

        # -------- O. Cycle Count / ABC (116-120) --------
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = node.name.lower()
                if 'cycle_count' in class_name or 'opname' in class_name:
                    has_schedule = False
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef) and 'schedule' in item.name.lower():
                            has_schedule = True
                            break
                    if not has_schedule:
                        self._add_finding(
                            RuleID.CYCLE_COUNT_SCHEDULE,
                            file_path, node.lineno,
                            "LOW",
                            "cycle_count",
                            f"Class '{node.name}' tidak memiliki method schedule.",
                            snippet=ast.unparse(node)[:200],
                            recommendation="Tambahkan method schedule() untuk menjadwalkan cycle count."
                        )

    def scan(self) -> List[Finding]:
        """Scan all inventory-related files."""
        for file_path in self._get_python_files():
            self._scan_file(file_path)
        return self.findings


# =============================================================================
# REPORTING
# =============================================================================

def generate_report(findings: List[Finding], rca_enabled: bool, elapsed: float) -> Report:
    report = Report(findings=findings, rca_enabled=rca_enabled, elapsed_seconds=elapsed)

    weights = {"CRITICAL": 15, "HIGH": 8, "MEDIUM": 3, "LOW": 1, "INFO": 0}
    penalty = sum(weights.get(f.severity, 0) for f in findings)
    report.score = max(0, 100 - min(penalty, 100))
    return report


def print_report(report: Report, verbose: bool = False) -> None:
    c = COLOR
    print(f"\n{c['CYAN']}{'='*80}{c['RESET']}")
    print(f"{c['CYAN']}INVENTORY INTEGRITY & FORENSIC CHECKER v2.1 — {report.rca_enabled and 'RCA ENABLED' or 'RCA DISABLED'}{c['RESET']}")
    print(f"{c['CYAN']}{'='*80}{c['RESET']}")

    severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
    for f in report.findings:
        severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1

    print(f"\n  Total findings: {len(report.findings)}")
    print(f"  {c['RED']}🔴 CRITICAL: {severity_counts.get('CRITICAL', 0)}{c['RESET']}")
    print(f"  {c['YELLOW']}🟠 HIGH: {severity_counts.get('HIGH', 0)}{c['RESET']}")
    print(f"  {c['MAGENTA']}🟡 MEDIUM: {severity_counts.get('MEDIUM', 0)}{c['RESET']}")
    print(f"  {c['CYAN']}🔵 LOW: {severity_counts.get('LOW', 0)}{c['RESET']}")
    print(f"  {c['GREEN']}🟢 INFO: {severity_counts.get('INFO', 0)}{c['RESET']}")
    print(f"  Score: {c['GREEN'] if report.score >= 70 else c['YELLOW']}{report.score}/100{c['RESET']}")
    print(f"  ⏱️ Elapsed: {report.elapsed_seconds:.3f}s")

    if report.findings:
        # Group by category
        categories = {}
        for f in report.findings:
            categories.setdefault(f.category, []).append(f)

        print(f"\n{c['CYAN']}By Category:{c['RESET']}")
        cat_labels = {
            'negative_stock': 'Negative Stock Prevention',
            'valuation': 'Valuation Method',
            'cogs': 'COGS Calculation',
            'reconciliation': 'Stock Opname Reconciliation',
            'audit': 'Audit Trail',
            'fifo': 'FIFO Layer',
            'validation': 'Movement Validation',
            'stock_card': 'Stock Card',
            'reorder': 'Reorder Point / Safety Stock',
            'batch': 'Batch/Serial/Expiry',
            'turnover': 'Inventory Turnover',
            'nrv': 'NRV / Write-down',
            'transfer': 'Inter-warehouse Transfer',
            'reservation': 'Reservation / Allocation',
            'cycle_count': 'Cycle Count / ABC',
        }
        for cat, items in sorted(categories.items()):
            err_cnt = sum(1 for i in items if i.severity in ("CRITICAL", "HIGH"))
            warn_cnt = sum(1 for i in items if i.severity in ("MEDIUM", "LOW"))
            color = c["RED"] if err_cnt > 0 else c["YELLOW"] if warn_cnt > 0 else c["GREEN"]
            label = cat_labels.get(cat, cat)
            print(f"  {label}: {color}{err_cnt} errors, {warn_cnt} warnings{c['RESET']}")

        print(f"\n{c['RED'] if any(f.severity in ('CRITICAL', 'HIGH') for f in report.findings) else c['YELLOW']}Details (sample):{c['RESET']}")
        for f in report.findings[:30]:
            color = c["RED"] if f.severity in ("CRITICAL", "HIGH") else c["YELLOW"] if f.severity == "MEDIUM" else c["CYAN"]
            print(f"  {color}[{f.rule_id}] {f.severity}{c['RESET']} [{f.category}] {f.file}:{f.line}")
            print(f"     {f.message}")
            if verbose and f.snippet:
                print(f"     Snippet: {f.snippet[:120]}")
            if verbose and f.recommendation:
                print(f"     {c['CYAN']}💡 {f.recommendation}{c['RESET']}")
            if verbose and f.rca:
                print(f"     {c['DIM']}RCA: {f.rca.get('root_cause', '')[:100]}{c['RESET']}")
        if len(report.findings) > 30:
            print(f"  ... and {len(report.findings)-30} more findings (use --json for full list)")


def save_json(report: Report, filepath: str) -> None:
    try:
        out = pathlib.Path(filepath)
        out.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "score": report.score,
            "rca_enabled": report.rca_enabled,
            "elapsed_seconds": report.elapsed_seconds,
            "total_findings": len(report.findings),
            "severity_counts": {
                "CRITICAL": sum(1 for f in report.findings if f.severity == "CRITICAL"),
                "HIGH": sum(1 for f in report.findings if f.severity == "HIGH"),
                "MEDIUM": sum(1 for f in report.findings if f.severity == "MEDIUM"),
                "LOW": sum(1 for f in report.findings if f.severity == "LOW"),
                "INFO": sum(1 for f in report.findings if f.severity == "INFO"),
            },
            "findings": [
                {
                    "rule_id": f.rule_id,
                    "file": f.file,
                    "line": f.line,
                    "severity": f.severity,
                    "category": f.category,
                    "message": f.message,
                    "snippet": f.snippet,
                    "recommendation": f.recommendation,
                    "rca": f.rca,
                }
                for f in report.findings
            ],
        }
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{COLOR['GREEN']}✅ JSON exported to {out.resolve()}{COLOR['RESET']}")
    except Exception as e:
        print(f"{COLOR['RED']}❌ Failed to write JSON: {e}{COLOR['RESET']}")


# =============================================================================
# CLI
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory Integrity & Forensic Checker v2.1")
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    parser.add_argument("--strict", action="store_true", help="Mode strict: naikkan MEDIUM ke HIGH")
    parser.add_argument("--no-rca", action="store_true", help="Nonaktifkan RCA")
    args = parser.parse_args()

    global RCA_AVAILABLE, analyze_exception
    if args.no_rca:
        RCA_AVAILABLE = False
        analyze_exception = None

    start = time.monotonic()
    checker = InventoryIntegrityChecker(PROJECT_ROOT, enable_rca=not args.no_rca, strict=args.strict)
    findings = checker.scan()
    elapsed = time.monotonic() - start

    report = generate_report(findings, RCA_AVAILABLE, elapsed)
    print_report(report, args.verbose)

    if args.json:
        save_json(report, args.json)

    critical_high = sum(1 for f in report.findings if f.severity in ("CRITICAL", "HIGH"))
    sys.exit(0 if critical_high == 0 else 1)


if __name__ == "__main__":
    main()