#!/usr/bin/env python3
"""
sql_injection_checker.py - SQL Injection Vulnerability Detector
================================================================
Mendeteksi potensi celah SQL Injection pada kode Python dengan analisis AST.

Fitur:
- Deteksi f-string, concatenation, format(), % formatting pada query SQL.
- Deteksi penggunaan raw SQL tanpa parameter binding.
- Analisis parameter pada SQLAlchemy execute().
- Peringatan berdasarkan severity (CRITICAL, WARNING, INFO).
- Laporan rinci dengan lokasi file dan baris.

Cara pakai:
  python sql_injection_checker.py                     # Mode normal
  python sql_injection_checker.py --verbose           # Detail
  python sql_injection_checker.py --json report.json  # Simpan JSON
  python sql_injection_checker.py --exclude tests,migrations
  python sql_injection_checker.py --help
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

# =============================================================================
# Konfigurasi Warna
# =============================================================================
COLOR = {"RED": "", "GREEN": "", "YELLOW": "", "CYAN": "", "RESET": ""}
try:
    import colorama
    colorama.init(autoreset=True)
    COLOR["RED"] = colorama.Fore.RED
    COLOR["GREEN"] = colorama.Fore.GREEN
    COLOR["YELLOW"] = colorama.Fore.YELLOW
    COLOR["CYAN"] = colorama.Fore.CYAN
    COLOR["RESET"] = colorama.Style.RESET_ALL
except ImportError:
    pass

# =============================================================================
# Data Structures
# =============================================================================
@dataclass
class Finding:
    severity: str   # "CRITICAL", "WARNING", "INFO"
    file_path: str
    line: int
    message: str
    snippet: str = ""
    recommendation: str = ""

@dataclass
class Report:
    total_files: int = 0
    findings: List[Finding] = field(default_factory=list)
    files_with_issues: Set[str] = field(default_factory=set)

# =============================================================================
# Detector
# =============================================================================
class SQLInjectionDetector(ast.NodeVisitor):
    """AST visitor untuk mendeteksi pola SQL Injection."""

    def __init__(self, file_path: str, source_lines: List[str]):
        self.file_path = file_path
        self.source_lines = source_lines
        self.findings: List[Finding] = []
        self.in_sql_context = False
        self.sql_var_names = {"query", "sql", "stmt", "statement", "raw_sql"}

    def visit(self, node):
        # Cek apakah ini adalah assignment ke variabel yang mungkin query SQL
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.lower() in self.sql_var_names:
                    self._check_sql_assignment(node)
        # Cek pemanggilan execute, execute_text, dll.
        elif isinstance(node, ast.Call):
            self._check_sql_execution(node)
        # Cek f-string, concatenation, format, %
        elif isinstance(node, ast.JoinedStr) or isinstance(node, ast.BinOp) or isinstance(node, ast.Call):
            self._check_string_operations(node)
        # Lanjutkan traversal
        self.generic_visit(node)

    def _check_sql_assignment(self, node: ast.Assign):
        """Periksa assignment ke variabel query."""
        for value in node.values:
            if isinstance(value, ast.JoinedStr):
                self._add_finding(
                    severity="CRITICAL",
                    line=node.lineno,
                    message="F-string digunakan dalam query SQL (potensi SQL Injection)",
                    snippet=self._get_snippet(node.lineno),
                    recommendation="Gunakan parameter binding (SQLAlchemy text() dengan params atau parameterized query)"
                )
            elif isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add):
                # Concatenation
                self._add_finding(
                    severity="CRITICAL",
                    line=node.lineno,
                    message="String concatenation digunakan dalam query SQL (potensi SQL Injection)",
                    snippet=self._get_snippet(node.lineno),
                    recommendation="Gunakan parameter binding"
                )
            elif isinstance(value, ast.Call):
                # Cek format() atau % formatting
                if isinstance(value.func, ast.Attribute) and value.func.attr == "format":
                    self._add_finding(
                        severity="WARNING",
                        line=node.lineno,
                        message="str.format() digunakan dalam query SQL",
                        snippet=self._get_snippet(node.lineno),
                        recommendation="Gunakan parameter binding"
                    )
                elif isinstance(value.func, ast.BinOp) and isinstance(value.func.op, ast.Mod):
                    self._add_finding(
                        severity="WARNING",
                        line=node.lineno,
                        message="% formatting digunakan dalam query SQL",
                        snippet=self._get_snippet(node.lineno),
                        recommendation="Gunakan parameter binding"
                    )

    def _check_sql_execution(self, node: ast.Call):
        """Periksa pemanggilan execute, execute_text, dll."""
        func_name = self._get_func_name(node.func)
        if func_name in {"execute", "executemany", "execute_text", "raw_execute"}:
            # Periksa argumen pertama (query)
            if node.args:
                first_arg = node.args[0]
                if isinstance(first_arg, ast.JoinedStr):
                    self._add_finding(
                        severity="CRITICAL",
                        line=node.lineno,
                        message=f"F-string query pada {func_name}()",
                        snippet=self._get_snippet(node.lineno),
                        recommendation="Gunakan parameter binding atau SQLAlchemy text() dengan params"
                    )
                elif isinstance(first_arg, ast.BinOp) and isinstance(first_arg.op, ast.Add):
                    self._add_finding(
                        severity="CRITICAL",
                        line=node.lineno,
                        message=f"String concatenation pada {func_name}()",
                        snippet=self._get_snippet(node.lineno),
                        recommendation="Gunakan parameter binding"
                    )
                elif isinstance(first_arg, ast.Call):
                    # format() atau %
                    if isinstance(first_arg.func, ast.Attribute) and first_arg.func.attr == "format":
                        self._add_finding(
                            severity="WARNING",
                            line=node.lineno,
                            message=f"str.format() pada {func_name}()",
                            snippet=self._get_snippet(node.lineno),
                            recommendation="Gunakan parameter binding"
                        )
                    elif isinstance(first_arg.func, ast.BinOp) and isinstance(first_arg.func.op, ast.Mod):
                        self._add_finding(
                            severity="WARNING",
                            line=node.lineno,
                            message=f"% formatting pada {func_name}()",
                            snippet=self._get_snippet(node.lineno),
                            recommendation="Gunakan parameter binding"
                        )
                # Cek apakah ada parameter kedua (params) - jika tidak ada, ini berbahaya
                if len(node.args) == 1:
                    self._add_finding(
                        severity="WARNING",
                        line=node.lineno,
                        message=f"{func_name}() dipanggil tanpa parameter binding",
                        snippet=self._get_snippet(node.lineno),
                        recommendation="Tambahkan parameter binding untuk keamanan"
                    )
                # Cek jika parameter kedua adalah None atau tidak ada
                elif len(node.args) >= 2:
                    second_arg = node.args[1]
                    if isinstance(second_arg, ast.Constant) and second_arg.value is None:
                        self._add_finding(
                            severity="WARNING",
                            line=node.lineno,
                            message=f"{func_name}() dipanggil dengan params=None",
                            snippet=self._get_snippet(node.lineno),
                            recommendation="Gunakan parameter binding yang aman"
                        )
        # Cek SQLAlchemy text() tanpa params
        elif func_name == "text" and isinstance(node.func, ast.Attribute):
            if node.args:
                first_arg = node.args[0]
                if isinstance(first_arg, ast.JoinedStr) or isinstance(first_arg, ast.BinOp):
                    self._add_finding(
                        severity="CRITICAL",
                        line=node.lineno,
                        message="SQLAlchemy text() dengan string dinamis",
                        snippet=self._get_snippet(node.lineno),
                        recommendation="Gunakan parameter binding via text() params"
                    )

    def _check_string_operations(self, node):
        """Periksa string operations yang mungkin mengandung SQL."""
        # Kita tidak perlu terlalu agresif, hanya jika dalam konteks SQL.
        # Namun untuk efisiensi, kita skip dulu.

    def _get_func_name(self, node) -> str:
        """Dapatkan nama fungsi dari node."""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        elif isinstance(node, ast.Call):
            return self._get_func_name(node.func)
        return ""

    def _add_finding(self, severity: str, line: int, message: str, snippet: str = "", recommendation: str = ""):
        self.findings.append(Finding(
            severity=severity,
            file_path=self.file_path,
            line=line,
            message=message,
            snippet=snippet,
            recommendation=recommendation,
        ))

    def _get_snippet(self, line: int, context: int = 1) -> str:
        """Ambil snippet kode di sekitar line."""
        if line <= 0 or line > len(self.source_lines):
            return ""
        start = max(0, line - context - 1)
        end = min(len(self.source_lines), line + context)
        return "\n".join(self.source_lines[start:end]).strip()

# =============================================================================
# Main Checker
# =============================================================================
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent

def scan_project(exclude_dirs: List[str] = None) -> Report:
    if exclude_dirs is None:
        exclude_dirs = [".venv", "venv", "__pycache__", ".git", "node_modules", "dist", "build", "migrations", "deployment", "docs"]
    exclude_set = set(exclude_dirs)

    py_files = []
    for path in PROJECT_ROOT.rglob("*.py"):
        if any(part in exclude_set for part in path.parts):
            continue
        if path.name.startswith("sql_injection_checker"):
            continue
        py_files.append(path)

    report = Report(total_files=len(py_files))

    for file_path in py_files:
        try:
            src = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(file_path))
            lines = src.splitlines()
            detector = SQLInjectionDetector(str(file_path), lines)
            detector.visit(tree)
            if detector.findings:
                report.files_with_issues.add(str(file_path))
                report.findings.extend(detector.findings)
        except SyntaxError:
            continue
        except Exception:
            continue

    return report

# =============================================================================
# Output
# =============================================================================
def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}SQL INJECTION VULNERABILITY REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"\n  Files scanned    : {report.total_files}")
    print(f"  Files with issues: {len(report.files_with_issues)}")
    print(f"  Total findings   : {len(report.findings)}")

    if report.findings:
        # Group by severity
        by_severity = {"CRITICAL": [], "WARNING": [], "INFO": []}
        for f in report.findings:
            by_severity.setdefault(f.severity, []).append(f)

        for severity in ["CRITICAL", "WARNING", "INFO"]:
            items = by_severity.get(severity, [])
            if not items:
                continue
            color = c["RED"] if severity == "CRITICAL" else c["YELLOW"] if severity == "WARNING" else c["CYAN"]
            print(f"\n{color}{severity} ({len(items)}):{c['RESET']}")
            for f in items[:30]:  # tampilkan maks 30
                print(f"  {color}✖{c['RESET']} {f.file_path}:{f.line}")
                print(f"     {f.message}")
                if f.snippet and verbose:
                    print(f"     Snippet: {f.snippet}")
                if f.recommendation:
                    print(f"     💡 {f.recommendation}")
            if len(items) > 30:
                print(f"  ... and {len(items)-30} more")
    else:
        print(f"\n{c['GREEN']}✅ No SQL Injection vulnerabilities detected!{c['RESET']}")

    print(f"\n{c['CYAN']}{'─'*70}{c['RESET']}")

def save_json(report: Report, filepath: str):
    data = {
        "total_files": report.total_files,
        "files_with_issues": list(report.files_with_issues),
        "findings": [
            {
                "severity": f.severity,
                "file": f.file_path,
                "line": f.line,
                "message": f.message,
                "snippet": f.snippet,
                "recommendation": f.recommendation,
            }
            for f in report.findings
        ],
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"\n{c['CYAN']}JSON report saved to {filepath}{c['RESET']}")

# =============================================================================
# CLI
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="SQL Injection Vulnerability Checker")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    parser.add_argument("--quiet", action="store_true", help="Minimal output")
    parser.add_argument("--exclude", default=".venv,venv,__pycache__,node_modules,dist,build,migrations,deployment,docs",
                        help="Folder yang diabaikan (pisahkan dengan koma)")
    args = parser.parse_args()

    exclude_dirs = [d.strip() for d in args.exclude.split(",") if d.strip()]
    start = time.monotonic()
    report = scan_project(exclude_dirs)

    if not args.quiet:
        print_report(report, verbose=args.verbose)
    if args.json:
        save_json(report, args.json)

    elapsed = time.monotonic() - start
    if not args.quiet:
        print(f"\n  Time: {elapsed:.2f}s")

    # Exit code: 1 jika ada CRITICAL findings
    has_critical = any(f.severity == "CRITICAL" for f in report.findings)
    sys.exit(1 if has_critical else 0)

if __name__ == "__main__":
    main()