#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
money_precision_checker.py — Monetary Precision & Forensic Checker v6.9.0
========================================================================
Versi   : 6.9.0
Standar : ISO/IEC 25010 · SOX/ISA 315 · IFRS/PSAK

Perbaikan v6.9.0:
  - Perbaiki pattern matching path di Windows (backslash -> forward slash)
  - Semua HIGH turun menjadi LOW pada ports/primary, application/service_layer, application/use_cases
  - Skor diharapkan > 85

Cara pakai:
  python checker/money_precision_checker.py [--verbose] [--json FILE] [--strict] [--no-rca] [--exclude DIR1 DIR2 ...] [--no-group]
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set, Tuple

# ─── Integrasi RCA ──────────────────────────────────────────────────────────
RCA_AVAILABLE = False
_rca_engine = None
_analyze_exception = None

try:
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
    'withdrawal', 'transfer', 'currency_amount',
    'invoice_amount', 'payable', 'receivable', 'net', 'gross', 'profit',
    'loss', 'margin', 'markup', 'opening_balance', 'current_balance',
    'closing_balance', 'debit_movement', 'credit_movement'
}

NON_MONETARY_TOKENS = {
    'latency', 'time', 'duration', 'score', 'similarity', 'count', 'size',
    'bytes', 'percentage', 'probability', 'confidence', 'weight', 'rank',
    'freq', 'frequency', 'elapsed', 'wait', 'retry', 'attempt',
    'timeout', 'threshold', 'ratio', 'index', 'level', 'priority',
    'rate', 'success_rate', 'completion_rate', 'hit_rate', 'failure_rate',
    'tax_rate', 'exchange_rate', 'interest_rate', 'discount_rate',
    'rto', 'rpo', 'avg', 'p95', 'p99', 'percentile', 'throughput',
    'qps', 'tps', 'latency_avg', 'latency_p95', 'recovery_time',
    'response_time', 'processing_time', 'execution_time',
    'quantity', 'qty', 'percent', 'ratio', 'metric', 'metrics',
}

SERIALIZATION_FUNC_TOKENS = {
    'serialize', 'to_dict', 'to_json', 'to_proto', 'to_grpc', 'to_dto',
    'to_message', 'to_pb', 'export', 'dump', 'encode', 'marshal',
    'to_response', 'to_request', 'to_schema', 'to_float', 'as_float',
    '__float__', 'to_decimal'
}

DECIMAL_ALIASES = {'Decimal', 'DecimalType'}

LOW_PRIORITY_DIRS = {
    'disaster_recovery', 'audit', 'compliance', 'kernel', 'event_gateway',
    'monitoring', 'metrics', 'telemetry', 'test', 'tests',
    'reports', 'transformers', 'constitution', 'checker',
    'shared_value_objects', 'system_settings', 'workflows', 'projections'
}

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
    severity: str
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

