#!/usr/bin/env python3
"""
Sovereign ERP System - Domain Event Publish Checker (Full Data Flow)
=====================================================================
Mendeteksi SEMUA event yang di-instantiate di seluruh project,
termasuk yang di-assign ke variabel, disimpan di _events, lalu dipublish.
Cross-check dengan registry (all_event_handlers.py).

Cara pakai:
  python checker/checker_domain_event_publish.py
  python checker/checker_domain_event_publish.py --json report.json
  python checker/checker_domain_event_publish.py --verbose
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
import time
from dataclasses import dataclass, field

# =============================================================================
# Konfigurasi Root Project
# =============================================================================
ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# =============================================================================
# Konfigurasi Terminal
# =============================================================================
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
    "docs", "scripts", "deployment", "monitoring", "reports", "alembic"
}

PUBLISH_METHODS = {"publish", "add_event", "apply", "record_event", "emit", "raise_event", "append"}
IGNORE_EVENTS = {"BaseEvent", "DomainEvent", "IntegrationEvent"}
FALSE_POSITIVE_EVENTS = {
    "event", "envelope", "record", "topic", "applied_by", "disclosure",
    "shutdown", "shutting_down", "shut_down", "timeout", "error", "warning"
}

@dataclass
class EventUsage:
    event_name: str
    file_path: str
    line_no: int
    context: str  # "instantiation", "assignment", "publish_call", "append_to_events"

@dataclass
class EventInfo:
    event_name: str
    usages: list[EventUsage] = field(default_factory=list)

@dataclass
class Violation:
    severity: str
    message: str
    detail: str = ""

class EventPublishChecker:
    def __init__(self, root_dir: pathlib.Path):
        self.root_dir = root_dir
        self.registry_events: set[str] = set()
        self.registry_events_norm: set[str] = set()
        self.event_classes: set[str] = set()
        self.instantiated_events: set[str] = set()  # semua event yang di-instantiate

    def _get_python_files(self, base_dir: pathlib.Path | None = None) -> list[pathlib.Path]:
        target = base_dir or self.root_dir
        py_files = []
        for p in target.rglob("*.py"):
            if any(part in EXCLUDED_DIRS for part in p.parts):
                continue
            if p.name.startswith(("test_", "conftest")):
                continue
            py_files.append(p)
        return py_files

    def _normalize_event_name(self, name: str) -> str:
        if name.endswith("Event"):
            return name[:-5]
        return name

    def _is_event_class_name(self, name: str) -> bool:
        if not name:
            return False
        if name in IGNORE_EVENTS:
            return False
        if name in FALSE_POSITIVE_EVENTS:
            return False
        return name.endswith("Event") and name not in IGNORE_EVENTS

    def load_registry_and_events(self):
        # 1. Load registry
        try:
            import application.events.all_event_handlers as all_handlers
            if hasattr(all_handlers, "register_all_handlers"):
                all_handlers.register_all_handlers()
                print(f"{COLOR['GREEN']}✅ register_all_handlers() dipanggil.{COLOR['RESET']}")
            from application.events.handler_registry import event_handler_registry
            registry = event_handler_registry
            for attr in ["_handlers", "handlers", "registry"]:
                if hasattr(registry, attr):
                    data = getattr(registry, attr)
                    if isinstance(data, dict):
                        for ev_type in data.keys():
                            ev_name = ev_type if isinstance(ev_type, str) else getattr(ev_type, "__name__", str(ev_type))
                            self.registry_events.add(ev_name)
                            self.registry_events_norm.add(self._normalize_event_name(ev_name))
                        break
            if not self.registry_events:
                if hasattr(all_handlers, "handlers") and isinstance(all_handlers.handlers, dict):
                    for ev_name in all_handlers.handlers.keys():
                        self.registry_events.add(ev_name)
                        self.registry_events_norm.add(self._normalize_event_name(ev_name))
            print(f"  Registry: {len(self.registry_events)} event terdaftar.")
        except Exception as e:
            print(f"{COLOR['YELLOW']}⚠ Gagal load registry: {e}{COLOR['RESET']}")

        # 2. Kumpulkan semua class event dari domain/
        domain_dir = self.root_dir / "domain"
        if domain_dir.exists():
            for py_file in domain_dir.rglob("*.py"):
                try:
                    src = py_file.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(src, filename=str(py_file))
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef) and self._is_event_class_name(node.name):
                            self.event_classes.add(node.name)
                except Exception:
                    pass
        print(f"  Event Classes: {len(self.event_classes)} ditemukan.")

    def scan_events(self) -> dict[str, EventInfo]:
        """Scan semua file untuk instansiasi event dan publish calls."""
        events_map: dict[str, EventInfo] = {}
        files = self._get_python_files()

        for py_file in files:
            try:
                src = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=str(py_file))
            except SyntaxError:
                continue

            rel_path = str(py_file.relative_to(self.root_dir))

            class EventTracker(ast.NodeVisitor):
                def __init__(self):
                    self.usages: list[EventUsage] = []
                    # Variable tracking (local scope)
                    self.var_to_event: dict[str, str] = {}  # var_name -> event_class
                    self.attr_to_event: dict[str, str] = {}  # self._attr -> event_class

                def visit_Assign(self, node):
                    # Track assignment: event = SomeEvent(...)
                    if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
                        if self._is_event_class(node.value.func.id):
                            event_name = node.value.func.id
                            for target in node.targets:
                                if isinstance(target, ast.Name):
                                    self.var_to_event[target.id] = event_name
                                    self.usages.append(EventUsage(
                                        event_name=event_name,
                                        file_path=rel_path,
                                        line_no=node.lineno,
                                        context=f"assignment to variable '{target.id}'"
                                    ))
                                elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                                    self.attr_to_event[target.attr] = event_name
                                    self.usages.append(EventUsage(
                                        event_name=event_name,
                                        file_path=rel_path,
                                        line_no=node.lineno,
                                        context=f"assignment to self.{target.attr}"
                                    ))
                    # Track: self._events.append(SomeEvent(...))
                    elif isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute):
                        if node.value.func.attr == "append" and node.value.args:
                            arg = node.value.args[0]
                            if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
                                if self._is_event_class(arg.func.id):
                                    event_name = arg.func.id
                                    self.usages.append(EventUsage(
                                        event_name=event_name,
                                        file_path=rel_path,
                                        line_no=node.lineno,
                                        context="_events.append(SomeEvent(...))"
                                    ))
                    # Track: event = other_var (propagasi)
                    elif isinstance(node.value, ast.Name):
                        if node.value.id in self.var_to_event:
                            for target in node.targets:
                                if isinstance(target, ast.Name):
                                    self.var_to_event[target.id] = self.var_to_event[node.value.id]
                    self.generic_visit(node)

                def visit_Call(self, node):
                    # Deteksi instansiasi event langsung (tanpa assignment): SomeEvent(...)
                    if isinstance(node.func, ast.Name) and self._is_event_class(node.func.id):
                        self.usages.append(EventUsage(
                            event_name=node.func.id,
                            file_path=rel_path,
                            line_no=node.lineno,
                            context="direct instantiation"
                        ))

                    # Deteksi pemanggilan publish
                    func = node.func
                    method_name = ""
                    is_publish = False

                    if isinstance(func, ast.Attribute) and func.attr in PUBLISH_METHODS:
                        is_publish = True
                        method_name = func.attr
                    elif isinstance(func, ast.Name) and func.id in PUBLISH_METHODS:
                        is_publish = True
                        method_name = func.id

                    if is_publish and node.args:
                        arg = node.args[0]
                        event_name = None

                        # Kasus 1: publish(EventClass(...))
                        if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name):
                            if self._is_event_class(arg.func.id):
                                event_name = arg.func.id
                        # Kasus 2: publish(event_var)
                        elif isinstance(arg, ast.Name):
                            if arg.id in self.var_to_event:
                                event_name = self.var_to_event[arg.id]
                            elif self._is_event_class(arg.id):
                                event_name = arg.id
                        # Kasus 3: publish(self._event)
                        elif isinstance(arg, ast.Attribute):
                            if self._is_event_class(arg.attr):
                                event_name = arg.attr
                            elif arg.attr in self.attr_to_event:
                                event_name = self.attr_to_event[arg.attr]

                        if event_name:
                            self.usages.append(EventUsage(
                                event_name=event_name,
                                file_path=rel_path,
                                line_no=node.lineno,
                                context=f"publish call ({method_name})"
                            ))

                    self.generic_visit(node)

                def _is_event_class(self, name: str) -> bool:
                    return name.endswith("Event") and name not in IGNORE_EVENTS and name not in FALSE_POSITIVE_EVENTS

            tracker = EventTracker()
            try:
                tracker.visit(tree)
            except Exception:
                continue

            for usage in tracker.usages:
                if usage.event_name not in events_map:
                    events_map[usage.event_name] = EventInfo(event_name=usage.event_name)
                events_map[usage.event_name].usages.append(usage)
                self.instantiated_events.add(usage.event_name)

        return events_map

    def check(self) -> tuple[dict[str, EventInfo], list[Violation]]:
        self.load_registry_and_events()
        events_map = self.scan_events()

        violations = []
        for ev_name, info in events_map.items():
            norm = self._normalize_event_name(ev_name)
            if ev_name not in self.registry_events and norm not in self.registry_events_norm:
                # Hanya laporkan jika event ini adalah class event yang valid
                if ev_name in self.event_classes:
                    detail = "\n".join(
                        f"    - {u.file_path}:{u.line_no} ({u.context})" for u in info.usages
                    )
                    violations.append(Violation(
                        severity="ERROR",
                        message=f"Event '{ev_name}' digunakan tetapi tidak terdaftar di registry.",
                        detail=detail
                    ))
        return events_map, violations

def main():
    parser = argparse.ArgumentParser(description="Domain Event Publish Checker (Full Data Flow)")
    parser.add_argument("--json", metavar="FILE", help="Ekspor laporan ke JSON")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail tambahan")
    args = parser.parse_args()

    start_time = time.monotonic()
    root_dir = ROOT
    checker = EventPublishChecker(root_dir)

    print(f"{COLOR['BOLD']}{COLOR['CYAN']}╔════════════════════════════════════════════════════════════════════╗")
    print("║      SOVEREIGN DOMAIN EVENT PUBLISH CHECKER (FULL DATA FLOW)   ║")
    print(f"╚════════════════════════════════════════════════════════════════════╝{COLOR['RESET']}")
    print(f"  Mode Deteksi             :  {COLOR['GREEN']}✅ Data Flow Analysis{COLOR['RESET']}")
    print(f"  Tracking Assignment      :  {COLOR['GREEN']}✅ event = SomeEvent(...){COLOR['RESET']}")
    print(f"  Tracking self._event     :  {COLOR['GREEN']}✅ self._event = SomeEvent(...){COLOR['RESET']}")
    print(f"  Tracking _events.append :  {COLOR['GREEN']}✅ self._events.append(SomeEvent(...)){COLOR['RESET']}")
    print(f"  Source of Truth          :  {COLOR['CYAN']}Registry from all_event_handlers.py{COLOR['RESET']}")
    print(f"  Proteksi Folder          :  {COLOR['GREEN']}✅ Excluded folders diabaikan{COLOR['RESET']}")

    events_map, violations = checker.check()

    total_events = len(events_map)
    error_count = sum(1 for v in violations if v.severity == "ERROR")
    score = max(0, 100 - (error_count * 2)) if total_events > 0 else 100

    print(f"\n  Total Event Digunakan    :  {total_events}")
    print(f"  ✅ Terdaftar di Registry :  {total_events - error_count}")
    print(f"  ❌ Tidak Terdaftar       :  {COLOR['RED'] if error_count > 0 else COLOR['GREEN']}{error_count}{COLOR['RESET']}")
    print(f"  📈 Skor Kepatuhan        :  {COLOR['CYAN']}{COLOR['BOLD']}{score}/100{COLOR['RESET']}")

    if violations:
        print(f"\n{COLOR['BOLD']}─── DETAIL VIOLATIONS ───{COLOR['RESET']}")
        for v in violations:
            print(f"  {COLOR['RED']}[{v.severity}]{COLOR['RESET']} {v.message}")
            if v.detail:
                print(f"      {v.detail}")
    else:
        print(f"\n{COLOR['GREEN']}✅ Semua event yang digunakan terdaftar di registry.{COLOR['RESET']}")

    if args.verbose and events_map:
        print(f"\n{COLOR['BOLD']}─── USED EVENTS ───{COLOR['RESET']}")
        for ev_name, info in sorted(events_map.items()):
            status = "✅" if ev_name in checker.registry_events or checker._normalize_event_name(ev_name) in checker.registry_events_norm else "❌"
            print(f"  {status} {ev_name} (ditemukan di {len(info.usages)} lokasi)")

    print(f"\n ⏱️ Waktu Audit: {time.monotonic() - start_time:.3f} detik")

    if args.json:
        payload = {
            "total_used": total_events,
            "registered": total_events - error_count,
            "unregistered": error_count,
            "score": score,
            "violations": [
                {"severity": v.severity, "message": v.message, "detail": v.detail}
                for v in violations
            ],
            "used_events": {
                ev: [{"file": u.file_path, "line": u.line_no, "context": u.context}
                     for u in info.usages]
                for ev, info in events_map.items()
            }
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"{COLOR['GREEN']}✅ Laporan diekspor ke {args.json}{COLOR['RESET']}")

    sys.exit(0 if error_count == 0 else 1)

if __name__ == "__main__":
    main()
