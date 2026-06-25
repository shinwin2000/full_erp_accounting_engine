#!/usr/bin/env python3
"""
Sovereign ERP System - Domain-Driven Design & Architecture Compliance Engine
===========================================================================
Skrip pertahanan mutlak untuk memvalidasi kepatuhan Aggregate Root (DDD)
dan mencegah terjadinya Architecture Drift di dalam ekosistem ERP.

Menggabungkan Analisis Statis AST (Abstract Syntax Tree) dengan Introspeksi
Runtime Dinamis (Dynamic Introspection Reflection via Signatures & Memory Allocation).
"""

from __future__ import annotations

import argparse
import ast
import importlib
import inspect
import json
import os
import pathlib
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

# =============================================================================
# Konfigurasi Terminal Bermartabat (ANSI Color)
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

# Matikan warna jika output dialihkan atau platform tidak mendukung
if not sys.stdout.isatty():
    COLOR = {k: "" for k in COLOR}

# =============================================================================
# Matriks Batasan Arsitektur & Aturan Layer
# =============================================================================
LAYER_MAP = {
    "domain": "domain",
    "application": "application",
    "infrastructure": "infrastructure",
    "adapters": "adapters",
    "ports": "ports",
    "kernel": "kernel",
    "bootstrap": "bootstrap",
    "config": "config",
    "constitution": "constitution",
    "axioms": "axioms",
    "policy_engine": "policy_engine",
    "compliance": "compliance",
    "audit": "audit",
    "projections": "projections",
    "reports": "reports",
    "event_gateway": "event_gateway",
    "app": "app",
    "tests": "tests",
}

ALLOWED_LAYER_DEPENDENCIES = {
    "domain": {"domain", "axioms", "constitution"},
    "axioms": {"axioms", "constitution"},
    "constitution": {"constitution", "domain", "axioms"},
    "kernel": {"kernel", "domain", "axioms", "constitution", "ports", "config"},
    "ports": {"ports", "domain"},
    "application": {"application", "domain", "kernel", "ports", "axioms", "constitution", "config", "bootstrap"},
    "adapters": {"adapters", "application", "domain", "kernel", "ports", "infrastructure", "config"},
    "infrastructure": {"infrastructure", "domain", "ports", "kernel", "config", "application"},
    "bootstrap": {"bootstrap", "config", "infrastructure", "application", "adapters"},
    "config": {"config", "bootstrap"},
    "app": {"app", "bootstrap", "adapters", "infrastructure"},
    "policy_engine": {"policy_engine", "domain", "kernel", "config", "compliance"},
    "compliance": {"compliance", "policy_engine", "domain", "application"},
    "audit": {"audit", "domain", "application", "kernel"},
    "projections": {"projections", "domain", "application", "infrastructure"},
    "reports": {"reports", "projections", "application", "infrastructure"},
    "event_gateway": {"event_gateway", "domain", "application", "infrastructure"},
    "tests": set(),
}

# =============================================================================
# Model Data Laporan Korektif
# =============================================================================
@dataclass
class DeviationInfo:
    line: int
    target: str
    message: str

@dataclass
class AggregateReport:
    class_name: str
    module_path: str
    file_path: str
    ast_valid: bool = False
    runtime_valid: bool = False
    detected_id_field: Optional[str] = None
    detected_events_field: Optional[str] = None
    implemented_methods: List[str] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)
    drift_deviations: List[DeviationInfo] = field(default_factory=list)
    runtime_notes: List[str] = field(default_factory=list)

@dataclass
class ComprehensiveMasterReport:
    total_scanned: int = 0
    clean_aggregates: int = 0
    corrupted_aggregates: int = 0
    architectural_drift_count: int = 0
    cyclic_dependency_chains: List[List[str]] = field(default_factory=list)
    aggregates: Dict[str, AggregateReport] = field(default_factory=dict)
    score: int = 100

