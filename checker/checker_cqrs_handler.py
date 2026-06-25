#!/usr/bin/env python3
"""
Sovereign ERP System - CQRS High-Integrity Architecture & Compliance Engine (Improved)
=======================================================================================
Memvalidasi kepatuhan CQRS dengan deteksi akurat:
- Command/Query berdasarkan inheritance (bukan hanya nama)
- Handler mapping dari registry dan AST
- Mengabaikan DTO/Pydantic model yang kebetulan berakhiran "Query"
- Tidak melakukan import massal yang berbahaya
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import pathlib
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

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
    COLOR = {k: "" for k in COLOR}

IGNORE_BASES = {"BaseCommand", "BaseQuery", "Command", "Query"}
INFRASTRUCTURE_HANDLERS = {
    "WebhookHandler", "CorrelationIdHandler", "SQLAlchemyCQRSQueryHandler",
    "KafkaDeadLetterHandler", "LifecycleHandler", "EventHandler",
    "AxiomViolationHandler", "RollbackHandler", "ConfigFileHandler",
    "ConstitutionExceptionHandler"
}
DTO_FOLDERS = {"dto_objects", "dto", "requests", "responses", "schemas"}

@dataclass
class CQRSObject:
    name: str
    file_path: str
    module_path: str
    is_command: bool = False
    is_query: bool = False
    is_handler: bool = False
    linked_commands: Set[str] = field(default_factory=set)
    has_handle_method: bool = False
    source_type: str = "AST"
    violations: List[str] = field(default_factory=list)

class SovereignCQRSVerifier:
    def __init__(self, root_dir: pathlib.Path):
        self.root_dir = root_dir
        self.skip_dirs = {
            "__pycache__", ".mypy_cache", ".pytest_cache", ".git", ".venv", "venv",
            "node_modules", "site-packages", "dist-packages", "tests", "migrations",
            "scripts", "alembic", "docs", "checker"
        }

    def _get_python_files(self) -> List[pathlib.Path]:
        py_files = []
        for p in self.root_dir.rglob("*.py"):
            if not any(part in self.skip_dirs for part in p.parts) and not p.name.startswith(("test_", "conftest")):
                py_files.append(p)
        return py_files

    def _module_name_from_path(self, path: pathlib.Path) -> str:
        rel = path.relative_to(self.root_dir)
        return str(rel.with_suffix("")).replace(os.sep, ".")

    def _is_dto_folder(self, file_path: pathlib.Path) -> bool:
        """Cek apakah file berada di folder DTO (biasanya berisi request/response models)."""
        parts = file_path.parts
        return any(folder in parts for folder in DTO_FOLDERS)

    def _extract_base_classes(self, node: ast.ClassDef) -> List[str]:
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(base.attr)
            elif isinstance(base, ast.Subscript):  # misal List[BaseQuery]
                if isinstance(base.value, ast.Name):
                    bases.append(base.value.id)
        return bases

    def introspect_ast(self, file_path: pathlib.Path, commands_queries: Dict[str, CQRSObject], handlers: Dict[str, CQRSObject]):
        try:
            src = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=str(file_path))
            rel_path = str(file_path.relative_to(self.root_dir))
            mod_name = self._module_name_from_path(file_path)

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                name = node.name
                bases = self._extract_base_classes(node)

                # Deteksi berdasarkan inheritance, bukan hanya nama
                is_cmd = any(b in ("BaseCommand", "Command") for b in bases) or (name.endswith("Command") and name not in IGNORE_BASES)
                is_qry = any(b in ("BaseQuery", "Query") for b in bases) or (name.endswith("Query") and name not in IGNORE_BASES)

                # Jika class berada di DTO folder, kita abaikan (anggap bukan CQRS)
                if self._is_dto_folder(file_path):
                    is_cmd = False
                    is_qry = False

                # Deteksi Handler
                is_hdlr = name.endswith("Handler") or name.endswith("UseCase")

                if not (is_cmd or is_qry or is_hdlr):
                    continue

                cqrs_obj = CQRSObject(
                    name=name,
                    file_path=rel_path,
                    module_path=mod_name,
                    is_command=is_cmd,
                    is_query=is_qry,
                    is_handler=is_hdlr,
                    source_type="AST"
                )

                if is_hdlr:
                    # Cek method handle/__call__
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in ("handle", "__call__"):
                            cqrs_obj.has_handle_method = True
                            # Ekstrak command/query dari parameter annotation
                            for arg in item.args.args:
                                if arg.annotation:
                                    anno_str = self._extract_annotation_string(arg.annotation)
                                    if anno_str and (anno_str.endswith("Command") or anno_str.endswith("Query")):
                                        cqrs_obj.linked_commands.add(anno_str)
                    handlers[name] = cqrs_obj
                else:
                    commands_queries[name] = cqrs_obj

        except Exception as e:
            # Skip file yang error
            pass

    def _extract_annotation_string(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Str):
            return node.s
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Subscript):
            return self._extract_annotation_string(node.slice)
        return None

    def read_runtime_registries_safe(self, command_to_handler_map: Dict[str, List[str]]):
        """Baca registry dari modul yang sudah diimpor (tanpa import baru)."""
        # Karena kita tidak melakukan import massal, kita hanya membaca dari modul yang sudah ada di sys.modules
        # Jika belum diimpor, kita skip.
        for path, cls_name in [
            ("application.commands_cqrs.command_handler_registry", "CommandHandlerRegistry"),
            ("application.commands_cqrs.query_handler_registry", "QueryHandlerRegistry")
        ]:
            if path in sys.modules:
                try:
                    mod = sys.modules[path]
                    reg_cls = getattr(mod, cls_name, None)
                    if reg_cls and hasattr(reg_cls, "get_instance"):
                        instance = reg_cls.get_instance()
                        if hasattr(instance, "_handlers"):
                            for key, h_list in instance._handlers.items():
                                cmd_name = key.__name__ if hasattr(key, "__name__") else str(key)
                                if not isinstance(h_list, list):
                                    h_list = [h_list]
                                for h in h_list:
                                    h_name = h.__name__ if hasattr(h, "__name__") else (h.__class__.__name__ if hasattr(h, "__class__") else str(h))
                                    if h_name not in command_to_handler_map[cmd_name]:
                                        command_to_handler_map[cmd_name].append(h_name)
                except Exception:
                    pass

    def scan(self) -> Tuple[Dict[str, CQRSObject], Dict[str, CQRSObject], Dict[str, List[str]]]:
        commands_queries: Dict[str, CQRSObject] = {}
        handlers: Dict[str, CQRSObject] = {}
        command_to_handler_map: Dict[str, List[str]] = defaultdict(list)

        files = self._get_python_files()
        for f in files:
            self.introspect_ast(f, commands_queries, handlers)

        # Baca registry dari modul yang sudah diimpor (jika ada)
        self.read_runtime_registries_safe(command_to_handler_map)

        # Resolusi konvensi penamaan untuk handler yang terdeteksi dari AST
        for h_name, h_obj in handlers.items():
            for cmd in h_obj.linked_commands:
                if h_name not in command_to_handler_map[cmd]:
                    command_to_handler_map[cmd].append(h_name)

        # Tambahan: coba cari handler berdasarkan naming convention
        for cq_name, cq_obj in commands_queries.items():
            if not command_to_handler_map.get(cq_name):
                base = cq_name.replace("Command", "").replace("Query", "")
                for candidate in [f"{base}Handler", f"{cq_name}Handler", f"{base}UseCase"]:
                    if candidate in handlers:
                        command_to_handler_map[cq_name].append(candidate)
                        handlers[candidate].linked_commands.add(cq_name)

        return commands_queries, handlers, dict(command_to_handler_map)

def main():
    parser = argparse.ArgumentParser(description="Sovereign CQRS Compliance Engine (Improved)")
    parser.add_argument("--json", metavar="FILE", help="Ekspor laporan ke JSON")
    args = parser.parse_args()

    start_time = time.monotonic()
    root_dir = pathlib.Path.cwd()
    verifier = SovereignCQRSVerifier(root_dir)

    print(f"{COLOR['BOLD']}{COLOR['CYAN']}╔════════════════════════════════════════════════════════════════════╗")
    print(f"║           SOVEREIGN HIGH-INTEGRITY CQRS COMPLIANCE ENGINE          ║")
    print(f"╚════════════════════════════════════════════════════════════════════╝{COLOR['RESET']}")
    print(f"  Mode Deteksi             :  {COLOR['GREEN']}✅ AST + Registry (tanpa import berbahaya){COLOR['RESET']}")

    commands_queries, handlers, mapping = verifier.scan()

    total_commands = sum(1 for c in commands_queries.values() if c.is_command)
    total_queries = sum(1 for q in commands_queries.values() if q.is_query)

    cmd_without_handler = 0
    qry_without_handler = 0
    all_violations = []

    for cq_name, cq_obj in commands_queries.items():
        assigned = mapping.get(cq_name, [])
        if not assigned:
            type_label = "Query" if cq_obj.is_query else "Command"
            all_violations.append(f"MISSING_HANDLER: {type_label} '{cq_name}' tidak memiliki handler terdaftar. [{cq_obj.file_path}]")
            if cq_obj.is_query:
                qry_without_handler += 1
            else:
                cmd_without_handler += 1
        else:
            # Cek apakah handler memiliki method handle
            for h in assigned:
                if h in handlers and not handlers[h].has_handle_method:
                    all_violations.append(f"CRITICAL_FAULT: Handler '{h}' untuk '{cq_name}' tidak memiliki method 'handle'. [{handlers[h].file_path}]")

    # Cek orphan handler (handler yang tidak terikat ke command/query apapun)
    for h_name, h_obj in handlers.items():
        if h_name in INFRASTRUCTURE_HANDLERS or "Base" in h_name:
            continue
        is_bound = any(h_name in h_list for h_list in mapping.values())
        if not is_bound and not h_obj.linked_commands:
            all_violations.append(f"ORPHAN_HANDLER: Handler '{h_name}' tidak terikat ke command/query. [{h_obj.file_path}]")

    # Skor
    penalty = (cmd_without_handler * 5) + (qry_without_handler * 5)
    penalty += sum(5 for v in all_violations if "CRITICAL_FAULT" in v)
    penalty += sum(2 for v in all_violations if "ORPHAN_HANDLER" in v)
    score = max(0, 100 - penalty)

    print(f"  Total Command Terdeteksi  :  {total_commands}")
    print(f"  Total Query Terdeteksi    :  {total_queries}")
    print(f"  Total Handler Terdeteksi  :  {len(handlers)}")
    print(f"  🚨 Command Tanpa Handler  :  {COLOR['RED'] if cmd_without_handler > 0 else COLOR['GREEN']}{cmd_without_handler}{COLOR['RESET']}")
    print(f"  🚨 Query Tanpa Handler    :  {COLOR['RED'] if qry_without_handler > 0 else COLOR['GREEN']}{qry_without_handler}{COLOR['RESET']}")
    print(f"  📉 Skor Kepatuhan CQRS    :  {COLOR['CYAN']}{COLOR['BOLD']}{score}/100{COLOR['RESET']}")
    print("-" * 72)
    print(f"{COLOR['BOLD']}─── DETAIL AUDIT INTEGRITAS CAKUPAN CQRS ───{COLOR['RESET']}")

    if all_violations:
        for violation in all_violations:
            color = COLOR['RED'] if "MISSING" in violation or "CRITICAL" in violation else COLOR['YELLOW']
            print(f"  ▪ {color}{violation}{COLOR['RESET']}")
    else:
        print(f"  {COLOR['GREEN']}✅ STATUS BERSIH: Seluruh Command, Query, dan Handler tersambung sempurna.{COLOR['RESET']}")

    print("-" * 72)
    print(f" ⏱️ Waktu Audit Arsitektur: {time.monotonic() - start_time:.3f} detik")

    if args.json:
        payload = {
            "score": score,
            "total_commands": total_commands,
            "total_queries": total_queries,
            "total_handlers": len(handlers),
            "commands_without_handler": cmd_without_handler,
            "queries_without_handler": qry_without_handler,
            "violations": all_violations,
            "mapping": {k: v for k, v in mapping.items()}
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"{COLOR['GREEN']}✅ Laporan diekspor ke {args.json}{COLOR['RESET']}")

    sys.exit(0 if score == 100 else 1)

if __name__ == "__main__":
    main()