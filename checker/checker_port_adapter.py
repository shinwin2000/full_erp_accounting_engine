#!/usr/bin/env python3
"""
PORT-ADAPTER ARCHITECTURE VERIFIER - V8 (AKURAT)
Menggunakan algoritma pencocokan yang sama dengan checker_dashboard_port_status.py
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # karena checker ada di subfolder

# fallback jika tidak ketemu
if not (ROOT / "ports").exists():
    ROOT = Path(__file__).resolve().parent

PORTS_DIR = ROOT / "ports"
ADAPTERS_DIR = ROOT / "adapters"
INFRA_DIR = ROOT / "infrastructure"

GLOBAL_REGISTRY: dict[str, dict] = {}

EXCLUDE_PORTS = {"BasePort", "BaseRepository", "BaseProtocol", "Port", "Repository", "Protocol"}


def parse_directory(directory_path: Path, layer: str):
    if not directory_path.exists():
        return
    for file_path in directory_path.rglob("*.py"):
        if file_path.name == "__init__.py" or "__pycache__" in str(file_path):
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    name = node.name
                    if name in EXCLUDE_PORTS or name.startswith("_"):
                        continue
                    # Port hanya yang berakhiran Port/Protocol
                    if layer == "PORT" and not (name.endswith("Port") or name.endswith("Protocol")):
                        continue
                    # Adapter: skip exception/error/factory
                    if layer == "ADAPTER" and name.endswith(("Error", "Exception", "Factory")):
                        continue
                    bases = set()
                    for b in node.bases:
                        if isinstance(b, ast.Name):
                            bases.add(b.id)
                        elif isinstance(b, ast.Attribute):
                            bases.add(b.attr)
                    methods = set()
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if not item.name.startswith("_"):
                                methods.add(item.name)
                    GLOBAL_REGISTRY[name] = {
                        "layer": layer,
                        "file": str(file_path.relative_to(ROOT)),
                        "bases": bases,
                        "methods": methods,
                        "resolved_methods": set()
                    }
        except Exception:
            continue


def resolve_methods(class_name: str, visited: set[str] = None):
    if visited is None:
        visited = set()
    if class_name in visited:
        return
    visited.add(class_name)
    info = GLOBAL_REGISTRY.get(class_name)
    if not info:
        return
    if info["resolved_methods"]:
        return
    info["resolved_methods"] = set(info["methods"])
    for base in info["bases"]:
        resolve_methods(base, visited)
        base_info = GLOBAL_REGISTRY.get(base)
        if base_info:
            info["resolved_methods"].update(base_info["resolved_methods"])


def main():
    print("=" * 100)
    print(" ⚡ SOVEREIGN ARCH-ENGINE COMPILER & COMPLIANCE DASHBOARD V8 (AKURAT) ⚡")
    print("=" * 100)
    print(f"📂 Project Root : {ROOT}")

    parse_directory(PORTS_DIR, "PORT")
    parse_directory(ADAPTERS_DIR, "ADAPTER")
    parse_directory(INFRA_DIR, "ADAPTER")

    # Resolusi inheritance
    for cls in list(GLOBAL_REGISTRY.keys()):
        resolve_methods(cls)

    ports = {k: v for k, v in GLOBAL_REGISTRY.items() if v["layer"] == "PORT"}
    adapters = {k: v for k, v in GLOBAL_REGISTRY.items() if v["layer"] == "ADAPTER"}

    # Untuk setiap port, cari adapter yang secara eksplisit mewarisi port
    port_to_adapter = {}
    for port_name, port_info in ports.items():
        best_adapter = None
        best_score = -1
        for adp_name, adp_info in adapters.items():
            # Cek inheritance eksplisit
            if port_name in adp_info["bases"]:
                score = 1000
            else:
                # Cek kemiripan nama (fallback)
                core_port = port_name.replace("Port", "").replace("Protocol", "").lower()
                core_adp = adp_name.replace("SQLAlchemy", "").replace("Kafka", "").replace("Impl", "").lower()
                if core_port in core_adp or core_adp in core_port:
                    score = 500
                else:
                    continue
            # Hitung method coverage
            port_methods = port_info["resolved_methods"]
            adp_methods = adp_info["resolved_methods"]
            if port_methods:
                covered = len(port_methods.intersection(adp_methods))
                score += covered * 30
                missing = port_methods - adp_methods
                score -= len(missing) * 20
            else:
                score += 100  # marker interface
            if score > best_score:
                best_score = score
                best_adapter = (adp_name, adp_info, missing if port_methods else set())

        if best_adapter and best_score >= 200:
            port_to_adapter[port_name] = best_adapter
        else:
            port_to_adapter[port_name] = None

    # Hitung statistik
    total = len(ports)
    passed = sum(1 for v in port_to_adapter.values() if v is not None and not v[2])
    partial = sum(1 for v in port_to_adapter.values() if v is not None and v[2])
    missing = sum(1 for v in port_to_adapter.values() if v is None)

    print("\n📊 METRICS SUMMARY:")
    print(f"   ▪️ Total Port Interface : {total}")
    print(f"   🟩 REAL (lengkap)      : {passed}")
    print(f"   🟨 PARTIAL (kurang)    : {partial}")
    print(f"   🟥 MISSING (tak ada)   : {missing}")
    print(f"   📈 Compliance Rate     : {(passed/total*100):.1f}%")
    print("-" * 100)

    # Tampilkan detail
    for port_name in sorted(port_to_adapter.keys()):
        info = port_to_adapter[port_name]
        if info is None:
            print(f"❌ {port_name} → TIDAK ADA ADAPTER")
            print(f"   📍 File: {ports[port_name]['file']}")
        else:
            adp_name, adp_info, missing_methods = info
            if missing_methods:
                print(f"⚠️  {port_name} → PARTIAL (Adapter: {adp_name})")
                print(f"   📍 File Port: {ports[port_name]['file']}")
                print(f"   📍 File Adapter: {adp_info['file']}")
                print(f"   ❌ Missing: {', '.join(sorted(missing_methods))}")
            else:
                print(f"✅ {port_name} → {adp_name}")
                print(f"   📍 File Port: {ports[port_name]['file']}")
                print(f"   📍 File Adapter: {adp_info['file']}")
        print("-" * 100)

    if missing > 0 or partial > 0:
        print("🛑 AUDIT STATUS: GAGAL. Selesaikan port yang PARTIAL/MISSING.")
        sys.exit(1)
    else:
        print("🎉 EXCELLENT: 100% Kepatuhan Arsitektur Tercapai. Engine Siap Audit.")
        sys.exit(0)


if __name__ == "__main__":
    main()