# =============================================================================
# Core Engine - Analisis Komponen Domain & Batasan Layer
# =============================================================================
class SovereignDomainVerifier:
    def __init__(self, root_dir: pathlib.Path):
        self.root_dir = root_dir
        sys.path.insert(0, str(root_dir))

    def identify_layer(self, module_name: str) -> str:
        if not module_name:
            return "unknown"
        top_level = module_name.split(".")[0]
        return LAYER_MAP.get(top_level, "unknown")

    def is_aggregate_root_class(self, node: ast.ClassDef) -> bool:
        name = node.name
        # Proteksi: kecualikan utilitas, repositori, pengecualian, dan tanda tangan digital
        if any(bad in name for bad in ["Repository", "Error", "Exception", "Signature", "Event", "VO", "Validator"]):
            return False
        
        # Konvensi penamaan sovereign terpadu
        if name.endswith("Aggregate") or name.endswith("AggregateRoot") or name.endswith("Root"):
            return True
            
        # Pengecekan berbasis decorator decorator meta
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id == "aggregate":
                return True
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name) and decorator.func.id == "aggregate":
                return True
        return False

    def inspect_static_ast(self, file_path: pathlib.Path) -> Optional[AggregateReport]:
        try:
            source_code = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source_code, filename=str(file_path))
        except (SyntaxError, UnicodeDecodeError):
            return None

        classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and self.is_aggregate_root_class(node)]
        if not classes:
            return None

        # Ambil representasi kelas aggregate utama dari file ini
        target_class = classes[0]
        relative_path = file_path.relative_to(self.root_dir)
        module_name = str(relative_path.with_suffix("")).replace(os.sep, ".")

        report = AggregateReport(
            class_name=target_class.name,
            module_path=module_name,
            file_path=str(relative_path)
        )

        # 1. Evaluasi Atribut & Fungsi via AST
        has_id = False
        has_events = False
        has_validation = False

        for node in target_class.body:
            if isinstance(node, ast.FunctionDef):
                report.implemented_methods.append(node.name)
                if node.name in ["validate", "check_invariants", "validate_invariants"]:
                    has_validation = True
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        if target.id in ["id", "aggregate_id", "_id", "id_field"]:
                            has_id = True
                            report.detected_id_field = target.id
                        if target.id in ["domain_events", "_domain_events", "events", "event_list"]:
                            has_events = True
                            report.detected_events_field = target.id

        # Pencarian fallback pada metode __init__ jika tidak diinisialisasi di tingkat kelas statis
        for node in ast.walk(target_class):
            if isinstance(node, ast.FunctionDef) and node.name == "__init__":
                for sub_node in ast.walk(node):
                    if isinstance(sub_node, ast.Attribute) and isinstance(sub_node.value, ast.Name) and sub_node.value.id == "self":
                        if sub_node.attr in ["id", "aggregate_id", "_id"]:
                            has_id = True
                            report.detected_id_field = sub_node.attr
                        if sub_node.attr in ["domain_events", "_domain_events", "events", "_events", "event_list"]:
                            has_events = True
                            report.detected_events_field = sub_node.attr

        if not has_id:
            report.violations.append("MISSING_ID: Tidak memiliki atribut identitas (id, aggregate_id, atau _id).")
        if not has_events:
            report.violations.append("MISSING_EVENTS: Tidak terdeteksi pelacak event domain (domain_events/events).")
        if not has_validation:
            report.violations.append("MISSING_VALIDATION: Tidak ada metode validasi pelindung domain (check_invariants / validate).")

        # 2. Pengecekan Pelanggaran Impor (Architecture Drift)
        source_layer = self.identify_layer(module_name)
        allowed_targets = ALLOWED_LAYER_DEPENDENCIES.get(source_layer, set())

        for node in ast.walk(tree):
            target_modules = []
            line_no = 0
            if isinstance(node, ast.Import):
                line_no = node.lineno
                target_modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                line_no = node.lineno
                if node.level == 0 and node.module:
                    target_modules = [node.module]
                
            for tgt in target_modules:
                tgt_layer = self.identify_layer(tgt)
                if tgt_layer != "unknown" and tgt_layer != source_layer and tgt_layer not in allowed_targets:
                    drift_msg = f"Pelanggaran Batasan Layer: Lapisan '{source_layer}' dilarang mengimpor '{tgt_layer}'"
                    report.drift_deviations.append(DeviationInfo(line=line_no, target=tgt, message=drift_msg))
                    report.violations.append(f"ARCHITECTURE_DRIFT: Impor ilegal ke modul luar layer ({tgt}) pada baris {line_no}.")

        report.ast_valid = len(report.violations) == 0
        return report

    def perform_runtime_introspection(self, report: AggregateReport) -> None:
        """
        Melakukan introspeksi runtime tingkat lanjut secara defensif untuk membedah
        karakteristik internal arsitektur kelas tanpa merusak alur eksekusi checker.
        """
        try:
            imported_module = importlib.import_module(report.module_path)
            target_class = getattr(imported_module, report.class_name, None)
            
            if not target_class or not inspect.isclass(target_class):
                report.violations.append(f"RUNTIME_ERROR: Kelas {report.class_name} gagal dimuat secara dinamis.")
                return

            # Sinkronisasi metode real hasil introspeksi objek runtime Python
            runtime_methods = [item[0] for item in inspect.getmembers(target_class, predicate=inspect.isfunction)]
            for m in runtime_methods:
                if m not in report.implemented_methods:
                    report.implemented_methods.append(m)

            # Validasi keberadaan gerbang pertahanan invariants secara fungsional
            if not any(m in runtime_methods for m in ["check_invariants", "validate", "validate_invariants"]):
                if "MISSING_VALIDATION: Tidak ada metode validasi pelindung domain (check_invariants / validate)." not in report.violations:
                    report.violations.append("MISSING_VALIDATION: Metode evaluasi invariants tidak dapat dipanggil.")

            # Strategi Alokasi Memori Defensif untuk membedah instansiasi objek
            instance: Any = None
            instantiation_strategy = "STANDARD"
            
            try:
                # Upayakan instansiasi pintar dengan membedah tanda tangan parameter konstruktor (__init__)
                constructor_signature = inspect.signature(target_class.__init__)
                synthetic_arguments = {}
                
                for param_name, param in constructor_signature.parameters.items():
                    if param_name == "self":
                        continue
                    if param.default != inspect.Parameter.empty:
                        continue
                    
                    # Sintesis tipe data tiruan berdasarkan type annotations untuk menghindari kegagalan instansiasi
                    parameter_annotation = param.annotation
                    if parameter_annotation == str or "str" in str(parameter_annotation):
                        synthetic_arguments[param_name] = "00000000-0000-0000-0000-000000000000"
                    elif parameter_annotation == int or "int" in str(parameter_annotation):
                        synthetic_arguments[param_name] = 1
                    elif parameter_annotation == float or "float" in str(parameter_annotation):
                        synthetic_arguments[param_name] = 0.0
                    elif parameter_annotation == bool or "bool" in str(parameter_annotation):
                        synthetic_arguments[param_name] = True
                    elif hasattr(parameter_annotation, "__members__"):
                        synthetic_arguments[param_name] = list(parameter_annotation.__members__.values())[0]
                    else:
                        synthetic_arguments[param_name] = None

                instance = target_class(**synthetic_arguments)
                report.runtime_notes.append("✅ Instansiasi Runtime: Berhasil melalui simulasi kecerdasan parameter.")
            
            except Exception as context_error:
                # Forge Memori Tingkat Tinggi: Bypass __init__ menggunakan alokasi memori mentah __new__
                # Ini menjamin kita bisa memeriksa struktur objek internal meskipun depedensi eksternalnya belum siap.
                try:
                    instance = target_class.__new__(target_class)
                    # Jalankan inisialisasi minimal jika memungkinkan secara aman
                    report.runtime_notes.append(f"⚠️ Alokasi Memori Menggunakan Kebijakan __new__ Bypass (Sebab __init__: {type(context_error).__name__})")
                except Exception as critical_fatal:
                    report.violations.append(f"RUNTIME_FATAL: Struktur internal kelas korup. Alokasi memori gagal: {critical_fatal}")
                    return

            # Lakukan analisis pasca alokasi memori pada instance objek murni Python
            if instance is not None:
                object_attributes = dir(instance)
                
                # Konfirmasi kepatuhan ID lapangan secara runtime
                actual_id_found = any(attr in object_attributes for attr in ["id", "aggregate_id", "_id", "id_field"])
                if not actual_id_found:
                    # Coba paksa pemanggilan fungsi inisialisasi jika properti kosong
                    if "MISSING_ID: Tidak memiliki atribut identitas (id, aggregate_id, atau _id)." not in report.violations:
                        report.violations.append("MISSING_ID: Properti Identitas gagal dipetakan pada siklus hidup objek.")
                
                # Konfirmasi pelacak event domain secara dinamis
                actual_events_found = any(attr in object_attributes for attr in ["domain_events", "_domain_events", "events", "_events", "event_list"])
                if not actual_events_found:
                    if "MISSING_EVENTS: Tidak terdeteksi pelacak event domain (domain_events/events)." not in report.violations:
                        report.violations.append("MISSING_EVENTS: Komponen pelacakan Domain Event tidak ditemukan di memori runtime.")

            report.runtime_valid = not any("RUNTIME" in v for v in report.violations)

        except Exception as global_runtime_exception:
            report.violations.append(f"COMPILER_UNCAUGHT_EXCEPTION: {type(global_runtime_exception).__name__} -> {global_runtime_exception}")

    def detect_cyclic_dependencies(self, files: List[pathlib.Path]) -> List[List[str]]:
        """
        Algoritma Pencarian Siklus Terdistribusi (Tarjan's Strongly Connected Components)
        untuk mendeteksi adanya keterikatan sirkular antar modul domain.
        """
        dependency_graph: Dict[str, Set[str]] = defaultdict(set)
        
        for file_path in files:
            try:
                source_code = file_path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source_code)
            except Exception:
                continue
                
            relative_path = file_path.relative_to(self.root_dir)
            source_module = str(relative_path.with_suffix("")).replace(os.sep, ".")
            
            for node in ast.walk(tree):
                target_modules = []
                if isinstance(node, ast.Import):
                    target_modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    target_modules = [node.module]
                    
                for tgt in target_modules:
                    if tgt.startswith("domain") and tgt != source_module:
                        dependency_graph[source_module].add(tgt)

        # Implementasi Algoritma Tarjan SCC
        execution_index = 0
        node_indices: Dict[str, int] = {}
        low_links: Dict[str, int] = {}
        execution_stack: List[str] = []
        stack_registry: Set[str] = set()
        detected_cycles: List[List[str]] = []

        def trace_strong_connections(v: str):
            nonlocal execution_index
            node_indices[v] = execution_index
            low_links[v] = execution_index
            execution_index += 1
            execution_stack.append(v)
            stack_registry.add(v)

            for neighbor in dependency_graph[v]:
                if neighbor not in node_indices:
                    trace_strong_connections(neighbor)
                    low_links[v] = min(low_links[v], low_links[neighbor])
                elif neighbor in stack_registry:
                    low_links[v] = min(low_links[v], node_indices[neighbor])

            if low_links[v] == node_indices[v]:
                scc_component = []
                while True:
                    node = execution_stack.pop()
                    stack_registry.remove(node)
                    scc_component.append(node)
                    if node == v:
                        break
                if len(scc_component) > 1:
                    detected_cycles.append(scc_component)

        for vertex in list(dependency_graph.keys()):
            if vertex not in node_indices:
                trace_strong_connections(vertex)

        return detected_cycles

