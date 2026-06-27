#!/usr/bin/env python3
"""
Sovereign ERP System - Architecture Drift & Circular Dependency Validator (Improved)
=====================================================================================
Memvalidasi kepatuhan arsitektur Layered + DDD dengan fokus pada:
1. AST Layer Drift (import dari layer terlarang).
2. Circular Dependencies (SCC) - membedakan intra-layer vs inter-layer.
3. Skor berbasis severity (lebih realistis untuk ERP ORM).
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

# =============================================================================
# Matriks Layer & Aturan Dependensi
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

SKIP_LAYERS = {"tests", "unknown"}

# =============================================================================
# Model Data
# =============================================================================
@dataclass
class ImportEdge:
    source_module: str
    source_layer: str
    target_module: str
    target_layer: str
    line: int
    file_path: str

@dataclass
class ViolationInfo:
    line: int
    target_module: str
    target_layer: str
    message: str

@dataclass
class ModuleReport:
    module_path: str
    file_path: str
    layer: str
    violations: list[ViolationInfo] = field(default_factory=list)

@dataclass
class ComprehensiveDriftReport:
    total_files_scanned: int = 0
    clean_modules: int = 0
    corrupted_modules: int = 0
    total_ast_violations: int = 0
    inter_layer_cycles: list[list[str]] = field(default_factory=list)
    intra_layer_cycles: list[list[str]] = field(default_factory=list)
    modules: dict[str, ModuleReport] = field(default_factory=dict)
    score: int = 100

# =============================================================================
# Core Engine
# =============================================================================
class SovereignArchitectureVerifier:
    def __init__(self, root_dir: pathlib.Path, strict_mode: bool = False):
        self.root_dir = root_dir
        self.strict_mode = strict_mode
        if str(root_dir) not in sys.path:
            sys.path.insert(0, str(root_dir))

    def identify_layer(self, module_name: str) -> str:
        if not module_name:
            return "unknown"
        top_level = module_name.split(".")[0]
        return LAYER_MAP.get(top_level, "unknown")

    def resolve_relative_import(self, source_module: str, level: int, target_module: str | None) -> str:
        parts = source_module.split(".")
        if len(parts) >= level:
            base = ".".join(parts[:-level])
            return f"{base}.{target_module}" if target_module else base
        return source_module

    def scan_module(self, file_path: pathlib.Path) -> ModuleReport | None:
        try:
            source_code = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source_code, filename=str(file_path))
        except (SyntaxError, UnicodeDecodeError):
            return None

        relative_path = file_path.relative_to(self.root_dir)
        source_module = str(relative_path.with_suffix("")).replace(os.sep, ".")
        source_layer = self.identify_layer(source_module)

        if source_layer in SKIP_LAYERS:
            return None

        report = ModuleReport(
            module_path=source_module,
            file_path=str(relative_path),
            layer=source_layer
        )

        allowed_targets = ALLOWED_LAYER_DEPENDENCIES.get(source_layer, set())

        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Import):
                for alias in node.names:
                    targets.append((alias.name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                target = None
                if node.module is None:
                    target = self.resolve_relative_import(source_module, node.level, None)
                else:
                    target = self.resolve_relative_import(source_module, node.level, node.module) if node.level > 0 else node.module

                if target:
                    targets.append((target, node.lineno))

            for target_mod, line_no in targets:
                target_layer = self.identify_layer(target_mod)
                if target_layer in SKIP_LAYERS:
                    continue

                # Deteksi layer drift
                if target_layer != source_layer and target_layer not in allowed_targets:
                    drift_msg = f"AST DRIFT: '{source_layer}' → '{target_layer}' (Modul: {target_mod})"
                    report.violations.append(ViolationInfo(line_no, target_mod, target_layer, drift_msg))

        return report

    def build_import_graph(self, all_edges: list[ImportEdge]) -> dict[str, set[str]]:
        graph: dict[str, set[str]] = defaultdict(set)
        for edge in all_edges:
            if edge.source_module != edge.target_module and edge.target_layer not in SKIP_LAYERS:
                graph[edge.source_module].add(edge.target_module)
        return graph

    def tarjan_scc(self, graph: dict[str, set[str]]) -> list[list[str]]:
        index = 0
        indices: dict[str, int] = {}
        lowlinks: dict[str, int] = {}
        stack: list[str] = []
        onstack: set[str] = set()
        sccs: list[list[str]] = []

        def strongconnect(v: str) -> None:
            nonlocal index
            indices[v] = index
            lowlinks[v] = index
            index += 1
            stack.append(v)
            onstack.add(v)

            for w in graph.get(v, set()):
                if w not in indices:
                    strongconnect(w)
                    lowlinks[v] = min(lowlinks[v], lowlinks[w])
                elif w in onstack:
                    lowlinks[v] = min(lowlinks[v], indices[w])

            if lowlinks[v] == indices[v]:
                scc = []
                while True:
                    w = stack.pop()
                    onstack.remove(w)
                    scc.append(w)
                    if w == v:
                        break
                if len(scc) > 1:
                    sccs.append(scc)

        for v in list(graph.keys()):
            if v not in indices:
                strongconnect(v)
        return sccs

    def classify_cycles(self, cycles: list[list[str]]) -> tuple[list[list[str]], list[list[str]]]:
        inter_layer = []
        intra_layer = []
        for cycle in cycles:
            layers = {self.identify_layer(node) for node in cycle}
            if len(layers) > 1:
                inter_layer.append(cycle)
            else:
                intra_layer.append(cycle)
        return inter_layer, intra_layer

# =============================================================================
# Main
# =============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Sovereign Architecture Drift & Circular Dependency Engine (Improved)"
    )
    parser.add_argument("--verbose", action="store_true", help="Tampilkan detail per modul")
    parser.add_argument("--json", metavar="FILE", help="Ekspor laporan ke JSON")
    parser.add_argument("--strict", action="store_true", help="Anggap intra-layer cycle sebagai error")
    parser.add_argument(
        "--exclude",
        default=".venv,venv,__pycache__,node_modules,dist,build,migrations,deployment,docs,tests",
        help="Folder yang dilarang di-scan (pisahkan koma)"
    )
    args = parser.parse_args()

    start_time = time.monotonic()
    root_dir = pathlib.Path.cwd()
    verifier = SovereignArchitectureVerifier(root_dir, strict_mode=args.strict)

    print(f"{COLOR['BOLD']}{COLOR['CYAN']}╔════════════════════════════════════════════════════════════════════╗")
    print("║        SOVEREIGN ARCHITECTURE DRIFT & BOUNDARY VALIDATOR           ║")
    print(f"╚════════════════════════════════════════════════════════════════════╝{COLOR['RESET']}")

    exclude_set = {d.strip() for d in args.exclude.split(",") if d.strip()}
    py_files = []
    for path in root_dir.rglob("*.py"):
        if any(part in exclude_set for part in path.parts):
            continue
        if path.name.startswith("architecture_drift_checker"):
            continue
        py_files.append(path)

    master_report = ComprehensiveDriftReport()
    all_edges: list[ImportEdge] = []

    # === SCAN MODULES ===
    for file_path in py_files:
        report = verifier.scan_module(file_path)
        if report is None:
            continue

        master_report.total_files_scanned += 1
        master_report.modules[report.module_path] = report

        if report.violations:
            master_report.corrupted_modules += 1
            master_report.total_ast_violations += len(report.violations)
        else:
            master_report.clean_modules += 1

        # Kumpulkan edges untuk graph
        for v in report.violations:
            # Buat edge dari sumber ke target yang melanggar
            all_edges.append(ImportEdge(
                source_module=report.module_path,
                source_layer=report.layer,
                target_module=v.target_module,
                target_layer=v.target_layer,
                line=v.line,
                file_path=report.file_path
            ))

        # Tambahkan edge dari AST import yang sah (untuk deteksi cycle)
        # Untuk cycle detection, kita perlu semua import, bukan hanya yang melanggar.
        # Kita perlu scan ulang AST untuk mengumpulkan semua import edge.
        # Lebih baik kita baca ulang file atau kita buat fungsi terpisah.
        # Untuk efisiensi, kita kumpulkan edges langsung saat scan.
        # Saya akan tambahkan atribut edges di ModuleReport.

    # Karena kita ingin cycle detection berdasarkan semua import, kita perlu mengumpulkan edges
    # dari semua file. Saya akan buat scan ulang khusus untuk edges di sini, atau modifikasi
    # di atas. Mari kita lakukan scan kedua untuk edges (atau integrasikan ke dalam scan pertama).
    # Untuk kesederhanaan, saya akan scan ulang.
    all_import_edges: list[ImportEdge] = []
    for file_path in py_files:
        try:
            code = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(code, filename=str(file_path))
        except (SyntaxError, UnicodeDecodeError):
            continue

        rel_path = file_path.relative_to(root_dir)
        source_mod = str(rel_path.with_suffix("")).replace(os.sep, ".")
        source_layer = verifier.identify_layer(source_mod)
        if source_layer in SKIP_LAYERS:
            continue

        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Import):
                for alias in node.names:
                    targets.append((alias.name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                target = None
                if node.module is None:
                    target = verifier.resolve_relative_import(source_mod, node.level, None)
                else:
                    target = verifier.resolve_relative_import(source_mod, node.level, node.module) if node.level > 0 else node.module
                if target:
                    targets.append((target, node.lineno))

            for target_mod, line_no in targets:
                target_layer = verifier.identify_layer(target_mod)
                all_import_edges.append(ImportEdge(
                    source_module=source_mod,
                    source_layer=source_layer,
                    target_module=target_mod,
                    target_layer=target_layer,
                    line=line_no,
                    file_path=str(rel_path)
                ))

    # === CYCLE DETECTION ===
    graph = verifier.build_import_graph(all_import_edges)
    raw_cycles = verifier.tarjan_scc(graph)
    inter_cycles, intra_cycles = verifier.classify_cycles(raw_cycles)

    master_report.inter_layer_cycles = inter_cycles
    master_report.intra_layer_cycles = intra_cycles

    # === SCORING ===
    score = 100
    score -= master_report.total_ast_violations * 3
    score -= len(inter_cycles) * 10
    if args.strict:
        score -= len(intra_cycles) * 2  # penalti kecil untuk strict mode
    master_report.score = max(0, score)

    # =========================================================================
    # LAPORAN
    # =========================================================================
    print("-" * 72)
    print(f"  Total Modul Diperiksa     :  {master_report.total_files_scanned}")
    print(f"  ✅ Modul Patuh (Clean)    :  {COLOR['GREEN']}{master_report.clean_modules}{COLOR['RESET']}")
    print(f"  ❌ Pelanggaran Layer Drift:  {COLOR['RED'] if master_report.total_ast_violations > 0 else COLOR['GREEN']}{master_report.total_ast_violations} Insiden{COLOR['RESET']}")
    print(f"  🔄 Siklus Antar Layer     :  {COLOR['RED'] if inter_cycles else COLOR['GREEN']}{len(inter_cycles)} Rantai{COLOR['RESET']}")
    print(f"  🔗 Siklus Intra Layer     :  {COLOR['YELLOW']}{len(intra_cycles)} Rantai (INFO){COLOR['RESET']}")
    print(f"  📉 Skor Integritas Sistem :  {COLOR['CYAN']}{COLOR['BOLD']}{master_report.score}/100{COLOR['RESET']}")
    print("-" * 72)

    # === DETAIL VIOLATIONS ===
    if master_report.total_ast_violations > 0:
        print(f"{COLOR['BOLD']}─── DETAIL PELANGGARAN DRIFT ───{COLOR['RESET']}")
        for mod_name, report in master_report.modules.items():
            if report.violations:
                print(f"\n{COLOR['RED']}❌ {mod_name}{COLOR['RESET']} (Layer: {report.layer})")
                for v in report.violations:
                    print(f"   └─ [AST] Baris {v.line}: {v.message}")

    # === DETAIL CYCLES ===
    if inter_cycles:
        print(f"\n{COLOR['RED']}{COLOR['BOLD']}🚨 BAHAYA: SIKLUS DEPENDENSI ANTAR LAYER:{COLOR['RESET']}")
        for idx, chain in enumerate(inter_cycles, 1):
            layers = " → ".join({verifier.identify_layer(m) for m in chain})
            print(f"  Rantai {idx}: {' ➔ '.join(chain)}")
            print(f"          (Layer: {layers})")
    else:
        print(f"\n{COLOR['GREEN']}✅ Tidak ada siklus antar layer yang terdeteksi.{COLOR['RESET']}")

    if intra_cycles and args.verbose:
        print(f"\n{COLOR['YELLOW']}🟡 Siklus Intra Layer (Info - diabaikan):{COLOR['RESET']}")
        for idx, chain in enumerate(intra_cycles, 1):
            layer = verifier.identify_layer(chain[0])
            print(f"  {idx}. {layer}: {' ➔ '.join(chain)}")
        print(f"  {COLOR['CYAN']}Tip: Siklus dalam layer yang sama sering terjadi pada ORM/Domain entities.{COLOR['RESET']}")

    print("-" * 72)
    elapsed = time.monotonic() - start_time
    print(f" ⏱️ Waktu Eksekusi: {elapsed:.3f} detik")

    # === JSON EXPORT ===
    if args.json:
        payload = {
            "score": master_report.score,
            "total_modules": master_report.total_files_scanned,
            "clean_modules": master_report.clean_modules,
            "corrupted_modules": master_report.corrupted_modules,
            "total_ast_violations": master_report.total_ast_violations,
            "inter_layer_cycles": master_report.inter_layer_cycles,
            "intra_layer_cycles": master_report.intra_layer_cycles,
            "details": {
                k: {
                    "file": v.file_path,
                    "layer": v.layer,
                    "violations": [
                        {"line": vi.line, "target": vi.target_module, "message": vi.message}
                        for vi in v.violations
                    ]
                } for k, v in master_report.modules.items() if v.violations
            }
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"{COLOR['GREEN']}✅ Laporan diekspor ke {args.json}{COLOR['RESET']}")

    # Exit code (0 = sukses, 1 = ada pelanggaran)
    has_errors = master_report.total_ast_violations > 0 or len(inter_cycles) > 0
    if args.strict and intra_cycles:
        has_errors = True
    sys.exit(1 if has_errors else 0)

if __name__ == "__main__":
    main()
