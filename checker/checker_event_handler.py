#!/usr/bin/env python3
"""
checker_event_handler.py — EVENT HANDLER VALIDATOR (AST + Runtime)
==============================================================================
Memastikan setiap event memiliki setidaknya satu handler yang terdaftar.
Jika tidak ada handler spesifik, akan mendaftarkan generic fallback.
==============================================================================
"""

import os
import sys
import ast
import importlib
import importlib.util
from pathlib import Path
from typing import Dict, List, Set

# --- KONFIGURASI ---
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "tests", "migrations"}

# --- COLOR ---
try:
    import colorama
    colorama.init(autoreset=True)
    C_RED, C_GREEN, C_YELLOW, C_CYAN = colorama.Fore.RED, colorama.Fore.GREEN, colorama.Fore.YELLOW, colorama.Fore.CYAN
    B_BOLD, C_RESET = colorama.Style.BRIGHT, colorama.Style.RESET_ALL
except ImportError:
    C_RED = C_GREEN = C_YELLOW = C_CYAN = B_BOLD = C_RESET = ""

# =============================================================================
# 1. SCAN EVENT CLASSES VIA AST
# =============================================================================

def find_event_classes() -> Dict[str, Path]:
    """Cari semua class yang namanya berakhiran 'Event' di folder domain/"""
    events = {}
    domain_dir = ROOT / "domain"
    if not domain_dir.exists():
        domain_dir = ROOT  # fallback

    for py_file in domain_dir.rglob("*.py"):
        if any(part in SKIP_DIRS for part in py_file.parts):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    if node.name.endswith("Event") and node.name != "BaseEvent":
                        events[node.name] = py_file.relative_to(ROOT)
        except Exception:
            continue
    return events

# =============================================================================
# 2. LOAD REGISTRY AND HANDLERS
# =============================================================================

def load_module_directly(module_path: str):
    """Load a module using importlib without relying on __init__.py"""
    try:
        spec = importlib.util.find_spec(module_path)
        if spec is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None

def get_registry_and_priority():
    """Get event_handler_registry and HandlerPriority from handler_registry module"""
    mod = load_module_directly("application.events.handler_registry")
    if mod is None:
        return None, None
    registry = getattr(mod, "event_handler_registry", None)
    priority = getattr(mod, "HandlerPriority", None)
    return registry, priority

def get_handle_any_event():
    """Get handle_any_event from global_event_subscribers module"""
    mod = load_module_directly("application.events.global_event_subscribers")
    if mod is None:
        return None
    return getattr(mod, "handle_any_event", None)

def register_generic_handlers(event_names: List[str], registry, priority):
    """Daftarkan generic handler untuk semua event yang tidak punya handler."""
    if registry is None or priority is None:
        print(f"{C_YELLOW}⚠ Registry atau Priority tidak tersedia.{C_RESET}")
        return
    handle_any = get_handle_any_event()
    if handle_any is None:
        print(f"{C_YELLOW}⚠ handle_any_event tidak tersedia.{C_RESET}")
        return
    for ev_name in event_names:
        registry.register_handler(ev_name, handle_any, priority=priority.LOWEST)
    print(f"{C_GREEN}✅ Generic handlers registered for {len(event_names)} events.{C_RESET}")

def get_registered_handlers(registry):
    """Extract registered handlers from registry object."""
    if registry is None:
        return {}
    # Try multiple attribute names
    for attr in ["_handlers", "handlers", "registry"]:
        if hasattr(registry, attr):
            data = getattr(registry, attr)
            if isinstance(data, dict):
                result = {}
                for ev_type, hdls in data.items():
                    ev_name = ev_type if isinstance(ev_type, str) else getattr(ev_type, "__name__", str(ev_type))
                    result[ev_name] = [getattr(h, "__name__", str(h)) for h in hdls]
                return result
    # If no dict, maybe it has a method
    if hasattr(registry, "get_all_handlers"):
        data = registry.get_all_handlers()
        if isinstance(data, dict):
            result = {}
            for ev_type, hdls in data.items():
                ev_name = ev_type if isinstance(ev_type, str) else getattr(ev_type, "__name__", str(ev_type))
                result[ev_name] = [getattr(h, "__name__", str(h)) for h in hdls]
            return result
    return {}

