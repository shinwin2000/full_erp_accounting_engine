#!/usr/bin/env python3
"""
==============================================================================
         FASTAPI HYBRID ROUTE AUDITOR & FORTRESS VALIDATOR (v1.0)
==============================================================================
Deskripsi : Menggabungkan Analisis Statis (AST) & Analisis Dinamis (Runtime)
            untuk mendeteksi tabrakan rute, router terisolasi (zombie),
            dan inkonsistensi arsitektur secara komprehensif.
==============================================================================
"""

import ast
import sys
import importlib
from pathlib import Path
from typing import Dict, List, Set, Tuple, Any, Optional
from dataclasses import dataclass, asdict

# --- KONFIGURASI NAVIGASI DIREKTORI ---
ROOT = Path(__file__).resolve().parent
DEFAULT_SCAN_DIRS = ["app", "apps", "api", "routers", "modules", "adapters", "infrastructure"]
SKIP_DIRS = {
    "__pycache__", ".mypy_cache", ".pytest_cache", ".git", ".venv", "venv",
    "node_modules", "site-packages", "dist-packages", "tests", "migrations"
}

# --- GRACEFUL COLOR TERMINAL SETUP ---
try:
    import colorama
    colorama.init(autoreset=True)
    C_RED, C_GREEN, C_YELLOW, C_CYAN = colorama.Fore.RED, colorama.Fore.GREEN, colorama.Fore.YELLOW, colorama.Fore.CYAN
    B_BOLD, C_RESET = colorama.Style.BRIGHT, colorama.Style.RESET_ALL
except ImportError:
    C_RED = C_GREEN = C_YELLOW = C_CYAN = B_BOLD = C_RESET = ""

@dataclass
class StaticRouteFinding:
    method: str
    path: str
    line: int
    file_path: str

@dataclass
class AuditReport:
    runtime_total: int = 0
    static_total: int = 0
    collisions: int = 0
    orphaned_routers: int = 0

