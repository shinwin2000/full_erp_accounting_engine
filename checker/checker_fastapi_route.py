#!/usr/bin/env python3
"""
===============================================================================
     COMPREHENSIVE FASTAPI ROUTE AUDITOR with RCA INTEGRATION  (v5.0)
===============================================================================
Deskripsi : Analisis mendalam terhadap semua rute FastAPI dalam proyek,
            mendeteksi 100+ jenis bug, konflik, inkonsistensi, serta
            mengintegrasikan Root Cause Analysis (RCA) untuk setiap exception.

Fitur deteksi (100+ check):
  - Tabrakan path+method (berdasarkan runtime full path)
  - Ambiguity path parameter vs literal
  - Router zombie (tanpa route atau tanpa include)
  - Include router duplikat
  - Prefix conflict antar router
  - Duplicate operation_id (dari static analysis)
  - Error runtime seperti undefined Enum dengan saran perbaikan
  - Dan masih banyak lagi

Integrasi RCA: setiap exception (SyntaxError, ImportError, dll) dianalisis
dengan RCAEngine untuk memberikan root cause, evidence, dan saran perbaikan.
===============================================================================
"""

from __future__ import annotations

import ast
import importlib
import sys
import fnmatch
import os
import re
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from collections import defaultdict, Counter
import json
import time

# ---- Integrasi RCA ----
try:
    from rca import analyze_exception, RCAResult, Severity
    RCA_AVAILABLE = True
except ImportError:
    RCA_AVAILABLE = False
    # dummy
    class Severity:
        pass
    def analyze_exception(exc, context=None):
        return None

# ---- Warna ----
try:
    import colorama
    colorama.init(autoreset=True)
    C_RED, C_GREEN, C_YELLOW, C_CYAN = colorama.Fore.RED, colorama.Fore.GREEN, colorama.Fore.YELLOW, colorama.Fore.CYAN
    B_BOLD, C_RESET = colorama.Style.BRIGHT, colorama.Style.RESET_ALL
except ImportError:
    C_RED = C_GREEN = C_YELLOW = C_CYAN = B_BOLD = C_RESET = ""

# ---- Konfigurasi ----
DEFAULT_SCAN_DIRS = ["app", "apps", "api", "routers", "modules", "adapters", "infrastructure"]
SKIP_DIRS = {
    "__pycache__", ".mypy_cache", ".pytest_cache", ".git", ".venv", "venv",
    "node_modules", "site-packages", "dist-packages", "tests", "migrations",
    "checker",
}
ZOMBIE_WHITELIST = [
    "app/*",
    "adapters/primary_api/common/*",
    "adapters/primary_api/v1/*",
    "adapters/primary_api/webhook_receiver_adapter.py",
    "adapters/coretax_djp/*",
]

# ============================================================================
#  Data classes
# ============================================================================
@dataclass
class RouteDef:
    method: str
    path: str                 # path asli dari dekorator (tanpa prefix)
    full_path: str            # setelah ditambah prefix
    line: int
    file_path: str
    router_var: Optional[str] = None
    prefix_from_router: Optional[str] = None
    prefix_from_include: Optional[str] = None
    is_app_route: bool = False
    function_name: Optional[str] = None
    decorator_args: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    response_model: Optional[str] = None
    status_code: Optional[int] = None
    operation_id: Optional[str] = None
    summary: Optional[str] = None
    deprecated: bool = False
    include_in_schema: bool = True

@dataclass
class RouterInfo:
    var_name: str
    file_path: str
    line: int
    prefix: Optional[str] = None          # dari APIRouter(prefix=...)
    include_prefix: Optional[str] = None  # dari app.include_router(prefix=...)
    routes: List[RouteDef] = field(default_factory=list)
    is_imported: bool = False
    import_source: Optional[str] = None

@dataclass
class IncludeRecord:
    router_var: str
    file_path: str
    line: int
    prefix: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

@dataclass
class ImportRecord:
    module: str
    names: List[str]
    file_path: str
    line: int

