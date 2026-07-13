#!/usr/bin/env python3
"""
audit_trail_completeness_checker.py - Ensure every mutative function has audit trail
=======================================================================================
Standar: SOX/ISA 315 · PCAOB AS 2405
Fitur: Deteksi audit logging, event publishing, hash chain, immutable store
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import json
import logging
import pathlib
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

# ---- Setup logging ----
logger = logging.getLogger("audit_trail")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)

# ---- Ensure root directory is in sys.path ----
_THIS_DIR = pathlib.Path(__file__).resolve().parent
_ROOT_DIR = _THIS_DIR.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

# ---- RCA integration ----
try:
    from checker.core.rca import (
        Category,
        ErrorCode,
        RCAEngine,
        RCAResult,
        RCARule,
        Severity,
        analyze_exception,
        get_engine,
    )
    RCA_AVAIL = True
    logger.info("RCA engine imported successfully")
except ImportError:
    RCA_AVAIL = False
    class RCARule: pass
    class RCAResult: pass
    class Severity: pass
    class Category: pass
    class ErrorCode: pass
    def get_engine(): return None
    def analyze_exception(e, ctx): return None
    logger.warning("RCA engine not available.")

# ---- Custom RCA Rule ----
class AuditTrailRule(RCARule):
    def __init__(self):
        if RCA_AVAIL:
            super().__init__(priority=170, category=Category.SECURITY, name="AuditTrailRule")
        else:
            self.priority = 170
            self.enabled = True
            self.name = "AuditTrailRule"
            self.category = "SECURITY"
            self.version = "1.0"
            self.author = "system"
            self._stats = {}

    def match(self, exc, frames, context) -> bool:
        if not RCA_AVAIL:
            return False
        if "audit" in str(exc).lower() or "audit trail" in str(exc).lower():
            return True
        if context and "func" in context:
            return True
        return False

    def analyze(self, exc, frames, context):
        if not RCA_AVAIL:
            return None
        if context and "func" in context:
            func = context.get("func")
            file = context.get("file", "unknown")
            kind = context.get("kind", "NO_AUDIT")
            sev = Severity.HIGH if kind == "NO_AUDIT" else Severity.MEDIUM
            return RCAResult(
                severity=sev,
                category=Category.SECURITY,
                error_code=ErrorCode.ERP_VALIDATION,
                root_cause=f"{kind}: Function '{func}' missing audit trail",
                evidence=[f"File: {file}", f"Function: {func}", f"Issue: {kind}"],
                impact=["SOX compliance failure – audit trail incomplete."],
                suggested_fix=(
                    "Add audit decorator @audit or call audit logging function. "
                    "For event sourcing, publish domain events using event publisher. "
                    "For persistent operations, update hash chain."
                ),
                raw_error=str(exc),
                confidence=0.85
            )
        return None

# ---- Color ----
COLOR = {
    "RED": "\033[91m", "GREEN": "\033[92m", "YELLOW": "\033[93m",
    "CYAN": "\033[96m", "MAGENTA": "\033[95m", "BOLD": "\033[1m", "RESET": "\033[0m"
}
def c(key: str) -> str: return COLOR.get(key, "")

# ---- AST Cache ----
_AST_CACHE: dict[str, ast.AST | None] = {}
_CACHE_LOCK = threading.Lock()

def get_ast(file_path: pathlib.Path) -> ast.AST | None:
    key = str(file_path.resolve())
    with _CACHE_LOCK:
        if key in _AST_CACHE:
            return _AST_CACHE[key]
    try:
        src = file_path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(file_path))
        with _CACHE_LOCK:
            _AST_CACHE[key] = tree
        return tree
    except Exception:
        with _CACHE_LOCK:
            _AST_CACHE[key] = None
        return None

# ---- Data ----
@dataclass
class AuditIssue:
    file: str
    line: int
    kind: str  # NO_AUDIT, NO_EVENT, NO_HASH
    detail: str
    confidence: float
    rca: dict | None = None

@dataclass
class Report:
    issues: list[AuditIssue]
    total_mutative_funcs: int
    total_files: int
    score: float
    scan_time: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

# ---- Main Checker ----
class AuditTrailCompletenessChecker:
    # Action prefixes (business commands)
    ACTION_PREFIXES = {
        "create", "update", "delete", "post", "publish", "submit",
        "approve", "reject", "close", "cancel", "reverse",
        "issue", "void", "dispose", "transfer", "revalue", "impair",
        "amortize", "depreciate", "allocate", "record", "register",
        "save", "persist", "archive", "restore", "activate", "deactivate"
    }

    # Domain keywords (must be present in function name)
    DOMAIN_KEYWORDS = {
        "journal", "entry", "ledger", "invoice", "payment", "receipt",
        "order", "purchase", "sales", "contract", "agreement",
        "asset", "fixed_asset", "depreciation", "amortization",
        "budget", "forecast", "period", "closing", "opening",
        "reconciliation", "tax", "faktur", "retainer", "goodwill",
        "hedge", "revaluation", "impairment", "disposal",
        "customer", "supplier", "employee", "payroll",
        "inventory", "stock", "movement", "adjustment",
        "project", "approval", "workflow", "saga", "orchestrator",
        "dividend", "equity", "retained", "forex", "exchange",
        "work_order", "intangible", "manufacturing"
    }

    # Audit logging calls
    AUDIT_CALLS = {
        "add_audit", "audit_log", "log_audit", "record_audit", "write_audit",
        "log_event", "_record_audit", "_add_audit", "_audit"
    }

    # Event publisher calls
    EVENT_CALLS = {
        "publish", "dispatch", "emit", "send", "notify",
        "publish_event", "register_event", "_publish_event"
    }

    # Hash chain calls
    HASH_CALLS = {
        "hash_chain", "append_hash", "update_hash", "timestamp", "take_snapshot"
    }

    # Audit decorators
    AUDIT_DECORATORS = {"audit", "audited", "log_audit"}

    # Skip if function name starts with these patterns (helpers)
    SKIP_PATTERNS = {
        "set_", "get_", "add_", "remove_", "clear_", "pop_", "pull_",
        "push_", "append_", "insert_", "delete_", "update_",
        "validate_", "to_", "from_", "clone_", "snapshot_",
        "_event", "_state", "_saga", "_orchestrator", "_factory",
        "register_", "impairment_", "carrying_", "remaining_",
        "total_", "accumulated_", "save_", "record_"
    }

    # Skip exact function names (false positive helpers)
    SKIP_EXACT = {
        "close", "delete", "save", "update", "create", "publish",
        "save_async", "save_sync", "delete_async",
        "impairment_percentage", "save_asset", "save_depreciation_entry",
        "save_depreciation", "record_payment", "record_purchase",
        "submit_for_approval", "allocate_impairment_to_cgus"
    }

    # Skip factory functions: create_*_service, create_*_saga_state, create_*_use_case
    FACTORY_SUFFIXES = {
        "service", "saga_state", "orchestrator", "store", "repository",
        "factory", "provider", "handler", "router", "use_case"
    }

    # Paths to skip entirely
    SKIP_PATHS = {
        "adapters", "infrastructure", "migrations", "docs", "tests",
        "checker", "bootstrap", "iam", "security_hardening",
        "deployment", "scripts", "constitution", "axioms", "kernel",
        "policy_engine", "reports", "analytics", "audit"
    }

    # Only scan domain/application
    RELEVANT_PATHS = {
        "domain/", "application/use_cases/", "application/service_layer/",
        "application/sagas/"
    }

    def __init__(self, root: pathlib.Path, exclude: list[str] = None, max_workers: int = 4):
        self.root = root
        self.exclude = set(exclude or [".venv", "venv", "__pycache__", "tests", "checker", "docs", "migrations"])
        self.max_workers = max_workers
        self._lock = threading.Lock()
        self._issues: list[AuditIssue] = []
        self._total_mutative = 0
        self._files = 0

        if RCA_AVAIL:
            engine = get_engine()
            if engine:
                try:
                    engine.register_rule(AuditTrailRule())
                    logger.info("AuditTrailRule registered with RCA engine.")
                except Exception as e:
                    logger.debug(f"RCA rule registration error: {e}")

    def scan(self, progress_callback: Callable | None = None) -> Report:
        t0 = time.perf_counter()
        files = list(self._walk())
        self._files = len(files)
        total = len(files)
        logger.info(f"Scanning {total} files for audit trail completeness...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {ex.submit(self._analyze_file, f): f for f in files}
            for idx, future in enumerate(concurrent.futures.as_completed(futures)):
                if progress_callback:
                    progress_callback(idx + 1, total)
                try:
                    issues, mut_count = future.result()
                    with self._lock:
                        self._issues.extend(issues)
                        self._total_mutative += mut_count
                except Exception as e:
                    logger.debug(f"Error analyzing file: {e}")

        # RCA
        if RCA_AVAIL and self._issues:
            ctx = {
                "total_mutative": self._total_mutative,
                "issue_count": len(self._issues),
                "sample": [{"file": i.file, "line": i.line, "kind": i.kind} for i in self._issues[:3]]
            }
            try:
                exc = RuntimeError("Audit trail issues detected")
                rca_result = analyze_exception(exc, ctx)
                if rca_result and self._issues:
                    rca_dict = rca_result.to_dict() if hasattr(rca_result, 'to_dict') else {"raw": str(rca_result)}
                    self._issues[0].rca = rca_dict
            except Exception as e:
                logger.debug(f"RCA analysis error: {e}")

        # Score: 2 points per issue, 0.01 per function
        if not self._issues:
            score = 100.0
        else:
            issue_penalty = len(self._issues) * 2
            func_penalty = self._total_mutative * 0.01
            score = max(0, 100 - issue_penalty - func_penalty)
        score = round(score, 2)

        return Report(
            issues=self._issues,
            total_mutative_funcs=self._total_mutative,
            total_files=self._files,
            score=score,
            scan_time=time.perf_counter() - t0
        )

    def _walk(self) -> Iterator[pathlib.Path]:
        for p in self.root.rglob("*.py"):
            if any(part in self.exclude for part in p.parts):
                continue
            if "checker" in str(p):
                continue
            rel = str(p.relative_to(self.root)).replace("\\", "/")
            for relevant in self.RELEVANT_PATHS:
                if relevant in rel:
                    yield p
                    break

    def _is_mutative(self, name: str) -> bool:
        """Return True if this is a business command that needs audit trail."""
        name_lower = name.lower()

        # Skip exact matches
        if name in self.SKIP_EXACT:
            return False

        # Skip factory functions (create_*_service, create_*_use_case, etc.)
        if name_lower.startswith("create_"):
            for suffix in self.FACTORY_SUFFIXES:
                if name_lower.endswith(suffix):
                    return False

        # Skip if starts with helper patterns
        for pattern in self.SKIP_PATTERNS:
            if name_lower.startswith(pattern):
                return False

        # Must have action prefix
        has_action = any(name_lower.startswith(prefix) for prefix in self.ACTION_PREFIXES)
        if not has_action:
            return False

        # Must have domain keyword
        has_domain = any(k in name_lower for k in self.DOMAIN_KEYWORDS)
        if not has_domain:
            return False

        return True

    def _analyze_file(self, py_file: pathlib.Path) -> tuple[list[AuditIssue], int]:
        tree = get_ast(py_file)
        if tree is None:
            return [], 0
        issues = []
        mut_count = 0
        rel = str(py_file.relative_to(self.root))

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                if not self._is_mutative(name):
                    continue
                mut_count += 1

                has_audit_decorator = False
                has_audit_call = False
                has_event_call = False
                has_hash_call = False

                # Check decorators
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Name):
                        if dec.id in self.AUDIT_DECORATORS:
                            has_audit_decorator = True
                    elif isinstance(dec, ast.Attribute):
                        if dec.attr in self.AUDIT_DECORATORS:
                            has_audit_decorator = True

                # Check body for audit/event calls
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        func_name = None
                        if isinstance(child.func, ast.Name):
                            func_name = child.func.id
                        elif isinstance(child.func, ast.Attribute):
                            func_name = child.func.attr
                        if func_name:
                            if func_name in self.AUDIT_CALLS:
                                has_audit_call = True
                            if func_name in self.EVENT_CALLS:
                                has_event_call = True
                            if func_name in self.HASH_CALLS:
                                has_hash_call = True

                if not has_audit_decorator and not has_audit_call and not has_event_call:
                    rca_ctx = {"func": name, "file": rel, "kind": "NO_AUDIT"}
                    rca = None
                    if RCA_AVAIL:
                        try:
                            r = analyze_exception(RuntimeError("Missing audit"), rca_ctx)
                            rca = r.to_dict() if r else None
                        except:
                            pass
                    issues.append(AuditIssue(
                        file=rel,
                        line=node.lineno,
                        kind="NO_AUDIT",
                        detail=f"Business command '{name}' lacks audit logging or event publishing",
                        confidence=0.85,
                        rca=rca
                    ))

        return issues, mut_count

# ---- Reporters ----
def print_report(r: Report, verbose: bool = False):
    print(f"\n{c('CYAN')}{'='*70}{c('RESET')}")
    print(f"{c('BOLD')}AUDIT TRAIL COMPLETENESS CHECKER REPORT{c('RESET')}")
    print(f"{'='*70}")
    print(f"  Timestamp       : {r.timestamp}")
    print(f"  Files           : {r.total_files}")
    print(f"  Business cmds   : {r.total_mutative_funcs}")
    print(f"  Issues          : {len(r.issues)}")
    print(f"  RCA Engine      : {'✅ Active' if RCA_AVAIL else '⚠️ Not available'}")
    print(f"  Score           : {c('GREEN') if r.score >= 90 else c('YELLOW') if r.score >= 70 else c('RED')}{r.score}/100{c('RESET')}")
    print(f"  Scan time       : {r.scan_time:.2f}s")

    if r.issues:
        print(f"\n{c('RED')}Issues:{c('RESET')}")
        for issue in r.issues[:20]:
            color = c("RED") if issue.kind == "NO_AUDIT" else c("YELLOW")
            print(f"  {color}[{issue.kind}]{c('RESET')} {issue.file}:{issue.line}  (conf:{issue.confidence:.2f})")
            print(f"      {issue.detail}")
            if verbose and issue.rca:
                if isinstance(issue.rca, dict):
                    rc = issue.rca.get('root_cause', '')
                    if rc:
                        print(f"      RCA: {rc[:150]}")
                    fix = issue.rca.get('suggested_fix', '')
                    if fix:
                        print(f"      Saran: {fix[:150]}")
        if len(r.issues) > 20:
            print(f"  ... and {len(r.issues)-20} more issues.")
    else:
        print(f"\n  {c('GREEN')}✅ All business commands have audit trail.{c('RESET')}")

def save_json(r: Report, path: pathlib.Path):
    data = {
        "timestamp": r.timestamp,
        "score": r.score,
        "total_mutative_funcs": r.total_mutative_funcs,
        "total_files": r.total_files,
        "scan_time": r.scan_time,
        "issues": [
            {"file": i.file, "line": i.line, "kind": i.kind, "detail": i.detail, "confidence": i.confidence}
            for i in r.issues
        ]
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  JSON saved to {path}")

def save_html(r: Report, path: pathlib.Path):
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Audit Trail Completeness Report</title>
<style>
body{{font-family:sans-serif;padding:2rem;background:#f8fafc}}
.issue{{margin:0.5rem 0;padding:0.5rem;border-left:4px solid #dc2626;background:#fef2f2;border-radius:4px}}
.score{{font-size:2rem;font-weight:bold}}
</style>
</head><body>
<h1>📋 Audit Trail Completeness Report</h1>
<p>Score: <span class="score" style="color:{'#16a34a' if r.score>=90 else '#ca8a04' if r.score>=70 else '#dc2626'}">{r.score}/100</span></p>
<p>Files: {r.total_files} | Business commands: {r.total_mutative_funcs}</p>
<h2>Issues ({len(r.issues)})</h2>
"""
    for i in r.issues[:50]:
        html += f"""
<div class="issue">
    <strong>[{i.kind}]</strong> {i.file}:{i.line} (conf:{i.confidence:.2f})
    <br><small>{i.detail}</small>
</div>
"""
    if len(r.issues) > 50:
        html += f"<p>... and {len(r.issues)-50} more issues.</p>"
    html += "</body></html>"
    with open(path, "w") as f:
        f.write(html)
    print(f"  HTML saved to {path}")