class RouteFortressValidator:
    def __init__(self, import_path: str = "app.main", app_variable: str = "app", scan_dirs: List[str] = None):
        self.import_path = import_path
        self.app_variable = app_variable
        self.scan_dirs = scan_dirs or DEFAULT_SCAN_DIRS
        
        # State Storage
        self.static_routers: Dict[Tuple[str, str], List[StaticRouteFinding]] = {}
        self.runtime_routes: List[Dict[str, Any]] = []
        self.errors_encountered: List[str] = []
        self.report = AuditReport()

    def log_info(self, msg: str): print(f"{C_CYAN}[INFO]{C_RESET} {msg}")
    def log_success(self, msg: str): print(f"{B_BOLD}{C_GREEN}[SUCCESS]{C_RESET} {msg}")
    def log_warn(self, msg: str): print(f"{B_BOLD}{C_YELLOW}[WARNING]{C_RESET} {msg}")
    def log_error(self, msg: str): print(f"{B_BOLD}{C_RED}[CRITICAL]{C_RESET} {msg}")

    # ==========================================
    # PHASE 1: HARDENED STATIC ANALYSIS (AST)
    # ==========================================
    def _find_py_files(self) -> List[Path]:
        valid_files = []
        # Scan root level first
        for p in ROOT.glob("*.py"):
            if not p.name.startswith(("test_", "setup", "route_")): 
                valid_files.append(p)
        # Scan sub directories
        for d in self.scan_dirs:
            dir_path = ROOT / d
            if dir_path.is_dir():
                for p in dir_path.rglob("*.py"):
                    if not any(part in SKIP_DIRS for part in p.parts) and not p.name.startswith(("test_", "__")):
                        valid_files.append(p)
        return list(set(valid_files))

    def _parse_ast_safely(self, path: Path) -> Optional[ast.AST]:
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
            return ast.parse(src, filename=str(path))
        except Exception as e:
            self.errors_encountered.append(f"Gagal membaca AST file {path.name}: {str(e)}")
            return None

    def run_static_scan(self):
        print(f"\n{B_BOLD}--- [FASE 1] MEMULAI ANALISIS STATIS KODE SUMBER (AST) ---")
        py_files = self._find_py_files()
        self.log_info(f"Menemukan {len(py_files)} file Python untuk diaudit secara statis.")

        for file_path in py_files:
            tree = self._parse_ast_safely(file_path)
            if not tree: continue

            rel_path = str(file_path.relative_to(ROOT)).replace("\\", "/")
            local_routers: Set[str] = set()

            # Deteksi inisialisasi APIRouter
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                    func = node.value.func
                    if (isinstance(func, ast.Name) and func.id in ("APIRouter", "Router")) or \
                       (isinstance(func, ast.Attribute) and func.attr in ("APIRouter", "Router")):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                local_routers.add(target.id)
                                self.static_routers[(rel_path, target.id)] = []

            # Deteksi dekorator rute bisnis
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    for dec in node.decorator_list:
                        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and isinstance(dec.func.value, ast.Name):
                            router_var = dec.func.value.id
                            method = dec.func.attr.upper()
                            
                            if method in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
                                if router_var in local_routers and dec.args:
                                    arg_val = dec.args[0]
                                    if isinstance(arg_val, ast.Constant) and isinstance(arg_val.value, str):
                                        path_val = arg_val.value
                                        finding = StaticRouteFinding(method=method, path=path_val, line=node.lineno, file_path=rel_path)
                                        self.static_routers[(rel_path, router_var)].append(finding)
                                        self.report.static_total += 1

    # ==========================================
    # PHASE 2: ROBUST RUNTIME ANALYSIS (ENGINE)
    # ==========================================
    def run_runtime_scan(self):
        print(f"\n{B_BOLD}--- [FASE 2] MEMULAI AKSES RUNTIME ENGINE FASTAPI ---")
        
        # Injeksi ROOT ke sys.path untuk menghindari ModuleNotFoundError
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))

        try:
            self.log_info(f"Mencoba memuat modul: '{self.import_path}'")
            mod = importlib.import_module(self.import_path)
            
            # Strategi Resolusi Akses Instance FastAPI yang Robust
            raw_app = getattr(mod, self.app_variable, None)
            if not raw_app:
                raise AttributeError(f"Variabel '{self.app_variable}' tidak ditemukan di {self.import_path}")

            # Deteksi jika app dibungkus objek adapter/wrapper (Menangani masalah '_app')
            if hasattr(raw_app, "_app"):
                self.log_info("Deteksi Wrapper Terdeteksi. Mengakses internal '_app' instance.")
                fastapi_instance = raw_app._app
            else:
                fastapi_instance = raw_app

            # Validasi akhir apakah ini benar-benar object FastAPI kelas tinggi
            if not hasattr(fastapi_instance, "routes"):
                # Emergency Scan: Cari secara rekursif atribut yang memiliki '.routes' di dalam modul
                fastapi_instance = None
                for attr_name in dir(mod):
                    candidate = getattr(mod, attr_name)
                    if hasattr(candidate, "routes") and hasattr(candidate, "include_router"):
                        fastapi_instance = candidate
                        self.log_info(f"Sistem otomatis memulihkan instance FastAPI dari atribut: '{attr_name}'")
                        break
                
                if not fastapi_instance:
                    raise TypeError("Objek yang ditemukan bukan instance FastAPI yang valid.")

            # Ekstraksi Rute Nyata
            from fastapi.routing import APIRoute
            actual_routes = [r for r in fastapi_instance.routes if isinstance(r, APIRoute)]
            self.report.runtime_total = len(actual_routes)
            self.log_success(f"Koneksi sukses. Total {len(actual_routes)} rute aktif di memori.")

            for r in actual_routes:
                self.runtime_routes.append({
                    "path": r.path,
                    "methods": list(r.methods),
                    "name": r.name,
                    "endpoint_quality": f"{r.endpoint.__module__}.{r.endpoint.__name__}"
                })

        except Exception as e:
            self.log_error(f"FAIL RUNTIME SCAN: {str(e)}")
            self.log_warn("Pastikan semua Environment Variables (ENV) dan database mock sudah aktif.")
            self.errors_encountered.append(f"Runtime Crash: {str(e)}")

    # ==========================================
    # PHASE 3: HYBRID CROSS-REFERENCE & AUDIT
    # ==========================================
    def execute_audit_report(self) -> int:
        print(f"\n{B_BOLD}--- [FASE 3] KONSOLIDASI & CROSS-REFERENCE AUDIT ---")
        
        # 1. Deteksi Tabrakan di Level Runtime (Akurasi 100%)
        seen_runtime: Dict[Tuple[str, str], str] = {}
        runtime_collisions = []

        for r in self.runtime_routes:
            for method in r["methods"]:
                key = (r["path"], method.upper())
                if key in seen_runtime:
                    runtime_collisions.append((key, seen_runtime[key], r["name"]))
                else:
                    seen_runtime[key] = r["name"]

        if runtime_collisions:
            self.log_error(f"TERDETEKSI {len(runtime_collisions)} TABRAKAN RUTE KRITIS DI RUNTIME!")
            for key, old_name, new_name in runtime_collisions:
                print(f"   {C_RED}➔{C_RESET} Konflik Endpoint {key}: Pertama '{old_name}', ditimpa oleh '{new_name}'")
            self.report.collisions = len(runtime_collisions)
        else:
            self.log_success("Evaluasi Runtime Bersih: Nol tabrakan rute aktif.")

        # 2. Deteksi Router Terisolasi / Zombie (Dari AST)
        zombie_routers = []
        for (file_p, r_var), static_routes in self.static_routers.items():
            if not static_routes:
                zombie_routers.append(f"File: {file_p} -> variable: {r_var}")
        
        if zombie_routers:
            print("")
            self.log_warn(f"Terdeteksi {len(zombie_routers)} APIRouter mandul/terisolasi (0 rute terikat):")
            for z in zombie_routers[:5]:
                print(f"   {C_YELLOW}⚠{C_RESET} {z}")
            if len(zombie_routers) > 5:
                print(f"   ... dan {len(zombie_routers)-5} router kosong lainnya.")
            self.report.orphaned_routers = len(zombie_routers)

        # Print Summary Panel
        print("\n" + "="*60)
        print(f"{B_BOLD}             FORTRESS SUMMARY REPORT{C_RESET}")
        print("="*60)
        print(f" Rute Aktif Terdaftar (Runtime) : {self.report.runtime_total}")
        print(f" Definisi Rute Terlacak (AST)   : {self.report.static_total}")
        print(f" Tabrakan Rute Kritis           : {C_RED if self.report.collisions else C_GREEN}{self.report.collisions}{C_RESET}")
        print(f" Instance Router Zombie/Kosong  : {C_YELLOW if self.report.orphaned_routers else C_GREEN}{self.report.orphaned_routers}{C_RESET}")
        print(f" Gangguan Sistem Internal       : {len(self.errors_encountered)}")
        print("="*60)

        if self.report.collisions > 0:
            return 1
        return 0

if __name__ == "__main__":
    import argparse  # Diletakkan di paling atas sebelum dipanggil
    
    parser = argparse.ArgumentParser(description="Fortress Hybrid Route Validator")
    parser.add_argument("--import-path", default="app.main", help="Path modul python utama aplikasi FastAPI")
    parser.add_argument("--app-var", default="app", help="Nama variabel instance FastAPI")
    args = parser.parse_args()

    validator = RouteFortressValidator(import_path=args.import_path, app_variable=args.app_var)
    validator.run_static_scan()
    validator.run_runtime_scan()
    exit_code = validator.execute_audit_report()
    sys.exit(exit_code)