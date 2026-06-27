#!/usr/bin/env python3
"""
==============================================================================
         FASTAPI HYBRID ROUTE AUDITOR & FORTRESS VALIDATOR (v2.3)
==============================================================================
Deskripsi : Menggabungkan Analisis Statis (AST) & Analisis Dinamis (Runtime)
            untuk mendeteksi tabrakan rute, router terisolasi (zombie),
            dan inkonsistensi arsitektur secara komprehensif.
==============================================================================
"""

import ast
import importlib
import sys
import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# --- KONFIGURASI NAVIGASI DIREKTORI ---
def detect_project_root() -> Path:
    current = Path(__file__).resolve().parent
    markers = ["pyproject.toml", "setup.py", "setup.cfg", ".git", "manage.py", "requirements.txt"]
    for _ in range(6):
        if any((current / marker).exists() for marker in markers):
            return current
        current = current.parent
    return Path(__file__).resolve().parent.parent

PROJECT_ROOT = detect_project_root()
DEFAULT_SCAN_DIRS = ["app", "apps", "api", "routers", "modules", "adapters", "infrastructure"]
SKIP_DIRS = {
    "__pycache__", ".mypy_cache", ".pytest_cache", ".git", ".venv", "venv",
    "node_modules", "site-packages", "dist-packages", "tests", "migrations",
    "checker",
}

# --- WHITELIST UNTUK ZOMBIE ROUTER (false positive) ---
# Mendukung wildcard: "app/*" untuk semua file di folder app
# atau "adapters/primary_api/v1/*" untuk semua router di v1
ZOMBIE_WHITELIST = [
    "app/*",                                    # semua router di app/main.py dan lainnya
    "adapters/primary_api/common/*",           # router factory
    "adapters/primary_api/v1/*",               # semua router versi 1 (false positive)
    "adapters/primary_api/webhook_receiver_adapter.py",
    "adapters/coretax_djp/*",                  # semua router di coretax_djp
    # Tambahkan pola lain jika diperlukan
]

