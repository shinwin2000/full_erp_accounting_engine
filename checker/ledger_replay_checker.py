#!/usr/bin/env python3
"""
ledger_replay_checker.py - Verify ledger can be reconstructed from event stream
===================================================================================
Standar: Big 4 Audit · ISO/IEC 25010 · Event Sourcing Compliance
Fitur: Deteksi event store, replay/reconstruct method, event versioning, snapshot
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
logger = logging.getLogger("ledger_replay")
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

# ---- RCA rule ----
class LedgerReplayRule(RCARule):
    def __init__(self):
        if RCA_AVAIL:
            super().__init__(priority=160, category=Category.DDD, name="LedgerReplayRule")
        else:
            self.priority = 160
            self.enabled = True
            self.name = "LedgerReplayRule"
            self.category = "DDD"
            self.version = "1.0"
            self.author = "system"
            self._stats = {}

    def match(self, exc, frames, context) -> bool:
        if not RCA_AVAIL:
            return False
        if "replay" in str(exc).lower() or "event sourcing" in str(exc).lower():
            return True
        if context and "class" in context:
            return True
        return False

    def analyze(self, exc, frames, context):
        if not RCA_AVAIL:
            return None
        if context and "class" in context:
            cls_name = context.get("class")
            file = context.get("file", "unknown")
            kind = context.get("kind", "NO_REPLAY")
            sev = Severity.HIGH if kind == "NO_REPLAY" else Severity.MEDIUM
            return RCAResult(
                severity=sev,
                category=Category.DDD,
                error_code=ErrorCode.ERP_VALIDATION,
                root_cause=f"{kind}: Class '{cls_name}' missing event sourcing support",
                evidence=[f"File: {file}", f"Class: {cls_name}", f"Issue: {kind}"],
                impact=["Event sourcing reconstruction may fail."],
                suggested_fix=(
                    "Add replay/reconstruct method: def replay(self, events): ... "
                    "Add version attribute: version: int = 0 "
                    "Add snapshot support: def take_snapshot(self): ..."
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
class ReplayIssue:
    file: str
    line: int
    kind: str  # NO_REPLAY, NO_VERSION, NO_SNAPSHOT
    detail: str
    confidence: float
    rca: dict | None = None

@dataclass
class Report:
    issues: list[ReplayIssue]
    total_classes: int
    total_files: int
    score: float
    scan_time: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

# ---- Scanner ----
class LedgerReplayChecker:
    REPLAY_METHODS = {"replay", "reconstruct", "rebuild", "restore", "rehydrate"}
    SNAPSHOT_METHODS = {"snapshot", "save_snapshot", "take_snapshot", "restore_snapshot"}
    VERSION_ATTRS = {"version", "event_version", "aggregate_version"}

    # Kata-kata yang menandakan kelas bukan aggregate (DTO, Value Object, dll.)
    SKIP_CLASS_TERMS = {
        "DTO", "Request", "Response", "Status", "Type", "Method",
        "Balance", "Enum", "Config", "Settings", "Error", "Exception",
        "Port", "Adapter", "Service", "Validator", "Rule", "Axiom",
        "Invariant", "Checker", "Processor", "Handler", "Manager",
        "Factory", "Repository", "Gateway", "Controller", "Router",
        "Middleware", "Decorator", "Mixin", "Base", "Abstract",
        "Record", "Report", "Attempt", "Snapshot", "Event", "Command",
        "Query", "Criteria", "Filter", "Context", "State", "Instruction",
        "Options", "Params", "Result", "Summary", "Detail", "History",
        "Trail", "Log", "Metric", "Dashboard", "View", "Template",
        "Schema", "Serializer", "Deserializer", "Mapper", "Converter",
        "Transformer", "Builder", "Creator", "Updater", "Deleter",
        "VO", "Value", "Object", "Projection", "Table", "Entity",
        "Entry", "Group", "Orchestrator", "Saga",
    }

    # Folder yang berisi domain aggregate (hanya scan ini)
    DOMAIN_FOLDERS = {"domain"}

    def __init__(self, root: pathlib.Path, exclude: list[str] = None, max_workers: int = 4):
        self.root = root
        self.exclude = set(exclude or [".venv", "venv", "__pycache__", "tests", "checker", "docs", "migrations"])
        self.max_workers = max_workers
        self._lock = threading.Lock()
        self._issues: list[ReplayIssue] = []
        self._total_classes = 0
        self._files = 0

        if RCA_AVAIL:
            engine = get_engine()
            if engine:
                try:
                    engine.register_rule(LedgerReplayRule())
                    logger.info("LedgerReplayRule registered with RCA engine.")
                except Exception as e:
                    logger.debug(f"RCA rule registration error: {e}")

    def scan(self, progress_callback: Callable | None = None) -> Report:
        t0 = time.perf_counter()
        files = list(self._walk())
        self._files = len(files)
        total = len(files)
        logger.info(f"Scanning {total} domain files for ledger replay support...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self._analyze_file, f): f for f in files}
            for idx, future in enumerate(concurrent.futures.as_completed(futures)):
                if progress_callback:
                    progress_callback(idx + 1, total)
                try:
                    issues, class_count = future.result()
                    with self._lock:
                        self._issues.extend(issues)
                        self._total_classes += class_count
                except Exception as e:
                    logger.warning(f"Error analyzing file: {e}")

        # RCA untuk issue pertama
        if RCA_AVAIL and self._issues:
            ctx = {
                "total_classes": self._total_classes,
                "issue_count": len(self._issues),
                "sample": [{"file": i.file, "line": i.line, "kind": i.kind, "class": i.detail.split("'")[1] if "'" in i.detail else "unknown"} for i in self._issues[:3]]
            }
            try:
                r = analyze_exception(RuntimeError("Ledger replay issues detected"), ctx)
                if r and self._issues:
                    self._issues[0].rca = r.to_dict() if hasattr(r, 'to_dict') else {"raw": str(r)}
            except Exception:
                pass

        # Score: penalty 5 for NO_REPLAY, 2 for NO_VERSION, 1 for NO_SNAPSHOT
        if not self._issues:
            score = 100.0
        else:
            penalty = sum(5 if i.kind == "NO_REPLAY" else 2 if i.kind == "NO_VERSION" else 1 for i in self._issues)
            score = max(0, 100 - penalty)
        score = round(score, 2)

        return Report(
            issues=self._issues,
            total_classes=self._total_classes,
            total_files=self._files,
            score=score,
            scan_time=time.perf_counter() - t0
        )

    def _walk(self) -> Iterator[pathlib.Path]:
        for p in self.root.rglob("*.py"):
            if any(part in self.exclude for part in p.parts):
                continue
            if p.name.startswith("__"):
                continue
            if "checker" in str(p):
                continue
            rel = str(p.relative_to(self.root)).replace("\\", "/")
            # Hanya file di domain folder
            if any(rel.startswith(f"{folder}/") for folder in self.DOMAIN_FOLDERS):
                yield p

    def _is_class_skipped(self, node: ast.ClassDef) -> bool:
        name = node.name
        # Skip berdasarkan nama
        for term in self.SKIP_CLASS_TERMS:
            if term in name:
                return True
        # Skip jika inherit dari Enum / BaseModel / dataclass
        for base in node.bases:
            if isinstance(base, ast.Name):
                if base.id in {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"}:
                    return True
                if base.id in {"BaseModel", "RootModel", "TypeAdapter"}:
                    return True
            if isinstance(base, ast.Attribute):
                if base.attr in {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"}:
                    return True
                if base.attr in {"BaseModel", "RootModel", "TypeAdapter"}:
                    return True
        # Skip jika di-dekorasi @dataclass
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name) and dec.id == "dataclass":
                return True
            if isinstance(dec, ast.Attribute) and dec.attr == "dataclass":
                return True
        return False

    def _is_aggregate_class(self, node: ast.ClassDef) -> bool:
        """
        Deteksi aggregate dengan kriteria:
        1. Nama mengandung "Aggregate" atau "Root"
        2. Mewarisi kelas bernama Aggregate / Root
        3. Memiliki metode apply/when/replay/reconstruct
        """
        name = node.name
        # Criterion 1: Nama mengandung Aggregate / Root
        if "Aggregate" in name or "Root" in name:
            return True

        # Criterion 2: Mewarisi Aggregate / Root
        for base in node.bases:
            if isinstance(base, ast.Name):
                if "Aggregate" in base.id or "Root" in base.id:
                    return True
            if isinstance(base, ast.Attribute):
                if "Aggregate" in base.attr or "Root" in base.attr:
                    return True

        # Criterion 3: Memiliki metode apply/when/replay
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name in {"apply", "when", "handle_event", "replay", "reconstruct"}:
                    return True

        return False

    def _analyze_file(self, py_file: pathlib.Path) -> tuple[list[ReplayIssue], int]:
        tree = get_ast(py_file)
        if tree is None:
            return [], 0

        rel = str(py_file.relative_to(self.root))
        issues = []
        class_count = 0

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Skip class yang tidak memenuhi syarat
                if self._is_class_skipped(node):
                    continue
                # Hanya aggregate yang valid
                if not self._is_aggregate_class(node):
                    continue
                class_count += 1
                issues.extend(self._analyze_class(node, rel))

        return issues, class_count

    def _analyze_class(self, node: ast.ClassDef, rel: str) -> list[ReplayIssue]:
        issues = []
        name = node.name
        has_replay = False
        has_snapshot = False
        has_version = False

        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name in self.REPLAY_METHODS:
                    has_replay = True
                if item.name in self.SNAPSHOT_METHODS:
                    has_snapshot = True
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id in self.VERSION_ATTRS:
                        has_version = True
            if isinstance(item, ast.AnnAssign):
                if isinstance(item.target, ast.Name) and item.target.id in self.VERSION_ATTRS:
                    has_version = True

        # Rule 1: Must have replay/reconstruct
        if not has_replay:
            rca_ctx = {"class": name, "file": rel, "kind": "NO_REPLAY"}
            rca = None
            if RCA_AVAIL:
                try:
                    r = analyze_exception(RuntimeError("Missing replay"), rca_ctx)
                    rca = r.to_dict() if r else None
                except:
                    pass
            issues.append(ReplayIssue(
                file=rel,
                line=node.lineno,
                kind="NO_REPLAY",
                detail=f"Aggregate class '{name}' missing replay/reconstruct method",
                confidence=0.9,
                rca=rca
            ))

        # Rule 2: Should have version
        if not has_version:
            rca_ctx = {"class": name, "file": rel, "kind": "NO_VERSION"}
            rca = None
            if RCA_AVAIL:
                try:
                    r = analyze_exception(RuntimeError("Missing version"), rca_ctx)
                    rca = r.to_dict() if r else None
                except:
                    pass
            issues.append(ReplayIssue(
                file=rel,
                line=node.lineno,
                kind="NO_VERSION",
                detail=f"Aggregate class '{name}' missing version attribute",
                confidence=0.7,
                rca=rca
            ))

        # Rule 3: Snapshot is nice-to-have
        if not has_snapshot:
            issues.append(ReplayIssue(
                file=rel,
                line=node.lineno,
                kind="NO_SNAPSHOT",
                detail=f"Aggregate class '{name}' missing snapshot method",
                confidence=0.5,
                rca=None
            ))

        return issues

# ---- Reporters ----
def print_report(report: Report, verbose: bool = False):
    print(f"\n{c('CYAN')}{'='*70}{c('RESET')}")
    print(f"{c('BOLD')}LEDGER REPLAY CHECKER REPORT{c('RESET')}")
    print(f"{'='*70}")
    print(f"  Timestamp       : {report.timestamp}")
    print(f"  Files scanned   : {report.total_files}")
    print(f"  Classes scanned : {report.total_classes}")
    print(f"  Issues detected : {len(report.issues)}")
    print(f"  RCA Engine      : {'✅ Active' if RCA_AVAIL else '⚠️ Not available'}")
    print(f"  Score           : {c('GREEN') if report.score >= 90 else c('YELLOW') if report.score >= 70 else c('RED')}{report.score}/100{c('RESET')}")
    print(f"  Scan time       : {report.scan_time:.2f}s")

    if report.issues:
        print(f"\n{c('RED')}Issues:{c('RESET')}")
        for issue in report.issues[:20]:
            color = c("RED") if issue.kind == "NO_REPLAY" else c("YELLOW")
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
        if len(report.issues) > 20:
            print(f"  ... and {len(report.issues)-20} more issues.")
    else:
        print(f"\n  {c('GREEN')}✅ All aggregate classes have replay support.{c('RESET')}")

def save_json(report: Report, path: pathlib.Path):
    data = {
        "timestamp": report.timestamp,
        "score": report.score,
        "total_classes": report.total_classes,
        "total_files": report.total_files,
        "scan_time": report.scan_time,
        "issues": [
            {"file": i.file, "line": i.line, "kind": i.kind, "detail": i.detail, "confidence": i.confidence}
            for i in report.issues
        ]
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  JSON saved to {path}")

def save_html(report: Report, path: pathlib.Path):
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Ledger Replay Report</title>
<style>
body{{font-family:sans-serif;padding:2rem;background:#f8fafc}}
.issue{{margin:0.5rem 0;padding:0.5rem;border-left:4px solid #dc3545;background:#fef2f2;border-radius:4px}}
.score{{font-size:2rem;font-weight:bold}}
</style>
</head><body>
<h1>📊 Ledger Replay Checker Report</h1>
<p>Score: <span class="score" style="color:{'#16a34a' if report.score>=90 else '#ca8a04' if report.score>=70 else '#dc2626'}">{report.score}/100</span></p>
<p>Files: {report.total_files} | Classes: {report.total_classes}</p>
<h2>Issues ({len(report.issues)})</h2>
"""
    for i in report.issues[:50]:
        html += f"""
<div class="issue">
    <strong>[{i.kind}]</strong> {i.file}:{i.line} (conf:{i.confidence:.2f})
    <br><small>{i.detail}</small>
</div>
"""
    if len(report.issues) > 50:
        html += f"<p>... and {len(report.issues)-50} more issues.</p>"
    html += "</body></html>"
    with open(path, "w") as f:
        f.write(html)
    print(f"  HTML saved to {path}")

