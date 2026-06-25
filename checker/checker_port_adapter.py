#!/usr/bin/env python3
"""
PORT-ADAPTER ARCHITECTURE VERIFIER - V7 (DASHBOARD COMPILER)
Menampilkan metrik komprehensif: Port yang lolos, Port yang gagal, 
serta tingkat persentase kepatuhan arsitektur sistem secara riil.
"""

import ast
import sys
from pathlib import Path
from typing import Dict, Set

ROOT = Path(__file__).resolve().parent
PORTS_DIR = ROOT / "ports"
ADAPTERS_DIR = ROOT / "adapters"

GLOBAL_REGISTRY: Dict[str, dict] = {}


class CodebaseParser:
    @staticmethod
    def parse_directory(directory_path: Path, layer: str):
        if not directory_path.exists():
            return
            
        for file_path in directory_path.rglob("*.py"):
            if file_path.name == "__init__.py" or "__pycache__" in str(file_path):
                continue
                
            try:
                content = file_path.read_text(encoding="utf-8")
                tree = compile(content, str(file_path), 'exec', ast.PyCF_ONLY_AST)
            except Exception as e:
                print(f"🚨 CRITICAL PYTHON SYNTAX ERROR!")
                print(f"   Path: {file_path}")
                print(f"   Detail: {str(e)}")
                sys.exit(1)

            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                
                if layer == "ADAPTER" and node.name.endswith(("Error", "Exception", "Factory")):
                    continue

                bases = set()
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        bases.add(base.id)
                    elif isinstance(base, ast.Attribute):
                        bases.add(base.attr)
                    elif isinstance(base, ast.Subscript):
                        if isinstance(base.value, ast.Name):
                            bases.add(base.value.id)

                local_methods = {item.name for item in node.body 
                                 if isinstance(item, ast.FunctionDef) and not item.name.startswith("_")}

                GLOBAL_REGISTRY[node.name] = {
                    "layer": layer,
                    "file": file_path.name,
                    "relative_path": str(file_path.relative_to(ROOT)),
                    "bases": bases,
                    "local_methods": local_methods,
                    "resolved_bases": set(),
                    "resolved_methods": set()
                }


def resolve_graph(class_name: str, visited: Set[str] = None):
    if visited is None:
        visited = set()
    if class_name in visited:
        return
    visited.add(class_name)

    info = GLOBAL_REGISTRY.get(class_name)
    if not info:
        return

    if info["resolved_bases"]:
        return

    info["resolved_bases"] = set(info["bases"])
    info["resolved_methods"] = set(info["local_methods"])

    for base in info["bases"]:
        resolve_graph(base, visited)
        base_info = GLOBAL_REGISTRY.get(base)
        if base_info:
            info["resolved_bases"].update(base_info["resolved_bases"])
            info["resolved_methods"].update(base_info["resolved_methods"])


def get_core_domain_name(name: str) -> str:
    return name.replace("Port", "").replace("Protocol", "").replace("Repository", "").replace("SQLAlchemy", "").replace("Kafka", "").replace("Impl", "")


