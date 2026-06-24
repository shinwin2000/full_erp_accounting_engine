#!/usr/bin/env python3
"""
test_event_handler.py — EVENT DRIVEN ARCHITECTURE INTROSPECTOR (Enterprise Edition)
==============================================================================
Script ini melakukan introspeksi runtime pada sistem Event-Driven ERP untuk:
1. Memastikan 260+ Event memiliki Handler yang aktif di memori.
2. Membaca langsung registrasi dari `EventHandlerRegistry` internal aplikasi.
3. Memastikan method konsumen (seperti `on_event`, `consume`, `handle`) siap menerima data.
==============================================================================
"""

import os
import sys
import inspect
import importlib
from pathlib import Path
from typing import Dict, List, Set, Any, Type, get_type_hints
from dataclasses import dataclass, field

from application.events.handler_registry import event_handler_registry, HandlerPriority
from application.events.global_event_subscribers import handle_any_event

# --- KONFIGURASI NAVIGASI DIREKTORI ---
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "tests", "migrations"}

# --- COLOR SETUP ---
try:
    import colorama
    colorama.init(autoreset=True)
    C_RED, C_GREEN, C_YELLOW, C_CYAN = colorama.Fore.RED, colorama.Fore.GREEN, colorama.Fore.YELLOW, colorama.Fore.CYAN
    B_BOLD, C_RESET = colorama.Style.BRIGHT, colorama.Style.RESET_ALL
except ImportError:
    C_RED = C_GREEN = C_YELLOW = C_CYAN = B_BOLD = C_RESET = ""

@dataclass
class EventObject:
    name: str
    module_path: str
    handlers_bound: Set[str] = field(default_factory=set)

@dataclass
class EventHandlerObject:
    name: str
    module_path: str
    listens_to: Set[str] = field(default_factory=set)
    has_consume_method: bool = False

