#!/usr/bin/env python3
"""
test_cqrs_handler.py — CQRS RUNTIME INTROSPECTOR (v2.1 - Enterprise Edition)
==============================================================================
Script ini memuat proyek secara riil ke dalam memori (Runtime Reflection)
untuk mengekstrak Command, Query, dan Handler berdasarkan:
1. Type Hinting pada method `handle` atau `__call__`
2. MRO (Method Resolution Order) & Inheritance
3. Fallback ke Abstract Syntax Tree (AST) jika modul gagal di-load (misal: butuh DB).
4. **NEW**: Membaca registri handler runtime dari CommandHandlerRegistry dan QueryHandlerRegistry
   (jika tersedia) untuk mendeteksi hubungan yang terdaftar secara dinamis.
==============================================================================
"""

import os
import sys
import ast
import json
import inspect
import importlib
import traceback
from pathlib import Path
from typing import Dict, List, Set, Type, Any, Optional, get_type_hints
from dataclasses import dataclass, field

# --- KONFIGURASI NAVIGASI DIREKTORI ---
ROOT = Path(__file__).resolve().parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SKIP_DIRS = {
    "__pycache__", ".mypy_cache", ".pytest_cache", ".git", ".venv", "venv",
    "node_modules", "site-packages", "dist-packages", "tests", "migrations",
    "scripts", "alembic", "docs"
}

IGNORE_BASES = {"BaseCommand", "BaseQuery", "Command", "Query"}

# --- COLOR SETUP ---
try:
    import colorama
    colorama.init(autoreset=True)
    C_RED, C_GREEN, C_YELLOW, C_CYAN = colorama.Fore.RED, colorama.Fore.GREEN, colorama.Fore.YELLOW, colorama.Fore.CYAN
    B_BOLD, C_RESET = colorama.Style.BRIGHT, colorama.Style.RESET_ALL
except ImportError:
    C_RED = C_GREEN = C_YELLOW = C_CYAN = B_BOLD = C_RESET = ""

# --- DATA MODELS ---
@dataclass
class CQRSObject:
    name: str
    module_path: str
    is_command: bool = False
    is_query: bool = False
    is_handler: bool = False
    linked_commands: Set[str] = field(default_factory=set) # Untuk Handler: Command apa saja yang dia tangani
    has_handle_method: bool = False
    source_type: str = "RUNTIME" # RUNTIME atau AST

@dataclass
class AuditFinding:
    severity: str
    target: str
    file_path: str
    message: str
    recommendation: str

