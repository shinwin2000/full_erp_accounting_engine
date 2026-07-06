#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inventory_integrity_checker.py — Inventory Integrity Checker v3.3
============================================================================
Versi   : 3.3.0
Standar : ISO/IEC 25010 · SOX/ISA 315 · IFRS/PSAK · IAS 2

Perbaikan v3.3.0:
  - Cycle count: hanya class dengan nama CycleCount/PhysicalCount atau yang memiliki field opname_id
  - Valuation: hanya class yang merupakan subclass ValuationMethodStrategy atau berakhiran Valuation
  - FIFO consume: tidak dianggap mutasi
  - Receive: inbound method tidak perlu validasi stock negatif
  - Repository methods: di-skip dari audit trail dan validasi
  - Reconciliation: hanya untuk domain inventory
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

# ─── Integrasi RCA ──────────────────────────────────────────────────────────
RCA_AVAILABLE = False
_analyze_exception = None

try:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from core.rca import analyze_exception as rca_analyze, get_engine
    _analyze_exception = rca_analyze
    RCA_AVAILABLE = True
except ImportError:
    try:
        import rca
        _analyze_exception = rca.analyze_exception
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

MUTATION_KEYWORDS = {
    'issue', 'consume', 'transfer', 'adjust', 'write_off', 'return',
    'receive', 'receipt', 'ship', 'allocate', 'reserve', 'move',
    'outbound', 'inbound'
}

SKIP_METHODS = {
    'count', 'identifier', 'get_', 'is_', 'has_', 'to_dict', 'from_dict',
    'clone', 'snapshot', 'version', 'audit_trail', 'validate', '_validate',
    '_check', '_record_audit', '_record', '_log', '__post_init__', '__init__',
    '__repr__', '__str__', '__eq__', '__hash__', 'schema', 'config', 'settings',
    'meta', 'metadata', 'field', 'fields', 'save', 'delete', 'update', 'create',
    'from_movements', 'movement_identifier', 'movement_id', 'remove_empty_layers',
    '_check_rapid_movement', 'add_movement', 'record_movement', 'adjust_stock'
}

SKIP_CLASS_NAMES = {
    'Event', 'Command', 'DTO', 'Request', 'Response', 'Repository',
    'Protocol', 'Mixin', 'ValueObject', 'Projection', 'Aggregate', 'Factory',
    'Service', 'Handler', 'UseCase', 'Controller', 'Port', 'Adapter',
    'Result', 'Summary', 'Entry', 'Item', 'Status', 'Reason', 'Type',
    'NotFoundError', 'ServiceError'
}
SKIP_FILES = {'domain_events.py'}

# ─── Data Classes ───────────────────────────────────────────────────────────
@dataclass
class Finding:
    rule_id: str
    file: str
    line: int
    severity: str
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


# ─── Rule IDs ───────────────────────────────────────────────────────────────
class RuleID:
    NEG_STOCK_VALIDATION = "INV-001"
    VAL_VALUATION_CLASS = "INV-021"
    RECONCILE_COMPARE = "INV-036"
    AUDIT_MOVEMENT_LOG = "INV-046"
    MOVEMENT_ITEM_EXISTS = "INV-068"
    MOVEMENT_WAREHOUSE_EXISTS = "INV-069"
    REORDER_POINT = "INV-086"
    SAFETY_STOCK = "INV-088"
    TRANSFER_VALIDATION = "INV-106"
    TRANSFER_IN_TRANSIT = "INV-107"
    CYCLE_SCHEDULE = "INV-117"