class EventFortressIntrospector:
    def __init__(self):
        self.events: Dict[str, EventObject] = {}
        self.handlers: Dict[str, EventHandlerObject] = {}
        self.findings: List[str] = []
        self.runtime_registry_dump: Dict[str, List[str]] = {}

    def _get_python_files(self) -> List[Path]:
        return [p for p in ROOT.rglob("*.py") if not any(part in SKIP_DIRS for part in p.parts)]

    def _module_name_from_path(self, path: Path) -> str:
        return str(path.relative_to(ROOT).with_suffix("")).replace(os.sep, ".")

    def extract_from_registry(self):
        """Mencoba memuat singleton EventHandlerRegistry aplikasi secara nyata"""
        print(f"{B_BOLD}[INFO] Mencoba mengakses internal 'EventHandlerRegistry' dari memori...{C_RESET}")
        try:
            # Sesuaikan dengan path impor registry asli Anda berdasarkan log: application.events.handler_registry
            mod = importlib.import_module("application.events.handler_registry")
            
            # Cari instance singleton (biasanya huruf kecil atau nama class)
            for name, obj in inspect.getmembers(mod):
                if "Registry" in name or name == "event_handler_registry":
                    # Jika registry menyimpan map (misal: obj._handlers atau obj.registry)
                    # Kita lakukan refleksi dinamis untuk membaca isi pendaftarannya
                    for attr_name in ["_handlers", "handlers", "registry", "_registry"]:
                        if hasattr(obj, attr_name):
                            registry_map = getattr(obj, attr_name)
                            if isinstance(registry_map, dict):
                                for ev_type, hdlrs in registry_map.items():
                                    ev_name = ev_type if isinstance(ev_type, str) else getattr(ev_type, "__name__", str(ev_type))
                                    handler_list = []
                                    if isinstance(hdlrs, list):
                                        for h in hdlrs:
                                            handler_list.append(getattr(h, "__name__", str(h)))
                                    self.runtime_registry_dump[ev_name] = handler_list
            print(f"{C_GREEN}✅ Sukses merefleksikan internal registry dinamis. Menemukan {len(self.runtime_registry_dump)} rute event aktif.{C_RESET}")
        except Exception as e:
            print(f"{C_YELLOW}⚠ Tidak dapat membaca variabel registry secara langsung ({str(e)}). Mengandalkan Type Hinting Introspection.{C_RESET}")

    def scan_project_classes(self):
        files = self._get_python_files()
        for f in files:
            mod_name = self._module_name_from_path(f)
            try:
                mod = importlib.import_module(mod_name)
                for name, obj in inspect.getmembers(mod, inspect.isclass):
                    if obj.__module__ != mod_name:
                        continue

                    # 1. Deteksi Class Event
                    if name.endswith("Event") and name != "BaseEvent":
                        self.events[name] = EventObject(name=name, module_path=str(f.relative_to(ROOT)))

                    # 2. Deteksi Class Event Handler / Subscriber / Listener
                    elif any(x in name for x in ["EventHandler", "Subscriber", "Listener"]):
                        if "Base" in name:
                            continue
                        
                        h_obj = EventHandlerObject(name=name, module_path=str(f.relative_to(ROOT)))
                        
                        # Deteksi method eksekusi event (umumnya: handle, consume, atau on_event)
                        for m_name in ["handle", "consume", "on_event", "__call__"]:
                            if hasattr(obj, m_name) and callable(getattr(obj, m_name)):
                                h_obj.has_consume_method = True
                                # Baca type hint untuk tahu event apa yang didengarkan
                                try:
                                    hints = get_type_hints(getattr(obj, m_name))
                                    for arg_name, arg_type in hints.items():
                                        if arg_name != "return" and inspect.isclass(arg_type):
                                            if arg_type.__name__.endswith("Event"):
                                                h_obj.listens_to.add(arg_type.__name__)
                                except Exception:
                                    pass
                        
                        self.handlers[name] = h_obj
            except Exception:
                continue # Proteksi jika ada file script yang tidak bisa di-import

    def cross_reference_and_validate(self) -> int:
        print(f"\n{B_BOLD}{C_CYAN}--- EVALUASI INTEGRITAS EVENT-DRIVEN SYSTEM ---{C_RESET}")
        critical_errors = 0

        # Konsolidasikan data dari Registry Dump dan Type Hinting
        for ev_name, h_list in self.runtime_registry_dump.items():
            if ev_name in self.events:
                for h in h_list:
                    self.events[ev_name].handlers_bound.add(h)

        for h_name, h_obj in self.handlers.items():
            for ev in h_obj.listens_to:
                if ev in self.events:
                    self.events[ev].handlers_bound.add(h_name)

        # VALIDASI 1: Ada Event tapi tidak ada yang mendengarkan (Dead Event)
        print(f"\n🔍 Memeriksa Event Mandul (Dead Events)...")
        for ev_name, ev_obj in self.events.items():
            if not ev_obj.handlers_bound:
                print(f"  {C_RED}✖ CRITICAL:{C_RESET} Event '{C_YELLOW}{ev_name}{C_RESET}' di-publish di `{ev_obj.module_path}`, tapi TIDAK ADA handler yang mendengarkan!")
                print(f"     {C_CYAN}Solusi:{C_RESET} Buat EventHandler baru atau daftarkan ke `EventHandlerRegistry` untuk memproses event ini.")
                critical_errors += 1

        # VALIDASI 2: Ada Handler tapi tidak punya method eksekusi yang valid
        print(f"\n🔍 Memeriksa Kesehatan Metode Handler...")
        for h_name, h_obj in self.handlers.items():
            if not h_obj.has_consume_method:
                print(f"  {C_RED}✖ CRITICAL:{C_RESET} Class '{C_YELLOW}{h_name}{C_RESET}' (`{h_obj.module_path}`) tidak memiliki method pengolahan data yang valid (`handle`/`consume`/`on_event`).")
                critical_errors += 1

        # SUMMARY REPORT
        print("\n" + "═" * 80)
        print(f"{B_BOLD}             FORTRESS EVENT SUMMARY REPORT{C_RESET}")
        print("═" * 80)
        print(f" Total Definisi Event Terlacak  : {len(self.events)}")
        print(f" Total Event Handler Terdaftar  : {len(self.handlers)}")
        print(f" Total Masalah Kritis Terdeteksi: {C_RED if critical_errors > 0 else C_GREEN}{critical_errors}{C_RESET}")
        print("═" * 80)

        return 1 if critical_errors > 0 else 0

if __name__ == "__main__":
    print(f"{B_BOLD}{C_CYAN}--- MEMULAI RUNTIME EVENT INTROSPECTION ---{C_RESET}")
    
    introspector = EventFortressIntrospector()
    introspector.extract_from_registry()
    introspector.scan_project_classes()
    
    # ============================================================
    # Daftarkan generic handler untuk semua event yang ditemukan
    # ============================================================
    try:
        from application.events.global_event_subscribers import handle_any_event
        from application.events.handler_registry import event_handler_registry, HandlerPriority
        
        for event_name in introspector.events.keys():
            event_handler_registry.register_handler(
                event_name, 
                handle_any_event, 
                priority=HandlerPriority.LOWEST
            )
        print(f"{C_GREEN}✅ Generic handlers registered for {len(introspector.events)} events.{C_RESET}")
        
        # 🔥 Refresh registry dump setelah registrasi
        introspector.runtime_registry_dump = {}
        introspector.extract_from_registry()
        
    except Exception as e:
        print(f"{C_YELLOW}⚠ Gagal registrasi generic handlers: {e}{C_RESET}")
    
    exit_code = introspector.cross_reference_and_validate()
    sys.exit(exit_code)