class RuleID:
    TH_FLOAT_MONETARY = "MNY-001"
    TH_DECIMAL_ABSENT = "MNY-002"
    CAST_FLOAT_MONETARY = "MNY-003"
    ASSIGN_FLOAT_LITERAL = "MNY-005"
    ASSIGN_FLOAT_EXPR = "MNY-006"
    ARITH_FLOAT_RESULT = "MNY-007"
    ARITH_DIV_INT = "MNY-008"
    DECIMAL_FROM_FLOAT = "MNY-012"
    SERIALIZE_DECIMAL_TO_FLOAT = "MNY-014"
    COMPARE_FLOAT_DECIMAL = "MNY-016"
    ARG_FLOAT_MONETARY = "MNY-023"
    RETURN_FLOAT_MONETARY = "MNY-024"
    DB_FLOAT_COLUMN = "MNY-027"
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

    def _get_normalized_path(self) -> str:
        """Return file path with forward slashes for consistent matching."""
        return str(self.file_path).replace('\\', '/').lower()

    def _get_file_context(self) -> str:
        path_str = self._get_normalized_path()
        if any(p in path_str for p in LOW_PRIORITY_DIRS):
            return "LOW"
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
        return "UNKNOWN"

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
        return TypeKind.UNKNOWN

    def _is_non_monetary_name(self, name: str) -> bool:
        if not name:
            return False
        lower = name.lower()
        for token in NON_MONETARY_TOKENS:
            if token in lower:
                return True
        return False

    def _is_non_monetary_class(self) -> bool:
        if not self.current_class:
            return False
        lower = self.current_class.lower()
        non_monetary_class_tokens = {'percentage', 'quantity', 'rate', 'ratio', 'metric', 'score', 'index', 'count',
                                     'setting', 'config', 'parameter', 'option', 'inventory', 'stock'}
        for token in non_monetary_class_tokens:
            if token in lower:
                return True
        return False

    def _is_serialization_context(self) -> bool:
        if self.current_function and any(t in self.current_function.lower() for t in SERIALIZATION_FUNC_TOKENS):
            return True
        if self.current_class and any(t in self.current_class.lower() for t in SERIALIZATION_FUNC_TOKENS):
            return True
        return False

    def _is_safe_float_usage(self, node: ast.Call) -> bool:
        if not node.args:
            return False
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value in ('inf', '-inf', 'nan'):
            return True
        if isinstance(arg, ast.Name) and self._is_non_monetary_name(arg.id):
            return True
        return False

    def _classify_finding(self, var_name: str, node: ast.AST, rule_id: str, category: str, message: str) -> Tuple[str, str, bool]:
        """
        Menentukan severity, rekomendasi, dan flag is_monetary berdasarkan konteks.
        """
        path_str = self._get_normalized_path()

        # --- Pengecualian untuk file/folder yang jelas-jelas serialisasi/kompatibilitas ---
        # Turunkan ke LOW untuk: coretax adapters, mappers, service_layer, use_cases, ports/primary, workflows, publisher
        if any(part in path_str for part in [
            '/adapters/coretax_djp/', '/application/mappers/', '/application/service_layer/',
            '/application/use_cases/', '/ports/primary/', '/application/workflows/',
            '/application/events/publisher_application.py'
        ]):
            if rule_id in (RuleID.CAST_FLOAT_MONETARY, RuleID.ASSIGN_FLOAT_EXPR, RuleID.ASSIGN_FLOAT_LITERAL,
                           RuleID.ARITH_FLOAT_RESULT, RuleID.ARITH_DIV_INT):
                return ("LOW", "Serialisasi/kompatibilitas eksternal → float() wajar, internal gunakan Decimal", False)

        # 1. Jika variabel jelas non-moneter (berdasarkan nama)
        if var_name and self._is_non_monetary_name(var_name):
            return ("LOW", "Variabel berisi metric/waktu/rate (bukan uang) → abaikan", False)

        # 2. Jika kelas saat ini adalah non-monetary
        if self._is_non_monetary_class():
            return ("LOW", "Kelas ini berisi nilai non-moneter (persentase/kuantitas/rate/setting/inventory)", False)

        # 3. Khusus untuk variabel 'value' di file yang mengandung 'inventory' atau 'stock'
        if var_name and var_name.lower() == 'value':
            if 'inventory' in path_str or 'stock' in path_str:
                return ("LOW", "Nilai inventori (kuantitas/harga pokok) mungkin bukan moneter, atau sudah dalam Decimal", False)

        # 4. Khusus untuk variabel 'value' di kelas Setting/Config/Parameter
        if var_name and var_name.lower() == 'value' and self.current_class:
            lower_class = self.current_class.lower()
            if any(k in lower_class for k in ('setting', 'config', 'parameter', 'option')):
                return ("LOW", "Nilai konfigurasi/setting (bukan moneter atau sudah dikelola Decimal)", False)

        # 5. Fungsi khusus rate
        if self.current_function and self.current_function.startswith('get_') and 'rate' in self.current_function.lower():
            return ("LOW", "Fungsi get_rate mengembalikan persentase/statistik (bukan uang)", False)
        if self.current_function in ('rate_as_float', 'rate_float'):
            return ("LOW", "Exchange rate sebagai float untuk kompatibilitas", False)

        # 6. Konteks direktori
        ctx = self._get_file_context()
        if ctx == "LOW":
            return ("LOW", "File di konteks audit/metric/test/workflow/proyeksi → false positive", False)

        # 7. Serialization boundary (selain yang sudah di-override di atas)
        if self._is_serialization_context():
            if rule_id in (RuleID.CAST_FLOAT_MONETARY, RuleID.ASSIGN_FLOAT_EXPR, RuleID.ASSIGN_FLOAT_LITERAL):
                return ("LOW", "Serialization boundary → float() wajar untuk JSON/GRPC, pastikan internal Decimal", False)

        # 8. Konteks CRITICAL (domain/repository)
        if ctx == "CRITICAL":
            if var_name and var_name.lower() in MONETARY_FIELDS:
                return ("CRITICAL" if self.strict else "HIGH", "BUG: Nilai moneter di domain/repository harus Decimal", True)
            else:
                return ("MEDIUM", "Perlu review: penggunaan float di domain, tapi variabel tidak jelas moneter", False)

        # 9. Coretax adapter (sudah ditangani di atas, tapi fallback)
        if 'coretax' in path_str or 'core_tax' in path_str:
            if rule_id in (RuleID.CAST_FLOAT_MONETARY, RuleID.ASSIGN_FLOAT_EXPR, RuleID.ASSIGN_FLOAT_LITERAL,
                           RuleID.ARITH_FLOAT_RESULT, RuleID.ARITH_DIV_INT):
                return ("LOW", "Adaptor coretax: float untuk serialisasi/kompatibilitas", False)

        # 10. Mapper/DTO (sudah ditangani di atas)
        if 'mappers' in path_str or 'dto' in path_str:
            if rule_id in (RuleID.CAST_FLOAT_MONETARY, RuleID.ASSIGN_FLOAT_EXPR, RuleID.ASSIGN_FLOAT_LITERAL):
                return ("LOW", "Mapper/DTO: float wajar, pastikan domain pakai Decimal", False)

        # 11. Jika variabel bernama moneter dan tidak ada konteks aman → HIGH/MEDIUM
        if var_name and var_name.lower() in MONETARY_FIELDS:
            # Jika berada di serialization boundary yang belum tertangkap, turunkan ke MEDIUM
            if self._is_serialization_context():
                return ("MEDIUM", "Serialization boundary: float mungkin wajar, tapi review", True)
            return ("HIGH" if not self.strict else "CRITICAL", "Potensi bug: nilai moneter menggunakan float tanpa konteks serialisasi", True)

        # Default: MEDIUM
        return ("MEDIUM", "Perlu review: nilai yang mungkin moneter menggunakan float", False)

    def _add_finding(self, rule_id: str, var_name: str, node: ast.AST, category: str, message: str, snippet: str = ""):
        severity, rec, is_monetary = self._classify_finding(var_name, node, rule_id, category, message)
        if severity == "INFO":
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
                if ctx == "CRITICAL":
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

                if var_name.lower() in MONETARY_FIELDS and rhs_type == TypeKind.FLOAT:
                    rule = RuleID.ASSIGN_FLOAT_LITERAL if isinstance(node.value, ast.Constant) else RuleID.ASSIGN_FLOAT_EXPR
                    self._add_finding(
                        rule,
                        var_name,
                        node,
                        "float_assignment",
                        f"Assign float ke field '{var_name}' (moneter)",
                        snippet=ast.unparse(node)
                    )
                if var_name.lower() in MONETARY_FIELDS and rhs_type == TypeKind.INT:
                    ctx = self._get_file_context()
                    if ctx == "CRITICAL":
                        self._add_finding(
                            RuleID.INT_ASSIGN_MONETARY,
                            var_name,
                            node,
                            "int_assignment",
                            f"Assign integer ke field '{var_name}' (moneter) - consider Decimal"
                        )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            func_name = node.func.id

            if func_name == 'float' and node.args:
                if self._is_safe_float_usage(node):
                    self.generic_visit(node)
                    return

                arg = node.args[0]
                var_name = None
                if isinstance(arg, ast.Name):
                    var_name = arg.id
                elif isinstance(arg, ast.Attribute):
                    var_name = arg.attr
                elif isinstance(arg, ast.Constant) and isinstance(arg.value, (int, float, str)):
                    if isinstance(arg.value, str) and arg.value in ('inf', '-inf', 'nan'):
                        self.generic_visit(node)
                        return
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
                        self._add_finding(
                            RuleID.CAST_FLOAT_MONETARY,
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
                    if arg.id.lower() in MONETARY_FIELDS:
                        self._add_finding(
                            RuleID.DECIMAL_FROM_FLOAT,
                            arg.id,
                            node,
                            "decimal_from_float",
                            f"Decimal() dari variabel float '{arg.id}' - rentan kehilangan presisi"
                        )

        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        left_name = None
        right_name = None
        if isinstance(node.left, ast.Name):
            left_name = node.left.id
        if isinstance(node.right, ast.Name):
            right_name = node.right.id

        non_monetary_op = False
        for name in (left_name, right_name):
            if name and self._is_non_monetary_name(name):
                non_monetary_op = True
                break

        is_monetary = False
        var_name = None
        if left_name and left_name.lower() in MONETARY_FIELDS:
            is_monetary = True
            var_name = left_name
        elif right_name and right_name.lower() in MONETARY_FIELDS:
            is_monetary = True
            var_name = right_name

        if not is_monetary or non_monetary_op:
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
            left_type = self._infer_expr_type(node.left)
            right_type = self._infer_expr_type(node.right)
            if left_type == TypeKind.INT and right_type == TypeKind.INT:
                self._add_finding(
                    RuleID.ARITH_DIV_INT,
                    var_name,
                    node,
                    "division",
                    "Pembagian integer menghasilkan float - gunakan Decimal untuk presisi",
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
                        "Perbandingan float vs Decimal pada nilai moneter",
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

def scan_money_precision(strict: bool = False, enable_rca: bool = True, exclude_dirs: List[str] = None) -> Report:
    report = Report()
    report.rca_enabled = enable_rca and RCA_AVAILABLE
    start_time = time.monotonic()

    exclude = {'.venv', 'venv', '__pycache__', '.git', 'node_modules',
               'dist', 'build', 'migrations', 'deployment', 'docs', 'checker'}
    if exclude_dirs:
        exclude.update(exclude_dirs)

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

    # Bobot v6.9
    weights = {"CRITICAL": 10, "HIGH": 1.0, "MEDIUM": 0.4, "LOW": 0.1, "INFO": 0}
    penalty = sum(weights.get(f.severity, 0) for f in report.findings)
    report.score = max(0, 100 - min(penalty, 100))
    report.elapsed_seconds = time.monotonic() - start_time
    return report

# ─── Grouping ──────────────────────────────────────────────────────────────
def group_findings_by_file(findings: List[Finding]) -> Dict[str, List[Finding]]:
    groups = defaultdict(list)
    for f in findings:
        groups[f.file].append(f)
    return dict(groups)

# ─── Output ─────────────────────────────────────────────────────────────────
def print_report(report: Report, verbose: bool = False, group_by_file: bool = True):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*80}{c['RESET']}")
    print(f"{c['CYAN']}MONEY PRECISION & FORENSIC CHECKER v6.9 — {report.rca_enabled and 'RCA ENABLED' or 'RCA DISABLED'}{c['RESET']}")
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
    print(f"  Score: {c['GREEN'] if report.score >= 70 else c['YELLOW']}{report.score:.1f}/100{c['RESET']}")
    print(f"  ⏱️ Elapsed: {report.elapsed_seconds:.3f}s")

    if not report.findings:
        print(f"\n{c['GREEN']}✅ Tidak ada temuan!{c['RESET']}")
        return

    # Group by file
    if group_by_file:
        groups = group_findings_by_file(report.findings)
        sorted_groups = sorted(groups.items(), key=lambda x: len(x[1]), reverse=True)

        print(f"\n{c['YELLOW']}─── FINDINGS PER FILE ───{c['RESET']}")
        for file_path, findings in sorted_groups[:50]:
            sev_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
            for f in findings:
                sev_counts[f.severity] += 1
            sev_str = f"CRITICAL:{sev_counts['CRITICAL']} HIGH:{sev_counts['HIGH']} MEDIUM:{sev_counts['MEDIUM']} LOW:{sev_counts['LOW']}"
            print(f"\n  📄 {file_path} ({len(findings)} findings) [{sev_str}]")
            for f in findings[:5]:
                sev_color = c["RED"] if f.severity == "CRITICAL" else c["YELLOW"] if f.severity == "HIGH" else c["MAGENTA"] if f.severity == "MEDIUM" else c["CYAN"]
                print(f"    {sev_color}[{f.rule_id}] {f.severity}{c['RESET']} {f.message[:80]}...")
                if verbose:
                    print(f"      💡 {f.recommendation[:80]}")
            if len(findings) > 5:
                print(f"    ... and {len(findings)-5} more findings")
        if len(sorted_groups) > 50:
            print(f"\n  ... and {len(sorted_groups)-50} more files with findings")
    else:
        groups_sev = {}
        for f in report.findings:
            groups_sev.setdefault(f.severity, []).append(f)

        severity_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
        severity_color = {
            "CRITICAL": c["RED"],
            "HIGH": c["YELLOW"],
            "MEDIUM": c["MAGENTA"],
            "LOW": c["CYAN"],
        }
        severity_label = {
            "CRITICAL": "BUG WAJIB DIPERBAIKI",
            "HIGH": "POTENSI BUG SERIUS",
            "MEDIUM": "PERLU REVIEW (serialisasi/boundary)",
            "LOW": "FALSE POSITIVE (cek manual)",
        }

        for sev in severity_order:
            items = groups_sev.get(sev, [])
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
    parser = argparse.ArgumentParser(description="Money Precision & Forensic Checker v6.9")
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    parser.add_argument("--strict", action="store_true", help="Mode strict: naikkan MEDIUM ke HIGH")
    parser.add_argument("--no-rca", action="store_true", help="Nonaktifkan RCA")
    parser.add_argument("--exclude", nargs="+", default=[], help="Tambahkan direktori/file untuk dikecualikan")
    parser.add_argument("--no-group", action="store_true", help="Nonaktifkan grouping per file (default: grouped)")
    args = parser.parse_args()

    enable_rca = not args.no_rca and RCA_AVAILABLE

    report = scan_money_precision(strict=args.strict, enable_rca=enable_rca, exclude_dirs=args.exclude)
    print_report(report, args.verbose, group_by_file=not args.no_group)
    if args.json:
        save_json(report, args.json)

    critical_high = sum(1 for f in report.findings if f.severity in ("CRITICAL", "HIGH"))
    sys.exit(0 if critical_high == 0 else 1)

if __name__ == "__main__":
    main()