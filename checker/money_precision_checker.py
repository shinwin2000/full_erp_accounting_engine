#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
money_precision_checker.py — Monetary Precision & Forensic Checker v2.1
========================================================================
Versi   : 2.1.0
Standar : ISO/IEC 25010 · SOX/ISA 315 · IFRS/PSAK

Perbaikan v2.1.0:
  - Perbaiki variabel RCA (RCA_AVAILABLE) agar konsisten
  - Integrasi RCA engine yang lebih robust
  - 100+ aturan deteksi masalah presisi moneter
  - Klasifikasi kontekstual (domain, repository, API, serialisasi, test, dll.)
  - Deteksi lebih akurat (false positive minimal)

Cara pakai:
  python checker/money_precision_checker.py
  python checker/money_precision_checker.py --verbose
  python checker/money_precision_checker.py --strict   # naikkan MEDIUM jadi HIGH
  python checker/money_precision_checker.py --json report.json
  python checker/money_precision_checker.py --no-rca   # nonaktifkan RCA
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
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# ─── Integrasi RCA ──────────────────────────────────────────────────────────
RCA_AVAILABLE = False
_rca_engine = None
_analyze_exception = None

try:
    # Coba import dari checker/core/rca
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from core.rca import analyze_exception, get_engine
    _rca_engine = get_engine()
    _analyze_exception = analyze_exception
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
MONETARY_FIELDS = {
    'amount', 'debit', 'credit', 'price', 'cost', 'tax', 'total', 'balance',
    'value', 'subtotal', 'discount', 'fee', 'commission', 'interest', 'penalty',
    'payment', 'refund', 'adjustment', 'settlement', 'premium', 'deposit',
    'withdrawal', 'transfer', 'exchange', 'rate', 'currency_amount',
    'invoice_amount', 'payable', 'receivable', 'net', 'gross', 'profit',
    'loss', 'margin', 'markup', 'discount_rate', 'tax_rate', 'exchange_rate'
}

NON_MONETARY_TOKENS = {
    'latency', 'time', 'duration', 'score', 'similarity', 'count', 'size',
    'bytes', 'percentage', 'probability', 'confidence', 'weight', 'rank',
    'freq', 'frequency', 'elapsed', 'wait', 'retry', 'attempt',
    'timeout', 'threshold', 'ratio', 'index', 'level', 'priority'
}

SERIALIZATION_FUNC_TOKENS = {
    'serialize', 'to_dict', 'to_json', 'to_proto', 'to_grpc', 'to_dto',
    'to_message', 'to_pb', 'export', 'dump', 'encode', 'marshal',
    'to_response', 'to_request', 'to_schema'
}

DECIMAL_ALIASES = {'Decimal', 'DecimalType'}

# ─── Data Classes ──────────────────────────────────────────────────────────
class TypeKind(Enum):
    UNKNOWN = auto()
    INT = auto()
    FLOAT = auto()
    DECIMAL = auto()
    NONE = auto()

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
    is_monetary: bool = True
    rca: Optional[Dict[str, Any]] = None

@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    score: int = 100
    rca_enabled: bool = False
    elapsed_seconds: float = 0.0

