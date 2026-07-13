#!/usr/bin/env python3
"""
exception_swallow_checker.py - Exception Swallowing & Bad Exception Handling Detector
=======================================================================================
Version 2.1 — Semantic Audit-Grade with Group-by-File

Fitur tambahan:
- --group-by-file / -g: tampilkan laporan per file
- --max-per-file: batas temuan per file (default 10)
- --max-findings: batas total temuan (default 100)
- Confidence score, breakdown, dll.

Cara pakai:
  python exception_swallow_checker.py --verbose --group-by-file
  python exception_swallow_checker.py --group-by-file --max-per-file 20
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import pathlib
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

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
    return "" if NO_COLOR else COLORS.get(key, "")

# =============================================================================
# Data Structures
# =============================================================================
@dataclass
class ExceptionFinding:
    file: str
    line: int
    severity: str          # "ERROR", "WARNING", "INFO"
    category: str
    message: str
    detail: str = ""
    suggestion: str = ""
    confidence: int = 0    # 0-100

@dataclass
class Report:
    total_files: int = 0
    total_except_blocks: int = 0
    findings: list[ExceptionFinding] = field(default_factory=list)
    score: float = 100.0
    # Breakdown stats
    valid_handling: int = 0
    business_handling: int = 0
    rollback_handling: int = 0
    cleanup_handling: int = 0
    logger_handling: int = 0
    real_violations: int = 0

# =============================================================================
# Semantic Analyzer
# =============================================================================
class SemanticExceptionAnalyzer:
    LOGGING_CALLS = {
        "logger", "logging", "log", "audit", "telemetry", "metrics", "trace",
        "debug", "info", "warning", "error", "critical", "exception",
    }
    ROLLBACK_CALLS = {
        "rollback", "close", "cancel", "cleanup", "revert", "undo",
        "session.rollback", "uow.rollback", "transaction.rollback",
    }
    BUSINESS_RESULT_RETURNS = {
        "Result.failure", "Result.success", "Either.left", "Either.right",
        "CommandResult.failure", "CommandResult.success",
        "Failure", "Error", "ValidationResult", "HTTPException",
        "JSONResponse", "Response", "RedirectResponse", "PlainTextResponse",
        "HTMLResponse", "FileResponse", "StreamingResponse",
    }
    BUSINESS_EXCEPTION_SUFFIXES = {"Error", "Exception", "Failure", "Invalid", "NotFound", "AlreadyExists", "Locked", "Timeout"}

    def __init__(self, options: dict[str, Any]):
        self.options = options
        self.ignore_import_error = options.get("ignore_import_error", False)
        self.allow_return_none = options.get("allow_return_none", False)
        self.strict = options.get("strict", False)

    def analyze_file(self, tree: ast.AST, file_path: str) -> tuple[list[ExceptionFinding], int, int, int, int, int, int, int]:
        findings: list[ExceptionFinding] = []
        total_except = 0
        valid_handling = 0
        business_handling = 0
        rollback_handling = 0
        cleanup_handling = 0
        logger_handling = 0
        real_violations = 0

        def _is_bare_except(handler: ast.ExceptHandler) -> bool:
            return handler.type is None

        def _is_empty_block(body: list[ast.stmt]) -> bool:
            if not body:
                return True
            if len(body) == 1:
                stmt = body[0]
                if isinstance(stmt, ast.Pass):
                    return True
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                    return True
            return False

        def _has_raise(body: list[ast.stmt]) -> bool:
            for stmt in body:
                if isinstance(stmt, ast.Raise):
                    return True
            return False

        def _has_logging(body: list[ast.stmt]) -> bool:
            for stmt in body:
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    func = stmt.value.func
                    if isinstance(func, ast.Name) and func.id in self.LOGGING_CALLS:
                        return True
                    if isinstance(func, ast.Attribute):
                        if func.attr in self.LOGGING_CALLS:
                            return True
                        if isinstance(func.value, ast.Name) and func.value.id in self.LOGGING_CALLS:
                            return True
            return False

        def _has_rollback_cleanup(body: list[ast.stmt]) -> tuple[bool, bool]:
            rollback = False
            cleanup = False
            for stmt in body:
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    func = stmt.value.func
                    if isinstance(func, ast.Name):
                        if func.id in self.ROLLBACK_CALLS:
                            rollback = True
                        if func.id in {"cleanup", "close", "cancel"}:
                            cleanup = True
                    elif isinstance(func, ast.Attribute):
                        attr = func.attr
                        if attr in self.ROLLBACK_CALLS:
                            rollback = True
                        if attr in {"cleanup", "close", "cancel"}:
                            cleanup = True
                        if attr == "rollback" and isinstance(func.value, ast.Name):
                            if func.value.id in {"session", "uow", "transaction"}:
                                rollback = True
            return rollback, cleanup

        def _has_business_result_return(body: list[ast.stmt]) -> bool:
            for stmt in body:
                if isinstance(stmt, ast.Return) and stmt.value is not None:
                    if isinstance(stmt.value, ast.Call):
                        func = stmt.value.func
                        if isinstance(func, ast.Name):
                            if func.id in {"Result", "Either", "CommandResult", "Failure", "Error", "ValidationResult"}:
                                return True
                        if isinstance(func, ast.Attribute):
                            if func.attr in {"failure", "success", "left", "right"}:
                                return True
                            if func.attr in {"invalid", "valid", "not_found", "already_exists"}:
                                return True
                    if isinstance(stmt.value, ast.Name):
                        if stmt.value.id in {"HTTPException", "JSONResponse", "Response"}:
                            return True
            return False

        def _has_return_none(body: list[ast.stmt]) -> bool:
            for stmt in body:
                if isinstance(stmt, ast.Return):
                    if stmt.value is None or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None):
                        return True
            return False

        def _has_return(body: list[ast.stmt]) -> bool:
            for stmt in body:
                if isinstance(stmt, ast.Return):
                    return True
            return False

        def _is_optional_import(handler: ast.ExceptHandler) -> bool:
            if handler.type is None:
                return False
            if isinstance(handler.type, ast.Name) and handler.type.id == "ImportError":
                return True
            if isinstance(handler.type, ast.Tuple):
                for elt in handler.type.elts:
                    if isinstance(elt, ast.Name) and elt.id == "ImportError":
                        return True
            return False

        def _is_business_exception(handler: ast.ExceptHandler) -> bool:
            if handler.type is None:
                return False
            if isinstance(handler.type, ast.Name):
                name = handler.type.id
                return any(name.endswith(suffix) for suffix in self.BUSINESS_EXCEPTION_SUFFIXES)
            if isinstance(handler.type, ast.Tuple):
                for elt in handler.type.elts:
                    if isinstance(elt, ast.Name):
                        if any(elt.id.endswith(suffix) for suffix in self.BUSINESS_EXCEPTION_SUFFIXES):
                            return True
            return False

        def _method_name_is_finder(handler: ast.ExceptHandler, tree: ast.AST) -> bool:
            parent = handler
            while parent:
                if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = parent.name.lower()
                    if any(name.startswith(prefix) for prefix in ("find", "get", "fetch", "retrieve")):
                        return True
                    break
                parent = getattr(parent, 'parent', None)
            return False

        def _determine_handling_type(handler: ast.ExceptHandler, body: list[ast.stmt]) -> dict[str, Any]:
            has_log = _has_logging(body)
            has_raise = _has_raise(body)
            has_rollback, has_cleanup = _has_rollback_cleanup(body)
            has_business_result = _has_business_result_return(body)
            has_return_none = _has_return_none(body)
            is_empty = _is_empty_block(body)
            is_import_error = _is_optional_import(handler)
            is_business_exc = _is_business_exception(handler)

            return {
                "has_log": has_log,
                "has_raise": has_raise,
                "has_rollback": has_rollback,
                "has_cleanup": has_cleanup,
                "has_business_result": has_business_result,
                "has_return_none": has_return_none,
                "is_empty": is_empty,
                "is_import_error": is_import_error,
                "is_business_exception": is_business_exc,
            }

        def _classify_handling(handler: ast.ExceptHandler, body: list[ast.stmt], exc_type: str) -> tuple[str, int, str, str]:
            info = _determine_handling_type(handler, body)
            is_bare = _is_bare_except(handler)
            is_empty = info["is_empty"]
            has_log = info["has_log"]
            has_raise = info["has_raise"]
            has_rollback = info["has_rollback"]
            has_cleanup = info["has_cleanup"]
            has_business_result = info["has_business_result"]
            has_return_none = info["has_return_none"]
            is_import_error = info["is_import_error"]
            is_business_exc = info["is_business_exception"]

            if self.ignore_import_error and is_import_error:
                return ("IGNORE", 0, "IGNORE", "")

            if is_bare:
                return ("ERROR", 95, "BARE_EXCEPT", "Spesifikasikan exception type (misal: except ValueError:) dan log error.")

            if has_raise:
                return ("PASS", 100, "RAISE", "Exception raised properly.")

            if has_log:
                return ("PASS", 100, "LOGGED", "Exception logged.")

            if has_rollback:
                return ("PASS", 95, "ROLLBACK", "Transaction rolled back.")

            if has_cleanup:
                if not has_raise and not has_log:
                    return ("WARNING", 60, "CLEANUP", "Only cleanup performed; consider logging or raising if critical.")
                return ("PASS", 90, "CLEANUP", "Cleanup performed.")

            if has_business_result:
                return ("PASS", 95, "BUSINESS_RESULT", "Exception converted to business result.")

            if is_business_exc:
                if _has_return(body) or has_business_result:
                    return ("PASS", 90, "BUSINESS_HANDLING", "Business exception handled properly.")
                else:
                    return ("WARNING", 50, "BUSINESS_HANDLING", "Business exception caught but no explicit handling (no return, no raise).")

            if has_return_none:
                if _method_name_is_finder(handler, handler):
                    if self.allow_return_none:
                        return ("PASS", 90, "RETURN_NONE", "Return None in finder method is acceptable.")
                    else:
                        return ("WARNING", 70, "RETURN_NONE", "Return None in exception handler; consider logging.")
                else:
                    if self.allow_return_none:
                        return ("WARNING", 60, "RETURN_NONE", "Return None in exception handler (allowed).")
                    else:
                        return ("ERROR", 80, "RETURN_NONE", "Return None without logging; exception swallowed.")

            if is_empty:
                return ("ERROR", 95, "EMPTY_EXCEPT", "Empty except block – no handling at all.")

            return ("ERROR", 85, "SILENT_SWALLOW", "No logging/raise/rollback/business result; exception likely swallowed.")

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

        def _check_try(node: ast.Try) -> None:
            nonlocal total_except, valid_handling, business_handling, rollback_handling, cleanup_handling, logger_handling, real_violations

            for handler in node.handlers:
                total_except += 1
                exc_type = _get_exception_names(handler)
                body = handler.body

                severity, confidence, category, suggestion = _classify_handling(handler, body, exc_type)

                if severity == "IGNORE":
                    continue

                if severity == "PASS":
                    valid_handling += 1
                    if category == "BUSINESS_RESULT" or category == "BUSINESS_HANDLING":
                        business_handling += 1
                    elif category == "ROLLBACK":
                        rollback_handling += 1
                    elif category == "CLEANUP":
                        cleanup_handling += 1
                    elif category == "LOGGED":
                        logger_handling += 1
                else:
                    real_violations += 1

                if self.strict and severity == "WARNING":
                    severity = "ERROR"

                findings.append(ExceptionFinding(
                    file=file_path,
                    line=handler.lineno,
                    severity=severity,
                    category=category,
                    message=f"Exception handling: {severity}",
                    detail=f"Exception type: {exc_type}. {suggestion}",
                    suggestion=suggestion,
                    confidence=confidence,
                ))

        # Set parent links for context
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                child.parent = node

        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                _check_try(node)

        return findings, total_except, valid_handling, business_handling, rollback_handling, cleanup_handling, logger_handling, real_violations

# =============================================================================
# Main Scanner
# =============================================================================
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

def scan_project(
    exclude_dirs: list[str],
    exclude_files: list[str],
    include_patterns: list[str],
    options: dict[str, Any],
) -> Report:
    exclude_set = set(exclude_dirs)
    exclude_file_patterns = exclude_files or []
    include_patterns = include_patterns or []

    py_files = []
    for path in PROJECT_ROOT.rglob("*.py"):
        if any(part in exclude_set for part in path.parts):
            continue
        rel_path = str(path.relative_to(PROJECT_ROOT))
        if any(fnmatch.fnmatch(rel_path, pat) for pat in exclude_file_patterns):
            continue
        if include_patterns:
            if not any(fnmatch.fnmatch(rel_path, pat) for pat in include_patterns):
                continue
        py_files.append(path)

    analyzer = SemanticExceptionAnalyzer(options)
    all_findings: list[ExceptionFinding] = []
    total_except_global = 0
    valid_handling_global = 0
    business_handling_global = 0
    rollback_handling_global = 0
    cleanup_handling_global = 0
    logger_handling_global = 0
    real_violations_global = 0

    for f in py_files:
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(f))
        except SyntaxError:
            continue

        findings, total_except, valid_handling, business_handling, rollback_handling, cleanup_handling, logger_handling, real_violations = analyzer.analyze_file(tree, str(f))
        total_except_global += total_except
        valid_handling_global += valid_handling
        business_handling_global += business_handling
        rollback_handling_global += rollback_handling
        cleanup_handling_global += cleanup_handling
        logger_handling_global += logger_handling
        real_violations_global += real_violations
        all_findings.extend(findings)

    if total_except_global > 0:
        score = (valid_handling_global / total_except_global) * 100
    else:
        score = 100.0

    return Report(
        total_files=len(py_files),
        total_except_blocks=total_except_global,
        findings=all_findings,
        score=round(score, 2),
        valid_handling=valid_handling_global,
        business_handling=business_handling_global,
        rollback_handling=rollback_handling_global,
        cleanup_handling=cleanup_handling_global,
        logger_handling=logger_handling_global,
        real_violations=real_violations_global,
    )

# =============================================================================
# Output
# =============================================================================
def print_report(report: Report, verbose: bool = False, min_severity: str = "INFO", max_findings: int = 50, group_by_file: bool = False, max_per_file: int = 10):
    severity_order = {"INFO": 0, "WARNING": 1, "ERROR": 2}
    min_level = severity_order.get(min_severity.upper(), 0)

    print(f"\n{c('BOLD')}{c('CYAN')}{'='*80}{c('RESET')}")
    print(f"{c('BOLD')}{c('CYAN')}EXCEPTION SWALLOW CHECKER REPORT v2.1 — Semantic Audit-Grade{c('RESET')}")
    print(f"{c('CYAN')}{'='*80}{c('RESET')}")

    print(f"\n  Files scanned              : {report.total_files}")
    print(f"  Total except blocks        : {report.total_except_blocks}")
    print(f"  Valid handling             : {c('GREEN')}{report.valid_handling}{c('RESET')} ({report.valid_handling/report.total_except_blocks*100:.1f}%)")
    print(f"    - Logging                : {report.logger_handling}")
    print("    - Raise                  : included in logging")
    print(f"    - Rollback               : {report.rollback_handling}")
    print(f"    - Cleanup                : {report.cleanup_handling}")
    print(f"    - Business result        : {report.business_handling}")
    print(f"  Real violations            : {c('RED')}{report.real_violations}{c('RESET')} ({report.real_violations/report.total_except_blocks*100:.1f}%)")
    print(f"  Compliance score           : {c('GREEN') if report.score >= 90 else c('YELLOW')}{report.score:.1f}/100{c('RESET')}")

    # Filter findings
    filtered = [f for f in report.findings if severity_order.get(f.severity, 0) >= min_level]

    if not filtered:
        print(f"\n{c('GREEN')}✅ No violations with severity >= {min_severity}!{c('RESET')}")
        print(f"\n{c('CYAN')}{'─'*80}{c('RESET')}")
        return

    if group_by_file:
        # Group by file
        grouped: dict[str, list[ExceptionFinding]] = defaultdict(list)
        for f in filtered:
            grouped[f.file].append(f)

        # Sort files by total violations (descending)
        sorted_files = sorted(grouped.items(), key=lambda kv: len(kv[1]), reverse=True)

        print(f"\n{c('BOLD')}{c('YELLOW')}Violations per file (showing {len(sorted_files)} files, max {max_per_file} per file):{c('RESET')}")
        print(f"{c('DIM')}{'─'*80}{c('RESET')}")

        for file_path, file_findings in sorted_files[:max_findings]:
            errors = sum(1 for f in file_findings if f.severity == "ERROR")
            warnings = sum(1 for f in file_findings if f.severity == "WARNING")
            infos = sum(1 for f in file_findings if f.severity == "INFO")
            total = len(file_findings)

            # Shorten file path for display (relative to project root)
            try:
                rel_path = str(pathlib.Path(file_path).relative_to(PROJECT_ROOT))
            except ValueError:
                rel_path = file_path

            print(f"\n{c('BOLD')}{c('CYAN')}{rel_path}{c('RESET')}")
            print(f"  {c('RED')}ERROR: {errors}{c('RESET')}  {c('YELLOW')}WARNING: {warnings}{c('RESET')}  {c('DIM')}INFO: {infos}{c('RESET')}  Total: {total}")

            # Show findings for this file (limited by max_per_file)
            for idx, f in enumerate(file_findings[:max_per_file]):
                color = c("RED") if f.severity == "ERROR" else c("YELLOW") if f.severity == "WARNING" else c("CYAN")
                conf_color = c("GREEN") if f.confidence >= 80 else c("YELLOW") if f.confidence >= 50 else c("RED")
                print(f"    {color}{f.severity}{c('RESET')} line {f.line}  [{f.category}]  {conf_color}Confidence: {f.confidence}%{c('RESET')}")
                print(f"       {f.message}")
                if f.detail:
                    print(f"       Detail: {f.detail}")
                if verbose and f.suggestion:
                    print(f"       💡 {f.suggestion}")

            if len(file_findings) > max_per_file:
                print(f"    ... and {len(file_findings)-max_per_file} more in this file")
    else:
        # Normal list mode
        print(f"\n{c('RED') if any(f.severity=='ERROR' for f in filtered) else c('YELLOW')}Violations (showing first {min(max_findings, len(filtered))}):{c('RESET')}")
        for idx, f in enumerate(filtered[:max_findings]):
            color = c("RED") if f.severity == "ERROR" else c("YELLOW") if f.severity == "WARNING" else c("CYAN")
            conf_color = c("GREEN") if f.confidence >= 80 else c("YELLOW") if f.confidence >= 50 else c("RED")
            print(f"  {color}{f.severity}{c('RESET')} {f.file}:{f.line}  [{f.category}]  {conf_color}Confidence: {f.confidence}%{c('RESET')}")
            print(f"       {f.message}")
            if f.detail:
                print(f"       Detail: {f.detail}")
            if verbose and f.suggestion:
                print(f"       💡 {f.suggestion}")

        if len(filtered) > max_findings:
            print(f"  ... and {len(filtered)-max_findings} more violations")

    print(f"\n{c('CYAN')}{'─'*80}{c('RESET')}")

def save_json(report: Report, filepath: str):
    data = {
        "version": "2.1",
        "total_files": report.total_files,
        "total_except_blocks": report.total_except_blocks,
        "valid_handling": report.valid_handling,
        "business_handling": report.business_handling,
        "rollback_handling": report.rollback_handling,
        "cleanup_handling": report.cleanup_handling,
        "logger_handling": report.logger_handling,
        "real_violations": report.real_violations,
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
                "confidence": f.confidence,
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
        description="Exception Swallow Checker v2.1 - Semantic Audit-Grade",
        epilog="""