# Tambahkan root ke sys.path
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
    def __init__(self, import_path: str = "app.main", app_variable: str = "app", 
                 scan_dirs: list[str] = None, ignore_zombie: bool = False):
        self.import_path = import_path
        self.app_variable = app_variable
        self.scan_dirs = scan_dirs or DEFAULT_SCAN_DIRS
        self.project_root = PROJECT_ROOT
        self.ignore_zombie = ignore_zombie

        # State Storage
        self.static_routers: dict[tuple[str, str], list[StaticRouteFinding]] = {}
        self.runtime_routes: list[dict[str, Any]] = []
        self.errors_encountered: list[str] = []
        self.report = AuditReport()

    def log_info(self, msg: str): print(f"{C_CYAN}[INFO]{C_RESET} {msg}")
    def log_success(self, msg: str): print(f"{B_BOLD}{C_GREEN}[SUCCESS]{C_RESET} {msg}")
    def log_warn(self, msg: str): print(f"{B_BOLD}{C_YELLOW}[WARNING]{C_RESET} {msg}")
    def log_error(self, msg: str): print(f"{B_BOLD}{C_RED}[CRITICAL]{C_RESET} {msg}")

    def _is_whitelisted(self, file_path: str) -> bool:
        """Cek apakah file ada di daftar whitelist (mendukung wildcard)."""
        for pattern in ZOMBIE_WHITELIST:
            if fnmatch.fnmatch(file_path, pattern):
                return True
        return False

    # ==========================================
    # PHASE 1: HARDENED STATIC ANALYSIS (AST)
    # ==========================================
    def _find_py_files(self) -> list[Path]:
        valid_files = []
        for p in self.project_root.glob("*.py"):
            if not p.name.startswith(("test_", "setup", "route_")):
                valid_files.append(p)
        for d in self.scan_dirs:
            dir_path = self.project_root / d
            if dir_path.is_dir():
                for p in dir_path.rglob("*.py"):
                    if not any(part in SKIP_DIRS for part in p.parts) and not p.name.startswith(("test_", "__")):
                        valid_files.append(p)
        return list(set(valid_files))

    def _parse_ast_safely(self, path: Path) -> ast.AST | None:
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
            return ast.parse(src, filename=str(path))
        except Exception as e:
            self.errors_encountered.append(f"Gagal membaca AST file {path.name}: {e!s}")
            return None

    def run_static_scan(self):
        print(f"\n{B_BOLD}--- [FASE 1] MEMULAI ANALISIS STATIS KODE SUMBER (AST) ---")
        py_files = self._find_py_files()
        self.log_info(f"Menemukan {len(py_files)} file Python untuk diaudit secara statis.")

        for file_path in py_files:
            tree = self._parse_ast_safely(file_path)
            if not tree: continue

            rel_path = str(file_path.relative_to(self.project_root)).replace("\\", "/")
            local_routers: set[str] = set()

            # Deteksi inisialisasi APIRouter di top-level
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                    func = node.value.func
                    if (isinstance(func, ast.Name) and func.id in ("APIRouter", "Router")) or \
                       (isinstance(func, ast.Attribute) and func.attr in ("APIRouter", "Router")):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                local_routers.add(target.id)
                                self.static_routers[(rel_path, target.id)] = []

            # Deteksi dekorator rute
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

        if str(self.project_root) not in sys.path:
            sys.path.insert(0, str(self.project_root))

        try:
            self.log_info(f"Mencoba memuat modul: '{self.import_path}'")
            mod = importlib.import_module(self.import_path)

            raw_app = getattr(mod, self.app_variable, None)
            if not raw_app:
                raise AttributeError(f"Variabel '{self.app_variable}' tidak ditemukan di {self.import_path}")

            if hasattr(raw_app, "_app"):
                self.log_info("Deteksi Wrapper Terdeteksi. Mengakses internal '_app' instance.")
                fastapi_instance = raw_app._app
            else:
                fastapi_instance = raw_app

            if not hasattr(fastapi_instance, "routes"):
                fastapi_instance = None
                for attr_name in dir(mod):
                    candidate = getattr(mod, attr_name)
                    if hasattr(candidate, "routes") and hasattr(candidate, "include_router"):
                        fastapi_instance = candidate
                        self.log_info(f"Sistem otomatis memulihkan instance FastAPI dari atribut: '{attr_name}'")
                        break

                if not fastapi_instance:
                    raise TypeError("Objek yang ditemukan bukan instance FastAPI yang valid.")

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

        except ImportError as e:
            self.log_error(f"FAIL RUNTIME SCAN: Modul '{self.import_path}' tidak ditemukan. Pastikan root proyek benar: {self.project_root}")
            self.errors_encountered.append(f"ImportError: {e!s}")
        except AttributeError as e:
            self.log_error(f"FAIL RUNTIME SCAN: {e!s}")
            self.errors_encountered.append(f"AttributeError: {e!s}")
        except Exception as e:
            self.log_error(f"FAIL RUNTIME SCAN: {e!s}")
            self.errors_encountered.append(f"Runtime Crash: {e!s}")

    # ==========================================
    # PHASE 3: HYBRID CROSS-REFERENCE & AUDIT
    # ==========================================
    def execute_audit_report(self) -> int:
        print(f"\n{B_BOLD}--- [FASE 3] KONSOLIDASI & CROSS-REFERENCE AUDIT ---")

        # 1. Deteksi Tabrakan Runtime
        seen_runtime: dict[tuple[str, str], str] = {}
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

        # 2. Deteksi Router Terisolasi / Zombie (Dengan Whitelist)
        zombie_routers = []
        whitelisted_zombies = []

        for (file_p, r_var), static_routes in self.static_routers.items():
            if not static_routes:
                if self._is_whitelisted(file_p):
                    whitelisted_zombies.append(f"{file_p} -> {r_var}")
                else:
                    zombie_routers.append(f"File: {file_p} -> variable: {r_var}")

        # Tampilkan whitelisted zombie sebagai info
        if whitelisted_zombies and not self.ignore_zombie:
            self.log_info(f"⚠️ {len(whitelisted_zombies)} router di-whitelist (diabaikan karena false positive):")
            for z in whitelisted_zombies[:3]:
                print(f"   {C_CYAN}ℹ{C_RESET} {z}")
            if len(whitelisted_zombies) > 3:
                print(f"   ... dan {len(whitelisted_zombies)-3} lainnya (lihat ZOMBIE_WHITELIST)")

        if zombie_routers and not self.ignore_zombie:
            print("")
            self.log_warn(f"Terdeteksi {len(zombie_routers)} APIRouter mandul/terisolasi (0 rute terikat):")
            for z in zombie_routers[:5]:
                print(f"   {C_YELLOW}⚠{C_RESET} {z}")
            if len(zombie_routers) > 5:
                print(f"   ... dan {len(zombie_routers)-5} router kosong lainnya.")
            self.report.orphaned_routers = len(zombie_routers)
        else:
            if not self.ignore_zombie:
                self.log_success("Tidak ada router zombie terdeteksi di luar whitelist.")

        # Print Summary
        print("\n" + "="*60)
        print(f"{B_BOLD}             FORTRESS SUMMARY REPORT{C_RESET}")
        print("="*60)
        print(f" Rute Aktif Terdaftar (Runtime) : {self.report.runtime_total}")
        print(f" Definisi Rute Terlacak (AST)   : {self.report.static_total}")
        print(f" Tabrakan Rute Kritis           : {C_RED if self.report.collisions else C_GREEN}{self.report.collisions}{C_RESET}")
        print(f" Instance Router Zombie/Kosong  : {C_YELLOW if self.report.orphaned_routers else C_GREEN}{self.report.orphaned_routers}{C_RESET}")
        print(f" Gangguan Sistem Internal       : {len(self.errors_encountered)}")
        if whitelisted_zombies:
            print(f" Router di-whitelist (FP)      : {len(whitelisted_zombies)}")
        print("="*60)

        if self.report.collisions > 0:
            return 1
        return 0

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fortress Hybrid Route Validator")
    parser.add_argument("--import-path", default="app.main", help="Path modul python utama aplikasi FastAPI")
    parser.add_argument("--app-var", default="app", help="Nama variabel instance FastAPI")
    parser.add_argument("--no-zombie-check", action="store_true", help="Nonaktifkan pemeriksaan router zombie sepenuhnya")
    args = parser.parse_args()

    validator = RouteFortressValidator(
        import_path=args.import_path,
        app_variable=args.app_var,
        ignore_zombie=args.no_zombie_check
    )
    validator.run_static_scan()
    validator.run_runtime_scan()
    exit_code = validator.execute_audit_report()
    sys.exit(exit_code)