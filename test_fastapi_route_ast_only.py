#!/usr/bin/env python3
"""
test_fastapi_route.py — FASTAPI ROUTE VALIDATOR (Diagnostics Edition - v5)
==============================================================================
Menyediakan audit rute lintas-file sekaligus mencetak struktur internal (AST dump)
dari file yang terisolasi untuk analisis forensik arsitektur sistem.
"""

import ast
import sys
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass

ROOT = Path(__file__).resolve().parent

DEFAULT_SCAN_DIRS = [
    "adapters", "app", "application", "bootstrap", "domain", 
    "infrastructure", "kernel", "ports", "api"
]

SKIP_DIRS = {
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".git", ".venv", "venv", "node_modules", ".tox", ".cache",
    "site-packages", "dist-packages", "dist", "build", "uv",
    "tests", "migrations", "docs", "deployment", "scripts"
}

HEALTH_ENDPOINTS = {
    ("/ping", "GET"), ("/health", "GET"), ("/healthz", "GET"),
    ("/ready", "GET"), ("/live", "GET"), ("/info", "GET"),
    ("/metrics", "GET"), ("/docs", "GET"), ("/openapi.json", "GET"),
    ("/", "GET"),
}

try:
    import colorama
    colorama.init(autoreset=True)
    RED = colorama.Fore.RED
    GREEN = colorama.Fore.GREEN
    YELLOW = colorama.Fore.YELLOW
    CYAN = colorama.Fore.CYAN
    BOLD = colorama.Style.BRIGHT
    RESET = colorama.Style.RESET_ALL
except ImportError:
    RED = GREEN = YELLOW = CYAN = BOLD = RESET = ""

@dataclass
class Finding:
    severity: str
    file: str
    line: int
    message: str
    recommendation: str = ""
    detail: str = ""

@dataclass
class RawFileInfo:
    rel_path: str
    stem: str
    tree: ast.AST
    router_vars: Set[str]
    imported_routers: Dict[str, Tuple[str, str]]

# ─── Core Stateful Scanner Engine ─────────────────────────────────────────────

def get_ast_tree(path: Path) -> Optional[ast.AST]:
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        return ast.parse(src, filename=str(path))
    except Exception:
        return None

def scan_file_phase1(path: Path) -> Optional[RawFileInfo]:
    tree = get_ast_tree(path)
    if tree is None:
        return None
        
    rel_path = str(path.relative_to(ROOT)).replace("\\", "/")
    router_vars = set()
    imported_routers = {}
    
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            is_router_call = False
            if isinstance(func, ast.Name) and func.id in ("APIRouter", "Router"):
                is_router_call = True
            elif isinstance(func, ast.Attribute) and func.attr in ("APIRouter", "Router"):
                is_router_call = True
                
            if is_router_call:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        router_vars.add(target.id)
                        
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if "router" in alias.name:
                    local_name = alias.asname if alias.asname else alias.name
                    imported_routers[local_name] = (node.module, alias.name)
                    
    return RawFileInfo(rel_path=rel_path, stem=path.stem, tree=tree, router_vars=router_vars, imported_routers=imported_routers)

def find_all_files(scan_dirs: List[str] = None) -> List[Path]:
    if scan_dirs is None:
        scan_dirs = DEFAULT_SCAN_DIRS
    found = []
    for p in ROOT.glob("*.py"):
        if not p.name.startswith(("test_", "main_")): found.append(p)
    for d in scan_dirs:
        dir_path = ROOT / d
        if dir_path.is_dir():
            for p in dir_path.rglob("*.py"):
                if not any(part in SKIP_DIRS for part in p.parts) and not p.name.startswith(("test_", "__")):
                    found.append(p)
    return sorted(set(found))

def diagnose_file(file_path: str):
    """Membongkar isi internal file untuk melihat ada apa saja di dalamnya secara riil."""
    p = ROOT / file_path
    if not p.exists(): return
    print(f"\n{CYAN}[DIAGNOSTICS]{RESET} Pemisahan Struktur Struktur Statis untuk: {file_path}")
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
        print(f"  -> Total Baris Kode: {len(lines)}")
        imports = [l for l in lines if l.startswith(("import ", "from "))]
        print(f"  -> Statement Impor Terdeteksi ({len(imports)}):")
        for imp in imports[:5]: print(f"     {imp}")
        
        # Ambil top level assignment atau fungsi
        tree = get_ast_tree(p)
        if tree:
            top_level_nodes = [node.__class__.__name__ for node in tree.body]
            print(f"  -> Komponen Top-Level AST: {top_level_nodes[:10]}")
    except Exception as e:
        print(f"  -> Gagal menganalisis berkas: {e}")