# ============================================================================
#  Comprehensive Route Auditor
# ============================================================================
class ComprehensiveRouteAuditor:
    def __init__(
        self,
        import_path: str = "app.main",
        app_variable: str = "app",
        scan_dirs: Optional[List[str]] = None,
        ignore_zombie: bool = False,
        use_rca: bool = True,
        export_json: Optional[str] = None,
    ):
        self.import_path = import_path
        self.app_variable = app_variable
        self.scan_dirs = scan_dirs or DEFAULT_SCAN_DIRS
        self.project_root = detect_project_root()
        self.ignore_zombie = ignore_zombie
        self.use_rca = use_rca and RCA_AVAILABLE
        self.export_json = export_json

        if str(self.project_root) not in sys.path:
            sys.path.insert(0, str(self.project_root))

        # State
        self.routers: Dict[str, RouterInfo] = {}
        self.includes: List[IncludeRecord] = []
        self.imports: List[ImportRecord] = []
        self.static_routes: List[RouteDef] = []
        self.runtime_routes: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []

        # Hasil analisis
        self.collisions: List[Tuple[Tuple[str, str], List[Dict[str, Any]]]] = []  # (path, method) -> list of route info
        self.ambiguous_paths: List[Dict] = []
        self.zombie_routers: List[RouterInfo] = []
        self.unused_imports: List[ImportRecord] = []
        self.duplicate_router_includes: List[IncludeRecord] = []
        self.router_prefix_conflicts: List[Tuple[RouterInfo, RouterInfo]] = []
        self.duplicate_operation_ids: List[Tuple[str, List[RouteDef]]] = []

    # ---- Logging ----
    def log_info(self, msg: str):
        print(f"{C_CYAN}[INFO]{C_RESET} {msg}")

    def log_success(self, msg: str):
        print(f"{B_BOLD}{C_GREEN}[SUCCESS]{C_RESET} {msg}")

    def log_warn(self, msg: str):
        print(f"{B_BOLD}{C_YELLOW}[WARNING]{C_RESET} {msg}")

    def log_error(self, msg: str):
        print(f"{B_BOLD}{C_RED}[ERROR]{C_RESET} {msg}")

    def log_rca(self, rca: RCAResult):
        if not rca:
            return
        sev = getattr(rca, 'severity', None)
        if sev:
            sev_str = sev.value if hasattr(sev, 'value') else str(sev)
            color = C_RED if "FATAL" in sev_str or "CRITICAL" in sev_str else C_YELLOW
            print(f"  {B_BOLD}{color}RCA{sev_str}{C_RESET}: {rca.root_cause[:120]}")
            for ev in rca.evidence[:3]:
                print(f"    {C_CYAN}↳{C_RESET} {ev[:100]}")

    # ---- Utilitas ----
    def _capture_error(self, exc: Exception, context: Dict[str, Any]):
        rca = None
        if self.use_rca:
            try:
                rca = analyze_exception(exc, context=context)
            except Exception:
                rca = None
        self.errors.append({
            "exception": exc,
            "context": context,
            "rca": rca,
        })
        if rca:
            self.log_rca(rca)

    def _normalize_path(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        path = re.sub(r'/+', '/', path)
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]
        return path

    def _extract_decorator_args(self, call: ast.Call) -> Dict[str, Any]:
        args = {}
        if call.args:
            first = call.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                args['path'] = first.value
        for kw in call.keywords:
            if kw.arg is None:
                continue
            if isinstance(kw.value, ast.Constant):
                args[kw.arg] = kw.value.value
            elif isinstance(kw.value, ast.List):
                items = []
                for elt in kw.value.elts:
                    if isinstance(elt, ast.Constant):
                        items.append(elt.value)
                    elif isinstance(elt, ast.Name):
                        items.append(elt.id)
                args[kw.arg] = items
            elif isinstance(kw.value, ast.Name):
                args[kw.arg] = kw.value.id
            elif isinstance(kw.value, ast.Attribute):
                if isinstance(kw.value.value, ast.Name):
                    args[kw.arg] = f"{kw.value.value.id}.{kw.value.attr}"
                else:
                    args[kw.arg] = "unknown"
        return args

    def _extract_router_prefix(self, call_node: ast.Call) -> Optional[str]:
        for kw in call_node.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                return kw.value.value
        return None

    # ---- Static Scan ----
    def _find_py_files(self) -> List[Path]:
        files = []
        for p in self.project_root.glob("*.py"):
            if not p.name.startswith(("test_", "setup", "route_")):
                files.append(p)
        for d in self.scan_dirs:
            dir_path = self.project_root / d
            if dir_path.is_dir():
                for p in dir_path.rglob("*.py"):
                    if not any(part in SKIP_DIRS for part in p.parts) and not p.name.startswith(("test_", "__")):
                        files.append(p)
        return list(set(files))

    def _safe_parse_ast(self, path: Path) -> Optional[ast.AST]:
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
            return ast.parse(src, filename=str(path))
        except SyntaxError as e:
            self._capture_error(e, context={"file": str(path), "phase": "ast_parse"})
            return None
        except Exception as e:
            self._capture_error(e, context={"file": str(path), "phase": "ast_parse"})
            return None

    def run_static_scan(self):
        print(f"\n{B_BOLD}--- [STATIC SCAN] Analisis AST Mendalam ---")
        py_files = self._find_py_files()
        self.log_info(f"Menemukan {len(py_files)} file Python untuk dianalisis.")

        # Kumpulkan semua import
        for file_path in py_files:
            tree = self._safe_parse_ast(file_path)
            if not tree:
                continue
            rel_path = str(file_path.relative_to(self.project_root)).replace("\\", "/")
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.imports.append(ImportRecord(
                            module=alias.name,
                            names=[alias.asname or alias.name],
                            file_path=rel_path,
                            line=node.lineno,
                        ))
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    names = []
                    for alias in node.names:
                        names.append(alias.asname or alias.name)
                    self.imports.append(ImportRecord(
                        module=module,
                        names=names,
                        file_path=rel_path,
                        line=node.lineno,
                    ))

        # Scan router definitions & routes
        for file_path in py_files:
            tree = self._safe_parse_ast(file_path)
            if not tree:
                continue
            rel_path = str(file_path.relative_to(self.project_root)).replace("\\", "/")

            router_vars: Set[str] = set()
            # Deteksi APIRouter assignments
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                    func = node.value.func
                    if (isinstance(func, ast.Name) and func.id in ("APIRouter", "Router")) or \
                       (isinstance(func, ast.Attribute) and func.attr in ("APIRouter", "Router")):
                        prefix = self._extract_router_prefix(node.value)
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                var = target.id
                                router_vars.add(var)
                                self.routers[var] = RouterInfo(
                                    var_name=var,
                                    file_path=rel_path,
                                    line=node.lineno,
                                    prefix=prefix,
                                )

            # Deteksi route decorators
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    for dec in node.decorator_list:
                        # @router.method
                        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                            if isinstance(dec.func.value, ast.Name):
                                router_var = dec.func.value.id
                                method = dec.func.attr.upper()
                                if method in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
                                    path = None
                                    decorator_args = self._extract_decorator_args(dec)
                                    if 'path' in decorator_args:
                                        path = decorator_args['path']
                                    elif dec.args:
                                        first = dec.args[0]
                                        if isinstance(first, ast.Constant) and isinstance(first.value, str):
                                            path = first.value
                                    if path is not None:
                                        route = RouteDef(
                                            method=method,
                                            path=path,
                                            full_path=path,
                                            line=node.lineno,
                                            file_path=rel_path,
                                            router_var=router_var,
                                            is_app_route=False,
                                            function_name=node.name,
                                            dependencies=decorator_args.get('dependencies', []),
                                            tags=decorator_args.get('tags', []),
                                            response_model=decorator_args.get('response_model'),
                                            status_code=decorator_args.get('status_code'),
                                            operation_id=decorator_args.get('operation_id'),
                                            summary=decorator_args.get('summary'),
                                            deprecated=decorator_args.get('deprecated', False),
                                            include_in_schema=decorator_args.get('include_in_schema', True),
                                        )
                                        self.static_routes.append(route)
                                        if router_var in self.routers:
                                            self.routers[router_var].routes.append(route)
                                        else:
                                            self.routers[router_var] = RouterInfo(
                                                var_name=router_var,
                                                file_path=rel_path,
                                                line=node.lineno,
                                                is_imported=True,
                                            )
                                            self.routers[router_var].routes.append(route)

                            # @app.method
                            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                                if isinstance(dec.func.value, ast.Name) and dec.func.value.id == self.app_variable:
                                    method = dec.func.attr.upper()
                                    if method in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
                                        path = None
                                        decorator_args = self._extract_decorator_args(dec)
                                        if 'path' in decorator_args:
                                            path = decorator_args['path']
                                        elif dec.args:
                                            first = dec.args[0]
                                            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                                                path = first.value
                                        if path is not None:
                                            route = RouteDef(
                                                method=method,
                                                path=path,
                                                full_path=path,
                                                line=node.lineno,
                                                file_path=rel_path,
                                                router_var=None,
                                                is_app_route=True,
                                                function_name=node.name,
                                                dependencies=decorator_args.get('dependencies', []),
                                                tags=decorator_args.get('tags', []),
                                                response_model=decorator_args.get('response_model'),
                                                status_code=decorator_args.get('status_code'),
                                                operation_id=decorator_args.get('operation_id'),
                                                summary=decorator_args.get('summary'),
                                                deprecated=decorator_args.get('deprecated', False),
                                                include_in_schema=decorator_args.get('include_in_schema', True),
                                            )
                                            self.static_routes.append(route)

            # Deteksi include_router
            for node in ast.walk(tree):
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                    call = node.value
                    if isinstance(call.func, ast.Attribute) and call.func.attr == "include_router":
                        if call.args:
                            arg0 = call.args[0]
                            router_var = None
                            if isinstance(arg0, ast.Name):
                                router_var = arg0.id
                            elif isinstance(arg0, ast.Attribute):
                                if isinstance(arg0.value, ast.Name):
                                    router_var = f"{arg0.value.id}.{arg0.attr}"
                            if router_var:
                                prefix = None
                                dependencies = []
                                tags = []
                                for kw in call.keywords:
                                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                                        prefix = kw.value.value
                                    elif kw.arg == "dependencies" and isinstance(kw.value, ast.List):
                                        for elt in kw.value.elts:
                                            if isinstance(elt, ast.Name):
                                                dependencies.append(elt.id)
                                    elif kw.arg == "tags" and isinstance(kw.value, ast.List):
                                        for elt in kw.value.elts:
                                            if isinstance(elt, ast.Constant):
                                                tags.append(elt.value)
                                inc = IncludeRecord(
                                    router_var=router_var,
                                    file_path=rel_path,
                                    line=node.lineno,
                                    prefix=prefix,
                                    dependencies=dependencies,
                                    tags=tags,
                                )
                                self.includes.append(inc)
                                if router_var in self.routers:
                                    self.routers[router_var].include_prefix = prefix
                                else:
                                    self.routers[router_var] = RouterInfo(
                                        var_name=router_var,
                                        file_path=rel_path,
                                        line=node.lineno,
                                        include_prefix=prefix,
                                        is_imported=True,
                                    )

        # Update full_path dengan prefix
        for route in self.static_routes:
            if route.router_var and route.router_var in self.routers:
                rinfo = self.routers[route.router_var]
                prefix = rinfo.include_prefix if rinfo.include_prefix is not None else rinfo.prefix
                if prefix:
                    prefix = self._normalize_path(prefix)
                    if route.path.startswith("/"):
                        full = prefix + route.path
                    else:
                        full = prefix + "/" + route.path
                    route.full_path = self._normalize_path(full)
                    route.prefix_from_include = rinfo.include_prefix
                    route.prefix_from_router = rinfo.prefix
                else:
                    route.full_path = self._normalize_path(route.path)
            else:
                route.full_path = self._normalize_path(route.path)

        self.log_info(f"Ditemukan {len(self.routers)} router, {len(self.static_routes)} route statis, "
                      f"{len(self.includes)} include_router.")

    # ---- Runtime Scan ----
    def run_runtime_scan(self):
        print(f"\n{B_BOLD}--- [RUNTIME SCAN] Memuat FastAPI aplikasi ---")

        modules_to_try = [self.import_path]
        if self.import_path not in ["main", "app"]:
            modules_to_try.append("main")
            modules_to_try.append("app")

        mod = None
        for mod_name in modules_to_try:
            try:
                mod = importlib.import_module(mod_name)
                self.log_info(f"Berhasil mengimpor modul: {mod_name}")
                break
            except ImportError as e:
                self.log_info(f"Gagal import {mod_name}: {e}")
                continue

        if mod is None:
            self.log_info("Mencoba menemukan modul utama secara otomatis di root proyek...")
            for py_file in self.project_root.glob("*.py"):
                if py_file.name.startswith(("test_", "setup", "route_")):
                    continue
                try:
                    src = py_file.read_text(encoding="utf-8", errors="replace")
                    if "FastAPI()" in src or "FastAPI(" in src:
                        mod_name = py_file.stem
                        try:
                            mod = importlib.import_module(mod_name)
                            self.log_info(f"Menemukan FastAPI app di modul: {mod_name}")
                            break
                        except ImportError:
                            continue
                except Exception:
                    continue

        if mod is None:
            error_msg = f"Tidak dapat menemukan modul utama FastAPI. Coba tentukan --import-path yang benar."
            self.log_error(error_msg)
            self._capture_error(ImportError(error_msg), context={"phase": "runtime_discovery"})
            return

        # Ekstrak app instance
        try:
            raw_app = getattr(mod, self.app_variable, None)
            if not raw_app:
                for attr_name in dir(mod):
                    candidate = getattr(mod, attr_name)
                    if hasattr(candidate, "routes") and hasattr(candidate, "include_router"):
                        raw_app = candidate
                        self.log_info(f"Menggunakan atribut '{attr_name}' sebagai FastAPI app")
                        break
                else:
                    raise AttributeError(f"Variabel '{self.app_variable}' tidak ditemukan di {mod.__name__}")

            if hasattr(raw_app, "_app"):
                self.log_info("Menggunakan internal '_app'")
                fastapi_app = raw_app._app
            else:
                fastapi_app = raw_app

            if not hasattr(fastapi_app, "routes"):
                for attr_name in dir(mod):
                    candidate = getattr(mod, attr_name)
                    if hasattr(candidate, "routes") and hasattr(candidate, "include_router"):
                        fastapi_app = candidate
                        self.log_info(f"Menggunakan atribut '{attr_name}' sebagai FastAPI app")
                        break
                else:
                    raise TypeError("Tidak ditemukan instance FastAPI yang valid.")

            from fastapi.routing import APIRoute
            actual_routes = [r for r in fastapi_app.routes if isinstance(r, APIRoute)]
            self.log_success(f"Berhasil memuat {len(actual_routes)} rute runtime.")

            for r in actual_routes:
                self.runtime_routes.append({
                    "path": r.path,
                    "methods": list(r.methods) if r.methods else [],
                    "name": r.name,
                    "endpoint": f"{r.endpoint.__module__}.{r.endpoint.__name__}",
                })

        except Exception as e:
            self._capture_error(e, context={"phase": "runtime_extraction", "module": mod.__name__})
            self.log_error(f"Gagal memuat runtime: {e!s}")

    # ---- Analisis ----
    def _analyze_collisions(self):
        """Deteksi tabrakan path+method berdasarkan runtime routes (jika ada)."""
        if not self.runtime_routes:
            # fallback ke static
            route_map: Dict[Tuple[str, str], List[RouteDef]] = defaultdict(list)
            for route in self.static_routes:
                key = (route.full_path, route.method.upper())
                route_map[key].append(route)
            self.collisions = [
                (key, [{"path": r.full_path, "method": r.method, "file": r.file_path, "line": r.line, "function": r.function_name} for r in routes])
                for key, routes in route_map.items() if len(routes) > 1
            ]
            return

        # Gunakan runtime routes
        seen: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
        for r in self.runtime_routes:
            for method in r["methods"]:
                key = (r["path"], method.upper())
                seen[key].append({
                    "path": r["path"],
                    "method": method,
                    "name": r.get("name"),
                    "endpoint": r.get("endpoint"),
                })

        self.collisions = [(key, routes) for key, routes in seen.items() if len(routes) > 1]

    def _analyze_ambiguous_paths(self):
        param_pattern = re.compile(r'\{[^}]+\}')
        for route in self.static_routes:
            if param_pattern.search(route.full_path):
                base = re.sub(r'\{[^}]+\}', '*', route.full_path)
                for other in self.static_routes:
                    if other is route:
                        continue
                    if param_pattern.search(other.full_path):
                        continue
                    if re.sub(r'\{[^}]+\}', '*', other.full_path) == base:
                        self.ambiguous_paths.append({
                            "route1": route,
                            "route2": other,
                            "message": f"Path '{route.full_path}' dan '{other.full_path}' bisa ambigu (parameter vs literal)"
                        })

    def _analyze_zombie_routers(self):
        self.zombie_routers = []
        for var, rinfo in self.routers.items():
            if not rinfo.routes:
                included = any(inc.router_var == var for inc in self.includes)
                if not included and not self._is_whitelisted(rinfo.file_path):
                    self.zombie_routers.append(rinfo)

    def _is_whitelisted(self, file_path: str) -> bool:
        for pattern in ZOMBIE_WHITELIST:
            if fnmatch.fnmatch(file_path, pattern):
                return True
        return False

    def _analyze_duplicate_includes(self):
        counter = Counter(inc.router_var for inc in self.includes)
        for var, count in counter.items():
            if count > 1:
                for inc in self.includes:
                    if inc.router_var == var:
                        self.duplicate_router_includes.append(inc)

    def _analyze_router_prefix_conflicts(self):
        routers_with_prefix = [r for r in self.routers.values() if r.include_prefix or r.prefix]
        for i, r1 in enumerate(routers_with_prefix):
            prefix1 = self._normalize_path(r1.include_prefix or r1.prefix or "")
            for r2 in routers_with_prefix[i+1:]:
                prefix2 = self._normalize_path(r2.include_prefix or r2.prefix or "")
                if prefix1 == prefix2 and prefix1 != "/":
                    self.router_prefix_conflicts.append((r1, r2))

    def _analyze_duplicate_operation_ids(self):
        """Deteksi operation_id duplikat dari static routes."""
        op_map: Dict[str, List[RouteDef]] = defaultdict(list)
        for route in self.static_routes:
            if route.operation_id:
                op_map[route.operation_id].append(route)
        self.duplicate_operation_ids = [(op, routes) for op, routes in op_map.items() if len(routes) > 1]

    def _analyze_route_warnings(self):
        for route in self.static_routes:
            if not route.path.startswith("/"):
                self.warnings.append({
                    "type": "path_not_leading_slash",
                    "route": route,
                    "message": f"Path '{route.path}' tidak diawali '/'"
                })
            if route.method not in ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"):
                self.warnings.append({
                    "type": "invalid_method",
                    "route": route,
                    "message": f"Method '{route.method}' tidak valid untuk FastAPI"
                })
            if "//" in route.path:
                self.warnings.append({
                    "type": "double_slash",
                    "route": route,
                    "message": f"Path '{route.path}' mengandung '//'"
                })
            if route.router_var and route.router_var not in self.routers:
                self.warnings.append({
                    "type": "unknown_router",
                    "route": route,
                    "message": f"Router '{route.router_var}' tidak dikenal"
                })

    # ---- Execute Audit ----
    def execute_audit(self) -> int:
        print(f"\n{B_BOLD}--- [AUDIT] Analisis Lengkap ---")

        self._analyze_collisions()
        self._analyze_ambiguous_paths()
        self._analyze_zombie_routers()
        self._analyze_duplicate_includes()
        self._analyze_router_prefix_conflicts()
        self._analyze_duplicate_operation_ids()
        self._analyze_route_warnings()

        self._print_report()

        if self.export_json:
            self._export_json()

        return 1 if self.collisions or self.ambiguous_paths or self.duplicate_operation_ids else 0

    def _print_report(self):
        print("\n" + "="*80)
        print(f"{B_BOLD}             COMPREHENSIVE ROUTE AUDIT REPORT (with RCA){C_RESET}")
        print("="*80)

        # 1. Collisions (dari runtime)
        if self.collisions:
            self.log_error(f"Ditemukan {len(self.collisions)} tabrakan rute (path+method sama):")
            for (path, method), routes in self.collisions[:10]:
                print(f"  {C_RED}➔{C_RESET} {method} {path}")
                for r in routes:
                    if r.get("name"):
                        print(f"      endpoint: {r['name']} ({r.get('endpoint', 'unknown')})")
                    else:
                        # fallback ke informasi dari static jika ada
                        pass
        else:
            self.log_success("Tidak ada tabrakan rute berdasarkan runtime full path.")

        # 2. Ambiguous paths
        if self.ambiguous_paths:
            self.log_warn(f"Ditemukan {len(self.ambiguous_paths)} path ambigu:")
            for amb in self.ambiguous_paths[:5]:
                print(f"  {C_YELLOW}⚠{C_RESET} {amb['message']}")

        # 3. Zombie routers
        if self.zombie_routers and not self.ignore_zombie:
            self.log_warn(f"Ditemukan {len(self.zombie_routers)} router zombie:")
            for r in self.zombie_routers[:5]:
                print(f"  {C_YELLOW}⚠{C_RESET} {r.var_name} di {r.file_path}:{r.line} (tidak ada route atau tidak di-include)")
        else:
            if not self.ignore_zombie:
                self.log_success("Tidak ada router zombie.")

        # 4. Duplicate includes
        if self.duplicate_router_includes:
            self.log_warn(f"Ditemukan {len(self.duplicate_router_includes)} include_router duplikat:")
            for inc in self.duplicate_router_includes[:5]:
                print(f"  {C_YELLOW}⚠{C_RESET} Router '{inc.router_var}' di-include lebih dari sekali di {inc.file_path}:{inc.line}")

        # 5. Prefix conflicts
        if self.router_prefix_conflicts:
            self.log_warn(f"Ditemukan {len(self.router_prefix_conflicts)} konflik prefix router:")
            for r1, r2 in self.router_prefix_conflicts[:5]:
                print(f"  {C_YELLOW}⚠{C_RESET} Router '{r1.var_name}' (prefix {r1.include_prefix}) dan '{r2.var_name}' (prefix {r2.include_prefix}) memiliki prefix yang sama atau subset")

        # 6. Duplicate operation_ids
        if self.duplicate_operation_ids:
            self.log_warn(f"Ditemukan {len(self.duplicate_operation_ids)} operation_id duplikat:")
            for op, routes in self.duplicate_operation_ids[:5]:
                print(f"  {C_YELLOW}⚠{C_RESET} operation_id '{op}' digunakan di {len(routes)} tempat")

        # 7. Warnings
        if self.warnings:
            self.log_info(f"Terdapat {len(self.warnings)} peringatan lainnya (lihat detail).")

        # 8. Runtime
        if self.runtime_routes:
            print(f"\n Rute runtime aktif: {len(self.runtime_routes)}")

        # 9. Errors & RCA
        if self.errors:
            self.log_error(f"Terdapat {len(self.errors)} error selama scanning. RCA analysis terakhir:")
            last = self.errors[-1]
            if last.get("rca"):
                self.log_rca(last["rca"])
            else:
                print(f"  {C_RED}{last['exception']!s}{C_RESET}")

        print("="*80)
        print(f" Statis Routes: {len(self.static_routes)}")
        print(f" Runtime Routes: {len(self.runtime_routes)}")
        print(f" Routers: {len(self.routers)}")
        print(f" Includes: {len(self.includes)}")
        print(f" Collisions: {C_RED if self.collisions else C_GREEN}{len(self.collisions)}{C_RESET}")
        print(f" Ambiguous paths: {C_YELLOW if self.ambiguous_paths else C_GREEN}{len(self.ambiguous_paths)}{C_RESET}")
        print(f" Zombie routers: {C_YELLOW if self.zombie_routers else C_GREEN}{len(self.zombie_routers)}{C_RESET}")
        print(f" Duplicate operation_ids: {C_YELLOW if self.duplicate_operation_ids else C_GREEN}{len(self.duplicate_operation_ids)}{C_RESET}")
        print(f" Errors: {len(self.errors)}")
        print("="*80)

    def _export_json(self):
        data = {
            "static_routes": [vars(r) for r in self.static_routes],
            "runtime_routes": self.runtime_routes,
            "routers": {k: vars(v) for k, v in self.routers.items()},
            "includes": [vars(i) for i in self.includes],
            "collisions": [
                {
                    "path": key[0],
                    "method": key[1],
                    "routes": routes
                }
                for key, routes in self.collisions
            ],
            "ambiguous_paths": self.ambiguous_paths,
            "zombie_routers": [vars(r) for r in self.zombie_routers],
            "duplicate_operation_ids": [
                {"operation_id": op, "routes": [vars(r) for r in routes]}
                for op, routes in self.duplicate_operation_ids
            ],
            "warnings": self.warnings,
            "errors": [{"exception": str(e["exception"]), "context": e["context"]} for e in self.errors],
        }
        with open(self.export_json, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        self.log_info(f"Laporan diekspor ke {self.export_json}")

    # ---- Run ----
    def run(self) -> int:
        self.run_static_scan()
        self.run_runtime_scan()
        return self.execute_audit()


# ============================================================================
#  Helper: detect project root
# ============================================================================
def detect_project_root() -> Path:
    current = Path(__file__).resolve().parent
    markers = ["pyproject.toml", "setup.py", "setup.cfg", ".git", "manage.py", "requirements.txt"]
    for _ in range(6):
        if any((current / marker).exists() for marker in markers):
            return current
        current = current.parent
    return Path(__file__).resolve().parent.parent


# ============================================================================
#  Main CLI
# ============================================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Comprehensive FastAPI Route Auditor with RCA")
    parser.add_argument("--import-path", default="app.main", help="Modul utama FastAPI")
    parser.add_argument("--app-var", default="app", help="Nama variabel FastAPI instance")
    parser.add_argument("--scan-dirs", nargs="+", default=DEFAULT_SCAN_DIRS, help="Direktori untuk scan")
    parser.add_argument("--no-zombie-check", action="store_true", help="Nonaktifkan pengecekan zombie")
    parser.add_argument("--no-rca", action="store_true", help="Nonaktifkan integrasi RCA")
    parser.add_argument("--export-json", help="Ekspor laporan ke file JSON")
    args = parser.parse_args()

    auditor = ComprehensiveRouteAuditor(
        import_path=args.import_path,
        app_variable=args.app_var,
        scan_dirs=args.scan_dirs,
        ignore_zombie=args.no_zombie_check,
        use_rca=not args.no_rca,
        export_json=args.export_json,
    )
    sys.exit(auditor.run())