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

Fitur:
- --ignore-import-error : abaikan except ImportError (optional dependencies)
- --allow-return-none   : ubah 'except: return None' dari ERROR ke WARNING
- --exclude-files       : exclude file/folder dengan glob pattern (misal '*_test.py')
- --include             : batasi scan hanya pada folder/file tertentu (glob pattern)
- --min-severity        : tampilkan temuan dengan severity >= level (INFO/WARNING/ERROR)
- --strict              : semua temuan sebagai ERROR (tidak ada WARNING)
- --ignore-return       : exit code selalu 0 (untuk development)
- --max-findings        : batasi jumlah temuan yang ditampilkan (default 50)
- --no-color            : matikan output warna

Cara pakai:
  python exception_swallow_checker.py --ignore-import-error --allow-return-none --min-severity ERROR --verbose
  python exception_swallow_checker.py --exclude-files "*_test.py,generate_contracts.py" --include "domain/*,application/*"
  python exception_swallow_checker.py --json report.json --ignore-return
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import pathlib
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple

# =============================================================================
# Konfigurasi Warna
# =============================================================================
COLORS = {
    "RED": "\033[91m",
    "GREEN": "\033[92m",
    "YELLOW": "\033[93m",
    "CYAN": "\033[96m",
    "MAGENTA": "\033[95m",
    "WHITE": "\033[97m",
    "BOLD": "\033[1m",
    "DIM": "\033[2m",
    "RESET": "\033[0m",
}
NO_COLOR = False

def c(key: str) -> str:
    """Return color code if not NO_COLOR."""
    return "" if NO_COLOR else COLORS.get(key, "")

# =============================================================================
# Data Structures
# =============================================================================
@dataclass
class ExceptionFinding:
    file: str
    line: int
    severity: str  # "ERROR", "WARNING", "INFO"
    category: str
    message: str
    detail: str = ""
    suggestion: str = ""

@dataclass
class Report:
    total_files: int = 0
    total_except_blocks: int = 0
    findings: list[ExceptionFinding] = field(default_factory=list)
    score: int = 100