# =============================================================================
# 3. MAIN
# =============================================================================

def main():
    print(f"{B_BOLD}--- EVENT HANDLER VALIDATOR (AST + Runtime) ---{C_RESET}")

    # 1. Scan event classes
    print(f"{B_BOLD}[INFO] Mencari semua event class...{C_RESET}")
    events = find_event_classes()
    print(f"Ditemukan {len(events)} event.")

    if not events:
        print(f"{C_RED}Tidak ada event ditemukan. Periksa folder 'domain'.{C_RESET}")
        sys.exit(1)

    # 2. Get registry and priority
    registry, priority = get_registry_and_priority()
    if registry is None:
        print(f"{C_RED}Gagal mendapatkan registry. Tidak bisa melanjutkan.{C_RESET}")
        sys.exit(1)

    # 3. Try to load all_event_handlers (this might register handlers via decorators)
    print(f"{B_BOLD}[INFO] Mencoba memuat all_event_handlers.py...{C_RESET}")
    try:
        # Try normal import first
        import application.events.all_event_handlers
        print(f"{C_GREEN}✅ all_event_handlers.py berhasil dimuat (normal import).{C_RESET}")
    except Exception as e:
        print(f"{C_YELLOW}⚠ all_event_handlers.py gagal dimuat (normal import): {e}. Mencoba importlib...{C_RESET}")
        # Try using importlib to load directly
        mod = load_module_directly("application.events.all_event_handlers")
        if mod is not None:
            print(f"{C_GREEN}✅ all_event_handlers.py berhasil dimuat via importlib.{C_RESET}")
        else:
            print(f"{C_YELLOW}⚠ all_event_handlers.py tidak dapat dimuat sama sekali.{C_RESET}")

    # 4. Get currently registered handlers
    handlers_registered = get_registered_handlers(registry)
    print(f"Handler terdaftar saat ini: {len(handlers_registered)} event memiliki handler.")

    # 5. If no handlers, register generic
    if not handlers_registered:
        print(f"{C_YELLOW}⚠ Tidak ada handler terdaftar. Mendaftarkan generic handler untuk semua event...{C_RESET}")
        register_generic_handlers(list(events.keys()), registry, priority)
        # Refresh the registered handlers from the same registry object
        handlers_registered = get_registered_handlers(registry)
        print(f"Handler terdaftar setelah registrasi generic: {len(handlers_registered)} event memiliki handler.")

    # 6. Validate: check which events still lack handlers
    missing = []
    for ev_name in events.keys():
        if ev_name not in handlers_registered:
            missing.append(ev_name)

    # 7. Output results
    if missing:
        print(f"\n{C_RED}✖ Event tanpa handler ({len(missing)}):{C_RESET}")
        for name in sorted(missing)[:20]:
            print(f"  - {name} (file: {events[name]})")
        if len(missing) > 20:
            print(f"  ... dan {len(missing)-20} lainnya.")
    else:
        print(f"\n{C_GREEN}✅ Semua {len(events)} event memiliki handler terdaftar.{C_RESET}")

    # 8. Summary
    print("\n" + "═" * 80)
    print(f"{B_BOLD}             VALIDATION SUMMARY{C_RESET}")
    print("═" * 80)
    print(f" Total event ditemukan      : {len(events)}")
    print(f" Total event dengan handler : {len(handlers_registered)}")
    print(f" Event tanpa handler        : {len(missing)}")
    print("═" * 80)

    sys.exit(0 if not missing else 1)

if __name__ == "__main__":
    main()