def save_sarif(report: Report, path: pathlib.Path):
    sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "LedgerReplayChecker", "version": "2.0"}},
            "results": [
                {"ruleId": "RPLAY-001", "level": "error" if i.kind == "NO_REPLAY" else "warning",
                 "message": {"text": i.detail},
                 "locations": [{"physicalLocation": {"artifactLocation": {"uri": i.file}, "region": {"startLine": i.line}}}]}
                for i in report.issues
            ]
        }]
    }
    with open(path, "w") as f:
        json.dump(sarif, f, indent=2)
    print(f"  SARIF saved to {path}")

# ---- Main ----
def main():
    parser = argparse.ArgumentParser(description="Ledger Replay Checker")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    parser.add_argument("--json", metavar="FILE", help="Save JSON report")
    parser.add_argument("--html", metavar="FILE", help="Save HTML report")
    parser.add_argument("--sarif", metavar="FILE", help="Save SARIF report")
    parser.add_argument("--exclude", default=".venv,venv,__pycache__,tests,checker,docs,migrations",
                        help="Comma-separated dirs to exclude")
    parser.add_argument("--max-workers", type=int, default=4, help="Number of parallel workers")
    parser.add_argument("--root", "-r", default=None, help="Root directory to scan (default: parent of script)")
    args = parser.parse_args()

    if args.root:
        root = pathlib.Path(args.root).resolve()
    else:
        root = _ROOT_DIR

    checker = LedgerReplayChecker(root, args.exclude.split(","), args.max_workers)

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
    if args.sarif:
        save_sarif(report, pathlib.Path(args.sarif))

if __name__ == "__main__":
    main()