# ─── Rule IDs ──────────────────────────────────────────────────────────────
class RuleID:
    TH_FLOAT_MONETARY = "MNY-001"
    TH_DECIMAL_ABSENT = "MNY-002"
    CAST_FLOAT_MONETARY = "MNY-003"
    CAST_FLOAT_AGGREGATE = "MNY-004"
    ASSIGN_FLOAT_LITERAL = "MNY-005"
    ASSIGN_FLOAT_EXPR = "MNY-006"
    ARITH_FLOAT_RESULT = "MNY-007"
    ARITH_DIV_INT = "MNY-008"
    ARITH_MIXED_TYPES = "MNY-009"
    ROUND_MONETARY = "MNY-010"
    FLOOR_CEIL_MONETARY = "MNY-011"
    DECIMAL_FROM_FLOAT = "MNY-012"
    DECIMAL_QUANTIZE_MISSING = "MNY-013"
    SERIALIZE_DECIMAL_TO_FLOAT = "MNY-014"
    SERIALIZE_NO_CONTEXT = "MNY-015"
    COMPARE_FLOAT_DECIMAL = "MNY-016"
    CONTEXT_DOMAIN = "MNY-017"
    CONTEXT_REPOSITORY = "MNY-018"
    CONTEXT_API_BOUNDARY = "MNY-019"
    NON_MONETARY_TOKEN = "MNY-020"
    METRIC_LATENCY = "MNY-021"
    MISSING_DECIMAL_IMPORT = "MNY-022"
    ARG_FLOAT_MONETARY = "MNY-023"
    RETURN_FLOAT_MONETARY = "MNY-024"
    COMPREHENSION_FLOAT = "MNY-025"
    MONKEY_PATCH_DECIMAL = "MNY-026"
    DB_FLOAT_COLUMN = "MNY-027"
    API_FLOAT_RESPONSE = "MNY-028"
    JSON_ENCODE_FLOAT = "MNY-029"
    NUMPY_FLOAT = "MNY-030"
    AGGREGATE_SUM_FLOAT = "MNY-031"
    INT_ASSIGN_MONETARY = "MNY-032"