# =============================================================================
# Main Orchestration Execution Execution Suite
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="Sovereign DDD Architecture Core Hardened Checker")
    parser.add_argument("--verbose", action="store_true", help="Tampilkan rincian metode introspeksi lengkap")
    parser.add_argument("--json", metavar="FILE", help="Simpan laporan komprehensif ke format JSON")
    args = parser.parse_args()

    start_time = time.monotonic()
    
    # Deteksi letak root repositori secara independen
    current_working_dir = pathlib.Path.cwd()
    verifier = SovereignDomainVerifier(current_working_dir)

    print(f"{COLOR['BOLD']}{COLOR['CYAN']}╔════════════════════════════════════════════════════════════════════╗")
    print(f"║          SOVEREIGN HIGH-INTEGRITY ARCHITECTURE ENGINE ENGINE       ║")
    print(f"╚════════════════════════════════════════════════════════════════════╝{COLOR['RESET']}")
    print(f"  Mode Introspeksi Runtime  :  {COLOR['GREEN']}✅ PERTAHANAN MULTILAYER AKTIF{COLOR['RESET']}")

    domain_folder = current_working_dir / "domain"
    if not domain_folder.exists():
        print(f"  {COLOR['RED']}✖ Batalkan Operasi: Direktori domain murni tidak ditemukan di {domain_folder}{COLOR['RESET']}")
        sys.exit(1)

    # Kumpulkan seluruh target file python
    python_source_files = [p for p in domain_folder.rglob("*.py") if not p.name.startswith("__init__")]
    
    master_report = ComprehensiveMasterReport()
    
    # 1. Jalankan deteksi siklus dependensi sirkular secara global
    cycles = verifier.detect_cyclic_dependencies(python_source_files)
    master_report.cyclic_dependency_chains = cycles

    # 2. Proses analisis tiap file secara terisolasi
    for file_path in python_source_files:
        aggregate_report = verifier.inspect_static_ast(file_path)
        if aggregate_report:
            master_report.total_scanned += 1
            # Jalankan introspeksi runtime tingkat lanjut secara dinamis
            verifier.perform_runtime_introspection(aggregate_report)
            
            # Hitung statistik
            if len(aggregate_report.violations) == 0:
                master_report.clean_aggregates += 1
            else:
                master_report.corrupted_aggregates += 1
                
            if len(aggregate_report.drift_deviations) > 0:
                master_report.architectural_drift_count += len(aggregate_report.drift_deviations)

            master_report.aggregates[aggregate_report.class_name] = aggregate_report

    # Hitung skor akhir arsitektur (Penalti bobot tinggi demi integritas enterprise)
    penalty = (master_report.corrupted_aggregates * 4) + (len(master_report.cyclic_dependency_chains) * 10)
    master_report.score = max(0, 100 - penalty)

    # =============================================================================
    # Cetak Laporan Visual Komprehensif
    # =============================================================================
    print(f"  Total Aggregate Found     :  {master_report.total_scanned}")
    print(f"  ✅ Valid Aggregates       :  {COLOR['GREEN']}{master_report.clean_aggregates}{COLOR['RESET']}")
    print(f"  ❌ Invalid Aggregates     :  {COLOR['RED'] if master_report.corrupted_aggregates > 0 else COLOR['GREEN']}{master_report.corrupted_aggregates}{COLOR['RESET']}")
    print(f"  🔄 Cyclic Dependencies    :  {COLOR['RED'] if cycles else COLOR['GREEN']}{len(cycles)} Rantai Terdeteksi{COLOR['RESET']}")
    print(f"  📉 Skor Kepatuhan Sistem  :  {COLOR['CYAN']}{COLOR['BOLD']}{master_report.score}/100{COLOR['RESET']}")
    print("-" * 72)

    print(f"{COLOR['BOLD']}─── DETAIL AUDIT AGGREGATE CORE ───{COLOR['RESET']}")
    
    for name, agg in master_report.aggregates.items():
        if len(agg.violations) == 0:
            print(f"\n{COLOR['GREEN']}✅ {name}{COLOR['RESET']} [{agg.module_path}]")
            if args.verbose:
                print(f"   └─ Properti ID  : {agg.detected_id_field}")
                print(f"   └─ Properti Event: {agg.detected_events_field}")
                print(f"   └─ Metode Ekpos  : {', '.join(agg.implemented_methods)}")
        else:
            print(f"\n{COLOR['RED']}❌ {name}{COLOR['RESET']} [{agg.module_path}]")
            print(f"   └─ {COLOR['BOLD']}Pelanggaran Integritas DDD / Arsitektur:{COLOR['RESET']}")
            for violation in agg.violations:
                print(f"      ▪ {COLOR['RED']}{violation}{COLOR['RESET']}")
            if args.verbose and agg.runtime_notes:
                print(f"   └─ {COLOR['YELLOW']}Log Diagnostik Introspeksi Runtime:{COLOR['RESET']}")
                for note in agg.runtime_notes:
                    print(f"      • {note}")

    if master_report.cyclic_dependency_chains:
        print(f"\n{COLOR['RED']}{COLOR['BOLD']}🚨 BAHAYA: TERDETEKSI SIKLUS DEPENDENSI SIRKULAR (DDD ANTI-PATTERN):{COLOR['RESET']}")
        for index, chain in enumerate(master_report.cyclic_dependency_chains, 1):
            print(f"  Rantai {index}: {' ➔ '.join(chain)}")

    print("-" * 72)
    execution_time = time.monotonic() - start_time
    print(f" ⏱️ Waktu Eksekusi Sistem: {execution_time:.3f} detik")

    # Simpan JSON jika diminta
    if args.json:
        json_payload = {
            "score": master_report.score,
            "total_aggregates": master_report.total_scanned,
            "valid_count": master_report.clean_aggregates,
            "invalid_count": master_report.corrupted_aggregates,
            "architectural_drift_violations": master_report.architectural_drift_count,
            "cycles": master_report.cyclic_dependency_chains,
            "details": {
                k: {
                    "file": v.file_path,
                    "module": v.module_path,
                    "ast_valid": v.ast_valid,
                    "runtime_valid": v.runtime_valid,
                    "violations": v.violations,
                    "methods": v.implemented_methods,
                } for k, v in master_report.aggregates.items()
            }
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(json_payload, f, indent=2)
        print(f"{COLOR['GREEN']}✅ Laporan audit ekosistem berhasil diekspor ke {args.json}{COLOR['RESET']}")

    # Exit code tegas demi otomasi CI/CD pipelines
    sys.exit(0 if master_report.corrupted_aggregates == 0 and len(cycles) == 0 else 1)

if __name__ == "__main__":
    main()