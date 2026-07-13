#!/usr/bin/env python3
"""
business_rule_conflict_checker.py - Detect conflicting business rules (same name, contradictory constraints)
================================================================================================================
Standar: SOX/ISA 315 · Policy Engine
Fitur: Deteksi rule name conflicts, contradictory conditions (positive/negative, allow/deny, active/inactive)
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
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

# ---- Setup logging ----
logger = logging.getLogger("rule_conflict")
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

# ---- Import RCA components ----
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
except ImportError:
    RCA_AVAIL = False
    # Fallback dummy
    class RCARule: pass
    class RCAResult: pass
    class Severity: pass
    class Category: pass
    class ErrorCode: pass
    def get_engine(): return None
    def analyze_exception(e, ctx): return None

# ---- Color ----
COLOR = {
    "RED": "\033[91m", "GREEN": "\033[92m", "YELLOW": "\033[93m",
    "CYAN": "\033[96m", "MAGENTA": "\033[95m", "BOLD": "\033[1m", "RESET": "\033[0m"
}
def c(k): return COLOR.get(k, "")

# ---- AST Cache ----
_AST_CACHE = {}
_CACHE_LOCK = threading.Lock()

def get_ast(p: pathlib.Path):
    key = str(p.resolve())
    with _CACHE_LOCK:
        if key in _AST_CACHE:
            return _AST_CACHE[key]
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        with _CACHE_LOCK:
            _AST_CACHE[key] = tree
        return tree
    except Exception:
        with _CACHE_LOCK:
            _AST_CACHE[key] = None
        return None

# ---- Data classes ----
@dataclass
class RuleConflict:
    file1: str
    line1: int
    file2: str
    line2: int
    rule1: str
    rule2: str
    description: str
    confidence: float
    rca: dict | None = None

@dataclass
class Report:
    conflicts: list[RuleConflict]
    total_rules: int
    total_files: int
    score: float
    scan_time: float
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

# ---- Custom RCA Rule for Business Rule Conflicts ----
class BusinessRuleConflictRule(RCARule):
    """RCA rule khusus untuk mendeteksi dan menganalisis konflik aturan bisnis."""

    def __init__(self):
        super().__init__(
            priority=200,
            category=Category.DDD,
            name="BusinessRuleConflictRule",
            version="1.0",
            author="BusinessRuleConflictChecker"
        )

    def match(self, exc, frames, context) -> bool:
        if isinstance(exc, BusinessRuleConflictError):
            return True
        msg = str(exc)
        return "business rule conflict" in msg.lower() or "rule conflict" in msg.lower()

    def analyze(self, exc, frames, context) -> RCAResult | None:
        if not isinstance(exc, BusinessRuleConflictError):
            return None

        conflicts = context.get("conflicts", [])
        total_rules = context.get("total_rules", 0)
        name_conflicts = context.get("name_conflicts", 0)
        contradictory = context.get("contradictory", 0)

        evidence = [
            f"Jumlah konflik ditemukan: {len(conflicts)}",
            f"Total aturan: {total_rules}",
            f"Konflik nama: {name_conflicts}, Kontradiksi: {contradictory}",
        ]
        for i, c in enumerate(conflicts[:3]):
            evidence.append(f"Contoh {i+1}: {c.rule1} vs {c.rule2} (file: {c.file1}:{c.line1} & {c.file2}:{c.line2})")

        impact = [
            "Konflik aturan menyebabkan ketidakpastian dalam evaluasi kebijakan.",
            "Risiko keputusan bisnis yang salah karena aturan bertentangan.",
            "Dapat mengakibatkan pelanggaran regulasi atau kepatuhan jika tidak diresolusi.",
        ]

        if len(conflicts) > 10:
            severity = Severity.FATAL
        elif len(conflicts) > 5:
            severity = Severity.CRITICAL
        else:
            severity = Severity.HIGH

        suggested_fix = (
            "1. Review semua aturan dengan nama yang sama — pastikan hanya satu definisi yang aktif. "
            "2. Untuk aturan yang kontradiktif (allow vs deny), tentukan prioritas atau ubah kondisi. "
            "3. Gunakan policy_engine/conflict_resolver.py untuk menangani konflik secara otomatis. "
            "4. Jika konflik tidak dapat dihindari, gunakan override_authorizer.py untuk approval manual."
        )

        return RCAResult(
            severity=severity,
            category=Category.DDD,
            error_code=ErrorCode.ERP_VALIDATION,
            root_cause=f"Terdeteksi {len(conflicts)} konflik aturan bisnis dalam sistem.",
            evidence=evidence,
            impact=impact,
            suggested_fix=suggested_fix,
            raw_error=str(exc),
            confidence=0.9,
            metadata={
                "conflict_count": len(conflicts),
                "name_conflicts": name_conflicts,
                "contradictory": contradictory,
                "total_rules": total_rules,
            }
        )


class BusinessRuleConflictError(Exception):
    """Exception khusus untuk konflik aturan bisnis."""
    pass


# ---- Main Checker ----
class BusinessRuleConflictChecker:
    CONTRADICTORY_PAIRS = [
        ({"positive", "allow", "enable", "active", "true"}, {"negative", "deny", "disable", "inactive", "false"}),
        ({"min", "minimum", "lower", "at_least"}, {"max", "maximum", "upper", "at_most"}),
        ({"before", "prior", "earlier"}, {"after", "later", "subsequent"}),
        ({"include", "contains", "allow"}, {"exclude", "deny", "block", "forbid"}),
        ({"valid", "approved", "accepted"}, {"invalid", "rejected", "denied"}),
    ]

    def __init__(self, root: pathlib.Path, exclude: list[str] = None, max_workers: int = 4,
                 ignore_same_file: bool = True):
        self.root = root
        self.exclude = set(exclude or [])
        self.max_workers = max_workers
        self.ignore_same_file = ignore_same_file
        self._lock = threading.Lock()
        self._conflicts: list[RuleConflict] = []
        self._total_rules = 0
        self._files = 0

        if RCA_AVAIL:
            engine = get_engine()
            if engine:
                engine.register_rule(BusinessRuleConflictRule())
                logger.info("BusinessRuleConflictRule registered with RCA engine.")

    def scan(self, progress_callback: Callable | None = None) -> Report:
        t0 = time.perf_counter()
        files = list(self._walk())
        self._files = len(files)
        total = len(files)
        logger.info(f"Scanning {total} files for business rules...")

        rule_defs = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = {ex.submit(self._parse_file, f): f for f in files}
            for idx, future in enumerate(concurrent.futures.as_completed(futures)):
                if progress_callback:
                    progress_callback(idx + 1, total)
                try:
                    rules = future.result()
                    with self._lock:
                        self._total_rules += len(rules)
                        rule_defs.extend(rules)
                except Exception as e:
                    logger.debug(f"Error parsing file: {e}")

        # Find conflicts with filtering
        name_conflicts = self._find_name_conflicts(rule_defs)
        contradictory = self._find_contradictory_rules(rule_defs)

        # Combine
        all_conflicts = name_conflicts + contradictory
        self._conflicts = all_conflicts

        # RCA analysis jika ada konflik
        if RCA_AVAIL and all_conflicts:
            ctx = {
                "conflicts": all_conflicts,
                "total_rules": self._total_rules,
                "name_conflicts": len(name_conflicts),
                "contradictory": len(contradictory),
            }
            try:
                exc = BusinessRuleConflictError(
                    f"Business rule conflicts detected: {len(all_conflicts)} conflicts found"
                )
                rca_result = analyze_exception(exc, ctx)
                if rca_result and all_conflicts:
                    rca_dict = rca_result.to_dict() if hasattr(rca_result, 'to_dict') else {"raw": str(rca_result)}
                    all_conflicts[0].rca = rca_dict
            except Exception as e:
                logger.debug(f"RCA analysis error: {e}")

        # ---- SCORE CALCULATION ----
        if not all_conflicts:
            # Tidak ada konflik sama sekali -> skor 100
            score = 100.0
        else:
            # Hitung konflik lintas file (hanya yang dianggap serius)
            cross_file_name_conflicts = [c for c in name_conflicts if c.file1 != c.file2]
            cross_file_contradictory = [c for c in contradictory if c.file1 != c.file2]

            name_penalty = len(cross_file_name_conflicts) * 8
            contradict_penalty = len(cross_file_contradictory) * 3

            # Penalti jumlah aturan hanya jika ada konflik lintas file
            if cross_file_name_conflicts or cross_file_contradictory:
                rule_penalty = self._total_rules * 0.2
            else:
                rule_penalty = 0  # jika hanya konflik dalam file yang sama (ignore_same_file=False)

            total_penalty = name_penalty + contradict_penalty + rule_penalty
            score = max(0, min(100, 100 - total_penalty))

        score = round(score, 2)

        return Report(
            conflicts=self._conflicts,
            total_rules=self._total_rules,
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
            if "rule" in str(p).lower() or "policy" in str(p).lower():
                yield p

    def _parse_file(self, py: pathlib.Path) -> list[tuple[str, int, str, str]]:
        tree = get_ast(py)
        if tree is None:
            return []
        rel = str(py.relative_to(self.root))
        rules = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith('_'):
                    continue
                if "rule" in node.name.lower() or "policy" in node.name.lower():
                    doc = ast.get_docstring(node) or ""
                    is_overload = False
                    for dec in node.decorator_list:
                        if (isinstance(dec, ast.Name) and dec.id == "overload") or (isinstance(dec, ast.Attribute) and dec.attr == "overload"):
                            is_overload = True
                            break
                    if not is_overload:
                        rules.append((rel, node.lineno, node.name, doc))
            elif isinstance(node, ast.ClassDef):
                if node.name.startswith('_'):
                    continue
                if "rule" in node.name.lower() or "policy" in node.name.lower():
                    doc = ast.get_docstring(node) or ""
                    rules.append((rel, node.lineno, node.name, doc))
        return rules

    def _find_name_conflicts(self, rules: list[tuple[str, int, str, str]]) -> list[RuleConflict]:
        conflicts = []
        name_map = defaultdict(list)
        for file, line, name, doc in rules:
            name_map[name].append((file, line, doc))

        for name, locations in name_map.items():
            if len(locations) > 1:
                # Jika semua lokasi di file yang sama dan ignore_same_file=True, abaikan
                files = {loc[0] for loc in locations}
                if self.ignore_same_file and len(files) == 1:
                    continue  # abaikan, kemungkinan overload/override

                for i in range(len(locations)):
                    for j in range(i + 1, len(locations)):
                        # Jika di file yang sama, confidence rendah
                        if locations[i][0] == locations[j][0]:
                            confidence = 0.3
                        else:
                            confidence = 0.9
                        conflicts.append(RuleConflict(
                            file1=locations[i][0],
                            line1=locations[i][1],
                            file2=locations[j][0],
                            line2=locations[j][1],
                            rule1=name,
                            rule2=name,
                            description=f"Rule '{name}' defined in multiple places",
                            confidence=confidence,
                            rca=None
                        ))
        return conflicts

    def _find_contradictory_rules(self, rules: list[tuple[str, int, str, str]]) -> list[RuleConflict]:
        conflicts = []
        for i in range(len(rules)):
            for j in range(i + 1, len(rules)):
                f1, l1, n1, d1 = rules[i]
                f2, l2, n2, d2 = rules[j]
                if n1 == n2:
                    continue
                if self._are_contradictory(n1, n2):
                    conflicts.append(RuleConflict(
                        file1=f1,
                        line1=l1,
                        file2=f2,
                        line2=l2,
                        rule1=n1,
                        rule2=n2,
                        description=f"Potential contradictory rules: '{n1}' vs '{n2}'",
                        confidence=0.6,
                        rca=None
                    ))
        return conflicts

    def _are_contradictory(self, name1: str, name2: str) -> bool:
        n1 = name1.lower()
        n2 = name2.lower()
        for pair in self.CONTRADICTORY_PAIRS:
            set1, set2 = pair
            if any(k in n1 for k in set1) and any(k in n2 for k in set2):
                return True
            if any(k in n2 for k in set1) and any(k in n1 for k in set2):
                return True
        return False

# ---- Reporters ----
def print_report(r: Report, verbose: bool = False):
    print(f"\n{c('CYAN')}{'='*70}{c('RESET')}")
    print(f"{c('BOLD')}BUSINESS RULE CONFLICT CHECKER REPORT{c('RESET')}")
    print(f"{'='*70}")
    print(f"  Timestamp   : {r.timestamp}")
    print(f"  Files       : {r.total_files}")
    print(f"  Rules found : {r.total_rules}")
    print(f"  Conflicts   : {len(r.conflicts)}")
    print(f"  Score       : {c('GREEN') if r.score >= 90 else c('YELLOW') if r.score >= 70 else c('RED')}{r.score}/100{c('RESET')}")
    print(f"  Scan time   : {r.scan_time:.2f}s")
    print(f"  RCA Engine  : {'✅ Active' if RCA_AVAIL else '⚠️ Not available'}")

    if r.conflicts:
        print(f"\n{c('RED')}Conflicts:{c('RESET')}")
        for conflict in r.conflicts[:20]:
            print(f"  {c('YELLOW')}[{conflict.description}]{c('RESET')} (conf: {conflict.confidence:.2f})")
            print(f"    {conflict.rule1} at {conflict.file1}:{conflict.line1}")
            print(f"    vs {conflict.rule2} at {conflict.file2}:{conflict.line2}")
            if verbose and conflict.rca:
                if isinstance(conflict.rca, dict):
                    rc = conflict.rca.get('root_cause', '')
                    if rc:
                        print(f"    RCA: {rc}")
                    fix = conflict.rca.get('suggested_fix', '')
                    if fix:
                        print(f"    Saran: {fix}")
                else:
                    print(f"    RCA: {conflict.rca!s}")
        if len(r.conflicts) > 20:
            print(f"  ... and {len(r.conflicts)-20} more conflicts.")
    else:
        print(f"\n  {c('GREEN')}✅ No rule conflicts detected.{c('RESET')}")

def save_json(r: Report, path: pathlib.Path):
    data = {
        "timestamp": r.timestamp,
        "score": r.score,
        "total_rules": r.total_rules,
        "total_files": r.total_files,
        "conflicts": [
            {
                "file1": c.file1, "line1": c.line1,
                "file2": c.file2, "line2": c.line2,
                "rule1": c.rule1, "rule2": c.rule2,
                "description": c.description,
                "confidence": c.confidence
            }
            for c in r.conflicts
        ]
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  JSON saved to {path}")

def save_html(r: Report, path: pathlib.Path):
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Business Rule Conflict Report</title>
<style>
body{{font-family:sans-serif;padding:2rem;background:#f8fafc}}
.conflict{{background:#fef2f2;padding:1rem;margin:0.5rem 0;border-left:4px solid #dc2626;border-radius:4px}}
.score{{font-size:2rem;font-weight:bold}}
.confidence{{color:#6b7280;font-size:0.9rem}}
</style>
</head><body>
<h1>📋 Business Rule Conflict Report</h1>
<p>Score: <span class="score" style="color:{'#16a34a' if r.score>=90 else '#ca8a04' if r.score>=70 else '#dc2626'}">{r.score}/100</span></p>
<p>Files: {r.total_files} | Rules: {r.total_rules}</p>
<h2>Conflicts ({len(r.conflicts)})</h2>
"""
    for c in r.conflicts[:50]:
        html += f"""
<div class="conflict">
    <p><strong>{c.description}</strong> <span class="confidence">(confidence: {c.confidence:.2f})</span></p>
    <p>{c.rule1} at {c.file1}:{c.line1}</p>
    <p>vs {c.rule2} at {c.file2}:{c.line2}</p>
</div>
"""
    if len(r.conflicts) > 50:
        html += f"<p>... and {len(r.conflicts)-50} more conflicts.</p>"
    html += "</body></html>"
    with open(path, "w") as f:
        f.write(html)
    print(f"  HTML saved to {path}")

# ---- Main ----
def main():
    parser = argparse.ArgumentParser(description="Business Rule Conflict Checker")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    parser.add_argument("--json", metavar="FILE", help="Save JSON report")
    parser.add_argument("--html", metavar="FILE", help="Save HTML report")
    parser.add_argument("--exclude", default=".venv,venv,__pycache__,tests,checker,docs,deployment,migrations",
                        help="Comma-separated dirs to exclude")
    parser.add_argument("--max-workers", type=int, default=4, help="Number of parallel workers")
    parser.add_argument("--root", "-r", default=None, help="Root directory to scan (default: parent of script)")
    parser.add_argument("--strict", action="store_true", help="Report conflicts within the same file (default: ignore)")
    args = parser.parse_args()

    if args.root:
        root = pathlib.Path(args.root).resolve()
    else:
        root = _ROOT_DIR

    checker = BusinessRuleConflictChecker(
        root,
        args.exclude.split(","),
        args.max_workers,
        ignore_same_file=not args.strict
    )

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