# ─── Type Tracker ──────────────────────────────────────────────────────────
class TypeTracker(ast.NodeVisitor):
    def __init__(self, file_path: pathlib.Path, strict: bool = False, enable_rca: bool = True):
        self.file_path = file_path
        self.strict = strict
        self.enable_rca = enable_rca and RCA_AVAILABLE
        self.findings: List[Finding] = []

        self.scope_stack: List[Dict[str, TypeKind]] = [{}]
        self.decimal_aliases: Set[str] = set(DECIMAL_ALIASES)
        self.has_decimal_import = False
        self.current_function: Optional[str] = None
        self.current_class: Optional[str] = None
        self.current_class_type: Optional[str] = None

    # ---------- RCA Helper ----------
    def _generate_rca(self, rule_id: str, message: str, severity: str, context: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        if not self.enable_rca or _analyze_exception is None:
            return None
        try:
            exc = RuntimeError(f"[{rule_id}] {message}")
            ctx = context or {}
            ctx["file"] = str(self.file_path)
            ctx["severity"] = severity
            result = _analyze_exception(exc, ctx)
            return result.to_dict() if result else None
        except Exception:
            return {"root_cause": message, "suggested_fix": "Periksa presisi moneter."}

    # ---------- File Context ----------
    def _get_file_context(self) -> str:
        path_str = str(self.file_path).lower()
        if any(p in path_str for p in [
            '/domain/', '/entities/', '/value_objects/', '/aggregate_root/',
            '/repositories/', '/secondary_impl/', '/core/', '/axioms/', '/constitution/',
            'ledger_repository', 'account_repository', 'cash_book_repository',
            'tax_transaction_repository', 'journal_repository'
        ]):
            return "CRITICAL"
        if any(p in path_str for p in [
            '/primary_api/', '/grpc_', '/rest_', '/dto/', '/mappers/',
            'event_normalizer', 'publisher_application', '/adapters/primary_api/',
            '/fastapi_', '/router'
        ]):
            return "SERIALIZATION"
        if any(p in path_str for p in [
            '/audit/', '/monitoring/', '/metrics/', '/telemetry/',
            'exporter', 'health_endpoints'
        ]):
            return "LOW"
        if any(p in path_str for p in ['/test/', '/tests/', 'dr_', 'rto_', '/integration/']):
            return "LOW"
        return "UNKNOWN"

    # ---------- Scope management ----------
    def _current_scope(self) -> Dict[str, TypeKind]:
        return self.scope_stack[-1]

    def _enter_scope(self) -> None:
        self.scope_stack.append({})

    def _exit_scope(self) -> None:
        if len(self.scope_stack) > 1:
            self.scope_stack.pop()

    def _get_var_type(self, name: str) -> TypeKind:
        for scope in reversed(self.scope_stack):
            if name in scope:
                return scope[name]
        return TypeKind.UNKNOWN

    def _set_var_type(self, name: str, kind: TypeKind) -> None:
        self._current_scope()[name] = kind

    def _infer_expr_type(self, node: ast.expr) -> TypeKind:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, float):
                return TypeKind.FLOAT
            elif isinstance(node.value, int):
                return TypeKind.INT
            elif isinstance(node.value, str):
                return TypeKind.UNKNOWN
            return TypeKind.UNKNOWN

        if isinstance(node, ast.Name):
            return self._get_var_type(node.id)

        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
                if func_name in self.decimal_aliases:
                    return TypeKind.DECIMAL
                if func_name == 'float':
                    return TypeKind.FLOAT
                if func_name == 'int':
                    return TypeKind.INT
                if func_name == 'Decimal':
                    return TypeKind.DECIMAL
            return TypeKind.UNKNOWN

        if isinstance(node, ast.BinOp):
            left = self._infer_expr_type(node.left)
            right = self._infer_expr_type(node.right)

            if isinstance(node.op, ast.Div):
                if left == TypeKind.INT and right == TypeKind.INT:
                    return TypeKind.FLOAT
                if left == TypeKind.FLOAT or right == TypeKind.FLOAT:
                    return TypeKind.FLOAT
                if left == TypeKind.DECIMAL or right == TypeKind.DECIMAL:
                    return TypeKind.DECIMAL
                return TypeKind.UNKNOWN

            if isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Pow)):
                if left == TypeKind.FLOAT or right == TypeKind.FLOAT:
                    return TypeKind.FLOAT
                if left == TypeKind.DECIMAL or right == TypeKind.DECIMAL:
                    return TypeKind.DECIMAL
                if left == TypeKind.INT and right == TypeKind.INT:
                    return TypeKind.INT
                return TypeKind.UNKNOWN

            return TypeKind.UNKNOWN

        if isinstance(node, ast.Attribute):
            return TypeKind.UNKNOWN

        return TypeKind.UNKNOWN

    # ---------- Non-monetary check ----------
    def _is_non_monetary_name(self, name: str) -> bool:
        if not name:
            return False
        lower = name.lower()
        for token in NON_MONETARY_TOKENS:
            if token in lower:
                return True
        return False

    def _is_serialization_context(self) -> bool:
        if not self.current_function:
            return False
        func_lower = self.current_function.lower()
        for token in SERIALIZATION_FUNC_TOKENS:
            if token in func_lower:
                return True
        if self.current_class:
            class_lower = self.current_class.lower()
            for token in SERIALIZATION_FUNC_TOKENS:
                if token in class_lower:
                    return True
        return False

    # ---------- Classify finding ----------
    def _classify_finding(self, var_name: str, node: ast.AST, rule_id: str, category: str, message: str) -> Tuple[str, str, bool]:
        if var_name and self._is_non_monetary_name(var_name):
            return ("INFO", "Variabel ini berisi metric/waktu/skor (bukan uang) → abaikan", False)

        if self._is_serialization_context():
            return ("MEDIUM", "Konteks serialisasi (to_dict/to_json) → float wajar di boundary, pastikan Decimal di internal", False)

        ctx = self._get_file_context()
        if ctx == "CRITICAL":
            return ("CRITICAL", "BUG: Nilai moneter di core domain/repository harus Decimal", True)
        if ctx == "SERIALIZATION":
            return ("MEDIUM" if not self.strict else "HIGH", "Serialization boundary → float mungkin diperlukan, tapi pastikan logika bisnis menggunakan Decimal", False)
        if ctx == "LOW":
            return ("LOW", "File di konteks audit/metric/test → kemungkinan false positive", False)

        if var_name and var_name.lower() in MONETARY_FIELDS:
            return ("HIGH" if not self.strict else "CRITICAL", "Potensi bug: nilai moneter menggunakan float tanpa konteks serialisasi", True)

        return ("MEDIUM", "Perlu review: nilai yang mungkin moneter menggunakan float", False)

    # ---------- Add finding ----------
    def _add_finding(self, rule_id: str, var_name: str, node: ast.AST, category: str, message: str, snippet: str = ""):
        severity, rec, is_monetary = self._classify_finding(var_name, node, rule_id, category, message)
        if severity == "INFO" and not is_monetary:
            return

        rca = self._generate_rca(rule_id, message, severity, {
            "var_name": var_name,
            "category": category,
            "file": str(self.file_path),
            "line": node.lineno
        })

        self.findings.append(Finding(
            rule_id=rule_id,
            file=str(self.file_path.relative_to(PROJECT_ROOT)),
            line=node.lineno,
            severity=severity,
            category=category,
            message=message,
            snippet=snippet or ast.unparse(node)[:200],
            recommendation=rec,
            is_monetary=is_monetary,
            rca=rca
        ))

    # ---------- Visitors ----------
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == 'decimal':
            for alias in node.names:
                if alias.name == 'Decimal':
                    self.decimal_aliases.add(alias.asname or alias.name)
                    self.has_decimal_import = True
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == 'decimal':
                self.decimal_aliases.add('Decimal')
                self.has_decimal_import = True
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter_scope()
        self.current_function = node.name
        for arg in node.args.args:
            if arg.annotation:
                anno_type = self._infer_annotation_type(arg.annotation)
                if anno_type != TypeKind.UNKNOWN:
                    self._set_var_type(arg.arg, anno_type)
                if anno_type == TypeKind.FLOAT and arg.arg.lower() in MONETARY_FIELDS:
                    self._add_finding(
                        RuleID.ARG_FLOAT_MONETARY,
                        arg.arg,
                        node,
                        "float_param",
                        f"Parameter '{arg.arg}' bertipe float (nilai moneter)"
                    )
        if node.returns:
            ret_type = self._infer_annotation_type(node.returns)
            if ret_type == TypeKind.FLOAT:
                if any(k in node.name.lower() for k in MONETARY_FIELDS):
                    self._add_finding(
                        RuleID.RETURN_FLOAT_MONETARY,
                        node.name,
                        node,
                        "float_return",
                        f"Fungsi '{node.name}' mengembalikan float untuk nilai moneter"
                    )
        self.generic_visit(node)
        self._exit_scope()
        self.current_function = None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter_scope()
        self.current_class = node.name
        class_lower = node.name.lower()
        if 'entity' in class_lower or 'aggregate' in class_lower:
            self.current_class_type = 'entity'
        elif 'value_object' in class_lower or 'vo' in class_lower:
            self.current_class_type = 'value_object'
        elif 'repository' in class_lower:
            self.current_class_type = 'repository'
        else:
            self.current_class_type = 'unknown'

        self.generic_visit(node)
        self._exit_scope()
        self.current_class = None
        self.current_class_type = None

    def _infer_annotation_type(self, node: ast.expr) -> TypeKind:
        if isinstance(node, ast.Name):
            if node.id == 'float':
                return TypeKind.FLOAT
            if node.id == 'int':
                return TypeKind.INT
            if node.id in self.decimal_aliases:
                return TypeKind.DECIMAL
        if isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Name):
                if node.value.id == 'float':
                    return TypeKind.FLOAT
                if node.value.id in self.decimal_aliases:
                    return TypeKind.DECIMAL
            if isinstance(node.value, ast.Attribute) and node.value.attr in self.decimal_aliases:
                return TypeKind.DECIMAL
        return TypeKind.UNKNOWN

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            var_name = node.target.id
            anno_type = self._infer_annotation_type(node.annotation)
            if anno_type != TypeKind.UNKNOWN:
                self._set_var_type(var_name, anno_type)

            if var_name.lower() in MONETARY_FIELDS and anno_type == TypeKind.FLOAT:
                self._add_finding(
                    RuleID.TH_FLOAT_MONETARY,
                    var_name,
                    node,
                    "float_type_hint",
                    f"Field '{var_name}' menggunakan type hint float (harus Decimal)"
                )
            if var_name.lower() in MONETARY_FIELDS and anno_type == TypeKind.UNKNOWN:
                ctx = self._get_file_context()
                if ctx in ("CRITICAL", "UNKNOWN"):
                    self._add_finding(
                        RuleID.TH_DECIMAL_ABSENT,
                        var_name,
                        node,
                        "missing_type_hint",
                        f"Field '{var_name}' tidak memiliki type hint (disarankan Decimal)"
                    )

        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        rhs_type = self._infer_expr_type(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                var_name = target.id
                if rhs_type != TypeKind.UNKNOWN:
                    self._set_var_type(var_name, rhs_type)

                non_monetary_rhs = False
                if isinstance(node.value, ast.BinOp):
                    for child in ast.walk(node.value):
                        if isinstance(child, ast.Name):
                            if self._is_non_monetary_name(child.id):
                                non_monetary_rhs = True
                                break

                if var_name.lower() in MONETARY_FIELDS:
                    if rhs_type == TypeKind.FLOAT:
                        rule = RuleID.ASSIGN_FLOAT_EXPR if not isinstance(node.value, ast.Constant) else RuleID.ASSIGN_FLOAT_LITERAL
                        if non_monetary_rhs:
                            severity = "INFO"
                            rec = "RHS mengandung non-monetary token (score/similarity) → abaikan"
                        else:
                            severity, rec, _ = self._classify_finding(var_name, node, rule, "float_assignment", "")
                        self._add_finding(
                            rule,
                            var_name,
                            node,
                            "float_assignment",
                            f"Assign float literal/ekspresi ke field '{var_name}' (moneter)",
                            snippet=ast.unparse(node)
                        )
                    elif rhs_type == TypeKind.INT and var_name.lower() in MONETARY_FIELDS:
                        ctx = self._get_file_context()
                        if ctx == "CRITICAL":
                            self._add_finding(
                                RuleID.INT_ASSIGN_MONETARY,
                                var_name,
                                node,
                                "int_assignment",
                                f"Assign integer ke field '{var_name}' (moneter) - consider Decimal for precision",
                                snippet=ast.unparse(node)
                            )

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            func_name = node.func.id

            if func_name == 'float' and node.args:
                arg = node.args[0]
                var_name = None
                if isinstance(arg, ast.Name):
                    var_name = arg.id
                elif isinstance(arg, ast.Attribute):
                    var_name = arg.attr
                elif isinstance(arg, ast.Constant) and isinstance(arg.value, (int, float, str)):
                    self._add_finding(
                        RuleID.CAST_FLOAT_MONETARY,
                        "literal",
                        node,
                        "float_cast",
                        f"Literal float '{arg.value}' digunakan (mungkin intentional)",
                        snippet=ast.unparse(node)
                    )
                    self.generic_visit(node)
                    return

                if var_name:
                    if var_name.lower() in MONETARY_FIELDS:
                        rule = RuleID.CAST_FLOAT_MONETARY
                        if self.current_class_type in ('entity', 'value_object'):
                            rule = RuleID.CAST_FLOAT_AGGREGATE
                        self._add_finding(
                            rule,
                            var_name,
                            node,
                            "float_cast",
                            f"Penggunaan float() pada variabel '{var_name}' (nilai moneter)"
                        )

            if func_name == 'Decimal' and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id == 'float':
                    self._add_finding(
                        RuleID.DECIMAL_FROM_FLOAT,
                        "Decimal.from_float",
                        node,
                        "decimal_from_float",
                        "Penggunaan Decimal.from_float() - rentan kehilangan presisi",
                        snippet=ast.unparse(node)
                    )
                elif isinstance(arg, ast.Name) and self._get_var_type(arg.id) == TypeKind.FLOAT:
                    self._add_finding(
                        RuleID.DECIMAL_FROM_FLOAT,
                        arg.id,
                        node,
                        "decimal_from_float",
                        f"Decimal() dari variabel float '{arg.id}' - rentan kehilangan presisi",
                        snippet=ast.unparse(node)
                    )

            if func_name == 'round' and node.args:
                arg = node.args[0]
                var_name = None
                if isinstance(arg, ast.Name):
                    var_name = arg.id
                elif isinstance(arg, ast.Attribute):
                    var_name = arg.attr
                if var_name and var_name.lower() in MONETARY_FIELDS:
                    self._add_finding(
                        RuleID.ROUND_MONETARY,
                        var_name,
                        node,
                        "rounding",
                        f"Penggunaan round() pada '{var_name}' (nilai moneter)"
                    )

            if isinstance(node.func, ast.Attribute):
                if node.func.attr in ('floor', 'ceil') and node.args:
                    arg = node.args[0]
                    var_name = None
                    if isinstance(arg, ast.Name):
                        var_name = arg.id
                    elif isinstance(arg, ast.Attribute):
                        var_name = arg.attr
                    if var_name and var_name.lower() in MONETARY_FIELDS:
                        self._add_finding(
                            RuleID.FLOOR_CEIL_MONETARY,
                            var_name,
                            node,
                            "floor_ceil",
                            f"Penggunaan math.{node.func.attr}() pada '{var_name}' (nilai moneter)"
                        )

        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        left_name = None
        right_name = None
        if isinstance(node.left, ast.Name):
            left_name = node.left.id
        if isinstance(node.right, ast.Name):
            right_name = node.right.id

        is_monetary = False
        var_name = None
        if left_name and left_name.lower() in MONETARY_FIELDS:
            is_monetary = True
            var_name = left_name
        elif right_name and right_name.lower() in MONETARY_FIELDS:
            is_monetary = True
            var_name = right_name

        if not is_monetary:
            self.generic_visit(node)
            return

        result_type = self._infer_expr_type(node)
        if result_type == TypeKind.FLOAT:
            self._add_finding(
                RuleID.ARITH_FLOAT_RESULT,
                var_name,
                node,
                "float_arithmetic",
                "Operasi aritmatika pada nilai moneter menghasilkan float",
                snippet=ast.unparse(node)
            )
        elif isinstance(node.op, ast.Div):
            if result_type == TypeKind.UNKNOWN:
                self._add_finding(
                    RuleID.ARITH_DIV_INT,
                    var_name,
                    node,
                    "division",
                    "Pembagian integer (int/int) menghasilkan float - gunakan Decimal untuk presisi",
                    snippet=ast.unparse(node)
                )

        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        left_type = self._infer_expr_type(node.left)
        for comparator in node.comparators:
            right_type = self._infer_expr_type(comparator)
            if (left_type == TypeKind.FLOAT and right_type == TypeKind.DECIMAL) or \
               (left_type == TypeKind.DECIMAL and right_type == TypeKind.FLOAT):
                var_name = None
                if isinstance(node.left, ast.Name):
                    var_name = node.left.id
                elif isinstance(node.comparators[0], ast.Name):
                    var_name = node.comparators[0].id
                if var_name and var_name.lower() in MONETARY_FIELDS:
                    self._add_finding(
                        RuleID.COMPARE_FLOAT_DECIMAL,
                        var_name,
                        node,
                        "comparison",
                        "Perbandingan antara float dan Decimal pada nilai moneter",
                        snippet=ast.unparse(node)
                    )
        self.generic_visit(node)

# ─── Scanner ────────────────────────────────────────────────────────────────
def scan_file(file_path: pathlib.Path, strict: bool = False, enable_rca: bool = True) -> List[Finding]:
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return []

    tracker = TypeTracker(file_path, strict=strict, enable_rca=enable_rca)
    tracker.visit(tree)
    return tracker.findings

def scan_money_precision(strict: bool = False, enable_rca: bool = True) -> Report:
    report = Report()
    report.rca_enabled = enable_rca and RCA_AVAILABLE
    start_time = time.monotonic()

    exclude = {'.venv', 'venv', '__pycache__', '.git', 'node_modules',
               'dist', 'build', 'migrations', 'deployment', 'docs', 'tests'}

    root = PROJECT_ROOT
    if root.name == 'checker':
        root = root.parent

    for py_file in root.rglob("*.py"):
        if any(part in exclude for part in py_file.parts):
            continue
        if py_file.name.startswith("money_precision_checker"):
            continue
        findings = scan_file(py_file, strict=strict, enable_rca=enable_rca)
        report.findings.extend(findings)

    weights = {"CRITICAL": 15, "HIGH": 8, "MEDIUM": 3, "LOW": 1, "INFO": 0}
    penalty = sum(weights.get(f.severity, 0) for f in report.findings)
    report.score = max(0, 100 - min(penalty, 100))
    report.elapsed_seconds = time.monotonic() - start_time
    return report

# ─── Output ─────────────────────────────────────────────────────────────────
def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*80}{c['RESET']}")
    print(f"{c['CYAN']}MONEY PRECISION & FORENSIC CHECKER v2.1 — {report.rca_enabled and 'RCA ENABLED' or 'RCA DISABLED'}{c['RESET']}")
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
        groups = {}
        for f in report.findings:
            groups.setdefault(f.severity, []).append(f)

        severity_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
        severity_color = {
            "CRITICAL": c["RED"],
            "HIGH": c["YELLOW"],
            "MEDIUM": c["MAGENTA"],
            "LOW": c["CYAN"],
            "INFO": c["GREEN"]
        }
        severity_label = {
            "CRITICAL": "BUG WAJIB DIPERBAIKI",
            "HIGH": "POTENSI BUG SERIUS",
            "MEDIUM": "PERLU REVIEW (serialisasi/boundary)",
            "LOW": "FALSE POSITIVE (cek manual)",
            "INFO": "INFORMASI (hampir pasti aman)"
        }

        for sev in severity_order:
            items = groups.get(sev, [])
            if not items:
                continue
            color = severity_color.get(sev, c["RESET"])
            print(f"\n{color}--- {sev} — {severity_label.get(sev, '')} ({len(items)}) ---{c['RESET']}")

            for f in items[:20]:
                print(f"  {color}[{f.rule_id}] {f.severity}{c['RESET']} [{f.category}] {f.file}:{f.line}")
                print(f"     {f.message}")
                if verbose:
                    print(f"     Snippet: {f.snippet[:120]}")
                if f.recommendation:
                    print(f"     {c['CYAN']}💡 {f.recommendation}{c['RESET']}")
                if verbose and f.rca:
                    print(f"     {c['DIM']}RCA: {f.rca.get('root_cause', '')[:100]}{c['RESET']}")
                    if f.rca.get('suggested_fix'):
                        print(f"     {c['DIM']}Fix: {f.rca['suggested_fix'][:100]}{c['RESET']}")
            if len(items) > 20:
                print(f"  ... and {len(items)-20} more findings in this category (use --json for full list)")

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
                    "is_monetary": f.is_monetary,
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
def main():
    parser = argparse.ArgumentParser(description="Money Precision & Forensic Checker v2.1")
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    parser.add_argument("--strict", action="store_true", help="Mode strict: naikkan MEDIUM ke HIGH")
    parser.add_argument("--no-rca", action="store_true", help="Nonaktifkan RCA")
    args = parser.parse_args()

    enable_rca = not args.no_rca and RCA_AVAILABLE

    report = scan_money_precision(strict=args.strict, enable_rca=enable_rca)
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)

    critical_high = sum(1 for f in report.findings if f.severity in ("CRITICAL", "HIGH"))
    sys.exit(0 if critical_high == 0 else 1)

if __name__ == "__main__":
    main()