Contoh:
  python exception_swallow_checker.py --verbose --group-by-file
  python exception_swallow_checker.py --group-by-file --max-per-file 20 --ignore-import-error
  python exception_swallow_checker.py --min-severity ERROR --verbose
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Tampilkan detail dan saran perbaikan")
    parser.add_argument("--json", metavar="FILE", help="Simpan laporan dalam format JSON")
    parser.add_argument("--quiet", "-q", action="store_true", help="Minimal output (hanya score)")
    parser.add_argument("--exclude", default=".venv,venv,__pycache__,node_modules,dist,build,migrations,deployment,docs,checker",
                        help="Folder yang diabaikan (pisahkan dengan koma)")
    parser.add_argument("--exclude-files", default="",
                        help="File/folder yang diabaikan dengan glob pattern (pisahkan dengan koma)")
    parser.add_argument("--include", default="",
                        help="Hanya scan file/folder yang match glob pattern (pisahkan dengan koma)")
    parser.add_argument("--min-severity", choices=["INFO", "WARNING", "ERROR"], default="INFO",
                        help="Minimal severity untuk ditampilkan (default: INFO)")
    parser.add_argument("--max-findings", type=int, default=50,
                        help="Maksimal jumlah temuan yang ditampilkan (default: 50)")
    parser.add_argument("--group-by-file", "-g", action="store_true",
                        help="Kelompokkan temuan per file")
    parser.add_argument("--max-per-file", type=int, default=10,
                        help="Maksimal temuan per file yang ditampilkan (default: 10, hanya berlaku dengan --group-by-file)")
    parser.add_argument("--ignore-import-error", action="store_true",
                        help="Abaikan except ImportError (tidak dilaporkan sama sekali)")
    parser.add_argument("--allow-return-none", action="store_true",
                        help="Izinkan return None di except (tidak dianggap error)")
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
        print_report(
            report,
            verbose=args.verbose,
            min_severity=args.min_severity,
            max_findings=args.max_findings,
            group_by_file=args.group_by_file,
            max_per_file=args.max_per_file,
        )
    if args.json:
        save_json(report, args.json)

    elapsed = time.monotonic() - start
    if not args.quiet:
        print(f"\n  Time: {elapsed:.2f}s")

    has_error = any(f.severity == "ERROR" for f in report.findings)
    if args.ignore_return:
        sys.exit(0)
    else:
        sys.exit(1 if has_error else 0)

if __name__ == "__main__":
    main()