# ─── Checker ────────────────────────────────────────────────────────────────
class InventoryIntegrityChecker:
    def __init__(self, root_dir: pathlib.Path, enable_rca: bool = True):
        self.root_dir = root_dir
        self.enable_rca = enable_rca and RCA_AVAILABLE
        self.findings: List[Finding] = []

    def _get_relevant_files(self) -> List[pathlib.Path]:
        files = []
        target_patterns = [
            "domain/inventory",
            "domain/subledger_inventory",
            "application/use_cases",
            "application/service_layer",
            "adapters/secondary_impl",
        ]
        domain_root = self.root_dir / "domain"
        if domain_root.exists():
            for sub in domain_root.iterdir():
                if sub.is_dir() and 'inventory' in sub.name.lower():
                    target_patterns.append(f"domain/{sub.name}")

        exclude = {'.venv', 'venv', '__pycache__', '.git', 'node_modules',
                   'dist', 'build', 'migrations', 'deployment', 'docs', 'tests', 'checker'}

        for pattern in target_patterns:
            dir_path = self.root_dir / pattern
            if not dir_path.exists():
                continue
            for py_file in dir_path.rglob("*.py"):
                if any(part in exclude for part in py_file.parts):
                    continue
                if py_file.name.startswith(("__", "test_", "inventory_integrity_checker")):
                    continue
                if py_file.name in SKIP_FILES:
                    continue
                files.append(py_file)
        return files

    def _is_enum_class(self, class_node: ast.ClassDef) -> bool:
        for base in class_node.bases:
            if isinstance(base, ast.Name) and base.id in ('Enum', 'StrEnum'):
                return True
            if isinstance(base, ast.Attribute) and base.attr in ('Enum', 'StrEnum'):
                return True
        return False

    def _is_item_class(self, class_node: ast.ClassDef) -> bool:
        if self._is_enum_class(class_node):
            return False
        name = class_node.name
        if any(k in name for k in SKIP_CLASS_NAMES):
            return False
        if not any(k in name.lower() for k in ('item', 'stock', 'inventory', 'product')):
            return False
        has_stock_attr = False
        for item in class_node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        if target.id.lower() in ('current_stock', 'quantity', 'reorder_point', 'safety_stock', 'stock'):
                            has_stock_attr = True
                            break
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                if item.target.id.lower() in ('current_stock', 'quantity', 'reorder_point', 'safety_stock', 'stock'):
                    has_stock_attr = True
                    break
        return has_stock_attr

    def _is_valuation_class(self, class_node: ast.ClassDef) -> bool:
        if self._is_enum_class(class_node):
            return False
        name = class_node.name
        if any(k in name for k in SKIP_CLASS_NAMES):
            return False
        # Only classes that are strategies or have "Valuation" suffix
        if name.endswith('Valuation') or name in ('FIFOValuation', 'LIFOValuation', 'AverageValuation',
                                                  'MovingAverageValuation', 'StandardCostValuation',
                                                  'SpecificIdentificationValuation'):
            # Check if it's a child class with no override, but we'll just check method existence
            pass
        else:
            return False
        # Check if it's a subclass of ValuationMethodStrategy or has calculate_cost
        has_cost_method = False
        for item in class_node.body:
            if isinstance(item, ast.FunctionDef) and any(k in item.name.lower() for k in ('cost', 'value', 'calculate')):
                has_cost_method = True
                break
        # If it's a simple alias (like WeightedAverageValuation), it inherits from parent, so allow
        if not has_cost_method:
            # Check if parent class has method
            for base in class_node.bases:
                if isinstance(base, ast.Name) and base.id in ('AverageValuation', 'FIFOValuation', 'ValuationMethodStrategy'):
                    # Parent likely has method, so skip
                    return False
        return not has_cost_method

    def _is_cycle_count_class(self, class_node: ast.ClassDef) -> bool:
        if self._is_enum_class(class_node):
            return False
        name = class_node.name
        if any(k in name for k in ('Repository', 'Command', 'Result', 'UseCase', 'Request', 'Response')):
            return False
        if 'CycleCount' in name or 'PhysicalCount' in name:
            return True
        if 'opname' in name.lower():
            # Must have opname_id or items field
            has_opname_attr = False
            for item in class_node.body:
                if isinstance(item, (ast.Assign, ast.AnnAssign)):
                    if isinstance(item.target, ast.Name):
                        if item.target.id in ('opname_id', 'items', 'opname_date'):
                            has_opname_attr = True
                            break
            return has_opname_attr
        return False

    def _is_mutation_function(self, func_node: ast.FunctionDef, file_path: pathlib.Path) -> bool:
        name = func_node.name.lower()
        if any(name.startswith(p) for p in SKIP_METHODS):
            return False
        if any(k in name for k in ['get', 'fetch', 'find', 'list', 'search', 'count', 'exists', 'calculate', 'from_']):
            return False
        if name.startswith('_'):
            return False
        # Skip consume in valuation file
        if name == 'consume' and 'valuation_method' in str(file_path):
            return False
        if not any(k in name for k in MUTATION_KEYWORDS):
            return False
        # Must have assignment to stock/quantity/current_stock
        body_str = ast.unparse(func_node).lower()
        has_state_change = 'current_stock' in body_str or 'stock' in body_str or 'quantity' in body_str
        has_assign = '=' in body_str
        return has_state_change and has_assign

    def _is_transfer_function(self, func_node: ast.FunctionDef) -> bool:
        name = func_node.name.lower()
        if not any(k in name for k in ('transfer', 'move')):
            return False
        params = [arg.arg for arg in func_node.args.args]
        has_from = any('from' in p.lower() or 'source' in p.lower() for p in params)
        has_to = any('to' in p.lower() or 'dest' in p.lower() for p in params)
        has_warehouse = any('warehouse' in p.lower() for p in params)
        return has_from and has_to and has_warehouse

    def _generate_rca(self, rule_id: str, message: str, severity: str, context: Dict) -> Optional[Dict]:
        if not self.enable_rca or _analyze_exception is None:
            return None
        try:
            exc = RuntimeError(f"[{rule_id}] {message}")
            result = _analyze_exception(exc, context)
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
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content, filename=str(file_path))
        except (SyntaxError, UnicodeDecodeError):
            return

        # -------- 1. Negative Stock Prevention (outbound only) --------
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not self._is_mutation_function(node, file_path):
                continue
            # Skip receive method (inbound)
            if node.name.lower() == 'receive' and 'inter_warehouse_transfer' in str(file_path):
                continue
            # Skip repository internal methods
            if 'repository' in str(file_path).lower() and node.name.lower() in ('add_movement', 'record_movement', 'adjust_stock'):
                continue

            has_neg_check = False
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.If):
                    cond = ast.unparse(stmt.test).lower()
                    if ('quantity' in cond or 'stock' in cond or 'qty' in cond) and ('< 0' in cond or '>= 0' in cond):
                        has_neg_check = True
                        break
                    if 'raise' in ast.unparse(stmt).lower() and ('quantity' in cond or 'stock' in cond):
                        has_neg_check = True
                        break
                elif isinstance(stmt, ast.Assert):
                    cond = ast.unparse(stmt.test).lower()
                    if ('quantity' in cond or 'stock' in cond or 'qty' in cond) and '>= 0' in cond:
                        has_neg_check = True
                        break
                elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    if isinstance(stmt.value.func, ast.Name):
                        if any(k in stmt.value.func.id.lower() for k in ('validate', 'check', 'assert')) and \
                           any(k in stmt.value.func.id.lower() for k in ('quantity', 'stock', 'qty')):
                            has_neg_check = True
                            break
                    elif isinstance(stmt.value.func, ast.Attribute):
                        attr = stmt.value.func.attr.lower()
                        if any(k in attr for k in ('validate', 'check', 'assert')) and \
                           any(k in attr for k in ('quantity', 'stock', 'qty')):
                            has_neg_check = True
                            break
            if not has_neg_check:
                self._add_finding(
                    RuleID.NEG_STOCK_VALIDATION,
                    file_path, node.lineno,
                    "CRITICAL",
                    "negative_stock",
                    f"Fungsi mutasi '{node.name}' tidak memiliki validasi stock negatif.",
                    snippet=ast.unparse(node)[:200],
                    recommendation="Tambahkan pengecekan quantity >= 0 sebelum movement."
                )

        # -------- 2. Valuation Method --------
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not self._is_valuation_class(node):
                continue
            # Already filtered, add finding
            self._add_finding(
                RuleID.VAL_VALUATION_CLASS,
                file_path, node.lineno,
                "HIGH",
                "valuation",
                f"Valuation class '{node.name}' tidak memiliki method perhitungan cost/value.",
                snippet=ast.unparse(node)[:200],
                recommendation="Tambahkan method calculate_cost() atau calculate_value()."
            )

        # -------- 3. Reorder Point & Safety Stock --------
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not self._is_item_class(node):
                continue
            has_reorder = False
            has_safety = False
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            if 'reorder' in target.id.lower():
                                has_reorder = True
                            if 'safety' in target.id.lower():
                                has_safety = True
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    if 'reorder' in item.target.id.lower():
                        has_reorder = True
                    if 'safety' in item.target.id.lower():
                        has_safety = True
            if not has_reorder:
                self._add_finding(
                    RuleID.REORDER_POINT,
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

        # -------- 4. Audit Trail --------
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not self._is_mutation_function(node, file_path):
                continue
            if 'repository' in str(file_path).lower():
                continue
            has_audit = False
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    if isinstance(stmt.value.func, ast.Name):
                        if any(k in stmt.value.func.id.lower() for k in ('event', 'audit', 'log', 'record')):
                            has_audit = True
                            break
                    elif isinstance(stmt.value.func, ast.Attribute):
                        attr = stmt.value.func.attr.lower()
                        if any(k in attr for k in ('event', 'audit', 'log', 'record')):
                            has_audit = True
                            break
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name) and any(k in target.id.lower() for k in ('audit', 'event', 'log')):
                            has_audit = True
                            break
            if not has_audit:
                self._add_finding(
                    RuleID.AUDIT_MOVEMENT_LOG,
                    file_path, node.lineno,
                    "WARNING",
                    "audit",
                    f"Fungsi mutasi '{node.name}' tidak mencatat audit trail.",
                    snippet=ast.unparse(node)[:200],
                    recommendation="Tambahkan event/audit logging untuk setiap movement."
                )

        # -------- 5. Movement Validation --------
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not self._is_mutation_function(node, file_path):
                continue
            if 'repository' in str(file_path).lower():
                continue
            body_str = ast.unparse(node).lower()
            if 'item' in body_str and 'exists' not in body_str and 'valid' not in body_str and 'is not none' not in body_str:
                self._add_finding(
                    RuleID.MOVEMENT_ITEM_EXISTS,
                    file_path, node.lineno,
                    "MEDIUM",
                    "validation",
                    f"Fungsi mutasi '{node.name}' tidak memvalidasi keberadaan item.",
                    snippet=ast.unparse(node)[:200],
                    recommendation="Pastikan item_id valid sebelum movement."
                )
            if 'warehouse' in body_str and 'exists' not in body_str and 'valid' not in body_str:
                self._add_finding(
                    RuleID.MOVEMENT_WAREHOUSE_EXISTS,
                    file_path, node.lineno,
                    "MEDIUM",
                    "validation",
                    f"Fungsi mutasi '{node.name}' tidak memvalidasi keberadaan warehouse.",
                    snippet=ast.unparse(node)[:200],
                    recommendation="Pastikan warehouse_id valid sebelum movement."
                )

        # -------- 6. Reconciliation (only in inventory domain) --------
        if 'inventory' in str(file_path).lower():
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                name = node.name.lower()
                if 'count' in name:
                    continue
                if not any(k in name for k in ('reconcile', 'opname', 'physical')):
                    continue
                body_str = ast.unparse(node).lower()
                if ('system' not in body_str or 'physical' not in body_str) and \
                   ('actual' not in body_str or 'expected' not in body_str):
                    self._add_finding(
                        RuleID.RECONCILE_COMPARE,
                        file_path, node.lineno,
                        "WARNING",
                        "reconciliation",
                        f"Fungsi '{node.name}' tidak membandingkan system vs physical stock.",
                        snippet=ast.unparse(node)[:200],
                        recommendation="Bandingkan system stock dengan hasil stock opname."
                    )

        # -------- 7. Transfer validation --------
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not self._is_transfer_function(node):
                continue
            body_str = ast.unparse(node).lower()
            if 'from_warehouse' not in body_str and 'to_warehouse' not in body_str:
                self._add_finding(
                    RuleID.TRANSFER_VALIDATION,
                    file_path, node.lineno,
                    "MEDIUM",
                    "transfer",
                    f"Fungsi '{node.name}' tidak memiliki from/to warehouse.",
                    snippet=ast.unparse(node)[:200],
                    recommendation="Validasi source dan destination warehouse."
                )
            if 'in_transit' not in body_str:
                self._add_finding(
                    RuleID.TRANSFER_IN_TRANSIT,
                    file_path, node.lineno,
                    "LOW",
                    "transfer",
                    f"Fungsi '{node.name}' tidak mencatat status in-transit.",
                    snippet=ast.unparse(node)[:200],
                    recommendation="Tambahkan status in_transit untuk tracking."
                )

        # -------- 8. Cycle Count --------
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not self._is_cycle_count_class(node):
                continue
            has_schedule = False
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and 'schedule' in item.name.lower():
                    has_schedule = True
                    break
            if not has_schedule:
                self._add_finding(
                    RuleID.CYCLE_SCHEDULE,
                    file_path, node.lineno,
                    "LOW",
                    "cycle_count",
                    f"Class '{node.name}' tidak memiliki method schedule.",
                    snippet=ast.unparse(node)[:200],
                    recommendation="Tambahkan method schedule() untuk menjadwalkan cycle count."
                )

    def scan(self) -> List[Finding]:
        for file_path in self._get_relevant_files():
            self._scan_file(file_path)
        return self.findings