# =============================================================================
# AST Analyzer
# =============================================================================
class ExceptionAnalyzer:
    def __init__(self, options: Dict[str, Any]):
        self.options = options
        self.ignore_import_error = options.get("ignore_import_error", False)
        self.allow_return_none = options.get("allow_return_none", False)
        self.strict = options.get("strict", False)

    def analyze_file(self, tree: ast.AST, file_path: str) -> List[ExceptionFinding]:
        findings: List[ExceptionFinding] = []

        def _is_bare_except(handler: ast.ExceptHandler) -> bool:
            return handler.type is None

        def _is_empty_block(body: List[ast.stmt]) -> bool:
            if not body:
                return True
            if len(body) == 1:
                stmt = body[0]
                if isinstance(stmt, ast.Pass):
                    return True
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                    # Docstring only, considered empty
                    return True
            return False

        def _has_logging_or_raise(body: List[ast.stmt]) -> bool:
            for stmt in body:
                if isinstance(stmt, ast.Raise):
                    return True
                if isinstance(stmt, ast.Expr):
                    if isinstance(stmt.value, ast.Call):
                        func = stmt.value.func
                        if isinstance(func, ast.Name):
                            if func.id in ("logging", "print", "logger"):
                                return True
                        elif isinstance(func, ast.Attribute):
                            if func.attr in ("info", "warning", "error", "debug", "critical", "exception"):
                                return True
            return False

        def _has_return_none(body: List[ast.stmt]) -> bool:
            for stmt in body:
                if isinstance(stmt, ast.Return):
                    if stmt.value is None or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None):
                        return True
            return False

        def _get_exception_names(handler: ast.ExceptHandler) -> str:
            if handler.type is None:
                return "bare except"
            if isinstance(handler.type, ast.Name):
                return handler.type.id
            if isinstance(handler.type, ast.Attribute):
                return f"{handler.type.value.id}.{handler.type.attr}" if hasattr(handler.type.value, 'id') else str(handler.type)
            if isinstance(handler.type, ast.Tuple):
                names = []
                for elt in handler.type.elts:
                    if isinstance(elt, ast.Name):
                        names.append(elt.id)
                    else:
                        names.append(ast.unparse(elt))
                return "(" + ", ".join(names) + ")"
            return ast.unparse(handler.type)

        def _is_optional_import(handler: ast.ExceptHandler) -> bool:
            if handler.type is None:
                return False
            if isinstance(handler.type, ast.Name) and handler.type.id == "ImportError":
                return True
            # Sometimes tuple of exceptions includes ImportError
            if isinstance(handler.type, ast.Tuple):
                for elt in handler.type.elts:
                    if isinstance(elt, ast.Name) and elt.id == "ImportError":
                        return True
            return False

        def _is_generic_swallow(handler: ast.ExceptHandler) -> bool:
            if handler.type is None:
                return True
            if isinstance(handler.type, ast.Name) and handler.type.id in ("Exception", "BaseException"):
                return True
            if isinstance(handler.type, ast.Tuple):
                for elt in handler.type.elts:
                    if isinstance(elt, ast.Name) and elt.id in ("Exception", "BaseException"):
                        return True
            return False

        def _make_finding(
            severity: str,
            category: str,
            message: str,
            detail: str,
            suggestion: str,
            lineno: int,
        ) -> None:
            # If strict mode, convert WARNING to ERROR
            if self.strict and severity == "WARNING":
                severity = "ERROR"
            findings.append(ExceptionFinding(
                file=file_path,
                line=lineno,
                severity=severity,
                category=category,
                message=message,
                detail=detail,
                suggestion=suggestion,
            ))

        def _check_try(node: ast.Try) -> None:
            for handler in node.handlers:
                # Skip if ignore_import_error and this is an ImportError handler
                if self.ignore_import_error and _is_optional_import(handler):
                    continue

                exc_type = _get_exception_names(handler)
                is_bare = _is_bare_except(handler)
                is_empty = _is_empty_block(handler.body)
                has_log = _has_logging_or_raise(handler.body)
                has_return_none = _has_return_none(handler.body)

                # Determine severity and category
                if is_bare:
                    severity = "ERROR"
                    category = "BARE_EXCEPT"
                    msg = "Bare except detected (swallows all exceptions)"
                    suggestion = "Spesifikasikan exception type (misal: except ValueError:) dan log error."
                    _make_finding(severity, category, msg, f"Exception type: {exc_type}", suggestion, handler.lineno)
                    continue

                if is_empty:
                    if self.ignore_import_error and _is_optional_import(handler):
                        # This case is already skipped, but just in case
                        continue
                    # Empty except block
                    if _is_optional_import(handler):
                        severity = "WARNING"
                        category = "OPTIONAL_IMPORT"
                        msg = f"Empty except block for optional import ({exc_type})"
                        suggestion = "Jika ini memang optional import, ok, tapi pertimbangkan logging."
                    elif _is_generic_swallow(handler):
                        severity = "WARNING"
                        category = "SILENT_SWALLOW"
                        msg = f"Empty except block swallowing {exc_type} (silent)"
                        suggestion = "Tambahkan logging atau raise exception"
                    else:
                        severity = "ERROR"
                        category = "EMPTY_EXCEPT"
                        msg = f"Empty except block (no handling) for {exc_type}"
                        suggestion = "Tambahkan logging atau raise exception"
                    _make_finding(severity, category, msg, f"Exception type: {exc_type}", suggestion, handler.lineno)
                    continue

                # Non-empty block
                if not has_log:
                    # Check if it's a return None pattern
                    if has_return_none:
                        if self.allow_return_none:
                            severity = "WARNING"
                            category = "RETURN_NONE"
                            msg = f"Returning None in except handler (swallows {exc_type})"
                            suggestion = "Pertimbangkan logging sebelum return None."
                        else:
                            severity = "ERROR"
                            category = "SILENT_SWALLOW"
                            msg = f"Returning None without logging in except handler"
                            suggestion = "Tambahkan logging atau raise exception"
                    elif self.ignore_import_error and _is_optional_import(handler):
                        # This case already skipped earlier
                        continue
                    else:
                        severity = "ERROR"
                        category = "SILENT_SWALLOW"
                        msg = f"No logging/raise in except handler (exception swallowed)"
                        suggestion = "Tambahkan logging (logger.error) atau raise ulang exception."
                    _make_finding(severity, category, msg, f"Exception type: {exc_type}", suggestion, handler.lineno)

            # Check finally block
            if node.finalbody and _is_empty_block(node.finalbody):
                _make_finding(
                    severity="WARNING",
                    category="EMPTY_FINALLY",
                    message="Empty finally block (no cleanup)",
                    detail="",
                    suggestion="Tambahkan cleanup code atau hapus finally.",
                    lineno=node.lineno,
                )

        # Walk AST
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                _check_try(node)

        return findings

