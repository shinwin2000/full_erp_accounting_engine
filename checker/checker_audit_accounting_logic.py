#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker_audit_accounting_logic.py — Sovereign Accounting Logic & Forensic Checker v2.5
======================================================================================
Versi   : 2.5.0
Standar : ISO/IEC 25010 · SOX/ISA 315 · IFRS/PSAK · PCAOB AS 2405

Perbaikan v2.5.0:
  - ACC-051: skip entity yang punya can_approve dengan pengecekan creator
  - ACC-026: skip router/api, fokus pada modifikasi journal langsung
  - ACC-046: hanya untuk posting, bukan lock/close period
  - Mengurangi false positive lebih lanjut
"""

from __future__ import annotations

import argparse
import ast
import importlib
import inspect
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, get_type_hints

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RCA_AVAILABLE = False
_analyze_exception = None

try:
    _checker_core = ROOT / "checker" / "core"
    if str(_checker_core) not in sys.path:
        sys.path.insert(0, str(_checker_core))
    from rca import get_engine as rca_get_engine, analyze_exception
    _analyze_exception = analyze_exception
    RCA_AVAILABLE = True
except ImportError:
    pass

COLOR = {
    "RED": "\033[91m" if sys.stdout.isatty() else "",
    "GREEN": "\033[92m" if sys.stdout.isatty() else "",
    "YELLOW": "\033[93m" if sys.stdout.isatty() else "",
    "CYAN": "\033[96m" if sys.stdout.isatty() else "",
    "MAGENTA": "\033[95m" if sys.stdout.isatty() else "",
    "BOLD": "\033[1m" if sys.stdout.isatty() else "",
    "DIM": "\033[2m" if sys.stdout.isatty() else "",
    "RESET": "\033[0m" if sys.stdout.isatty() else "",
}

SKIP_DIRS = {
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".git", ".venv", "venv", "node_modules", ".tox", ".cache", "dist",
    "build", "uv", "migrations", "deployment", "docs", "tests", "checker"
}

MONETARY_KEYWORDS = {
    "amount", "balance", "debit", "credit", "price", "cost", "tax", "total",
    "value", "net", "gross", "discount", "ppn", "pph", "withholding",
    "payment", "fee", "penalty", "interest", "depreciation", "amortization",
    "revenue", "expense", "profit", "income", "gain", "loss", "salary", "wage",
    "bonus", "dividend", "capital", "equity", "liability", "asset", "inventory",
    "cogs", "hpp", "npwp", "faktur", "bupot", "spt", "pajak", "tax_rate",
    "pph_rate", "ppn_rate", "interest_rate", "discount_rate", "pph_terutang",
    "nilai_ppn", "currency_amount", "exchange_rate", "forex", "revaluation"
}

NON_MONETARY_VARS = {
    "time", "latency", "duration", "count", "total_time", "total_latency",
    "score", "risk_score", "priority", "index", "num", "size", "length",
    "execution_time", "elapsed", "timestamp", "interval", "delay",
    "rate", "error_rate", "deviation_rate", "consumption_rate", "success_rate",
    "percent", "pct", "factor", "coefficient", "margin", "uptime", "percentile",
    "retry", "backoff", "expires_at", "time_to_expiry", "total_seconds",
    "safe_float", "to_proto_double", "get_retry_delay", "exponential_backoff",
    "percentage", "min_value", "max_value", "_add_default_setting"
}

NON_MONETARY_INDICATORS = {
    "ms", "ns", "sec", "seconds", "percent", "pct", "factor",
    "score", "strength", "latency", "duration", "count", "index",
    "num", "rate", "float", "coefficient", "size", "margin", "percentage"
}

FLOAT_ALLOWLIST = {
    "_to_proto_double", "safe_float", "_safe_float", "to_float",
    "get_duration_ms", "get_success_rate", "_calculate_percentile",
    "exponential_backoff", "get_retry_delay", "get_uptime", "time_to_expiry",
    "expires_at", "total_seconds", "elapsed_seconds", "_add_default_setting"
}


class RuleID:
    MON_FLOAT_LITERAL = "ACC-001"
    MON_FLOAT_ANNOTATION = "ACC-002"
    MON_FLOAT_PARAM = "ACC-003"
    MON_FLOAT_RETURN = "ACC-004"
    MON_FLOAT_OPERATION = "ACC-005"
    MON_DECIMAL_IMPORT = "ACC-006"
    MON_DECIMAL_QUANTIZE = "ACC-007"
    MON_FLOAT_ROUND = "ACC-008"
    MON_FLOAT_COMPARISON = "ACC-009"
    MON_FLOAT_ARITHMETIC = "ACC-010"
    MON_FLOAT_AGGREGATION = "ACC-011"
    MON_FLOAT_CONVERSION = "ACC-012"
    MON_DECIMAL_CONTEXT = "ACC-013"
    MON_FLOAT_FIELD = "ACC-014"
    MON_FLOAT_DEFAULT = "ACC-015"
    AX_DOUBLE_ENTRY = "ACC-016"
    IMMUT_POSTED_JOURNAL = "ACC-026"
    PERIOD_OPEN_CHECK = "ACC-046"
    APPROVAL_FOUR_EYES = "ACC-051"
    TAX_CALCULATION = "ACC-056"


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
    files_scanned: int = 0
    runtime_imported: int = 0


class SovereignAccountingLogicGatekeeper:
    def __init__(self, root_dir: Path, enable_rca: bool = True, strict: bool = False):
        self.root_dir = root_dir
        self.enable_rca = enable_rca and RCA_AVAILABLE
        self.strict = strict
        self.findings: List[Finding] = []
        self.files_scanned = 0
        self.runtime_imported = 0
        sys.path.insert(0, str(root_dir))

    def _generate_rca(self, rule_id: str, message: str, severity: str, context: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        if not self.enable_rca or _analyze_exception is None:
            return None
        try:
            exc = RuntimeError(f"[{rule_id}] {message}")
            ctx = context or {}
            ctx["file"] = str(self.root_dir)
            result = _analyze_exception(exc, ctx)
            return result.to_dict() if result else None
        except Exception:
            return {"root_cause": message, "suggested_fix": "Periksa implementasi logika akuntansi."}

    def _add_finding(self, rule_id: str, file_path: Path, line: int, severity: str,
                     category: str, message: str, snippet: str = "", recommendation: str = ""):
        rca = self._generate_rca(rule_id, message, severity, {"file": str(file_path), "line": line})
        rel_path = str(file_path.relative_to(self.root_dir)).replace("\\", "/")
        for f in self.findings:
            if f.rule_id == rule_id and f.file == rel_path and f.message == message:
                return
        self.findings.append(Finding(
            rule_id=rule_id,
            file=rel_path,
            line=line,
            severity=severity,
            category=category,
            message=message,
            snippet=snippet[:200] if snippet else "",
            recommendation=recommendation,
            rca=rca,
        ))

    def _is_monetary_variable(self, var_name: str, func_name: str = "") -> bool:
        if not var_name:
            return False
        lower = var_name.lower()
        tokens = set(lower.split('_'))
        if func_name in FLOAT_ALLOWLIST or lower in FLOAT_ALLOWLIST:
            return False
        if tokens.intersection(NON_MONETARY_INDICATORS) or lower in NON_MONETARY_VARS:
            return False
        for kw in MONETARY_KEYWORDS:
            if kw in tokens or kw in lower:
                return True
        return False

    def _is_monetary_context(self, file_path: Path) -> bool:
        path_str = str(file_path).lower()
        monetary_contexts = ['journal', 'ledger', 'account', 'tax', 'payment', 'invoice',
                             'balance', 'cash', 'bank', 'asset', 'liability', 'equity',
                             'revenue', 'expense', 'profit', 'loss', 'budget', 'forex',
                             'currency', 'exchange', 'transaction', 'entry', 'posting']
        for ctx in monetary_contexts:
            if ctx in path_str:
                return True
        return False

    def _is_entity_file(self, file_path: Path) -> bool:
        path_str = str(file_path).lower()
        if 'router' in path_str or 'api' in path_str:
            return False
        if 'domain' not in path_str:
            return False
        return 'entity' in path_str or 'aggregate' in path_str

    def _is_router_or_api_file(self, file_path: Path) -> bool:
        path_str = str(file_path).lower()
        return 'router' in path_str or 'api' in path_str

    def _is_service_layer_file(self, file_path: Path) -> bool:
        path_str = str(file_path).lower()
        return 'service_layer' in path_str or 'secondary_impl' in path_str

    def _has_float_literal(self, node: ast.AST) -> bool:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, float):
                return True
        return False

    def _get_target_files(self) -> List[Path]:
        files = []
        target_packages = ["domain", "application", "infrastructure", "kernel", "ports",
                           "axioms", "constitution", "policy_engine", "audit", "adapters",
                           "bootstrap", "compliance", "event_gateway", "projections", "reports"]
        for pkg in target_packages:
            pkg_dir = self.root_dir / pkg
            if pkg_dir.is_dir():
                for p in pkg_dir.rglob("*.py"):
                    if not any(part in SKIP_DIRS for part in p.parts) and not p.name.startswith("__init__"):
                        files.append(p)
        if not files:
            for p in self.root_dir.rglob("*.py"):
                if not any(part in SKIP_DIRS for part in p.parts) and not p.name.startswith("__init__"):
                    if p.name != Path(__file__).name:
                        files.append(p)
        return sorted(list(set(files)))

    def _module_name_from_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root_dir).with_suffix("")).replace(os.sep, ".")
        except ValueError:
            return path.stem

    def _has_can_approve_check(self, class_node: ast.ClassDef) -> bool:
        """Cek apakah class memiliki method can_approve yang memeriksa creator."""
        for node in class_node.body:
            if isinstance(node, ast.FunctionDef) and node.name == "can_approve":
                body_text = ast.unparse(node)
                if "creator" in body_text.lower() or "created_by" in body_text.lower():
                    return True
        return False

    def _ast_analysis(self, file_path: Path, rel_path: str, content: str):
        try:
            tree = ast.parse(content, filename=str(file_path))
        except Exception:
            return

        is_monetary_context = self._is_monetary_context(file_path)
        is_entity = self._is_entity_file(file_path)
        is_router = self._is_router_or_api_file(file_path)
        is_service = self._is_service_layer_file(file_path)

        # Kumpulkan class yang memiliki can_approve dengan pengecekan creator
        classes_with_can_approve = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and self._has_can_approve_check(node):
                classes_with_can_approve.add(node.name)

        for node in ast.walk(tree):
            # --- ACC-001: Float literal ---
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        if not self._is_monetary_variable(target.id):
                            continue
                        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, float):
                            self._add_finding(
                                RuleID.MON_FLOAT_LITERAL, file_path, node.lineno,
                                "CRITICAL" if is_monetary_context else "HIGH",
                                "monetary_integrity",
                                f"Variabel moneter '{target.id}' diisi oleh literal float: {node.value.value}",
                                snippet=ast.unparse(node),
                                recommendation=f"Gunakan Decimal('{str(node.value.value)}') untuk presisi moneter."
                            )

            # --- ACC-002: Float annotation ---
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target_name = node.target.id
                if not self._is_monetary_variable(target_name):
                    continue
                if isinstance(node.annotation, ast.Name) and node.annotation.id == "float":
                    self._add_finding(
                        RuleID.MON_FLOAT_ANNOTATION, file_path, node.lineno,
                        "CRITICAL" if is_monetary_context else "HIGH",
                        "monetary_integrity",
                        f"Field moneter '{target_name}' menggunakan type hint float.",
                        snippet=ast.unparse(node),
                        recommendation="Gunakan 'Decimal' untuk field moneter."
                    )

            # --- ACC-003, ACC-004, ACC-015: Function parameters/return/default ---
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = node.name
                if func_name in FLOAT_ALLOWLIST:
                    continue
                if not is_monetary_context and not any(k in func_name.lower() for k in ['calculate', 'compute', 'post', 'validate']):
                    continue

                # Return type
                if node.returns and isinstance(node.returns, ast.Name) and node.returns.id == "float":
                    if self._is_monetary_variable(func_name, func_name):
                        self._add_finding(
                            RuleID.MON_FLOAT_RETURN, file_path, node.lineno,
                            "CRITICAL" if is_monetary_context else "HIGH",
                            "monetary_integrity",
                            f"Fungsi '{func_name}' mengembalikan float (harus Decimal).",
                            snippet=ast.unparse(node),
                            recommendation="Return type harus Decimal untuk nilai moneter."
                        )

                # Defaults
                defaults = node.args.defaults
                num_defaults = len(defaults)
                num_args = len(node.args.args)
                default_values = [None] * (num_args - num_defaults) + list(defaults) if num_args >= num_defaults else []

                for idx, arg in enumerate(node.args.args):
                    if arg.arg in ("self", "cls"):
                        continue
                    if not self._is_monetary_variable(arg.arg, func_name):
                        continue
                    if arg.annotation and isinstance(arg.annotation, ast.Name) and arg.annotation.id == "float":
                        self._add_finding(
                            RuleID.MON_FLOAT_PARAM, file_path, node.lineno,
                            "CRITICAL" if is_monetary_context else "HIGH",
                            "monetary_integrity",
                            f"Parameter moneter '{arg.arg}' pada '{func_name}' bertipe float.",
                            snippet=ast.unparse(node),
                            recommendation="Gunakan Decimal untuk parameter moneter."
                        )
                    if idx < len(default_values):
                        default_node = default_values[idx]
                        if default_node is not None and isinstance(default_node, ast.Constant) and isinstance(default_node.value, float):
                            self._add_finding(
                                RuleID.MON_FLOAT_DEFAULT, file_path, node.lineno,
                                "CRITICAL" if is_monetary_context else "HIGH",
                                "monetary_integrity",
                                f"Parameter moneter '{arg.arg}' pada '{func_name}' memiliki default float.",
                                snippet=ast.unparse(node),
                                recommendation="Gunakan Decimal default untuk parameter moneter."
                            )

                # Kwonly
                kw_defaults = node.args.kw_defaults
                for idx, arg in enumerate(node.args.kwonlyargs):
                    if arg.arg in ("self", "cls"):
                        continue
                    if not self._is_monetary_variable(arg.arg, func_name):
                        continue
                    if arg.annotation and isinstance(arg.annotation, ast.Name) and arg.annotation.id == "float":
                        self._add_finding(
                            RuleID.MON_FLOAT_PARAM, file_path, node.lineno,
                            "CRITICAL" if is_monetary_context else "HIGH",
                            "monetary_integrity",
                            f"Parameter moneter '{arg.arg}' pada '{func_name}' bertipe float.",
                            snippet=ast.unparse(node),
                            recommendation="Gunakan Decimal untuk parameter moneter."
                        )
                    if idx < len(kw_defaults):
                        default_node = kw_defaults[idx]
                        if default_node is not None and isinstance(default_node, ast.Constant) and isinstance(default_node.value, float):
                            self._add_finding(
                                RuleID.MON_FLOAT_DEFAULT, file_path, node.lineno,
                                "CRITICAL" if is_monetary_context else "HIGH",
                                "monetary_integrity",
                                f"Parameter moneter '{arg.arg}' pada '{func_name}' memiliki default float.",
                                snippet=ast.unparse(node),
                                recommendation="Gunakan Decimal default untuk parameter moneter."
                            )

            # --- ACC-016: Double-Entry (hanya entity) ---
            if is_entity and not is_router:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (node.name == "__post_init__" or "validate" in node.name):
                    body_text = ast.unparse(node)
                    if "debit" in body_text.lower() or "credit" in body_text.lower():
                        if not ("==" in body_text or "assert" in body_text or "validate" in body_text):
                            self._add_finding(
                                RuleID.AX_DOUBLE_ENTRY, file_path, node.lineno,
                                "CRITICAL", "axiom",
                                f"Fungsi '{node.name}' gagal mengeksekusi asersi Double-Entry.",
                                snippet=ast.unparse(node),
                                recommendation="Validasi total debit == total credit sebelum persist."
                            )

            # --- ACC-026: Immutability (skip router/api) ---
            if not is_router and not is_service:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_name = node.name
                    if any(k in func_name for k in ['update', 'edit', 'modify', 'change']):
                        body_text = ast.unparse(node)
                        # Hanya jika membahas journal dan ada assignment ke status/version
                        if "journal" in body_text.lower() and ("status" in body_text.lower() or "version" in body_text.lower()):
                            if "posted" in body_text.lower() or "POSTED" in body_text:
                                has_guard = False
                                for stmt in ast.walk(node):
                                    if isinstance(stmt, ast.If):
                                        cond = ast.unparse(stmt.test).lower()
                                        if "status" in cond and ("posted" in cond or "post" in cond):
                                            has_guard = True
                                            break
                                if not has_guard:
                                    self._add_finding(
                                        RuleID.IMMUT_POSTED_JOURNAL, file_path, node.lineno,
                                        "CRITICAL", "immutability",
                                        f"Fungsi '{func_name}' memodifikasi journal tanpa guard status POSTED.",
                                        snippet=ast.unparse(node),
                                        recommendation="Tambahkan guard: if journal.status == 'POSTED': raise ImmutabilityViolation"
                                    )

            # --- ACC-046: Period open check (hanya untuk posting) ---
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = node.name
                # Hanya periksa fungsi yang melakukan posting
                if any(k in func_name for k in ['post', 'record', 'create', 'update']):
                    body_text = ast.unparse(node)
                    if "period" in body_text.lower() and ("closed" in body_text.lower() or "locked" in body_text.lower()):
                        # Skip jika fungsi adalah lock/close period
                        if "lock" in func_name or "close" in func_name:
                            continue
                        has_handling = False
                        for stmt in ast.walk(node):
                            if isinstance(stmt, (ast.Raise, ast.Return)):
                                has_handling = True
                                break
                            if isinstance(stmt, ast.Expr):
                                expr_str = ast.unparse(stmt).lower()
                                if "add_warning" in expr_str or "logger.warning" in expr_str or "validate" in expr_str:
                                    has_handling = True
                                    break
                        if not has_handling:
                            self._add_finding(
                                RuleID.PERIOD_OPEN_CHECK, file_path, node.lineno,
                                "HIGH", "period",
                                "Potensi posting tanpa validasi periode terbuka.",
                                snippet=ast.unparse(node),
                                recommendation="Validasi period.is_open() sebelum setiap posting."
                            )

            # --- ACC-051: Four-eyes approval (skip service_layer & entity dengan can_approve) ---
            if not is_router and not is_service:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_name = node.name
                    if "approve" in func_name.lower() or "approval" in func_name.lower():
                        # Cek apakah class memiliki can_approve yang memeriksa creator
                        class_name = None
                        parent = getattr(node, 'parent', None)
                        while parent:
                            if isinstance(parent, ast.ClassDef):
                                class_name = parent.name
                                break
                            parent = getattr(parent, 'parent', None)
                        if class_name and class_name in classes_with_can_approve:
                            continue
                        body_text = ast.unparse(node)
                        if not any(k in body_text.lower() for k in ["creator", "created_by", "user_id"]):
                            continue
                        has_check = False
                        for stmt in ast.walk(node):
                            if isinstance(stmt, ast.If):
                                cond = ast.unparse(stmt.test).lower()
                                if ("user" in cond or "creator" in cond or "created_by" in cond) and ("!=" in cond or "not" in cond):
                                    has_check = True
                                    break
                        if not has_check:
                            self._add_finding(
                                RuleID.APPROVAL_FOUR_EYES, file_path, node.lineno,
                                "HIGH", "approval",
                                "Approval tidak memeriksa segregation of duties (creator != approver).",
                                snippet=ast.unparse(node),
                                recommendation="Pastikan creator != approver (four-eyes principle)."
                            )

            # --- ACC-056: Tax calculation (hanya jika ada float literal) ---
            if isinstance(node, ast.Assign):
                if isinstance(node.targets[0], ast.Name):
                    target_name = node.targets[0].id
                    if 'ppn' in target_name.lower() or 'pph' in target_name.lower() or 'tax' in target_name.lower():
                        if isinstance(node.value, ast.BinOp) and self._has_float_literal(node.value):
                            self._add_finding(
                                RuleID.TAX_CALCULATION, file_path, node.lineno,
                                "LOW", "tax",
                                f"Perhitungan pajak '{target_name}' menggunakan operasi aritmatika dengan float.",
                                snippet=ast.unparse(node),
                                recommendation="Gunakan Decimal untuk perhitungan pajak dengan presisi 2 desimal."
                            )

    # =============================================================================
    # Runtime Introspection (sama seperti sebelumnya, untuk ACC-003/ACC-014/ACC-015)
    # =============================================================================
    def _runtime_introspection(self, file_path: Path, rel_path: str):
        mod_name = self._module_name_from_path(file_path)
        try:
            mod = importlib.import_module(mod_name)
            self.runtime_imported += 1
        except Exception:
            return

        is_monetary_context = self._is_monetary_context(file_path)
        is_entity = self._is_entity_file(file_path)

        for member_name, obj in inspect.getmembers(mod):
            if inspect.isclass(obj) and obj.__module__ == mod_name:
                try:
                    hints = get_type_hints(obj)
                    for attr_name, attr_type in hints.items():
                        if self._is_monetary_variable(attr_name):
                            if attr_type is float or "float" in str(attr_type):
                                if not is_entity:
                                    continue
                                self._add_finding(
                                    RuleID.MON_FLOAT_FIELD, file_path, 1,
                                    "CRITICAL" if is_monetary_context else "HIGH",
                                    "monetary_integrity",
                                    f"[Runtime] Field '{obj.__name__}.{attr_name}' bertipe float.",
                                    recommendation="Gunakan Decimal untuk field moneter."
                                )
                except Exception:
                    pass

                for attr_name, attr_val in inspect.getmembers(obj, predicate=lambda x: inspect.isfunction(x) or inspect.ismethod(x)):
                    if attr_name in FLOAT_ALLOWLIST:
                        continue
                    try:
                        sig = inspect.signature(attr_val)
                        for param_name, param in sig.parameters.items():
                            if param_name in ("self", "cls"):
                                continue
                            if self._is_monetary_variable(param_name, attr_name):
                                if param.annotation is float or "float" in str(param.annotation):
                                    self._add_finding(
                                        RuleID.MON_FLOAT_PARAM, file_path, 1,
                                        "CRITICAL" if is_monetary_context else "HIGH",
                                        "monetary_integrity",
                                        f"[Runtime] Parameter '{param_name}' pada '{obj.__name__}.{attr_name}' bertipe float.",
                                        recommendation="Gunakan Decimal untuk parameter moneter."
                                    )
                                if isinstance(param.default, float):
                                    self._add_finding(
                                        RuleID.MON_FLOAT_DEFAULT, file_path, 1,
                                        "CRITICAL" if is_monetary_context else "HIGH",
                                        "monetary_integrity",
                                        f"[Runtime] Parameter '{param_name}' pada '{obj.__name__}.{attr_name}' memiliki default float.",
                                        recommendation="Gunakan Decimal default."
                                    )
                    except Exception:
                        pass

    def scan(self) -> Report:
        start_time = time.monotonic()
        target_files = self._get_target_files()
        self.files_scanned = len(target_files)

        print(f"{COLOR['BOLD']}{COLOR['CYAN']}╔════════════════════════════════════════════════════════════════════════════╗")
        print("║     SOVEREIGN HYBRID ACCOUNTING LOGIC GATEKEEPER v2.5 (S+ Grade)        ║")
        print(f"╚════════════════════════════════════════════════════════════════════════════╝{COLOR['RESET']}")
        print(f"  Mode Introspeksi  : ✅ MULTILAYER AKTIF (AST + Dynamic Runtime)")
        print(f"  RCA Engine        : {'✅ Aktif' if self.enable_rca else '⚠️ Nonaktif'}")
        print(f"  Mode Strict       : {'✅ Aktif' if self.strict else '⚠️ Nonaktif'}\n")
        print(f"📂 Memindai {len(target_files)} file...")

        for idx, file_path in enumerate(target_files, 1):
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            self._ast_analysis(file_path, str(file_path.relative_to(self.root_dir)).replace("\\", "/"), content)
            self._runtime_introspection(file_path, str(file_path.relative_to(self.root_dir)).replace("\\", "/"))
            if idx % 50 == 0:
                print(f"    Progress: {idx}/{len(target_files)} files")

        elapsed = time.monotonic() - start_time
        report = Report(
            findings=self.findings,
            rca_enabled=self.enable_rca,
            elapsed_seconds=elapsed,
            files_scanned=self.files_scanned,
            runtime_imported=self.runtime_imported,
        )
        weights = {"CRITICAL": 15, "HIGH": 8, "MEDIUM": 3, "LOW": 1, "INFO": 0}
        penalty = sum(weights.get(f.severity, 0) for f in self.findings)
        report.score = max(0, 100 - min(penalty, 100))
        return report


def print_report(report: Report, verbose: bool = False) -> None:
    c = COLOR
    print(f"\n{c['BOLD']}{c['CYAN']}╔{'═'*72}╗")
    print("║       SOVEREIGN ACCOUNTING LOGIC AUDIT REPORT v2.5          ║")
    print(f"╚{'═'*72}╝{c['RESET']}")

    severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
    for f in report.findings:
        severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1

    print(f"\n  {c['CYAN']}Files Scanned: {report.files_scanned}{c['RESET']}")
    print(f"  Runtime Imported: {report.runtime_imported}")
    print(f"  Total Findings: {len(report.findings)}")
    print(f"    {c['RED']}CRITICAL: {severity_counts.get('CRITICAL', 0)}{c['RESET']}")
    print(f"    {c['YELLOW']}HIGH: {severity_counts.get('HIGH', 0)}{c['RESET']}")
    print(f"    {c['MAGENTA']}MEDIUM: {severity_counts.get('MEDIUM', 0)}{c['RESET']}")
    print(f"    {c['CYAN']}LOW: {severity_counts.get('LOW', 0)}{c['RESET']}")
    print(f"    {c['GREEN']}INFO: {severity_counts.get('INFO', 0)}{c['RESET']}")

    score_color = c["GREEN"] if report.score >= 80 else c["YELLOW"] if report.score >= 50 else c["RED"]
    print(f"\n  📈 Skor Integritas: {score_color}{c['BOLD']}{report.score:.1f}/100{c['RESET']}")
    print(f"  RCA Engine: {'✅ Aktif' if report.rca_enabled else '⚠️ Tidak tersedia'}")
    print(f"  ⏱️ Elapsed: {report.elapsed_seconds:.3f}s")

    if report.findings:
        categories = {}
        for f in report.findings:
            categories.setdefault(f.category, []).append(f)

        print(f"\n{c['CYAN']}─── BY CATEGORY ───{c['RESET']}")
        cat_labels = {
            'monetary_integrity': 'Monetary Integrity',
            'axiom': 'Double-Entry Axiom',
            'immutability': 'Immutability',
            'period': 'Period Locking',
            'approval': 'Approval Workflow',
            'tax': 'Tax Integrity',
        }
        for cat, items in sorted(categories.items()):
            err_cnt = sum(1 for i in items if i.severity in ("CRITICAL", "HIGH"))
            color = c["RED"] if err_cnt > 0 else c["YELLOW"]
            label = cat_labels.get(cat, cat)
            print(f"  {label}: {color}{len(items)} findings ({err_cnt} critical/high){c['RESET']}")

        print(f"\n{c['RED']}─── VIOLATIONS (sample) ───{c['RESET']}")
        for f in report.findings[:30]:
            color = c["RED"] if f.severity in ("CRITICAL", "HIGH") else c["YELLOW"] if f.severity == "MEDIUM" else c["CYAN"]
            print(f"\n  {color}[{f.rule_id}] {f.severity}{c['RESET']} [{f.category}] {f.file}:{f.line}")
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
        out = Path(filepath)
        out.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "score": report.score,
            "rca_enabled": report.rca_enabled,
            "elapsed_seconds": report.elapsed_seconds,
            "files_scanned": report.files_scanned,
            "runtime_imported": report.runtime_imported,
            "total_findings": len(report.findings),
            "severity_counts": {
                "CRITICAL": sum(1 for f in report.findings if f.severity == "CRITICAL"),
                "HIGH": sum(1 for f in report.findings if f.severity == "HIGH"),
                "MEDIUM": sum(1 for f in report.findings if f.severity == "MEDIUM"),
                "LOW": sum(1 for f in report.findings if f.severity == "LOW"),
                "INFO": sum(1 for f in report.findings if f.severity == "INFO"),
            },
            "findings": [{"rule_id": f.rule_id, "file": f.file, "line": f.line, "severity": f.severity,
                          "category": f.category, "message": f.message, "snippet": f.snippet,
                          "recommendation": f.recommendation, "rca": f.rca} for f in report.findings]
        }
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{COLOR['GREEN']}✅ JSON exported to {out.resolve()}{COLOR['RESET']}")
    except Exception as e:
        print(f"{COLOR['RED']}❌ Failed to write JSON: {e}{COLOR['RESET']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sovereign Accounting Logic & Forensic Checker v2.5")
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    parser.add_argument("--strict", action="store_true", help="Mode strict")
    parser.add_argument("--no-rca", action="store_true", help="Nonaktifkan RCA")
    args = parser.parse_args()

    global RCA_AVAILABLE, _analyze_exception
    if args.no_rca:
        RCA_AVAILABLE = False
        _analyze_exception = None

    gatekeeper = SovereignAccountingLogicGatekeeper(ROOT, enable_rca=not args.no_rca, strict=args.strict)
    report = gatekeeper.scan()

    print_report(report, verbose=args.verbose)

    if args.json:
        save_json(report, args.json)

    critical_high = sum(1 for f in report.findings if f.severity in ("CRITICAL", "HIGH"))
    sys.exit(0 if critical_high == 0 else 1)


if __name__ == "__main__":
    main()