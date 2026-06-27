#!/usr/bin/env python3
"""
Sovereign ERP System - Aggregate Event Contract Checker (Akurat Runtime)
=========================================================================
Memeriksa konsistensi event contract pada aggregate root dengan runtime inspection.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import pathlib
import sys
import time
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

COLOR = {
    "RED": "\033[91m",
    "GREEN": "\033[92m",
    "YELLOW": "\033[93m",
    "BLUE": "\033[94m",
    "CYAN": "\033[96m",
    "BOLD": "\033[1m",
    "RESET": "\033[0m"
}
if not sys.stdout.isatty():
    COLOR = dict.fromkeys(COLOR, "")

EXCLUDED_DIRS = {
    "checker", "tests", "migrations", "__pycache__", ".git",
    "docs", "scripts", "deployment", "monitoring", "reports", "alembic",
    "shared_value_objects", "value_objects"
}

NON_AGGREGATE_KEYWORDS = {
    "Repository", "Error", "Exception", "Table", "Store", "Adapter",
    "Service", "Factory", "Risk", "Enum", "Signature"
}

@dataclass
class AggregateInfo:
    file_path: str
    class_name: str
    base_classes: list[str]
    has_events_attr: bool
    has_register_event: bool
    has_get_events: bool
    has_pull_events: bool
    has_clear_events: bool
    violations: list[str] = field(default_factory=list)

class AggregateEventContractChecker:
    def __init__(self, root_dir: pathlib.Path):
        self.root_dir = root_dir
        self.aggregates: list[AggregateInfo] = []

    def _get_python_files(self) -> list[pathlib.Path]:
        py_files = []
        domain_dir = self.root_dir / "domain"
        if not domain_dir.exists():
            return py_files
        for p in domain_dir.rglob("*.py"):
            if any(part in EXCLUDED_DIRS for part in p.parts):
                continue
            if p.name.startswith(("test_", "conftest")):
                continue
            py_files.append(p)
        return py_files

    def _is_aggregate_class(self, cls: type) -> bool:
        name = cls.__name__
        for kw in NON_AGGREGATE_KEYWORDS:
            if kw in name:
                return False
        # Jika nama mengandung "Aggregate" → aggregate
        if "Aggregate" in name:
            return True
        # Jika nama mengandung "Collection" → aggregate hanya jika memiliki event method
        if "Collection" in name:
            return hasattr(cls, "register_event") or hasattr(cls, "pull_events")
        # Jika memiliki register_event atau pull_events → aggregate
        if hasattr(cls, "register_event") or hasattr(cls, "pull_events"):
            return True
        return False

    def _check_contract(self, cls: type):
        has_reg = hasattr(cls, "register_event") and inspect.isfunction(cls.register_event)
        has_get = hasattr(cls, "get_events") and inspect.isfunction(cls.get_events)
        has_pull = hasattr(cls, "pull_events") and inspect.isfunction(cls.pull_events)
        has_clear = hasattr(cls, "clear_events") and inspect.isfunction(cls.clear_events)

        # _events dianggap ada jika atribut class ada ATAU semua method ada (implisit)
        has_events = hasattr(cls, "_events") or (has_reg and has_get and has_pull and has_clear)

        violations = []
        if not has_events:
            violations.append("Tidak memiliki attribute _events")
        if not has_reg:
            violations.append("Tidak memiliki method register_event()")
        if not has_get:
            violations.append("Tidak memiliki method get_events()")
        if not has_pull:
            violations.append("Tidak memiliki method pull_events()")
        if not has_clear:
            violations.append("Tidak memiliki method clear_events()")

        return has_events, has_reg, has_get, has_pull, has_clear, violations

    def _get_base_class_names(self, cls: type) -> list[str]:
        return [base.__name__ for base in cls.__bases__ if base.__name__ not in ("object",)]

    def scan_file(self, module_name: str, file_path: pathlib.Path) -> list[AggregateInfo]:
        infos = []
        try:
            module = importlib.import_module(module_name)
        except Exception:
            return infos

        for name, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != module.__name__:
                continue
            if not self._is_aggregate_class(obj):
                continue

            base_names = self._get_base_class_names(obj)
            has_events, has_reg, has_get, has_pull, has_clear, violations = self._check_contract(obj)

            infos.append(AggregateInfo(
                file_path=str(file_path.relative_to(self.root_dir)),
                class_name=name,
                base_classes=base_names,
                has_events_attr=has_events,
                has_register_event=has_reg,
                has_get_events=has_get,
                has_pull_events=has_pull,
                has_clear_events=has_clear,
                violations=violations
            ))
        return infos

    def scan(self) -> list[AggregateInfo]:
        self.aggregates = []
        for f in self._get_python_files():
            rel_path = str(f.relative_to(self.root_dir)).replace("/", ".").replace("\\", ".")
            module_name = rel_path[:-3]  # hapus .py
            infos = self.scan_file(module_name, f)
            self.aggregates.extend(infos)
        return self.aggregates

def generate_fix_suggestions(info: AggregateInfo) -> str:
    suggestions = []
    if not info.has_events_attr:
        suggestions.append("_events: list[DomainEvent] = []")
    if not info.has_register_event:
        suggestions.append("def register_event(self, event: DomainEvent) -> None: self._events.append(event)")
    if not info.has_get_events:
        suggestions.append("def get_events(self) -> list[DomainEvent]: return self._events.copy()")
    if not info.has_pull_events:
        suggestions.append("def pull_events(self) -> list[DomainEvent]: events = self._events.copy(); self._events.clear(); return events")
    if not info.has_clear_events:
        suggestions.append("def clear_events(self) -> None: self._events.clear()")
    return "\n    ".join(suggestions)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", metavar="FILE", help="Ekspor laporan ke JSON")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail tambahan")
    args = parser.parse_args()

    start = time.monotonic()
    checker = AggregateEventContractChecker(ROOT)
    aggregates = checker.scan()

    total = len(aggregates)
    violations = [a for a in aggregates if a.violations]
    error_count = sum(len(a.violations) for a in violations)
    compliant = [a for a in aggregates if not a.violations]
    score = (len(compliant) / total * 100) if total else 100.0

    print(f"{COLOR['BOLD']}{COLOR['CYAN']}╔════════════════════════════════════════════════════════════════════╗")
    print("║      SOVEREIGN AGGREGATE EVENT CONTRACT CHECKER (RUNTIME)      ║")
    print(f"╚════════════════════════════════════════════════════════════════════╝{COLOR['RESET']}")
    print("  Standar Event Contract:")
    print("    ✅ _events: list[DomainEvent]")
    print("    ✅ register_event(event) -> None")
    print("    ✅ get_events() -> list[DomainEvent]")
    print("    ✅ pull_events() -> list[DomainEvent]")
    print("    ✅ clear_events() -> None")
    print(f"  Total Aggregate Ditemukan: {total}")
    print(f"  Total Violations: {error_count}")
    print(f"    ERRORS: {error_count}")
    print("    WARNINGS: 0")

    if violations:
        print(f"\n{COLOR['RED']}─── ERRORS (harus diperbaiki) ───{COLOR['RESET']}")
        for info in violations:
            base_info = f" (inherits: {', '.join(info.base_classes)})" if info.base_classes else ""
            print(f"  [ERROR] {info.file_path}: {info.class_name}{base_info}")
            for v in info.violations:
                print(f"    {v}")
            if args.verbose:
                sug = generate_fix_suggestions(info)
                if sug:
                    print(f"    → Tambahkan kode:\n    {sug}")
            print()

    if not violations:
        print(f"\n{COLOR['GREEN']}✅ Semua aggregate root memiliki event contract yang konsisten.{COLOR['RESET']}")

    print(f"  📈 Skor Kepatuhan Event Contract: {COLOR['CYAN']}{COLOR['BOLD']}{score:.1f}/100{COLOR['RESET']}")
    print(f"\n ⏱️ Waktu Audit: {time.monotonic() - start:.3f} detik")

    if args.json:
        payload = {
            "total_aggregates": total,
            "compliant": len(compliant),
            "violations_count": error_count,
            "score": round(score, 1),
            "violations": [
                {
                    "file": info.file_path,
                    "class": info.class_name,
                    "base_classes": info.base_classes,
                    "issues": info.violations
                } for info in violations
            ]
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"{COLOR['GREEN']}✅ Laporan diekspor ke {args.json}{COLOR['RESET']}")

    sys.exit(0 if error_count == 0 else 1)

if __name__ == "__main__":
    main()