class CQRSIntrospector:
    def __init__(self):
        self.commands_queries: Dict[str, CQRSObject] = {}
        self.handlers: Dict[str, CQRSObject] = {}
        self.load_errors: List[str] = []
        self.findings: List[AuditFinding] = []
        self._runtime_registry_handlers: Dict[str, List[str]] = {}  # command_name -> list of handler_names

    def _get_python_files(self) -> List[Path]:
        py_files = []
        for p in ROOT.rglob("*.py"):
            if not any(part in SKIP_DIRS for part in p.parts) and not p.name.startswith(("test_", "conftest")):
                py_files.append(p)
        return py_files

    def _module_name_from_path(self, path: Path) -> str:
        rel_path = path.relative_to(ROOT)
        return str(rel_path.with_suffix("")).replace(os.sep, ".")

    # ==========================================
    # ENGINE 1: RUNTIME REFLECTION (REAL LOAD)
    # ==========================================
    def introspect_runtime(self, module_name: str, file_path: str):
        try:
            # Load modul ke memori secara nyata
            mod = importlib.import_module(module_name)

            # Iterasi semua class di dalam modul tersebut
            for name, obj in inspect.getmembers(mod, inspect.isclass):
                # Pastikan class berasal dari modul ini (bukan sekadar hasil import)
                if obj.__module__ != module_name:
                    continue

                # Abaikan class exception/error
                if issubclass(obj, BaseException):
                    continue

                is_cmd = name.endswith("Command") and name not in IGNORE_BASES
                is_qry = name.endswith("Query") and name not in IGNORE_BASES
                is_hdlr = name.endswith("Handler") or name.endswith("UseCase")

                if not (is_cmd or is_qry or is_hdlr):
                    continue

                cqrs_obj = CQRSObject(
                    name=name,
                    module_path=file_path,
                    is_command=is_cmd,
                    is_query=is_qry,
                    is_handler=is_hdlr,
                    source_type="RUNTIME"
                )

                if is_hdlr:
                    self._analyze_handler_signature(obj, cqrs_obj)
                    self.handlers[name] = cqrs_obj
                else:
                    self.commands_queries[name] = cqrs_obj

            return True
        except Exception as e:
            # Gagal load (mungkin butuh Env Vars, DB, dll). Fallback ke AST.
            return False

    def _analyze_handler_signature(self, cls_obj: Type, cqrs_obj: CQRSObject):
        """Membaca Type Hint dari memori untuk mengetahui Command apa yang ditangani."""
        target_method = None
        if hasattr(cls_obj, "handle") and callable(getattr(cls_obj, "handle")):
            target_method = getattr(cls_obj, "handle")
            cqrs_obj.has_handle_method = True
        elif hasattr(cls_obj, "__call__") and callable(getattr(cls_obj, "__call__")):
            target_method = getattr(cls_obj, "__call__")
            cqrs_obj.has_handle_method = True

        if target_method:
            try:
                # Membaca type hints (misal: def handle(self, command: PostJournalEntryCommand))
                hints = get_type_hints(target_method)
                for arg_name, arg_type in hints.items():
                    if arg_name == "return":
                        continue
                    # Jika type hint-nya adalah class nyata
                    if inspect.isclass(arg_type):
                        type_name = arg_type.__name__
                        if type_name.endswith("Command") or type_name.endswith("Query"):
                            cqrs_obj.linked_commands.add(type_name)
            except Exception:
                pass # Terkadang type hint tidak bisa di-resolve saat runtime

    # ==========================================
    # ENGINE 2: AST FALLBACK (STATIC SCAN)
    # ==========================================
    def introspect_ast(self, path: Path):
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(path))
            rel_path = str(path.relative_to(ROOT))

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
                    if any("Exception" in b or "Error" in b for b in bases):
                        continue

                    name = node.name
                    is_cmd = name.endswith("Command") and name not in IGNORE_BASES
                    is_qry = name.endswith("Query") and name not in IGNORE_BASES
                    is_hdlr = name.endswith("Handler") or name.endswith("UseCase")

                    if not (is_cmd or is_qry or is_hdlr):
                        continue

                    # Jangan timpa jika sudah ada versi RUNTIME yang lebih akurat
                    if name in self.commands_queries or name in self.handlers:
                        continue

                    cqrs_obj = CQRSObject(
                        name=name,
                        module_path=rel_path,
                        is_command=is_cmd,
                        is_query=is_qry,
                        is_handler=is_hdlr,
                        source_type="AST_FALLBACK"
                    )

                    if is_hdlr:
                        # Deteksi method via AST
                        for item in node.body:
                            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                if item.name in ("handle", "__call__"):
                                    cqrs_obj.has_handle_method = True
                                    # Deteksi argumen type hint dari teks AST
                                    for arg in item.args.args:
                                        if arg.annotation and isinstance(arg.annotation, ast.Name):
                                            arg_type = arg.annotation.id
                                            if arg_type.endswith("Command") or arg_type.endswith("Query"):
                                                cqrs_obj.linked_commands.add(arg_type)
                        self.handlers[name] = cqrs_obj
                    else:
                        self.commands_queries[name] = cqrs_obj

        except Exception as e:
            self.load_errors.append(f"{path.name} -> AST Parse Error: {str(e)}")

    # ==========================================
    # NEW: READ RUNTIME REGISTRY
    # ==========================================
    def _read_runtime_registry(self):
        """Mencoba mengakses CommandHandlerRegistry dan QueryHandlerRegistry secara langsung."""
        try:
            from application.commands_cqrs.command_handler_registry import CommandHandlerRegistry
            cmd_registry = CommandHandlerRegistry.get_instance()
            # Asumsikan ada atribut _handlers yang berisi mapping
            if hasattr(cmd_registry, '_handlers'):
                for cmd_name, handler_instances in cmd_registry._handlers.items():
                    # handler_instances bisa berupa list atau single
                    if not isinstance(handler_instances, list):
                        handler_instances = [handler_instances]
                    for h in handler_instances:
                        if hasattr(h, '__name__'):
                            handler_name = h.__name__
                        elif hasattr(h, '__class__'):
                            handler_name = h.__class__.__name__
                        else:
                            handler_name = str(h)
                        self._runtime_registry_handlers.setdefault(cmd_name, []).append(handler_name)
            logger.debug(f"Loaded {len(self._runtime_registry_handlers)} command registrations from runtime")
        except Exception as e:
            logger.debug(f"Could not read CommandHandlerRegistry: {e}")

        try:
            from application.commands_cqrs.query_handler_registry import QueryHandlerRegistry
            qry_registry = QueryHandlerRegistry.get_instance()
            if hasattr(qry_registry, '_handlers'):
                for qry_name, handler_instances in qry_registry._handlers.items():
                    if not isinstance(handler_instances, list):
                        handler_instances = [handler_instances]
                    for h in handler_instances:
                        if hasattr(h, '__name__'):
                            handler_name = h.__name__
                        elif hasattr(h, '__class__'):
                            handler_name = h.__class__.__name__
                        else:
                            handler_name = str(h)
                        self._runtime_registry_handlers.setdefault(qry_name, []).append(handler_name)
            logger.debug(f"Loaded {len(self._runtime_registry_handlers)} query registrations from runtime")
        except Exception as e:
            logger.debug(f"Could not read QueryHandlerRegistry: {e}")

    # ==========================================
    # LOGIC: RECONCILIATION & VALIDATION
    # ==========================================
    def run_scan(self):
        print(f"{B_BOLD}{C_CYAN}--- MEMULAI RUNTIME INTROSPECTION & HYBRID SCAN ---{C_RESET}")
        files = self._get_python_files()
        runtime_success = 0
        ast_fallback = 0

        for f in files:
            mod_name = self._module_name_from_path(f)
            rel_path = str(f.relative_to(ROOT))

            # Coba load secara real
            if self.introspect_runtime(mod_name, rel_path):
                runtime_success += 1
            else:
                # Jika meledak, fallback ke AST (membaca teks murni)
                self.introspect_ast(f)
                ast_fallback += 1

        # Baca registri runtime setelah semua modul dimuat
        self._read_runtime_registry()

        print(f"✅ Modul dimuat sempurna (Runtime) : {runtime_success} file")
        print(f"⚠️  Modul pakai AST (Blocked)       : {ast_fallback} file")

    def evaluate_architecture(self) -> int:
        print(f"\n{B_BOLD}{C_CYAN}--- EVALUASI ARSITEKTUR CQRS ---{C_RESET}")

        # 1. Bangun Peta Handler -> Command (Reverse Indexing)
        # Pertama, coba dari runtime registry terlebih dahulu
        command_to_handler_map: Dict[str, List[str]] = {}

        # Copy dari runtime registry
        for cmd_name, handler_names in self._runtime_registry_handlers.items():
            command_to_handler_map.setdefault(cmd_name, []).extend(handler_names)

        # Kemudian tambahkan dari type hinting (untuk hubungan yang tidak terdaftar di registry)
        for h_name, h_obj in self.handlers.items():
            for cmd in h_obj.linked_commands:
                if cmd not in command_to_handler_map:
                    command_to_handler_map[cmd] = []
                if h_name not in command_to_handler_map[cmd]:
                    command_to_handler_map[cmd].append(h_name)

        # 2. Validasi Command/Query
        for cq_name, cq_obj in self.commands_queries.items():
            assigned_handlers = command_to_handler_map.get(cq_name, [])

            # Jika tidak ada link lewat registry atau type hint, fallback ke Name Convention
            if not assigned_handlers:
                base = cq_name.replace("Command", "").replace("Query", "")
                expected = [f"{base}Handler", f"{cq_name}Handler", f"{base}UseCase"]
                for exp in expected:
                    if exp in self.handlers:
                        assigned_handlers.append(exp)
                        # Patching the memory link
                        self.handlers[exp].linked_commands.add(cq_name)

            if not assigned_handlers:
                self.findings.append(AuditFinding(
                    severity="CRITICAL",
                    target=cq_name,
                    file_path=cq_obj.module_path,
                    message="Command/Query tidak memiliki handler yang terkait.",
                    recommendation="Buat Handler dan beri type hint: `def handle(self, command: " + cq_name + ")`"
                ))
            else:
                # Periksa apakah handler yang ditunjuk punya method handle
                for h in assigned_handlers:
                    if h in self.handlers:
                        h_obj = self.handlers[h]
                        if not h_obj.has_handle_method:
                            self.findings.append(AuditFinding(
                                severity="CRITICAL",
                                target=h_obj.name,
                                file_path=h_obj.module_path,
                                message=f"Handler terkait ({h_obj.name}) TIDAK punya method 'handle' atau '__call__'.",
                                recommendation="Tambahkan method `async def handle(self, command)` di dalam class tersebut."
                            ))

        # 3. Deteksi Handler Orphan (Tidak terikat ke Command apapun)
        for h_name, h_obj in self.handlers.items():
            if not h_obj.linked_commands and h_obj.name not in IGNORE_BASES and "Base" not in h_obj.name:
                # Cek apakah terdaftar di runtime registry sebagai handler untuk suatu command
                is_registered = False
                for cmd_list in command_to_handler_map.values():
                    if h_name in cmd_list:
                        is_registered = True
                        break
                if not is_registered:
                    self.findings.append(AuditFinding(
                        severity="WARNING",
                        target=h_name,
                        file_path=h_obj.module_path,
                        message="Handler tidak terikat ke Command/Query manapun secara definitif.",
                        recommendation="Gunakan Type Hint pada argumen handler. Misal: `def handle(self, req: MyCommand)`"
                    ))

        # Cetak Hasil
        criticals = [f for f in self.findings if f.severity == "CRITICAL"]
        warnings = [f for f in self.findings if f.severity == "WARNING"]

        if criticals:
            print(f"\n{C_RED}{B_BOLD}🔴 CRITICAL ISSUES ({len(criticals)}){C_RESET}")
            for f in criticals:
                print(f"  {C_RED}✖{C_RESET} {f.file_path} -> {C_YELLOW}{f.target}{C_RESET}")
                print(f"      Kesalahan : {f.message}")
                print(f"      Solusi    : {f.recommendation}\n")

        if warnings:
            print(f"\n{C_YELLOW}{B_BOLD}⚠️  WARNINGS ({len(warnings)}){C_RESET}")
            for f in warnings[:10]:
                print(f"  {C_YELLOW}⚠{C_RESET} {f.file_path} -> {f.target}")
                print(f"      {f.message}")
            if len(warnings) > 10:
                print(f"      ... dan {len(warnings)-10} peringatan lainnya.\n")

        # Cetak Ringkasan
        total_cq = len(self.commands_queries)
        valid_cq = total_cq - len([c for c in criticals if "tidak memiliki handler" in c.message])

        print("═" * 80)
        print(f"{B_BOLD}             FORTRESS CQRS SUMMARY REPORT{C_RESET}")
        print("═" * 80)
        print(f" Total Command/Query Ditemukan : {total_cq}")
        print(f" Total Handler Ditemukan       : {len(self.handlers)}")
        print(f" Valid Command/Query Tersambung: {C_GREEN if valid_cq == total_cq else C_YELLOW}{valid_cq}{C_RESET}")
        print(f" Total Isu Kritis              : {C_RED if criticals else C_GREEN}{len(criticals)}{C_RESET}")
        print("═" * 80)

        return 1 if criticals else 0


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger(__name__)

    introspector = CQRSIntrospector()
    introspector.run_scan()
    exit_code = introspector.evaluate_architecture()
    sys.exit(exit_code)