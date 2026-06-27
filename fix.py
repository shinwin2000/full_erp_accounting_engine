#!/usr/bin/env python3
"""
generate_all_event_handlers.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Membuat application/events/all_event_handlers.py dengan handler untuk setiap event.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOMAIN_DIR = ROOT / "domain"
OUTPUT_FILE = ROOT / "application" / "events" / "all_event_handlers.py"
SKIP_DIRS = {"__pycache__", ".git", ".venv", "tests", "migrations"}

def find_event_classes() -> dict[str, str]:
    """Scan domain/ dan kembalikan mapping nama_event -> path relatif (tanpa backslash)."""
    events = {}
    for py_file in DOMAIN_DIR.rglob("*.py"):
        if any(part in SKIP_DIRS for part in py_file.parts):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    if node.name.endswith("Event") and node.name != "BaseEvent":
                        events[node.name] = py_file.relative_to(ROOT).as_posix()
        except Exception:
            continue
    return events

def generate_handlers_file(events: dict[str, str]) -> str:
    """Buat konten file all_event_handlers.py."""
    lines = []
    lines.append('"""')
    lines.append('ALL EVENT HANDLERS - AUTO-GENERATED')
    lines.append('=====================================')
    lines.append(f'Total events: {len(events)}')
    lines.append('Setiap event memiliki handler sendiri (spesifik).')
    lines.append('Handler saat ini hanya mencatat log; Anda dapat menambahkan logika bisnis.')
    lines.append('"""')
    lines.append('')
    lines.append('import logging')
    lines.append('from application.events.handler_registry import register_handler, HandlerPriority, event_handler_registry')
    lines.append('from application.events.publisher_application import EventEnvelope')
    lines.append('')
    lines.append('logger = logging.getLogger("event_handlers")')
    lines.append('')
    lines.append('')
    lines.append('# ============================================================================')
    lines.append('# HANDLER FUNCTIONS')
    lines.append('# ============================================================================')
    lines.append('')

    # Buat fungsi handler untuk setiap event
    for event_name in sorted(events.keys()):
        func_name = f"handle_{event_name}"
        lines.append(f'async def {func_name}(envelope: EventEnvelope) -> None:')
        lines.append(f'    """Handler untuk {event_name}."""')
        lines.append(f'    logger.info(f"{event_name} diterima: {{envelope.event}}")')
        lines.append('')
        lines.append('')

    lines.append('# ============================================================================')
    lines.append('# REGISTRATION')
    lines.append('# ============================================================================')
    lines.append('')
    lines.append('def register_all_handlers(registry=None):')
    lines.append('    """Daftarkan semua handler ke registry yang diberikan. Jika registry None, gunakan singleton."""')
    lines.append('    if registry is None:')
    lines.append('        registry = event_handler_registry')
    lines.append('    handlers = {')
    for event_name in sorted(events.keys()):
        lines.append(f'        "{event_name}": handle_{event_name},')
    lines.append('    }')
    lines.append('    for event_type, handler_func in handlers.items():')
    lines.append('        registry.register_handler(event_type, handler_func, priority=HandlerPriority.NORMAL)')
    lines.append('')
    lines.append('')
    lines.append('# ============================================================================')
    lines.append('# AUTO-REGISTER (saat modul diimpor)')
    lines.append('# ============================================================================')
    lines.append('try:')
    lines.append('    register_all_handlers()')
    lines.append('    logger.info(f"Registered {len(events)} event handlers.")')
    lines.append('except Exception as e:')
    lines.append('    logger.warning(f"Auto-registration failed: {e}")')
    lines.append('')
    lines.append('# ============================================================================')
    lines.append('# END')
    lines.append('# ============================================================================')

    return "\n".join(lines)

def main():
    print(f"Memindai event di {DOMAIN_DIR}...")
    events = find_event_classes()
    if not events:
        print("Tidak ditemukan event. Periksa folder domain.")
        sys.exit(1)
    print(f"Ditemukan {len(events)} event.")
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    content = generate_handlers_file(events)
    OUTPUT_FILE.write_text(content, encoding="utf-8")
    print(f"File berhasil dibuat: {OUTPUT_FILE}")
    print(f"Total {len(events)} handler ditulis.")

if __name__ == "__main__":
    main()