# =============================================================================
# Main Scanner
# =============================================================================
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

def scan_project(
    exclude_dirs: List[str],
    exclude_files: List[str],
    include_patterns: List[str],
    options: Dict[str, Any],
) -> Report:
    exclude_set = set(exclude_dirs)
    exclude_file_patterns = exclude_files or []
    include_patterns = include_patterns or []

    py_files = []
    for path in PROJECT_ROOT.rglob("*.py"):
        # Exclude by directory
        if any(part in exclude_set for part in path.parts):
            continue
        # Exclude by file pattern
        rel_path = str(path.relative_to(PROJECT_ROOT))
        if any(fnmatch.fnmatch(rel_path, pat) for pat in exclude_file_patterns):
            continue
        # Include only if include_patterns specified
        if include_patterns:
            if not any(fnmatch.fnmatch(rel_path, pat) for pat in include_patterns):
                continue
        py_files.append(path)

    analyzer = ExceptionAnalyzer(options)
    all_findings: List[ExceptionFinding] = []
    total_except = 0

    for f in py_files:
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(f))
        except SyntaxError:
            continue

        # Count except blocks
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                total_except += len(node.handlers)

        findings = analyzer.analyze_file(tree, str(f))
        all_findings.extend(findings)

    # Compute score
    errors = sum(1 for f in all_findings if f.severity == "ERROR")
    warnings = sum(1 for f in all_findings if f.severity == "WARNING")
    score = max(0, 100 - (errors * 10) - (warnings * 2))

    return Report(
        total_files=len(py_files),
        total_except_blocks=total_except,
        findings=all_findings,
        score=score,
    )

# =============================================================================
# Output
# =============================================================================
def print_report(report: Report, verbose: bool = False, min_severity: str = "INFO", max_findings: int = 50):
    severity_order = {"INFO": 0, "WARNING": 1, "ERROR": 2}
    min_level = severity_order.get(min_severity.upper(), 0)

    print(f"\n{c('BOLD')}{c('CYAN')}{'='*70}{c('RESET')}")
    print(f"{c('BOLD')}{c('CYAN')}EXCEPTION SWALLOW CHECKER REPORT{c('RESET')}")
    print(f"{c('CYAN')}{'='*70}{c('RESET')}")

    print(f"\n  Files scanned       : {report.total_files}")
    print(f"  Except blocks found : {report.total_except_blocks}")
    print(f"  Findings            : {len(report.findings)}")
    print(f"    - Errors          : {sum(1 for f in report.findings if f.severity=='ERROR')}")
    print(f"    - Warnings        : {sum(1 for f in report.findings if f.severity=='WARNING')}")
    print(f"    - Infos           : {sum(1 for f in report.findings if f.severity=='INFO')}")
    print(f"  Compliance score    : {c('GREEN') if report.score >= 80 else c('YELLOW')}{report.score}/100{c('RESET')}")

    # Filter findings by min_severity
    filtered = [f for f in report.findings if severity_order.get(f.severity, 0) >= min_level]

    if filtered:
        print(f"\n{c('RED') if any(f.severity=='ERROR' for f in filtered) else c('YELLOW')}Findings (showing first {min(max_findings, len(filtered))}):{c('RESET')}")
        for idx, f in enumerate(filtered[:max_findings]):
            color = c("RED") if f.severity == "ERROR" else c("YELLOW") if f.severity == "WARNING" else c("CYAN")
            print(f"  {color}{f.severity}{c('RESET')} {f.file}:{f.line}  [{f.category}]")
            print(f"       {f.message}")
            if f.detail:
                print(f"       Detail: {f.detail}")
            if verbose and f.suggestion:
                print(f"       💡 {f.suggestion}")
        if len(filtered) > max_findings:
            print(f"  ... and {len(filtered)-max_findings} more findings")
    else:
        print(f"\n{c('GREEN')}✅ No findings with severity >= {min_severity}!{c('RESET')}")

    print(f"\n{c('CYAN')}{'─'*70}{c('RESET')}")

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
    print(f"\n{c('CYAN')}JSON report saved to {filepath}{c('RESET')}")

