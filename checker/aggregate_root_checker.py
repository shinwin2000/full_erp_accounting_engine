#!/usr/bin/env python3
"""
aggregate_root_checker.py — Aggregate Event Contract & Forensic Checker v6.0
============================================================================
Versi   : 6.0.0
Standar : Event Sourcing · DDD · SOX/ISA 315

Perbaikan v6.0.0:
  - Deteksi annotated assignment (ast.AnnAssign) di __init__ untuk _events, id, version
  - Perluas deteksi id ke attribute berakhiran _id (coa_id, asset_id, dll)
  - Turunkan severity apply menjadi MEDIUM jika aggregate punya register_event dan _events
  - Deteksi factory method lebih luas: create, from_events, reconstruct, reconstitute
  - Scoring: CRITICAL=-10, HIGH=-5, MEDIUM=-2, LOW=-0.5 (tetap)
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ─── COLOR ──────────────────────────────────────────────────────────────────
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

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ─── RCA INTEGRATION ────────────────────────────────────────────────────────
RCA_AVAILABLE = False
_analyze_exception = None
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from core.rca import analyze_exception, get_engine
    _analyze_exception = analyze_exception
    RCA_AVAILABLE = True
except ImportError:
    try:
        import rca
        _analyze_exception = rca.analyze_exception
        RCA_AVAILABLE = True
    except ImportError:
        pass

# ─── DATA CLASSES ──────────────────────────────────────────────────────────
@dataclass
class Violation:
    rule_id: str
    file_path: str
    aggregate_name: str
    severity: str
    message: str
    suggestion: str
    line: int = 0
    rca: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "rule_id": self.rule_id,
            "file": self.file_path,
            "aggregate": self.aggregate_name,
            "severity": self.severity,
            "message": self.message,
            "suggestion": self.suggestion,
            "line": self.line,
        }
        if self.rca:
            d["rca"] = self.rca
        return d

@dataclass
class AggregateInfo:
    file_path: str
    name: str
    line: int
    has_events: bool
    has_register_event: bool
    has_get_events: bool
    has_pull_events: bool
    has_clear_events: bool
    has_id: bool
    has_version: bool
    has_apply: bool
    has_factory: bool
    violations: list[Violation] = field(default_factory=list)

@dataclass
class Report:
    aggregates: list[AggregateInfo] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    score: int = 100
    rca_enabled: bool = False
    elapsed_seconds: float = 0.0

# ─── RULE IDS ──────────────────────────────────────────────────────────────
class RuleID:
    EVENTS_ATTR = "AGG-001"
    REGISTER_EVENT = "AGG-002"
    GET_EVENTS = "AGG-003"
    PULL_EVENTS = "AGG-004"
    CLEAR_EVENTS = "AGG-005"
    ID_ATTR = "AGG-011"
    VERSION_ATTR = "AGG-012"
    APPLY_METHOD = "AGG-021"
    FACTORY_METHOD = "AGG-061"

# ─── CHECKER ────────────────────────────────────────────────────────────────
class AggregateChecker:
    def __init__(self, root: Path, enable_rca: bool = True):
        self.root = root
        self.enable_rca = enable_rca and RCA_AVAILABLE
        self.aggregates: list[AggregateInfo] = []

    def _get_python_files(self) -> list[Path]:
        py_files = []
        scan_dirs = ['domain', 'application/aggregates']
        for dir_name in scan_dirs:
            base = self.root / dir_name
            if not base.exists():
                continue
            for p in base.rglob("*.py"):
                if any(part in ('.venv', 'venv', '__pycache__', '.git', 'node_modules', 'migrations', 'tests', 'checker') for part in p.parts):
                    continue
                if p.name.startswith(('test_', 'conftest', '__init__')):
                    continue
                py_files.append(p)
        return py_files

    def _skip_class(self, name: str) -> bool:
        skip_suffixes = ('Error', 'Exception', 'Repository', 'Service', 'Handler',
                         'Integrator', 'Processor', 'Generator', 'Manager', 'Validator',
                         'Builder', 'Config', 'Port', 'Adapter', 'Factory', 'Provider')
        if any(name.endswith(suffix) for suffix in skip_suffixes):
            return True
        skip_tokens = ('Error', 'Exception', 'Repository', 'Integrator', 'Processor', 'Generator', 'Manager')
        if any(token in name for token in skip_tokens):
            return True
        return False

    def _is_aggregate_root(self, node: ast.ClassDef, file_path: Path) -> tuple[bool, str]:
        name = node.name
        rel_path = str(file_path.relative_to(self.root))

        if 'adapters' in rel_path or 'infrastructure' in rel_path:
            return False, ""

        if self._skip_class(name):
            return False, ""

        if 'Aggregate' not in name and 'AggregateRoot' not in name:
            return False, ""

        # Inheritance detection
        is_inherited = False
        for base in node.bases:
            base_name = ''
            if isinstance(base, ast.Name):
                base_name = base.id
            elif isinstance(base, ast.Attribute):
                base_name = base.attr
            if base_name in ('AggregateRoot', 'BaseAggregate', 'RootAggregate', 'EventSourcedAggregate'):
                is_inherited = True
                break

        # Method detection
        methods = [item.name for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]
        has_register = 'register_event' in methods
        has_apply = 'apply' in methods or 'when' in methods
        has_pull = 'pull_events' in methods

        # Attribute detection (instance or class) - v6.0: include AnnAssign
        has_events = False
        has_id = False
        has_version = False

        # Scan __init__ for instance attributes (including annotated assignments)
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == '__init__':
                for sub in ast.walk(item):
                    if isinstance(sub, ast.Assign):
                        for target in sub.targets:
                            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == 'self':
                                attr = target.attr
                                if attr == '_events':
                                    has_events = True
                                elif attr == 'id' or attr == 'aggregate_id' or attr.endswith('_id'):
                                    has_id = True
                                elif attr == 'version' or attr == '_version':
                                    has_version = True
                    elif isinstance(sub, ast.AnnAssign):
                        if isinstance(sub.target, ast.Attribute) and isinstance(sub.target.value, ast.Name) and sub.target.value.id == 'self':
                            attr = sub.target.attr
                            if attr == '_events':
                                has_events = True
                            elif attr == 'id' or attr == 'aggregate_id' or attr.endswith('_id'):
                                has_id = True
                            elif attr == 'version' or attr == '_version':
                                has_version = True

        # Also check class-level assignments (including AnnAssign)
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        attr = target.id
                        if attr == '_events':
                            has_events = True
                        elif attr == 'id' or attr == 'aggregate_id' or attr.endswith('_id'):
                            has_id = True
                        elif attr == 'version' or attr == '_version':
                            has_version = True
            elif isinstance(item, ast.AnnAssign):
                if isinstance(item.target, ast.Name):
                    attr = item.target.id
                    if attr == '_events':
                        has_events = True
                    elif attr == 'id' or attr == 'aggregate_id' or attr.endswith('_id'):
                        has_id = True
                    elif attr == 'version' or attr == '_version':
                        has_version = True

        # If still not found, check if there is any attribute ending with _id
        if not has_id:
            for item in node.body:
                if isinstance(item, (ast.Assign, ast.AnnAssign)):
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name) and (target.id == 'id' or target.id == 'aggregate_id' or target.id.endswith('_id')):
                                has_id = True
                    else:
                        if isinstance(item.target, ast.Name) and (item.target.id == 'id' or item.target.id == 'aggregate_id' or item.target.id.endswith('_id')):
                            has_id = True

        # Aggregate must have at least 2 indicators: events + register OR apply + pull
        indicators = [has_events, has_register, has_apply, has_pull]
        if sum(indicators) >= 2:
            return True, "event_sourced"
        return False, ""

    def _get_fields_and_methods(self, node: ast.ClassDef) -> tuple[set[str], set[str]]:
        fields, methods = set(), set()
        for item in node.body:
            if isinstance(item, (ast.Assign, ast.AnnAssign)):
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            fields.add(target.id)
                else:
                    if isinstance(item.target, ast.Name):
                        fields.add(item.target.id)
            elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.add(item.name)
        return fields, methods

    def _generate_rca(self, rule_id: str, message: str, severity: str) -> dict[str, Any] | None:
        if not self.enable_rca or _analyze_exception is None:
            return None
        try:
            exc = RuntimeError(f"[{rule_id}] {message}")
            result = _analyze_exception(exc, {"rule_id": rule_id, "severity": severity})
            return result.to_dict() if result else None
        except Exception:
            return {"root_cause": message, "suggested_fix": "Periksa implementasi Aggregate."}

    def _check_aggregate(self, node: ast.ClassDef, file_path: Path) -> AggregateInfo:
        name = node.name
        # v6.0: scan __init__ and class body for _events, id, version
        has_events = False
        has_id = False
        has_version = False

        # Scan __init__
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == '__init__':
                for sub in ast.walk(item):
                    if isinstance(sub, ast.Assign):
                        for target in sub.targets:
                            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == 'self':
                                attr = target.attr
                                if attr == '_events':
                                    has_events = True
                                elif attr == 'id' or attr == 'aggregate_id' or attr.endswith('_id'):
                                    has_id = True
                                elif attr == 'version' or attr == '_version':
                                    has_version = True
                    elif isinstance(sub, ast.AnnAssign):
                        if isinstance(sub.target, ast.Attribute) and isinstance(sub.target.value, ast.Name) and sub.target.value.id == 'self':
                            attr = sub.target.attr
                            if attr == '_events':
                                has_events = True
                            elif attr == 'id' or attr == 'aggregate_id' or attr.endswith('_id'):
                                has_id = True
                            elif attr == 'version' or attr == '_version':
                                has_version = True

        # Class-level
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        attr = target.id
                        if attr == '_events':
                            has_events = True
                        elif attr == 'id' or attr == 'aggregate_id' or attr.endswith('_id'):
                            has_id = True
                        elif attr == 'version' or attr == '_version':
                            has_version = True
            elif isinstance(item, ast.AnnAssign):
                if isinstance(item.target, ast.Name):
                    attr = item.target.id
                    if attr == '_events':
                        has_events = True
                    elif attr == 'id' or attr == 'aggregate_id' or attr.endswith('_id'):
                        has_id = True
                    elif attr == 'version' or attr == '_version':
                        has_version = True

        # Fallback: check any attribute ending with _id
        if not has_id:
            for item in node.body:
                if isinstance(item, (ast.Assign, ast.AnnAssign)):
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name) and (target.id == 'id' or target.id == 'aggregate_id' or target.id.endswith('_id')):
                                has_id = True
                    else:
                        if isinstance(item.target, ast.Name) and (item.target.id == 'id' or item.target.id == 'aggregate_id' or item.target.id.endswith('_id')):
                            has_id = True

        methods = [item.name for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]
        has_register = 'register_event' in methods
        has_get = 'get_events' in methods
        has_pull = 'pull_events' in methods
        has_clear = 'clear_events' in methods
        has_apply = 'apply' in methods or 'when' in methods
        has_factory = any(m in methods for m in ('create', 'from_events', 'reconstitute', 'reconstruct'))

        rel_path = str(file_path.relative_to(self.root))
        violations = []

        # Only check strict rules if aggregate is event-sourced (has some indicators)
        if has_events or has_register or has_apply:
            if not has_events:
                violations.append(Violation(
                    rule_id=RuleID.EVENTS_ATTR,
                    file_path=rel_path,
                    aggregate_name=name,
                    severity="CRITICAL" if has_register or has_apply else "HIGH",
                    message=f"Aggregate '{name}' tidak memiliki attribute '_events' (instance atau class).",
                    suggestion="Tambahkan '_events: list[DomainEvent] = []' di __init__ atau class body.",
                    line=node.lineno,
                    rca=self._generate_rca(RuleID.EVENTS_ATTR, f"Missing _events on {name}", "CRITICAL"),
                ))
            if not has_register:
                violations.append(Violation(
                    rule_id=RuleID.REGISTER_EVENT,
                    file_path=rel_path,
                    aggregate_name=name,
                    severity="CRITICAL",
                    message=f"Aggregate '{name}' tidak memiliki method 'register_event(event)'.",
                    suggestion="Tambahkan method untuk menambahkan event ke _events.",
                    line=node.lineno,
                    rca=self._generate_rca(RuleID.REGISTER_EVENT, f"Missing register_event on {name}", "CRITICAL"),
                ))
        else:
            # If no event sourcing indicators, skip CRITICAL (maybe it's not event-sourced)
            pass

        # HIGH rules
        if not has_get:
            violations.append(Violation(
                rule_id=RuleID.GET_EVENTS,
                file_path=rel_path,
                aggregate_name=name,
                severity="HIGH",
                message=f"Aggregate '{name}' tidak memiliki method 'get_events()'.",
                suggestion="Tambahkan method untuk mengambil event yang belum diproses.",
                line=node.lineno,
                rca=self._generate_rca(RuleID.GET_EVENTS, f"Missing get_events on {name}", "HIGH"),
            ))
        if not has_pull:
            violations.append(Violation(
                rule_id=RuleID.PULL_EVENTS,
                file_path=rel_path,
                aggregate_name=name,
                severity="HIGH",
                message=f"Aggregate '{name}' tidak memiliki method 'pull_events()'.",
                suggestion="Tambahkan method untuk mengambil dan membersihkan event.",
                line=node.lineno,
                rca=self._generate_rca(RuleID.PULL_EVENTS, f"Missing pull_events on {name}", "HIGH"),
            ))
        if not has_id:
            violations.append(Violation(
                rule_id=RuleID.ID_ATTR,
                file_path=rel_path,
                aggregate_name=name,
                severity="HIGH",
                message=f"Aggregate '{name}' tidak memiliki attribute 'id', 'aggregate_id', atau '*_id' (instance atau class).",
                suggestion="Setiap aggregate root harus memiliki identitas unik (self.id, aggregate_id, atau coa_id).",
                line=node.lineno,
                rca=self._generate_rca(RuleID.ID_ATTR, f"Missing id on {name}", "HIGH"),
            ))
        if not has_version:
            violations.append(Violation(
                rule_id=RuleID.VERSION_ATTR,
                file_path=rel_path,
                aggregate_name=name,
                severity="HIGH",
                message=f"Aggregate '{name}' tidak memiliki attribute 'version' atau '_version' (instance atau class).",
                suggestion="Tambahkan attribute version untuk optimistic locking.",
                line=node.lineno,
                rca=self._generate_rca(RuleID.VERSION_ATTR, f"Missing version on {name}", "HIGH"),
            ))

        # v6.0: Turunkan severity apply jika ada register_event + _events
        if not has_apply:
            if has_register and has_events:
                severity = "MEDIUM"
                suggestion = "Aggregate memiliki register_event dan _events, tetapi tidak ada apply. Ini mungkin bukan event sourcing penuh. Tambahkan apply/when jika diperlukan."
            else:
                severity = "HIGH"
                suggestion = "Tambahkan method untuk menerapkan event ke state."
            violations.append(Violation(
                rule_id=RuleID.APPLY_METHOD,
                file_path=rel_path,
                aggregate_name=name,
                severity=severity,
                message=f"Aggregate '{name}' tidak memiliki method 'apply(event)' atau 'when(event)'.",
                suggestion=suggestion,
                line=node.lineno,
                rca=self._generate_rca(RuleID.APPLY_METHOD, f"Missing apply on {name}", severity),
            ))

        # MEDIUM: clear_events
        if not has_clear:
            violations.append(Violation(
                rule_id=RuleID.CLEAR_EVENTS,
                file_path=rel_path,
                aggregate_name=name,
                severity="MEDIUM",
                message=f"Aggregate '{name}' tidak memiliki method 'clear_events()'.",
                suggestion="Tambahkan method untuk membersihkan event setelah diproses.",
                line=node.lineno,
                rca=self._generate_rca(RuleID.CLEAR_EVENTS, f"Missing clear_events on {name}", "MEDIUM"),
            ))

        # LOW: factory method
        if not has_factory:
            violations.append(Violation(
                rule_id=RuleID.FACTORY_METHOD,
                file_path=rel_path,
                aggregate_name=name,
                severity="LOW",
                message=f"Aggregate '{name}' tidak memiliki factory method (create/from_events/reconstruct).",
                suggestion="Tambahkan factory method untuk membuat aggregate dari event stream.",
                line=node.lineno,
                rca=self._generate_rca(RuleID.FACTORY_METHOD, f"Missing factory on {name}", "LOW"),
            ))

        return AggregateInfo(
            file_path=rel_path,
            name=name,
            line=node.lineno,
            has_events=has_events,
            has_register_event=has_register,
            has_get_events=has_get,
            has_pull_events=has_pull,
            has_clear_events=has_clear,
            has_id=has_id,
            has_version=has_version,
            has_apply=has_apply,
            has_factory=has_factory,
            violations=violations,
        )

    def scan(self) -> Report:
        report = Report()
        report.rca_enabled = self.enable_rca
        start = time.monotonic()

        for py_file in self._get_python_files():
            try:
                src = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=str(py_file))
            except (SyntaxError, UnicodeDecodeError):
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                is_agg, reason = self._is_aggregate_root(node, py_file)
                if not is_agg:
                    continue

                info = self._check_aggregate(node, py_file)
                self.aggregates.append(info)
                report.violations.extend(info.violations)

        weights = {"CRITICAL": 10, "HIGH": 5, "MEDIUM": 2, "LOW": 0.5}
        penalty = sum(weights.get(v.severity, 0) for v in report.violations)
        report.score = max(0, 100 - min(penalty, 100))
        report.elapsed_seconds = time.monotonic() - start
        report.aggregates = self.aggregates
        return report

# ─── REPORT ──────────────────────────────────────────────────────────────────
def print_report(report: Report, verbose: bool = False):
    c = COLOR
    print(f"\n{c['CYAN']}{'='*80}{c['RESET']}")
    print(f"{c['CYAN']}AGGREGATE EVENT CONTRACT & FORENSIC CHECKER v6.0 — {(report.rca_enabled and 'RCA ENABLED') or 'RCA DISABLED'}{c['RESET']}")
    print(f"{c['CYAN']}{'='*80}{c['RESET']}")

    severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for v in report.violations:
        severity_counts[v.severity] = severity_counts.get(v.severity, 0) + 1

    print(f"\n  Total Aggregates: {len(report.aggregates)}")
    print(f"  Total Violations: {len(report.violations)}")
    print(f"  {c['RED']}CRITICAL: {severity_counts.get('CRITICAL', 0)}{c['RESET']}")
    print(f"  {c['YELLOW']}HIGH: {severity_counts.get('HIGH', 0)}{c['RESET']}")
    print(f"  {c['MAGENTA']}MEDIUM: {severity_counts.get('MEDIUM', 0)}{c['RESET']}")
    print(f"  {c['CYAN']}LOW: {severity_counts.get('LOW', 0)}{c['RESET']}")
    score_color = c["GREEN"] if report.score >= 70 else c["YELLOW"] if report.score >= 50 else c["RED"]
    print(f"  Score: {score_color}{report.score}/100{c['RESET']}")
    print(f"  ⏱️ Elapsed: {report.elapsed_seconds:.3f}s")

    if report.aggregates:
        print(f"\n{c['CYAN']}AGGREGATES:{c['RESET']}")
        for agg in report.aggregates[:30]:
            status = f"{c['RED']}{len(agg.violations)} violations{c['RESET']}" if agg.violations else f"{c['GREEN']}✓ Compliant{c['RESET']}"
            print(f"  {agg.name} @ {agg.file_path}:{agg.line} {status}")
        if len(report.aggregates) > 30:
            print(f"  ... and {len(report.aggregates)-30} more")

    if report.violations:
        print(f"\n{c['RED']}VIOLATIONS (sample):{c['RESET']}")
        for v in report.violations[:30]:
            color = c["RED"] if v.severity == "CRITICAL" else c["YELLOW"] if v.severity == "HIGH" else c["CYAN"]
            print(f"  {color}[{v.rule_id}] {v.severity}{c['RESET']} {v.message}")
            print(f"    💡 {v.suggestion}")
            if verbose and v.rca:
                if v.rca.get("root_cause"):
                    print(f"    RCA: {v.rca['root_cause'][:120]}")
                if v.rca.get("suggested_fix"):
                    print(f"    Fix: {v.rca['suggested_fix'][:120]}")
        if len(report.violations) > 30:
            print(f"  ... and {len(report.violations)-30} more")

def save_json(report: Report, path: str) -> None:
    try:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "score": report.score,
            "rca_enabled": report.rca_enabled,
            "elapsed_seconds": report.elapsed_seconds,
            "total_aggregates": len(report.aggregates),
            "total_violations": len(report.violations),
            "severity_counts": {
                "CRITICAL": sum(1 for v in report.violations if v.severity == "CRITICAL"),
                "HIGH": sum(1 for v in report.violations if v.severity == "HIGH"),
                "MEDIUM": sum(1 for v in report.violations if v.severity == "MEDIUM"),
                "LOW": sum(1 for v in report.violations if v.severity == "LOW"),
            },
            "aggregates": [
                {
                    "name": a.name,
                    "file": a.file_path,
                    "line": a.line,
                    "has_events": a.has_events,
                    "has_register_event": a.has_register_event,
                    "has_get_events": a.has_get_events,
                    "has_pull_events": a.has_pull_events,
                    "has_clear_events": a.has_clear_events,
                    "has_id": a.has_id,
                    "has_version": a.has_version,
                    "has_apply": a.has_apply,
                    "has_factory": a.has_factory,
                    "violations": [v.to_dict() for v in a.violations],
                }
                for a in report.aggregates
            ],
        }
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{COLOR['GREEN']}✅ JSON exported to {out.resolve()}{COLOR['RESET']}")
    except Exception as e:
        print(f"{COLOR['RED']}❌ Failed to write JSON: {e}{COLOR['RESET']}")

def main():
    parser = argparse.ArgumentParser(description="Aggregate Root Checker v6.0")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE")
    parser.add_argument("--no-rca", action="store_true")
    args = parser.parse_args()

    enable_rca = not args.no_rca and RCA_AVAILABLE
    checker = AggregateChecker(PROJECT_ROOT, enable_rca=enable_rca)
    report = checker.scan()
    print_report(report, args.verbose)
    if args.json:
        save_json(report, args.json)

    critical_high = sum(1 for v in report.violations if v.severity in ("CRITICAL", "HIGH"))
    sys.exit(0 if critical_high == 0 else 1)

if __name__ == "__main__":
    main()
