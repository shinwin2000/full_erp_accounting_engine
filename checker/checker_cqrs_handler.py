#!/usr/bin/env python3
"""
Sovereign ERP System - CQRS High-Integrity Architecture & Compliance Engine (Ultimate Fixed)
=======================================================================================
Fixes:
1. Registry Parsing: Membaca __init__.py/app_factory.py sebagai sumber kebenaran utama.
2. Smart Orphan Detection: Hanya lapor orphan jika tidak ada registry DAN tidak ada tipe param Command/Query.
3. Case-Insensitive Matching: Menangani HPP vs Hpp naming inconsistency.
4. Strict Exclusion: Blokir folder mapper/workflow/kernel sejak awal.
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

BASE_COMMAND_NAMES = {"BaseCommand", "Command"}
BASE_QUERY_NAMES = {"BaseQuery", "Query"}
IGNORE_BASES = BASE_COMMAND_NAMES | BASE_QUERY_NAMES

INFRASTRUCTURE_HANDLERS = {
    "WebhookHandler", "CorrelationIdHandler", "SQLAlchemyCQRSQueryHandler",
    "KafkaDeadLetterHandler", "LifecycleHandler", "EventHandler",
    "AxiomViolationHandler", "RollbackHandler", "ConfigFileHandler",
    "ConstitutionExceptionHandler", "QueryHandler"
}

# Folder yang TIDAK BOLEH mengandung CQRS Command/Query bisnis
EXCLUDED_DIRS = {
    "mappers", "workflows", "sagas", "orchestrators", "kernel",
    "dto_objects", "dto", "requests", "responses", "schemas", "models",
    "__pycache__", ".git", "tests", "migrations", "scripts", "alembic", "docs", "checker"
}

@dataclass
class CQRSObject:
    name: str
    file_path: str
    module_path: str
    is_command: bool = False
    is_query: bool = False
    is_handler: bool = False
    linked_commands: set[str] = field(default_factory=set)
    has_execute_method: bool = False
    source_type: str = "AST"

    def normalized_name(self) -> str:
        """Normalisasi nama untuk pencocokan case-insensitive."""
        base = self.name.replace("Command", "").replace("Query", "").replace("Handler", "").replace("UseCase", "")
        return base.lower()

class SovereignCQRSVerifier:
    def __init__(self, root_dir: pathlib.Path):
        self.root_dir = root_dir
        self.registry_pairs: list[tuple[str, str]] = [] # (CommandName, HandlerName)

    def _get_python_files(self) -> list[pathlib.Path]:
        py_files = []
        for p in self.root_dir.rglob("*.py"):
            # Cek apakah path mengandung folder yang dikecualikan
            if any(part in EXCLUDED_DIRS for part in p.parts):
                continue
            if p.name.startswith(("test_", "conftest")):
                continue
            py_files.append(p)
        return py_files

    def _module_name_from_path(self, path: pathlib.Path) -> str:
        rel = path.relative_to(self.root_dir)
        return str(rel.with_suffix("")).replace(os.sep, ".")

    def _extract_base_classes(self, node: ast.ClassDef) -> list[str]:
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(base.attr)
            elif isinstance(base, ast.Subscript):
                if isinstance(base.value, ast.Name):
                    bases.append(base.value.id)
        return bases

    def parse_registry_files(self):
        """Membaca file __init__.py atau app_factory.py untuk menemukan registrasi eksplisit."""
        candidates = [
            self.root_dir / "application" / "use_cases" / "__init__.py",
            self.root_dir / "application" / "app_factory.py",
            self.root_dir / "application" / "commands_cqrs" / "command_handler_registry.py"
        ]

        for file_path in candidates:
            if not file_path.exists():
                continue

            try:
                src = file_path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=str(file_path))

                for node in ast.walk(tree):
                    # Cari Tuple atau List yang berisi 3 elemen (Command, Handler, UseCase)
                    # Contoh: (CreateInvoiceCommand, handler, CreateInvoiceUseCase)
                    if isinstance(node, (ast.Tuple, ast.List)) and len(node.elts) >= 2:
                        elts = node.elts

                        # Coba identifikasi elemen pertama sebagai Command dan terakhir sebagai Handler/UseCase
                        first_name = None
                        last_name = None

                        if isinstance(elts[0], ast.Name):
                            first_name = elts[0].id
                        if isinstance(elts[-1], ast.Name):
                            last_name = elts[-1].id

                        # Jika pola terlihat seperti registrasi CQRS
                        if first_name and last_name:
                            if first_name.endswith("Command") or first_name.endswith("Query"):
                                if last_name.endswith("Handler") or last_name.endswith("UseCase"):
                                    self.registry_pairs.append((first_name, last_name))

            except Exception:
                pass

    def introspect_ast(self, file_path: pathlib.Path, commands_queries: dict[str, CQRSObject], handlers: dict[str, CQRSObject]):
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

                # Skip Exception classes
                if any(b in ("Exception", "Error", "Warning") for b in bases):
                    continue

                # Deteksi Inheritance
                is_cmd_inherit = any(b in BASE_COMMAND_NAMES for b in bases)
                is_qry_inherit = any(b in BASE_QUERY_NAMES for b in bases)

                # Fallback nama (hanya jika bukan dari folder excluded yang sudah difilter di _get_python_files)
                is_cmd_name = name.endswith("Command") and name not in IGNORE_BASES
                is_qry_name = name.endswith("Query") and name not in IGNORE_BASES

                is_cmd = is_cmd_inherit or (not is_cmd_inherit and is_cmd_name)
                is_qry = is_qry_inherit or (not is_qry_inherit and is_qry_name)

                # Deteksi Handler/UseCase
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
                    # Cek method execute/handle dan parameter tipenya
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in ("handle", "execute", "__call__"):
                            cqrs_obj.has_execute_method = True
                            # Cek parameter
                            for arg in item.args.args:
                                if arg.annotation:
                                    anno_str = self._extract_annotation_string(arg.annotation)
                                    if anno_str and (anno_str.endswith("Command") or anno_str.endswith("Query")):
                                        cqrs_obj.linked_commands.add(anno_str)

                    # Hanya simpan jika punya method eksekusi
                    if cqrs_obj.has_execute_method:
                        handlers[name] = cqrs_obj
                else:
                    commands_queries[name] = cqrs_obj

        except Exception:
            pass

    def _extract_annotation_string(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.s
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Subscript):
            return self._extract_annotation_string(node.slice)
        return None

    def scan(self) -> tuple[dict[str, CQRSObject], dict[str, CQRSObject], dict[str, list[str]]]:
        commands_queries: dict[str, CQRSObject] = {}
        handlers: dict[str, CQRSObject] = {}
        command_to_handler_map: dict[str, list[str]] = defaultdict(list)

        # 1. Baca Registry terlebih dahulu
        self.parse_registry_files()

        # Map registry ke struktur data
        registered_handlers = set()
        for cmd_name, hdl_name in self.registry_pairs:
            command_to_handler_map[cmd_name].append(hdl_name)
            registered_handlers.add(hdl_name)

        # 2. Scan File
        files = self._get_python_files()
        for f in files:
            self.introspect_ast(f, commands_queries, handlers)

        # 3. Gabungkan informasi AST dengan Registry
        # Jika handler ada di registry, paksa link ke command-nya meskipun AST tidak menangkap annotation
        for cmd_name, hdl_name in self.registry_pairs:
            if hdl_name in handlers:
                handlers[hdl_name].linked_commands.add(cmd_name)
            # Pastikan command terdeteksi (jika ada di registry tapi mungkin terlewat AST karena alasan tertentu)
            # Di sini kita asumsikan AST sudah menangkap semua class definisi

        # 4. Fallback Naming Convention (Case-Insensitive)
        # Hanya untuk command yang belum punya handler dari registry
        for cq_name, cq_obj in commands_queries.items():
            if not command_to_handler_map.get(cq_name):
                base_norm = cq_obj.normalized_name()
                for h_name, h_obj in handlers.items():
                    if h_obj.normalized_name() == base_norm:
                        # Match ditemukan
                        command_to_handler_map[cq_name].append(h_name)
                        h_obj.linked_commands.add(cq_name)
                        break

        return commands_queries, handlers, dict(command_to_handler_map)

def main():
    parser = argparse.ArgumentParser(description="Sovereign CQRS Compliance Engine (Ultimate)")
    parser.add_argument("--json", metavar="FILE", help="Ekspor laporan ke JSON")
    args = parser.parse_args()

    start_time = time.monotonic()
    root_dir = pathlib.Path.cwd()
    verifier = SovereignCQRSVerifier(root_dir)

    print(f"{COLOR['BOLD']}{COLOR['CYAN']}╔════════════════════════════════════════════════════════════════════╗")
    print("║      SOVEREIGN CQRS COMPLIANCE ENGINE (ULTIMATE FIXED)           ║")
    print(f"╚════════════════════════════════════════════════════════════════════╝{COLOR['RESET']}")
    print(f"  Mode Deteksi             :  {COLOR['GREEN']}✅ AST + Registry Parsing{COLOR['RESET']}")
    print(f"  Proteksi Folder          :  {COLOR['GREEN']}✅ Mapper/Workflow/Kernel diabaikan{COLOR['RESET']}")
    print(f"  Validasi Handler         :  {COLOR['GREEN']}✅ Harus punya execute()/handle(){COLOR['RESET']}")
    print(f"  Source of Truth          :  {COLOR['CYAN']}Registry (__init__.py/app_factory){COLOR['RESET']}")

    commands_queries, handlers, mapping = verifier.scan()

    total_commands = sum(1 for c in commands_queries.values() if c.is_command)
    total_queries = sum(1 for q in commands_queries.values() if q.is_query)

    cmd_without_handler = 0
    qry_without_handler = 0
    all_violations = []

    # Cek Missing Handler
        # =========================================================================
    # Cek Missing Handler (Command/Query tanpa handler)
    # =========================================================================
    for cq_name, cq_obj in commands_queries.items():
        assigned = mapping.get(cq_name, [])
        if not assigned:
            type_label = "Query" if cq_obj.is_query else "Command"
            all_violations.append(
                f"MISSING_HANDLER: {type_label} '{cq_name}' tidak memiliki handler. [{cq_obj.file_path}]"
            )
            if cq_obj.is_query:
                qry_without_handler += 1
            else:
                cmd_without_handler += 1

    # =========================================================================
    # Cek Handler yang Terikat (Registry atau Parameter) – Deteksi UNREGISTERED
    # =========================================================================
    for h_name, h_obj in handlers.items():
        if h_name in INFRASTRUCTURE_HANDLERS or "Base" in h_name:
            continue

        # Apakah handler ini terikat secara eksplisit di registry?
        is_bound_by_mapping = any(h_name in h_list for h_list in mapping.values())
        # Apakah handler ini memiliki parameter bertipe Command/Query (dari AST)?
        is_bound_by_param = len(h_obj.linked_commands) > 0

        # Kasus 1: Tidak terikat sama sekali → BUKAN CQRS handler → ABAIKAN
        if not is_bound_by_mapping and not is_bound_by_param:
            continue

        # Kasus 2: Terikat melalui parameter tapi TIDAK ada di registry → UNREGISTERED
        if is_bound_by_param and not is_bound_by_mapping:
            all_violations.append(
                f"UNREGISTERED_HANDLER: Handler '{h_name}' memiliki parameter Command/Query "
                f"tetapi tidak terdaftar di registry. [{h_obj.file_path}]"
            )

        # Kasus 3: Terdaftar di registry → SUDAH BENAR (tidak perlu laporan)

    # =========================================================================
    # Hitung Skor (Penalti disesuaikan)
    # =========================================================================
    penalty = (cmd_without_handler * 5) + (qry_without_handler * 5)
    penalty += sum(5 for v in all_violations if "MISSING_HANDLER" in v or "CRITICAL_FAULT" in v)
    penalty += sum(2 for v in all_violations if "UNREGISTERED_HANDLER" in v)
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
            "mapping": {k: v for k, v in mapping.items()},
            "registry_pairs_found": verifier.registry_pairs,
            "compliance_notes": "Deteksi berbasis Registry + AST. Orphan hanya dilaporkan jika tidak ada registry DAN tidak ada parameter Command/Query."
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"{COLOR['GREEN']}✅ Laporan diekspor ke {args.json}{COLOR['RESET']}")

    sys.exit(0 if score >= 90 else 1)

if __name__ == "__main__":
    main()
