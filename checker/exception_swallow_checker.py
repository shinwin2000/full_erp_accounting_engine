#!/usr/bin/env python3
"""
exception_swallow_checker.py - Exception Swallowing & Bad Exception Handling Detector
=======================================================================================
Mendeteksi pola penanganan exception yang tidak aman:
- Bare except (except:)
- Empty except block (hanya pass, atau tidak ada kode)
- Catch-all except Exception tanpa logging atau re-raise
- Except yang menangkap base exception (Exception, BaseException) tanpa aksi
- Except dengan pass atau comment saja
- Try-finally yang menelan exception (tidak aman)

Cara pakai:
  python exception_swallow_checker.py                     # Mode normal
  python exception_swallow_checker.py --verbose           # Detail
  python exception_swallow_checker.py --json report.json  # Simpan JSON
  python exception_swallow_checker.py --exclude tests,migrations  # Exclude folder
  python exception_swallow_checker.py --ignore-return     # Hanya warning, tidak error
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

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
class ExceptionFinding:
    file: str
    line: int
    severity: str  # "ERROR" atau "WARNING"
    category: str
    message: str
    detail: str = ""
    suggestion: str = ""

@dataclass
class Report:
    total_files: int = 0
    total_except_blocks: int = 0
    findings: List[ExceptionFinding] = field(default_factory=list)
    score: int = 100

# =============================================================================
# AST Analyzer
# =============================================================================
def analyze_exception_handling(tree: ast.AST, file_path: str) -> List[ExceptionFinding]:
    findings = []

    def _is_bare_except(handler: ast.ExceptHandler) -> bool:
        """Cek apakah except handler adalah bare except (tanpa tipe)."""
        return handler.type is None

    def _is_empty_block(body: List[ast.stmt]) -> bool:
        """Cek apakah block hanya berisi pass, docstring, atau kosong."""
        if not body:
            return True
        if len(body) == 1:
            stmt = body[0]
            if isinstance(stmt, ast.Pass):
                return True
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                # Docstring hanya sebagai expr, dianggap kosong
                return True
        return False

    def _has_logging_or_raise(body: List[ast.stmt]) -> bool:
        """Cek apakah ada logging, print, atau raise di dalam block."""
        for stmt in body:
            if isinstance(stmt, ast.Raise):
                return True
            if isinstance(stmt, ast.Expr):
                if isinstance(stmt.value, ast.Call):
                    func = stmt.value.func
                    if isinstance(func, ast.Name):
                        if func.id in ("logging", "print"):
                            return True
                        # Cek apakah memanggil logger
                    elif isinstance(func, ast.Attribute):
                        if func.attr in ("info", "warning", "error", "debug", "critical", "exception"):
                            return True
        return False

    def _has_comment(body: List[ast.stmt]) -> bool:
        """Cek apakah ada komentar di dalam block (tidak bisa deteksi via AST). Kita abaikan."""
        return False

    def _is_swallow_pattern(handler: ast.ExceptHandler) -> bool:
        """
        True jika handler kemungkinan menelan exception (tidak ada logging/raise).
        """
        # Jika bare except, selalu dianggap menelan
        if _is_bare_except(handler):
            return True
        # Jika block kosong atau hanya pass
        if _is_empty_block(handler.body):
            return True
        # Jika tidak ada logging/raise, dianggap menelan
        if not _has_logging_or_raise(handler.body):
            return True
        return False

    def _get_exception_names(handler: ast.ExceptHandler) -> str:
        """Dapatkan nama exception yang ditangkap."""
        if handler.type is None:
            return "bare except"
        if isinstance(handler.type, ast.Name):
            return handler.type.id
        elif isinstance(handler.type, ast.Attribute):
            return f"{handler.type.value.id}.{handler.type.attr}" if hasattr(handler.type.value, 'id') else str(handler.type)
        else:
            return ast.unparse(handler.type)

    def _get_suggestion(handler: ast.ExceptHandler) -> str:
        """Berikan saran perbaikan."""
        if _is_bare_except(handler):
            return "Spesifikasikan exception type (misal: except ValueError:) dan log error."
        if _is_empty_block(handler.body):
            return "Tambahkan logging atau raise exception, jangan kosong."
        if not _has_logging_or_raise(handler.body):
            return "Tambahkan logging (logger.error) atau raise ulang exception."
        return ""

    def _check_try(node: ast.Try) -> None:
        # Cek setiap except handler
        for handler in node.handlers:
            if _is_swallow_pattern(handler):
                severity = "ERROR"
                category = "SILENT_SWALLOW"
                msg = f"Potential exception swallow: {_get_exception_names(handler)}"
                if _is_bare_except(handler):
                    msg = f"Bare except detected (swallows all exceptions)"
                elif _is_empty_block(handler.body):
                    msg = f"Empty except block (no handling)"
                else:
                    msg = f"No logging/raise in except handler (exception swallowed)"
                suggestion = _get_suggestion(handler)
                findings.append(ExceptionFinding(
                    file=file_path,
                    line=handler.lineno,
                    severity=severity,
                    category=category,
                    message=msg,
                    detail=f"Exception type: {_get_exception_names(handler)}",
                    suggestion=suggestion,
                ))

        # Cek finally block: jika ada pass atau kosong, mungkin menelan? Tidak, finally tidak menelan.
        # Tapi kita bisa peringatkan jika finally kosong.
        if node.finalbody and _is_empty_block(node.finalbody):
            findings.append(ExceptionFinding(
                file=file_path,
                line=node.lineno,
                severity="WARNING",
                category="EMPTY_FINALLY",
                message="Empty finally block (no cleanup)",
                suggestion="Tambahkan cleanup code atau hapus finally.",
            ))

    # Walk AST
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            _check_try(node)

    return findings

# =============================================================================
# Main Scanner
# =============================================================================
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent

def scan_project(exclude_dirs: List[str] = None, ignore_return: bool = False) -> Report:
    if exclude_dirs is None:
        exclude_dirs = [".venv", "venv", "__pycache__", ".git", "node_modules", "dist", "build", "migrations", "deployment", "docs"]
    exclude_set = set(exclude_dirs)

    py_files = []
    for path in PROJECT_ROOT.rglob("*.py"):
        if any(part in exclude_set for part in path.parts):
            continue
        if path.name.startswith("exception_swallow_checker"):
            continue
        py_files.append(path)

    all_findings = []
    total_except = 0

    for f in py_files:
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(f))
        except SyntaxError:
            continue

        # Hitung jumlah except blocks
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                total_except += len(node.handlers)

        findings = analyze_exception_handling(tree, str(f))
        all_findings.extend(findings)

    # Hitung skor: setiap ERROR mengurangi 10, WARNING mengurangi 2, max 100
    errors = sum(1 for f in all_findings if f.severity == "ERROR")
    warnings = sum(1 for f in all_findings if f.severity == "WARNING")
    score = max(0, 100 - (errors * 10) - (warnings * 2))

    # Jika ignore_return, jadikan semua severity WARNING? Tidak, kita tetap tampilkan tapi exit 0.
    # Kita akan ubah severity untuk output? Kita biarkan saja.

    return Report(
        total_files=len(py_files),
        total_except_blocks=total_except,
        findings=all_findings,
        score=score,
    )

# =============================================================================
# Output
# =============================================================================
def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*70}{c['RESET']}")
    print(f"{c['CYAN']}EXCEPTION SWALLOW CHECKER REPORT{c['RESET']}")
    print(f"{c['CYAN']}{'='*70}{c['RESET']}")

    print(f"\n  Files scanned       : {report.total_files}")
    print(f"  Except blocks found : {report.total_except_blocks}")
    print(f"  Findings            : {len(report.findings)}")
    print(f"    - Errors          : {sum(1 for f in report.findings if f.severity=='ERROR')}")
    print(f"    - Warnings        : {sum(1 for f in report.findings if f.severity=='WARNING')}")
    print(f"  Compliance score    : {c['GREEN'] if report.score >= 80 else c['YELLOW']}{report.score}/100{c['RESET']}")

    if report.findings:
        print(f"\n{c['RED'] if any(f.severity=='ERROR' for f in report.findings) else c['YELLOW']}Findings:{c['RESET']}")
        for f in report.findings[:30]:  # tampilkan maks 30
            color = c["RED"] if f.severity == "ERROR" else c["YELLOW"]
            print(f"  {color}{f.severity}{c['RESET']} {f.file}:{f.line}  [{f.category}]")
            print(f"       {f.message}")
            if f.detail:
                print(f"       Detail: {f.detail}")
            if verbose and f.suggestion:
                print(f"       💡 {f.suggestion}")
        if len(report.findings) > 30:
            print(f"  ... and {len(report.findings)-30} more findings")
    else:
        print(f"\n{c['GREEN']}✅ No exception swallowing detected!{c['RESET']}")

    print(f"\n{c['CYAN']}{'─'*70}{c['RESET']}")

def save_json(report: Report, filepath: str):
    data = {
        "total_files": report.total_files,
        "total_except_blocks": report.total_except_blocks,
        "findings_count": len(report.findings),
        "score": report.score,
        "findings": [
            {
                "file": f.file,
                "line": f.line,
                "severity": f.severity,
                "category": f.category,
                "message": f.message,
                "detail": f.detail,
                "suggestion": f.suggestion,
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
    parser = argparse.ArgumentParser(description="Exception Swallow Checker")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail")
    parser.add_argument("--json", metavar="FILE", help="Simpan JSON")
    parser.add_argument("--quiet", action="store_true", help="Minimal output")
    parser.add_argument("--exclude", default=".venv,venv,__pycache__,node_modules,dist,build,migrations,deployment,docs",
                        help="Folder yang diabaikan (pisahkan dengan koma)")
    parser.add_argument("--ignore-return", action="store_true", help="Exit code 0 meski ada temuan (untuk development)")
    args = parser.parse_args()

    exclude_dirs = [d.strip() for d in args.exclude.split(",") if d.strip()]
    start = time.monotonic()
    report = scan_project(exclude_dirs, args.ignore_return)

    if not args.quiet:
        print_report(report, verbose=args.verbose)
    if args.json:
        save_json(report, args.json)

    elapsed = time.monotonic() - start
    if not args.quiet:
        print(f"\n  Time: {elapsed:.2f}s")

    # Exit code: 0 jika tidak ada ERROR findings, kecuali ignore_return
    has_error = any(f.severity == "ERROR" for f in report.findings)
    if args.ignore_return:
        sys.exit(0)
    else:
        sys.exit(1 if has_error else 0)

if __name__ == "__main__":
    main()