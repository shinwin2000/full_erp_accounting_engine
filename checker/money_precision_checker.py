#!/usr/bin/env python3
"""
money_precision_checker.py - Monetary Precision Checker (KONTEKSTUAL)
========================================================================
Versi dengan klasifikasi kontekstual untuk membedakan:
- BUG nyata (CRITICAL/HIGH): decimal wajib
- Serialisasi (MEDIUM): float wajar di boundary
- False positive (LOW/INFO): metrics, latency, score, similarity

Cara pakai:
  python checker/money_precision_checker.py
  python checker/money_precision_checker.py --verbose
  python checker/money_precision_checker.py --strict   # naikkan MEDIUM jadi HIGH
  python checker/money_precision_checker.py --json report.json
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# Warna
COLOR = {"RED": "", "GREEN": "", "YELLOW": "", "CYAN": "", "MAGENTA": "", "RESET": ""}
try:
    import colorama
    colorama.init(autoreset=True)
    COLOR["RED"] = colorama.Fore.RED
    COLOR["GREEN"] = colorama.Fore.GREEN
    COLOR["YELLOW"] = colorama.Fore.YELLOW
    COLOR["CYAN"] = colorama.Fore.CYAN
    COLOR["MAGENTA"] = colorama.Fore.MAGENTA
    COLOR["RESET"] = colorama.Style.RESET_ALL
except ImportError:
    pass

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

# --- Field moneter (case-insensitive) ---
MONETARY_FIELDS = {
    'amount', 'debit', 'credit', 'price', 'cost', 'tax', 'total', 'balance',
    'value', 'subtotal', 'discount', 'fee', 'commission', 'interest', 'penalty',
    'payment', 'refund', 'adjustment', 'settlement', 'premium', 'deposit',
    'withdrawal', 'transfer', 'exchange', 'rate', 'currency_amount'
}

# --- Token NON-moneter (biasanya metric, score, waktu, dll) ---
NON_MONETARY_TOKENS = {
    'latency', 'time', 'duration', 'score', 'similarity', 'count', 'size',
    'bytes', 'percentage', 'probability', 'confidence', 'weight', 'rank',
    'freq', 'frequency', 'elapsed', 'wait', 'retry', 'attempt'
}

# --- Kata kunci fungsi serialisasi (float wajar) ---
SERIALIZATION_FUNC_TOKENS = {
    'serialize', 'to_dict', 'to_json', 'to_proto', 'to_grpc', 'to_dto',
    'to_message', 'to_pb', 'export', 'dump', 'encode', 'marshal'
}


class TypeKind(Enum):
    UNKNOWN = auto()
    INT = auto()
    FLOAT = auto()
    DECIMAL = auto()
    NONE = auto()


@dataclass
class Finding:
    file: str
    line: int
    severity: str          # CRITICAL / HIGH / MEDIUM / LOW / INFO
    category: str
    message: str
    snippet: str = ""
    recommendation: str = ""
    is_monetary: bool = True


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    score: int = 100


class TypeTracker(ast.NodeVisitor):
    def __init__(self, file_path: pathlib.Path, strict: bool = False):
        self.file_path = file_path
        self.strict = strict
        self.findings: list[Finding] = []

        self.scope_stack: list[dict[str, TypeKind]] = [{}]
        self.decimal_aliases: set[str] = {'Decimal'}

        self.current_function: Optional[str] = None
        self.current_class: Optional[str] = None

    # ---------- File Context ----------
    def _get_file_context(self) -> str:
        """Klasifikasi folder/file untuk menentukan seberapa kritis."""
        path_str = str(self.file_path).lower()
        # Core domain / repository → KRITIS
        if any(p in path_str for p in [
            '/domain/', '/entities/', '/value_objects/',
            '/repositories/', '/secondary_impl/', '/core/',
            'ledger_repository', 'account_repository', 'cash_book_repository',
            'tax_transaction_repository', 'ar_repository'
        ]):
            return "CRITICAL"
        # Primary API, gRPC, DTO, Mappers → SERIALISASI
        if any(p in path_str for p in [
            '/primary_api/', '/grpc_', '/rest_', '/dto', '/mappers/',
            'event_normalizer', 'publisher_application'
        ]):
            return "SERIALIZATION"
        # Audit, Monitoring, Metrics, Telemetry → RENDAH
        if any(p in path_str for p in [
            '/audit/', '/monitoring/', '/metrics/', '/telemetry/',
            'exporter', 'health_endpoints'
        ]):
            return "LOW"
        # Test / Disaster Recovery → RENDAH
        if any(p in path_str for p in ['/test/', '/tests/', 'dr_', 'rto_']):
            return "LOW"
        return "UNKNOWN"

    # ---------- Variable analyzer ----------
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
        return False

    # ---------- Scope management ----------
    def _current_scope(self) -> dict[str, TypeKind]:
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

        if isinstance(node, ast.Attribute):
            return TypeKind.UNKNOWN

        return TypeKind.UNKNOWN

    # ---------- Classify finding ----------
    def _classify_finding(self, var_name: str, node: ast.AST, category: str) -> tuple[str, str, bool]:
        """
        Klasifikasi severity dan rekomendasi.
        Returns: (severity, recommendation, is_monetary_bug)
        """
        # 1. Cek nama variabel non-moneter (score, latency, dll)
        if var_name and self._is_non_monetary_name(var_name):
            return ("INFO",
                    "Variabel ini berisi metric/waktu/skor (bukan uang) → abaikan jika bukan moneter",
                    False)

        # 2. Cek konteks serialisasi (gRPC, JSON, DTO)
        if self._is_serialization_context():
            return ("MEDIUM",
                    "Konteks serialisasi (to_proto/to_json) → float wajar di boundary, "
                    "pastikan nilai asli tetap Decimal sebelum dikonversi",
                    False)  # bukan bug, tapi perlu review

        # 3. Cek file context
        ctx = self._get_file_context()
        if ctx == "CRITICAL":
            return ("CRITICAL",
                    "BUG: Nilai moneter di core domain/repository harus Decimal, "
                    "jangan gunakan float() atau operasi float",
                    True)
        if ctx == "SERIALIZATION":
            return ("MEDIUM",
                    "Serialization boundary → float mungkin diperlukan, "
                    "tapi pastikan logika bisnis menggunakan Decimal",
                    False)
        if ctx == "LOW":
            return ("LOW",
                    "File di konteks audit/metric/test → kemungkinan false positive, "
                    "periksa manual jika ini benar-benar moneter",
                    False)

        # 4. Default: jika variabel ada di MONETARY_FIELDS → HIGH
        if var_name and var_name.lower() in MONETARY_FIELDS:
            return ("HIGH",
                    "Potensi bug: nilai moneter menggunakan float tanpa konteks serialisasi "
                    "→ periksa apakah ini benar-benar membutuhkan float",
                    True)

        return ("MEDIUM",
                "Perlu review: nilai yang mungkin moneter menggunakan float",
                False)

    # ---------- Visitors ----------
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == 'decimal':
            for alias in node.names:
                if alias.name == 'Decimal':
                    self.decimal_aliases.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == 'decimal':
                self.decimal_aliases.add('Decimal')
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter_scope()
        self.current_function = node.name
        for arg in node.args.args:
            if arg.annotation:
                anno_type = self._infer_annotation_type(arg.annotation)
                if anno_type != TypeKind.UNKNOWN:
                    self._set_var_type(arg.arg, anno_type)
        self.generic_visit(node)
        self._exit_scope()
        self.current_function = None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter_scope()
        self.current_class = node.name
        self.generic_visit(node)
        self._exit_scope()
        self.current_class = None

    def _infer_annotation_type(self, node: ast.expr) -> TypeKind:
        if isinstance(node, ast.Name):
            if node.id == 'float':
                return TypeKind.FLOAT
            if node.id == 'int':
                return TypeKind.INT
            if node.id == 'Decimal':
                return TypeKind.DECIMAL
        return TypeKind.UNKNOWN

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            var_name = node.target.id
            anno_type = self._infer_annotation_type(node.annotation)
            if anno_type != TypeKind.UNKNOWN:
                self._set_var_type(var_name, anno_type)

            if var_name.lower() in MONETARY_FIELDS and anno_type == TypeKind.FLOAT:
                severity, rec, _ = self._classify_finding(var_name, node, "float_type")
                self.findings.append(Finding(
                    file=str(self.file_path),
                    line=node.lineno,
                    severity=severity,
                    category="float_type",
                    message=f"Field '{var_name}' menggunakan type hint float (harus Decimal)",
                    snippet=ast.unparse(node),
                    recommendation=rec
                ))
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        rhs_type = self._infer_expr_type(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                var_name = target.id
                if rhs_type != TypeKind.UNKNOWN:
                    self._set_var_type(var_name, rhs_type)

                if var_name.lower() in MONETARY_FIELDS and rhs_type == TypeKind.FLOAT:
                    # Cek apakah RHS mengandung non-monetary token (misal similarity)
                    non_monetary_rhs = False
                    if isinstance(node.value, ast.BinOp):
                        # Cek apakah ada 'similarity' atau 'score' di left/right
                        for child in ast.walk(node.value):
                            if isinstance(child, ast.Name):
                                if self._is_non_monetary_name(child.id):
                                    non_monetary_rhs = True
                                    break
                    if non_monetary_rhs:
                        severity, rec, _ = "INFO", "RHS mengandung non-monetary token (score/similarity) → abaikan", False
                    else:
                        severity, rec, _ = self._classify_finding(var_name, node, "float_assignment")

                    self.findings.append(Finding(
                        file=str(self.file_path),
                        line=node.lineno,
                        severity=severity,
                        category="float_assignment",
                        message=f"Assign float literal/ekspresi ke field '{var_name}' (moneter)",
                        snippet=ast.unparse(node),
                        recommendation=rec
                    ))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            func_name = node.func.id

            # float(...)
            if func_name == 'float' and node.args:
                arg = node.args[0]
                var_name = None
                if isinstance(arg, ast.Name):
                    var_name = arg.id
                elif isinstance(arg, ast.Attribute):
                    # misal obj.amount
                    if isinstance(arg.attr, str):
                        var_name = arg.attr

                if var_name:
                    # Cek apakah variabel moneter
                    if var_name.lower() in MONETARY_FIELDS:
                        severity, rec, _ = self._classify_finding(var_name, node, "float_cast")
                        self.findings.append(Finding(
                            file=str(self.file_path),
                            line=node.lineno,
                            severity=severity,
                            category="float_cast",
                            message=f"Penggunaan float() pada variabel '{var_name}' (nilai moneter)",
                            snippet=ast.unparse(node),
                            recommendation=rec
                        ))
                elif isinstance(arg, ast.Constant) and isinstance(arg.value, float):
                    # float literal langsung
                    self.findings.append(Finding(
                        file=str(self.file_path),
                        line=node.lineno,
                        severity="LOW",
                        category="float_cast",
                        message="Literal float digunakan langsung (mungkin intentional)",
                        snippet=ast.unparse(node),
                        recommendation="Jika untuk konstanta, gunakan Decimal('...') jika moneter"
                    ))

            # round(...)
            if func_name == 'round' and node.args:
                arg = node.args[0]
                var_name = None
                if isinstance(arg, ast.Name):
                    var_name = arg.id
                elif isinstance(arg, ast.Attribute):
                    var_name = arg.attr

                if var_name and var_name.lower() in MONETARY_FIELDS:
                    severity, rec, _ = self._classify_finding(var_name, node, "rounding")
                    self.findings.append(Finding(
                        file=str(self.file_path),
                        line=node.lineno,
                        severity=severity,
                        category="rounding",
                        message=f"Penggunaan round() pada '{var_name}' (nilai moneter)",
                        snippet=ast.unparse(node),
                        recommendation=rec
                    ))

        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        # Deteksi operasi yang menghasilkan float dan melibatkan variabel moneter
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
            # Klasifikasi
            severity, rec, _ = self._classify_finding(var_name, node, "float_arithmetic")
            self.findings.append(Finding(
                file=str(self.file_path),
                line=node.lineno,
                severity=severity,
                category="float_arithmetic",
                message="Operasi aritmatika pada nilai moneter menghasilkan float",
                snippet=ast.unparse(node),
                recommendation=rec
            ))
        elif result_type == TypeKind.UNKNOWN and self.strict:
            self.findings.append(Finding(
                file=str(self.file_path),
                line=node.lineno,
                severity="INFO",
                category="float_arithmetic",
                message="Operasi dengan tipe tidak diketahui (strict mode)",
                snippet=ast.unparse(node),
                recommendation="Periksa manual apakah ini moneter"
            ))

        self.generic_visit(node)


# ----------------------------------------------------------------------
# Scanner
# ----------------------------------------------------------------------
def scan_file(file_path: pathlib.Path, strict: bool = False) -> list[Finding]:
    try:
        src = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(file_path))
    except SyntaxError:
        return []

    tracker = TypeTracker(file_path, strict=strict)
    tracker.visit(tree)
    return tracker.findings


def scan_money_precision(strict: bool = False) -> Report:
    report = Report()
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
        report.findings.extend(scan_file(py_file, strict=strict))

    # Scoring: CRITICAL -15, HIGH -8, MEDIUM -3, LOW -1, INFO 0
    weights = {"CRITICAL": 15, "HIGH": 8, "MEDIUM": 3, "LOW": 1, "INFO": 0}
    penalty = sum(weights.get(f.severity, 0) for f in report.findings)
    report.score = max(0, 100 - penalty)
    return report


# ----------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------
def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*80}{c['RESET']}")
    print(f"{c['CYAN']}MONEY PRECISION CHECKER — KONTEKSTUAL & CERDAS{c['RESET']}")
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

    if report.findings:
        # Group by severity
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
            "CRITICAL": "BUG HARUS DIPERBAIKI",
            "HIGH": "POTENSI BUG",
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

            for f in items[:20]:  # tampilkan 20 per kategori
                print(f"  {color}[{f.severity}]{c['RESET']} [{f.category}] {f.file}:{f.line}")
                print(f"     {f.message}")
                if verbose:
                    print(f"     Snippet: {f.snippet}")
                if f.recommendation:
                    print(f"     {c['CYAN']}💡 {f.recommendation}{c['RESET']}")
            if len(items) > 20:
                print(f"  ... and {len(items)-20} more findings in this category")


def save_json(report: Report, filepath: str):
    data = {
        "findings": [
            {"file": f.file, "line": f.line, "severity": f.severity,
             "category": f.category, "message": f.message,
             "snippet": f.snippet, "recommendation": f.recommendation}
            for f in report.findings
        ],
        "score": report.score,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{COLOR['CYAN']}JSON saved to {filepath}{COLOR['RESET']}")


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Money Precision Checker (Kontekstual)")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    parser.add_argument("--strict", action="store_true",
                        help="Mode strict: naikkan MEDIUM ke HIGH")
    args = parser.parse_args()

    report = scan_money_precision(strict=args.strict)
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)

    # Exit code: 1 jika ada CRITICAL atau HIGH
    critical_high = sum(1 for f in report.findings if f.severity in ("CRITICAL", "HIGH"))
    sys.exit(0 if critical_high == 0 else 1)


if __name__ == "__main__":
    main()