# ---- Main ----
def main():
    parser = argparse.ArgumentParser(description="Audit Trail Completeness Checker")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    parser.add_argument("--json", metavar="FILE", help="Save JSON report")
    parser.add_argument("--html", metavar="FILE", help="Save HTML report")
    parser.add_argument("--exclude", default=".venv,venv,__pycache__,tests,checker,docs,deployment,migrations",
                        help="Comma-separated dirs to exclude")
    parser.add_argument("--max-workers", type=int, default=4, help="Number of parallel workers")
    parser.add_argument("--root", "-r", default=None, help="Root directory to scan (default: parent of script)")
    args = parser.parse_args()

    if args.root:
        root = pathlib.Path(args.root).resolve()
    else:
        root = _ROOT_DIR

    checker = AuditTrailCompletenessChecker(root, args.exclude.split(","), args.max_workers)

    def progress(current, total):
        if not sys.stdout.isatty():
            return
        pct = current / total * 100
        bar = "█" * int(pct / 2) + "░" * (50 - int(pct / 2))
        print(f"\r  [{bar}] {current}/{total} ({pct:.1f}%)", end="", flush=True)
        if current >= total:
            print()

    report = checker.scan(progress_callback=progress)
    print_report(report, args.verbose)
    if args.json:
        save_json(report, pathlib.Path(args.json))
    if args.html:
        save_html(report, pathlib.Path(args.html))

if __name__ == "__main__":
    main()