# ─── Reporting ─────────────────────────────────────────────────────────────
def generate_report(findings: List[Finding], rca_enabled: bool, elapsed: float) -> Report:
    report = Report(findings=findings, rca_enabled=rca_enabled, elapsed_seconds=elapsed)
    weights = {"CRITICAL": 10, "HIGH": 5, "MEDIUM": 2, "LOW": 1, "INFO": 0}
    penalty = sum(weights.get(f.severity, 0) for f in findings)
    report.score = max(0, 100 - min(penalty, 100))
    return report


def print_report(report: Report, verbose: bool = False) -> None:
    c = COLOR
    print(f"\n{c['CYAN']}{'='*80}{c['RESET']}")
    print(f"{c['CYAN']}INVENTORY INTEGRITY CHECKER v3.3 — {report.rca_enabled and 'RCA ON' or 'RCA OFF'}{c['RESET']}")
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
        categories = {}
        for f in report.findings:
            categories.setdefault(f.category, []).append(f)

        print(f"\n{c['CYAN']}By Category:{c['RESET']}")
        cat_labels = {
            'negative_stock': 'Negative Stock',
            'valuation': 'Valuation Method',
            'reorder': 'Reorder/Safety Stock',
            'audit': 'Audit Trail',
            'validation': 'Movement Validation',
            'reconciliation': 'Reconciliation',
            'transfer': 'Transfer',
            'cycle_count': 'Cycle Count',
        }
        for cat, items in categories.items():
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


# ─── CLI ────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory Integrity Checker v3.3")
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    parser.add_argument("--no-rca", action="store_true", help="Nonaktifkan RCA")
    args = parser.parse_args()

    global RCA_AVAILABLE, _analyze_exception
    if args.no_rca:
        RCA_AVAILABLE = False
        _analyze_exception = None

    start = time.monotonic()
    checker = InventoryIntegrityChecker(PROJECT_ROOT, enable_rca=not args.no_rca)
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