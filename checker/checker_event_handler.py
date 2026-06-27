#!/usr/bin/env python3
"""
Sovereign ERP System - Event Handler Validator (Realistic)
===========================================================
- Registry di-load dari all_event_handlers.py
- Event discan dari domain/
- Normalisasi nama (hilangkan suffix "Event") untuk pencocokan
- Klasifikasi: Registered | Used (kritis) | Audit-only
- Filter: __init__.py dan tests/ diabaikan dari deteksi penggunaan
- Skor proporsional
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import sys
import time
from dataclasses import dataclass

# =============================================================================
# Pastikan root project ada di sys.path
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
    "docs", "scripts", "deployment", "monitoring", "reports",
    "shared_value_objects", "reality"
}

IGNORE_EVENTS = {"BaseEvent", "DomainEvent", "IntegrationEvent"}
NON_EVENT_SUFFIXES = {"Publisher", "Type", "Store", "Service", "Helper", "Factory", "Config", "Settings", "Repository"}

@dataclass
class EventInfo:
    name: str
    file_path: str
    in_registry: bool = False
    used_outside_domain: bool = False

class SovereignEventHandlerVerifier:
    def __init__(self, root_dir: pathlib.Path):
        self.root_dir = root_dir
        self.registry_events: set[str] = set()
        self.registry_events_norm: set[str] = set()
        self.handler_count: int = 0

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

    def _extract_base_classes(self, node: ast.ClassDef) -> list[str]:
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(base.attr)
        return bases

    def _normalize_event_name(self, name: str) -> str:
        if name.endswith("Event"):
            return name[:-5]
        return name

    def load_registry_runtime(self):
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
                            hdls = data[ev_type]
                            self.handler_count += len(hdls) if isinstance(hdls, list) else 1
                        break
            if not self.registry_events:
                if hasattr(all_handlers, "handlers") and isinstance(all_handlers.handlers, dict):
                    for ev_name in all_handlers.handlers.keys():
                        self.registry_events.add(ev_name)
                        self.registry_events_norm.add(self._normalize_event_name(ev_name))
                        self.handler_count += 1
            print(f"  Registry: {len(self.registry_events)} event terdaftar, {self.handler_count} handler.")
        except Exception as e:
            print(f"{COLOR['YELLOW']}⚠ Gagal load registry: {e}{COLOR['RESET']}")

    def scan_events_ast(self) -> dict[str, EventInfo]:
        events: dict[str, EventInfo] = {}
        domain_dir = self.root_dir / "domain"
        if not domain_dir.exists():
            return events

        for py_file in self._get_python_files(domain_dir):
            try:
                src = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=str(py_file))
                rel_path = str(py_file.relative_to(self.root_dir))
                is_domain_events = "domain_events" in str(py_file)

                for node in ast.walk(tree):
                    if not isinstance(node, ast.ClassDef):
                        continue
                    name = node.name
                    bases = self._extract_base_classes(node)

                    is_event = False
                    if any(b in IGNORE_EVENTS for b in bases) or (name.endswith("Event") and name not in IGNORE_EVENTS):
                        is_event = True
                    elif is_domain_events and not name.startswith("_"):
                        if any(name.endswith(suffix) for suffix in NON_EVENT_SUFFIXES):
                            continue
                        is_event = True

                    if is_event and name not in events:
                        events[name] = EventInfo(name=name, file_path=rel_path)
            except Exception:
                continue
        return events

    def classify_events(self, events: dict[str, EventInfo]):
        """Tentukan status event: registry dan penggunaan di luar domain."""
        # Tandai yang terdaftar
        for ev_name, ev_info in events.items():
            norm = self._normalize_event_name(ev_name)
            if ev_name in self.registry_events or norm in self.registry_events_norm:
                ev_info.in_registry = True

        # Cek penggunaan di luar domain (tapi skip __init__.py dan tests/)
        all_files = self._get_python_files()
        for ev_name, ev_info in events.items():
            used = False
            for py_file in all_files:
                # Skip file di domain/ (kecuali domain_events.py itu sendiri)
                if "domain" in str(py_file) and "domain_events" not in str(py_file):
                    continue
                # Skip __init__.py
                if py_file.name == "__init__.py":
                    continue
                # Skip tests/
                if "tests" in str(py_file):
                    continue
                try:
                    if ev_name in py_file.read_text(encoding="utf-8", errors="replace"):
                        used = True
                        break
                except Exception:
                    continue
            ev_info.used_outside_domain = used

def main():
    parser = argparse.ArgumentParser(description="Event Handler Validator (Realistic)")
    parser.add_argument("--json", metavar="FILE", help="Ekspor laporan ke JSON")
    args = parser.parse_args()

    start_time = time.monotonic()
    root_dir = ROOT
    verifier = SovereignEventHandlerVerifier(root_dir)

    print(f"{COLOR['BOLD']}{COLOR['CYAN']}╔════════════════════════════════════════════════════════════════════╗")
    print("║      SOVEREIGN EVENT HANDLER VALIDATOR (REALISTIC)           ║")
    print(f"╚════════════════════════════════════════════════════════════════════╝{COLOR['RESET']}")
    print(f"  Mode Deteksi             :  {COLOR['GREEN']}✅ AST (domain) + Runtime Registry{COLOR['RESET']}")
    print(f"  Normalisasi Nama         :  {COLOR['GREEN']}✅ Hilangkan suffix 'Event' untuk match{COLOR['RESET']}")
    print(f"  Filter Penggunaan        :  {COLOR['GREEN']}✅ Skip __init__.py & tests/{COLOR['RESET']}")
    print(f"  Proteksi Folder          :  {COLOR['GREEN']}✅ Excluded folders diabaikan{COLOR['RESET']}")

    verifier.load_registry_runtime()
    events = verifier.scan_events_ast()
    verifier.classify_events(events)

    total = len(events)
    registered = sum(1 for e in events.values() if e.in_registry)
    used_not_registered = sum(1 for e in events.values() if e.used_outside_domain and not e.in_registry)
    audit_only = total - registered - used_not_registered

    denominator = registered + used_not_registered
    score = (registered / denominator * 100) if denominator > 0 else 100.0

    print(f"  Total Event Domain        :  {total}")
    print(f"  Event Terdaftar           :  {COLOR['GREEN']}{registered}{COLOR['RESET']}")
    print(f"  Event Digunakan (kritis)  :  {COLOR['RED']}{used_not_registered}{COLOR['RESET']}")
    print(f"  Event Audit-only          :  {COLOR['YELLOW']}{audit_only}{COLOR['RESET']}")
    print(f"  📈 Skor Kepatuhan Event   :  {COLOR['CYAN']}{COLOR['BOLD']}{score:.1f}/100{COLOR['RESET']}")
    print("-" * 72)
    print(f"{COLOR['BOLD']}─── DETAIL AUDIT EVENT HANDLER ───{COLOR['RESET']}")

    if used_not_registered > 0:
        print(f"{COLOR['RED']}❌ Event KRITIS (digunakan tapi tidak terdaftar):{COLOR['RESET']}")
        for ev in sorted(events.values(), key=lambda x: x.name):
            if ev.used_outside_domain and not ev.in_registry:
                print(f"  ▪ MISSING_HANDLER: {ev.name} [{ev.file_path}]")
    else:
        print(f"  {COLOR['GREEN']}✅ Semua event yang digunakan sudah terdaftar.{COLOR['RESET']}")

    if audit_only > 0:
        print(f"{COLOR['YELLOW']}⚠️ Event audit-only (tidak wajib handler):{COLOR['RESET']}")
        for ev in sorted(events.values(), key=lambda x: x.name):
            if not ev.used_outside_domain and not ev.in_registry:
                print(f"  ▪ AUDIT_ONLY: {ev.name} [{ev.file_path}]")

    print("-" * 72)
    print(f" ⏱️ Waktu Audit: {time.monotonic() - start_time:.3f} detik")

    if args.json:
        payload = {
            "total_events": total,
            "registered": registered,
            "used_not_registered": used_not_registered,
            "audit_only": audit_only,
            "score": round(score, 1),
            "critical_missing": [
                {"event": ev.name, "file": ev.file_path}
                for ev in events.values() if ev.used_outside_domain and not ev.in_registry
            ],
            "audit_only_events": [
                {"event": ev.name, "file": ev.file_path}
                for ev in events.values() if not ev.used_outside_domain and not ev.in_registry
            ]
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"{COLOR['GREEN']}✅ Laporan diekspor ke {args.json}{COLOR['RESET']}")

    sys.exit(0 if used_not_registered == 0 else 1)

if __name__ == "__main__":
    main()