def main():
    print("=" * 100)
    print(" ⚡ SOVEREIGN ARCH-ENGINE COMPILER & COMPLIANCE DASHBOARD V7 ⚡")
    print("=" * 100)

    CodebaseParser.parse_directory(PORTS_DIR, "PORT")
    CodebaseParser.parse_directory(ADAPTERS_DIR, "ADAPTER")

    for class_name in list(GLOBAL_REGISTRY.keys()):
        resolve_graph(class_name)

    all_ports = {k: v for k, v in GLOBAL_REGISTRY.items() 
                 if v["layer"] == "PORT" and (k.endswith("Port") or k.endswith("Protocol"))}
    all_adapters = {k: v for k, v in GLOBAL_REGISTRY.items() if v["layer"] == "ADAPTER"}

    passed_ports = []
    unmatched_ports = []
    contract_violations = []

    for port_name, port_info in all_ports.items():
        matched_adapters = {}
        core_port = get_core_domain_name(port_name).lower()

        for adapter_name, adapter_info in all_adapters.items():
            core_adapter = get_core_domain_name(adapter_name).lower()
            
            is_explicit = port_name in adapter_info["resolved_bases"]
            is_implicit_match = (core_port == core_adapter or core_port in adapter_name.lower())
            
            if is_explicit or is_implicit_match:
                matched_adapters[adapter_name] = adapter_info

        if not matched_adapters:
            unmatched_ports.append((port_name, port_info["relative_path"]))
            continue

        port_methods = port_info["resolved_methods"]
        port_has_violation = False
        
        for adapter_name, adapter_info in matched_adapters.items():
            adapter_methods = adapter_info["resolved_methods"]
            missing_methods = port_methods - adapter_methods
            
            if missing_methods:
                port_has_violation = True
                contract_violations.append({
                    "port": port_name,
                    "port_file": port_info["relative_path"],
                    "adapter": adapter_name,
                    "adapter_file": adapter_info["relative_path"],
                    "missing": missing_methods
                })
        
        if not port_has_violation:
            passed_ports.append((port_name, port_info["relative_path"], list(matched_adapters.keys())))

    # --- RENDER DASHBOARD METRIKS ---
    total_ports_count = len(all_ports)
    passed_count = len(passed_ports)
    failed_count = len(unmatched_ports) + len(set(v['port'] for v in contract_violations))
    compliance_rate = (passed_count / total_ports_count * 100) if total_ports_count > 0 else 0

    print(f"📊 METRICS SUMMARY:")
    print(f"   ▪️ Total Port Interface Terdaftar : {total_ports_count}")
    print(f"   ▪️ Total Active Adapters Terurai : {len(all_adapters)}")
    print(f"   🟩 Total Port LOLOS Kontrak      : {passed_count}")
    print(f"   🟥 Total Port GAGAL/Bolong       : {failed_count}")
    print(f"   📈 Architectural Compliance Rate : {compliance_rate:.1f}%")
    print("-" * 100)

    # 1. SEKSI PASSED PORTS
    print(f"\n🟩 PASSED PORTS ({passed_count}/{total_ports_count}) - KONTRAK TERPENUHI:")
    for port, path, adapters in sorted(passed_ports):
        adapters_str = ", ".join(adapters)
        print(f"  ✅ [{port}]")
        print(f"     📍 Path     : {path}")
        print(f"     🔗 Bound to : {adapters_str}")

    print("-" * 100)

    # 2. SEKSI UNMATCHED PORTS
    if unmatched_ports:
        print(f"\n🟥 UNMATCHED PORTS ({len(unmatched_ports)}) - BELUM ADA IMPLEMENTASI INFRASTRUKTUR:")
        for port, file in sorted(unmatched_ports):
            print(f"  ❌ {port}")
            print(f"     📍 File Port: {file}")

    # 3. SEKSI CONTRACT VIOLATIONS
    if contract_violations:
        print(f"\n🚨 CONTRACT VIOLATIONS ({len(contract_violations)}) - IMPLEMENTASI CACAT/TIDAK LENGKAP:")
        for v in contract_violations:
            print(f"  ⚠️  {v['port']} ➔ Gagal dipenuhi oleh kelas [{v['adapter']}]")
            print(f"     📍 File Port   : {v['port_file']}")
            print(f"     📍 File Adapter: {v['adapter_file']}")
            print(f"     ❌ Fungsi yang Hilang: {', '.join(v['missing'])}")

    print("\n" + "=" * 100)
    if failed_count == 0:
        print("🎉 EXCELLENT: 100% Kepatuhan Arsitektur Tercapai. Engine Siap Audit.")
        sys.exit(0)
    else:
        print(f"🛑 AUDIT STATUS: GAGAL. Selesaikan {failed_count} masalah di atas untuk mengamankan integritas sistem.")
        sys.exit(1)


if __name__ == "__main__":
    main()