def validate_routes(verbose: bool = False, json_out: Optional[str] = None, scan_dirs: List[str] = None) -> int:
    print(f"{BOLD}{CYAN}╔{'═'*78}╗{RESET}")
    print(f"{BOLD}{CYAN}║{' '*15}FASTAPI ROUTE VALIDATOR — DIAGNOSTICS SCAN v5{' '*16}║{RESET}")
    print(f"{BOLD}{CYAN}╚{'═'*78}╝{RESET}\n")

    all_paths = find_all_files(scan_dirs)
    file_map: Dict[str, RawFileInfo] = {}
    
    for p in all_paths:
        info = scan_file_phase1(p)
        if info: file_map[info.rel_path] = info

    router_registry: Dict[Tuple[str, str], List[Tuple[str, str, int, str]]] = {}
    composition_registry: Set[Tuple[str, str]] = set()

    for rel_path, info in file_map.items():
        for r_var in info.router_vars:
            router_registry[(rel_path, r_var)] = []

    def resolve_module_to_file(module_str: str) -> Optional[str]:
        parts = module_str.split('.')
        pot_path = "/".join(parts) + ".py"
        if pot_path in file_map: return pot_path
        pot_init = "/".join(parts) + "/__init__.py"
        if pot_init in file_map: return pot_init
        for k in file_map.keys():
            if k.replace('.py', '').replace('/__init__', '').endswith(("/" + "/".join(parts))):
                return k
        return None

    # Phase 2: Analisis Tautan Node Lintas Batas File
    for rel_path, info in file_map.items():
        for node in ast.walk(info.tree):
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and isinstance(dec.func.value, ast.Name):
                        local_var = dec.func.value.id
                        method = dec.func.attr.upper()
                        
                        if method in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
                            if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                                path_val = dec.args[0].value
                                if local_var in info.router_vars:
                                    router_registry[(rel_path, local_var)].append((method, path_val, node.lineno, rel_path))
                                elif local_var in info.imported_routers:
                                    mod_str, remote_name = info.imported_routers[local_var]
                                    target_file = resolve_module_to_file(mod_str)
                                    if target_file and (target_file, remote_name) in router_registry:
                                        router_registry[(target_file, remote_name)].append((method, path_val, node.lineno, rel_path))

            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                local_var = node.func.value.id
                if node.func.attr == "include_router":
                    if local_var in info.router_vars:
                        composition_registry.add((rel_path, local_var))
                    elif local_var in info.imported_routers:
                        mod_str, remote_name = info.imported_routers[local_var]
                        target_file = resolve_module_to_file(mod_str)
                        if target_file: composition_registry.add((target_file, remote_name))
                elif node.func.attr == "add_api_route":
                    path_val = "/unknown"
                    method = "ANY"
                    if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                        path_val = node.args[0].value
                    for kw in node.keywords:
                        if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Set, ast.Tuple)):
                            elts = [elt.value for elt in kw.value.elts if isinstance(elt, ast.Constant)]
                            if elts: method = "/".join(elts).upper()
                        elif kw.arg == "path" and isinstance(kw.value, ast.Constant):
                            path_val = kw.value.value
                            
                    if local_var in info.router_vars:
                        router_registry[(rel_path, local_var)].append((method, path_val, node.lineno, rel_path))
                    elif local_var in info.imported_routers:
                        mod_str, remote_name = info.imported_routers[local_var]
                        target_file = resolve_module_to_file(mod_str)
                        if target_file and (target_file, remote_name) in router_registry:
                            router_registry[(target_file, remote_name)].append((method, path_val, node.lineno, rel_path))

    findings: List[Finding] = []
    global_business_routes: Dict[Tuple[str, str], List[Tuple[str, str, int]]] = {}
    
    empty_routers_list = []
    active_routers_count = 0

    for (owner_file, r_var), routes_list in router_registry.items():
        if not routes_list and (owner_file, r_var) not in composition_registry:
            empty_routers_list.append((owner_file, r_var))
            findings.append(Finding(
                severity="WARNING", file=owner_file, line=0,
                message=f"Router instance '{r_var}' is statically empty (0 bound routes mapped).",
                recommendation="Jika pendaftaran rute menggunakan Refleksi/Runtime Scan Engine, peringatan ini aman diabaikan."
            ))
        else:
            active_routers_count += 1
            for method, path, line, consumer_file in routes_list:
                if (path, method) in HEALTH_ENDPOINTS: continue
                global_business_routes.setdefault((path, method), []).append((owner_file, consumer_file, line))

    # Cek tabrakan rute bisnis kritis
    for (path, method), locations in global_business_routes.items():
        if len(locations) > 1:
            trace_items = [f"{own} ({cons}:{l})" for own, cons, l in locations]
            findings.append(Finding(
                severity="CRITICAL", file=locations[0][0], line=locations[0][2],
                message=f"Collision detected: Route {method} '{path}' registered multiple times!",
                detail=f"Traced at: {', '.join(trace_items)}"
            ))

    critical = [f for f in findings if f.severity == "CRITICAL"]
    warnings = [f for f in findings if f.severity == "WARNING"]

    if critical:
        print(f"{RED}{BOLD}🔴 CRITICAL ISSUES ({len(critical)}){RESET}")
        for f in critical: print(f"  {RED}✖{RESET} {f.file} -> {f.message}\n      📌 {f.detail}")
    else:
        print(f"{GREEN}{BOLD}✅ CRITICAL (0) - Tidak ada tabrakan endpoint bisnis lintas domain.{RESET}")

    if warnings:
        print(f"\n{YELLOW}{BOLD}⚠️  WARNINGS ({len(warnings)}){RESET}")
        for f in warnings[:5]:
            print(f"  {YELLOW}⚠{RESET} {f.file} -> {f.message}")
        if len(warnings) > 5:
            print(f"   ... dan {len(warnings)-5} modul router terisolasi lainnya.")

    # Jalankan pemeriksaan forensik otomatis pada sampel file peringatan pertama
    if empty_routers_list:
        diagnose_file(empty_routers_list[0][0])

    print("\n" + "═" * 80)
    print(f"{BOLD}SUMMARY — ARCHITECTURE FORENSIC REPORT{RESET}")
    print(f"  Total verified router objects:   {len(router_registry)}")
    print(f"  Statically integrated routers:   {active_routers_count}")
    print(f"  Statically empty / isolated:     {len(empty_routers_list)}")
    print(f"  Total resolved core routes:      {sum(len(v) for v in router_registry.values())}")
    print("═" * 80)

    return 1 if critical else 0

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FastAPI Diagnostics Validator")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--dir", action="append")
    args = parser.parse_args()
    sys.exit(validate_routes(verbose=args.verbose, scan_dirs=args.dir))