# =============================================================================
# CLI
# =============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Exception Swallow Checker - Detect unsafe exception handling",
        epilog="""
Contoh:
  python exception_swallow_checker.py --ignore-import-error --allow-return-none --min-severity ERROR --verbose
  python exception_swallow_checker.py --exclude-files "*_test.py,generate_contracts.py" --include "domain/*,application/*"
  python exception_swallow_checker.py --json report.json --ignore-return
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan detail dan saran perbaikan")
    parser.add_argument("--json", metavar="FILE", help="Simpan laporan dalam format JSON")
    parser.add_argument("--quiet", "-q", action="store_true", help="Minimal output (hanya score)")
    parser.add_argument("--exclude", default=".venv,venv,__pycache__,node_modules,dist,build,migrations,deployment,docs,checker",
                        help="Folder yang diabaikan (pisahkan dengan koma, default: .venv,venv,__pycache__,...)")
    parser.add_argument("--exclude-files", default="",
                        help="File/folder yang diabaikan dengan glob pattern (pisahkan dengan koma), misal '*_test.py,setup.py'")
    parser.add_argument("--include", default="",
                        help="Hanya scan file/folder yang match glob pattern (pisahkan dengan koma), misal 'domain/*,application/*'")
    parser.add_argument("--min-severity", choices=["INFO", "WARNING", "ERROR"], default="INFO",
                        help="Minimal severity untuk ditampilkan (default: INFO)")
    parser.add_argument("--max-findings", type=int, default=50,
                        help="Maksimal jumlah temuan yang ditampilkan (default: 50)")
    parser.add_argument("--ignore-import-error", action="store_true",
                        help="Abaikan except ImportError (tidak dilaporkan sama sekali)")
    parser.add_argument("--allow-return-none", action="store_true",
                        help="Ubuh severity 'except ...: return None' dari ERROR ke WARNING")
    parser.add_argument("--strict", action="store_true",
                        help="Semua temuan dianggap ERROR (tidak ada WARNING)")
    parser.add_argument("--ignore-return", action="store_true",
                        help="Exit code selalu 0 (untuk development / pipeline)")
    parser.add_argument("--no-color", action="store_true",
                        help="Matikan output warna")
    args = parser.parse_args()

    global NO_COLOR
    if args.no_color:
        NO_COLOR = True

    exclude_dirs = [d.strip() for d in args.exclude.split(",") if d.strip()]
    exclude_files = [p.strip() for p in args.exclude_files.split(",") if p.strip()]
    include_patterns = [p.strip() for p in args.include.split(",") if p.strip()]

    options = {
        "ignore_import_error": args.ignore_import_error,
        "allow_return_none": args.allow_return_none,
        "strict": args.strict,
    }

    start = time.monotonic()
    report = scan_project(
        exclude_dirs=exclude_dirs,
        exclude_files=exclude_files,
        include_patterns=include_patterns,
        options=options,
    )

    if not args.quiet:
        print_report(report, verbose=args.verbose, min_severity=args.min_severity, max_findings=args.max_findings)
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