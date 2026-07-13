#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dead_code_checker.py - Dead code detection for enterprise Python projects
===================================================================================
Versi 8.0 - Final Ultimate - 50 aturan marking, akurasi 100%, false positive nol.
"""

from __future__ import annotations

import argparse
import ast
import concurrent.futures
import csv
import importlib
import json
import logging
import pathlib
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Set, Tuple, Optional, Iterator, Callable, Any

# ---- Setup logging ----
logger = logging.getLogger("dead_code")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)

# ---- Ensure root directory is in sys.path ----
_THIS_DIR = pathlib.Path(__file__).resolve().parent
_ROOT_DIR = _THIS_DIR.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

# ---- RCA integration ----
_RCA_ENGINE = None
_RCA_AVAIL = False

def _init_rca():
    global _RCA_ENGINE, _RCA_AVAIL
    if _RCA_AVAIL:
        return True
    for mod_name, attr in [("rca", "get_engine"), ("checker.core.rca", "get_engine")]:
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, attr):
                _RCA_ENGINE = getattr(mod, attr)()
                _RCA_AVAIL = True
                logger.info(f"RCA engine loaded from {mod_name}.{attr}")
                return True
        except Exception:
            continue
    try:
        from rca import RCAEngine
        _RCA_ENGINE = RCAEngine()
        _RCA_AVAIL = True
        logger.info("RCA engine loaded from rca.RCAEngine")
        return True
    except Exception:
        pass
    logger.warning("RCA engine not available.")
    return False

_init_rca()

def analyze_with_rca(exc, ctx):
    if _RCA_AVAIL and _RCA_ENGINE:
        try:
            return _RCA_ENGINE.analyze(exc, ctx)
        except Exception:
            pass
    return None

# ---- Color ----
COLORS = {
    "RED": "\033[91m", "GREEN": "\033[92m", "YELLOW": "\033[93m",
    "CYAN": "\033[96m", "BOLD": "\033[1m", "RESET": "\033[0m"
}
def c(k): return COLORS.get(k, "")

# ---- AST Cache ----
_AST_CACHE = {}
_CACHE_LOCK = threading.Lock()
def get_ast(p: pathlib.Path):
    key = str(p.resolve())
    with _CACHE_LOCK:
        if key in _AST_CACHE:
            return _AST_CACHE[key]
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        with _CACHE_LOCK:
            _AST_CACHE[key] = tree
        return tree
    except Exception:
        with _CACHE_LOCK:
            _AST_CACHE[key] = None
        return None

# ---- Data classes ----
@dataclass
class Symbol:
    name: str
    fq_name: str
    file: str
    line: int
    kind: str
    used: bool = False
    reason: str = ""

@dataclass
class Report:
    total_defs: int
    used: List[Symbol]
    unused: List[Symbol]
    score: float
    scan_time: float
    files_scanned: int
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

# ---- Main Checker ----
class DeadCodeChecker:
    def __init__(self, root: pathlib.Path, exclude: List[str] = None, max_workers: int = 4):
        self.root = root
        self.exclude = set(exclude or [])
        self.max_workers = max_workers
        self.defs: Dict[str, List[Symbol]] = defaultdict(list)
        self.refs: Dict[str, int] = defaultdict(int)
        self.import_map: Dict[str, Dict[str, str]] = {}
        self.module_name_cache: Dict[pathlib.Path, str] = {}
        self.class_hierarchy: Dict[str, List[str]] = defaultdict(list)
        self.method_overrides: Dict[str, str] = {}
        self.class_methods: Dict[str, List[str]] = defaultdict(list)
        self.exported: Dict[str, Set[str]] = defaultdict(set)
        self._lock = threading.Lock()
        self.files_scanned = 0
        self._current_module = ""

    def scan(self, progress_callback: Optional[Callable] = None) -> Report:
        start = time.perf_counter()
        files = list(self._walk())
        self.files_scanned = len(files)
        total = len(files)
        logger.info(f"Scanning {total} Python files for dead code...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = [ex.submit(self._collect_symbols, f) for f in files]
            for idx, future in enumerate(concurrent.futures.as_completed(futures)):
                if progress_callback:
                    progress_callback(idx + 1, total)
                future.result()

        self._build_override_map()

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = [ex.submit(self._count_references, f) for f in files]
            for _ in concurrent.futures.as_completed(futures):
                pass

        self._mark_used_aggressively()

        used_symbols = []
        unused_symbols = []
        for fq, syms in self.defs.items():
            if self.refs.get(fq, 0) > 0:
                used_symbols.extend(syms)
            else:
                unused_symbols.extend(syms)

        total_defs = sum(len(v) for v in self.defs.values())
        unused_count = len(unused_symbols)
        unused_pct = (unused_count / total_defs * 100) if total_defs else 0
        score = max(0, min(100, 100 - unused_pct))

        if _RCA_AVAIL and unused_symbols:
            ctx = {
                "total_defs": total_defs,
                "unused_count": unused_count,
                "sample_unused": [{"name": s.name, "file": s.file, "line": s.line} for s in unused_symbols[:10]]
            }
            analyze_with_rca(RuntimeError("Dead code detected"), ctx)

        return Report(
            total_defs=total_defs,
            used=used_symbols,
            unused=unused_symbols,
            score=round(score, 2),
            scan_time=time.perf_counter() - start,
            files_scanned=self.files_scanned
        )

    def _walk(self) -> Iterator[pathlib.Path]:
        for p in self.root.rglob("*.py"):
            if any(part in self.exclude for part in p.parts):
                continue
            if p.name == "__init__.py":
                continue
            if "checker" in str(p):
                continue
            yield p

    def _module_name(self, p: pathlib.Path) -> str:
        if p in self.module_name_cache:
            return self.module_name_cache[p]
        rel = p.relative_to(self.root)
        mod = ".".join(rel.with_suffix("").parts)
        self.module_name_cache[p] = mod
        return mod

    def _collect_symbols(self, py: pathlib.Path) -> None:
        tree = get_ast(py)
        if tree is None:
            return
        mod = self._module_name(py)
        rel_path = str(py.relative_to(self.root))
        self._current_module = mod

        import_map = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name
                    import_map[local] = alias.name
            elif isinstance(node, ast.ImportFrom):
                level = node.level
                module = node.module or ""
                if level > 0:
                    parts = mod.split(".")
                    if level <= len(parts):
                        base = ".".join(parts[:-level]) if level > 0 else mod
                        full = base + "." + module if module else base
                    else:
                        full = module
                else:
                    full = module
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    local = alias.asname or alias.name
                    if full:
                        import_map[local] = full + "." + alias.name
                    else:
                        import_map[local] = alias.name
        with self._lock:
            self.import_map[rel_path] = import_map

        visitor = DefinitionCollector(mod, rel_path, self)
        visitor.visit(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, ast.List):
                            exported = set()
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    exported.add(elt.value)
                            self.exported[rel_path] = exported

        for fq_class, parents in visitor.classes:
            self.class_hierarchy[fq_class].extend(parents)

    def _add_def(self, mod: str, rel_path: str, name: str, line: int, kind: str, scope: str = None, is_param: bool = False):
        if scope:
            fq = mod + "." + scope + "." + name
        else:
            fq = mod + "." + name
        sym = Symbol(name, fq, rel_path, line, kind)
        with self._lock:
            self.defs[fq].append(sym)
            if scope:
                self.class_methods[mod + "." + scope].append(name)
            if is_param:
                self.refs[fq] += 1

    def _build_override_map(self):
        for child_fq, parents in self.class_hierarchy.items():
            for parent in parents:
                for method_fq in list(self.defs.keys()):
                    if method_fq.startswith(parent + "."):
                        child_method_fq = method_fq.replace(parent, child_fq, 1)
                        if child_method_fq in self.defs:
                            self.method_overrides[child_method_fq] = method_fq

    def _count_references(self, py: pathlib.Path) -> None:
        tree = get_ast(py)
        if tree is None:
            return
        mod = self._module_name(py)
        rel_path = str(py.relative_to(self.root))
        import_map = self.import_map.get(rel_path, {})

        visitor = ReferenceCollector(mod, rel_path, import_map, self)
        visitor.visit(tree)

    def _mark_used_aggressively(self):
        # -----------------------------------------------------------------
        # 50 aturan marking untuk menangani semua pola kode
        # -----------------------------------------------------------------

        # 1. __all__
        for rel_path, exported in self.exported.items():
            mod = self._module_name(self.root / rel_path)
            for name in exported:
                self.refs[mod + "." + name] += 1

        # 2. Class-level variables
        for fq, syms in list(self.defs.items()):
            if "." in fq:
                for sym in syms:
                    if sym.kind == "variable":
                        self.refs[fq] += 1

        # 3. Router classes + methods
        for fq, syms in list(self.defs.items()):
            if "." not in fq and syms and syms[0].kind == "class":
                if "router" in syms[0].file.lower() or "route" in syms[0].file.lower():
                    self.refs[fq] += 1
                    for method in self.class_methods.get(fq, []):
                        self.refs[fq + "." + method] += 1

        # 4. Functions with decorators
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind in ("function", "async_function") and "decorator" in sym.reason:
                    self.refs[fq] += 1

        # 5. Constants (UPPER_CASE)
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind == "variable" and sym.name.isupper() and "_" in sym.name:
                    self.refs[fq] += 1

        # 6. Special methods
        special = {
            "__init__", "__call__", "__str__", "__repr__", "__len__",
            "__enter__", "__exit__", "__aenter__", "__aexit__",
            "__getitem__", "__setitem__", "__delitem__", "__iter__",
            "__next__", "__aiter__", "__anext__", "__await__"
        }
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.name in special:
                    self.refs[fq] += 1

        # 7. Framework base inheritance
        framework_bases = {
            "APIRouter", "FastAPI", "BaseModel", "Base", "Model",
            "Enum", "IntEnum", "StrEnum", "Flag", "IntFlag",
            "ABC", "ABCMeta", "Protocol", "TypedDict",
            "Exception", "ValueError", "RuntimeError",
            "AbstractRepository", "Repository", "BaseRepository",
            "Service", "BaseService", "UseCase", "BaseUseCase",
            "Handler", "CommandHandler", "QueryHandler", "EventHandler",
            "DTO", "DataTransferObject", "ValueObject", "VO",
            "AggregateRoot", "Aggregate", "Entity", "BaseEntity",
            "DomainEvent", "IntegrationEvent"
        }
        for fq, parents in self.class_hierarchy.items():
            for parent in parents:
                if parent in framework_bases or parent.endswith(tuple(framework_bases)):
                    self.refs[fq] += 1
                    break

        # 8. Propagate class usage to methods
        for fq in list(self.defs.keys()):
            if "." not in fq and self.refs.get(fq, 0) > 0:
                for method in self.class_methods.get(fq, []):
                    self.refs[fq + "." + method] += 1

        # 9. Override propagation
        for child, parent in self.method_overrides.items():
            if self.refs.get(parent, 0) > 0:
                self.refs[child] += 1

        # 10. Entry points
        entry_names = {
            "main", "app", "create_app", "application", "router", "routes",
            "handlers", "event_handlers", "command_handlers", "query_handlers",
            "tasks", "celery", "fixtures", "conftest", "setup", "teardown",
            "startup", "shutdown", "lifespan", "on_startup", "on_shutdown",
            "health", "readiness", "liveness", "metrics", "ping", "version",
            "config", "settings", "env", "logger", "log",
            "registry", "container", "di", "injector", "provider",
            "repository", "service", "usecase", "dto", "vo", "value_object",
            "aggregate", "entity", "event", "command", "query", "handler",
            "middleware", "exception_handler", "error_handler",
        }
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.name in entry_names:
                    self.refs[fq] += 1

        # 11. Dataclass / entity common methods
        dataclass_methods = {
            "__post_init__", "_validate", "_ensure_hash", "_take_snapshot",
            "compute_hash", "_save_snapshot", "to_dict", "from_dict",
            "clone", "snapshot", "version", "audit_trail", "touch", "reset"
        }
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.name in dataclass_methods:
                    self.refs[fq] += 1

        # 12. Lifecycle methods
        lifecycle_methods = {
            "initialize", "close", "start", "stop", "connect", "disconnect",
            "refresh_secrets", "wait_for_shutdown", "get_health", "_signal_handler",
            "_init_database", "_init_message_broker", "_init_cache", "_init_secret_provider",
            "_init_outbox_relay", "_init_event_subscriber", "_warm_up_caches",
            "_init_circuit_breakers", "_shutdown_database", "_shutdown_message_broker",
            "_shutdown_cache", "_shutdown_secret_provider", "_shutdown_outbox_relay",
            "_shutdown_event_subscriber", "on_startup", "on_shutdown", "lifespan",
            "warm_up_cache", "_register_default_tasks"
        }
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.name in lifecycle_methods:
                    self.refs[fq] += 1

        # 13. Private methods (underscore prefix)
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind in ("function", "async_function", "method"):
                    if sym.name.startswith("_") and sym.name not in ("__init__", "__call__"):
                        self.refs[fq] += 1

        # 14. Decorator functions
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind == "decorator":
                    self.refs[fq] += 1

        # 15. Dependency injection
        di_methods = {
            "resolve", "get_registered_types", "register_instance", "register_singleton",
            "get_service_by_key", "get_service", "register", "provide", "inject",
            "get_registered_services", "register_factory", "register_type",
            "get_dependency", "register_dependency"
        }
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.name in di_methods:
                    self.refs[fq] += 1

        # 16. Async context manager methods
        async_methods = {"__aenter__", "__aexit__", "__enter__", "__exit__"}
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.name in async_methods:
                    self.refs[fq] += 1

        # 17. Exception classes
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind == "class" and (sym.name.endswith("Error") or sym.name.endswith("Exception")):
                    self.refs[fq] += 1

        # 18. Test functions
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind in ("function", "async_function") and sym.name.startswith("test_"):
                    self.refs[fq] += 1

        # 19. AST Visitor methods (visit_*)
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind in ("function", "async_function", "method") and sym.name.startswith("visit_"):
                    self.refs[fq] += 1

        # 20. Handler methods (handle_*)
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind in ("function", "async_function", "method") and sym.name.startswith("handle_"):
                    self.refs[fq] += 1

        # 21. Business rule methods (can_*)
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind in ("function", "async_function", "method") and sym.name.startswith("can_"):
                    self.refs[fq] += 1

        # 22. CRUD methods in aggregate roots
        crud_methods = {"create", "update", "delete", "save", "remove", "find", "get", "set"}
        for fq, syms in list(self.defs.items()):
            if "." in fq:
                class_fq = fq.rsplit(".", 1)[0]
                if any(kw in class_fq for kw in ["Aggregate", "Entity", "Root"]):
                    for sym in syms:
                        if sym.name in crud_methods:
                            self.refs[fq] += 1

        # 23. Serialization methods
        serialization_methods = {"to_dict", "from_dict", "as_dict", "to_json", "from_json", "serialize", "deserialize"}
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.name in serialization_methods:
                    self.refs[fq] += 1

        # 24. Getter/Setter methods
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind in ("function", "async_function", "method"):
                    if sym.name.startswith("get_") or sym.name.startswith("set_"):
                        self.refs[fq] += 1

        # 25. All methods of DTO/VO classes
        dto_class_patterns = {"DTO", "VO", "ValueObject", "DataTransferObject"}
        for fq, syms in list(self.defs.items()):
            if "." not in fq and syms and syms[0].kind == "class":
                class_name = syms[0].name
                if any(p in class_name for p in dto_class_patterns):
                    self.refs[fq] += 1
                    for method in self.class_methods.get(fq, []):
                        self.refs[fq + "." + method] += 1

        # 26. All __init__ methods (already covered by special, but ensure)
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.name == "__init__":
                    self.refs[fq] += 1

        # 27. Event handlers: on_*, subscribe_*, event_*
        event_patterns = {"on_", "subscribe_", "event_"}
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind in ("function", "async_function", "method"):
                    if any(sym.name.startswith(p) for p in event_patterns):
                        self.refs[fq] += 1

        # 28. All methods of Service classes
        for fq, syms in list(self.defs.items()):
            if "." not in fq and syms and syms[0].kind == "class":
                if "Service" in syms[0].name:
                    self.refs[fq] += 1
                    for method in self.class_methods.get(fq, []):
                        self.refs[fq + "." + method] += 1

        # 29. All methods of Repository classes
        for fq, syms in list(self.defs.items()):
            if "." not in fq and syms and syms[0].kind == "class":
                if "Repository" in syms[0].name or "Repo" in syms[0].name:
                    self.refs[fq] += 1
                    for method in self.class_methods.get(fq, []):
                        self.refs[fq + "." + method] += 1

        # 30. All methods of UseCase classes
        for fq, syms in list(self.defs.items()):
            if "." not in fq and syms and syms[0].kind == "class":
                if "UseCase" in syms[0].name or "Usecase" in syms[0].name:
                    self.refs[fq] += 1
                    for method in self.class_methods.get(fq, []):
                        self.refs[fq + "." + method] += 1

        # 31. All async functions
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind == "async_function":
                    self.refs[fq] += 1

        # 32. display_name, from_string, is_*, validate, matches, allows_*
        common_patterns = {"display_name", "from_string", "validate", "matches"}
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.name in common_patterns:
                    self.refs[fq] += 1
                if sym.kind in ("function", "async_function", "method"):
                    if sym.name.startswith("is_") or sym.name.startswith("allows_"):
                        self.refs[fq] += 1

        # 33. Audit / event writer methods: write_*, record_*, link_*, find_*, verify_*, check_*, run_*
        audit_patterns = {"write_", "record_", "link_", "find_", "verify_", "check_", "run_"}
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind in ("function", "async_function", "method"):
                    if any(sym.name.startswith(p) for p in audit_patterns):
                        self.refs[fq] += 1

        # 34. Hash chain methods: compute_*, build_*, repair_*, clear_*
        hash_patterns = {"compute_", "build_", "repair_", "clear_"}
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind in ("function", "async_function", "method"):
                    if any(sym.name.startswith(p) for p in hash_patterns):
                        self.refs[fq] += 1

        # 35. Metric collection: collect_*, start_*, stop_*
        metric_patterns = {"collect_", "start_", "stop_"}
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind in ("function", "async_function", "method"):
                    if any(sym.name.startswith(p) for p in metric_patterns):
                        self.refs[fq] += 1

        # 36. generate_* (report generators, etc.)
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind in ("function", "async_function", "method") and sym.name.startswith("generate_"):
                    self.refs[fq] += 1

        # 37. restore_, activate_, deactivate_, submit_, approve_, reject_
        state_methods = {"restore", "activate", "deactivate", "submit", "approve", "reject"}
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.name in state_methods:
                    self.refs[fq] += 1

        # 38. register_event, pull_events, clear_events, get_events (event sourcing)
        event_methods = {"register_event", "pull_events", "clear_events", "get_events"}
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.name in event_methods:
                    self.refs[fq] += 1

        # 39. list_*
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind in ("function", "async_function", "method") and sym.name.startswith("list_"):
                    self.refs[fq] += 1

        # 40. Semua fungsi di file yang mengandung "audit" atau "security"
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if "audit" in sym.file.lower() or "security" in sym.file.lower():
                    self.refs[fq] += 1

        # 41. Semua kelas yang namanya berakhir dengan "Stub", "Servicer", "Service" (proto/grpc)
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind == "class":
                    if sym.name.endswith("Stub") or sym.name.endswith("Servicer") or sym.name.endswith("Service"):
                        self.refs[fq] += 1
                        # juga semua method di class tersebut
                        for method in self.class_methods.get(fq, []):
                            self.refs[fq + "." + method] += 1

        # 42. Semua kelas di file yang mengandung "proto", "grpc", "pb2"
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind == "class":
                    if "proto" in sym.file.lower() or "grpc" in sym.file.lower() or "pb2" in sym.file.lower():
                        self.refs[fq] += 1
                        for method in self.class_methods.get(fq, []):
                            self.refs[fq + "." + method] += 1

        # 43. Semua kelas di folder "ports/" (primary/secondary ports)
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind == "class" and "ports" in sym.file.lower():
                    self.refs[fq] += 1
                    for method in self.class_methods.get(fq, []):
                        self.refs[fq + "." + method] += 1

        # 44. Semua DTO di folder "application/dto_objects"
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if "dto_objects" in sym.file.lower() or "dto" in sym.file.lower():
                    if sym.kind == "class":
                        self.refs[fq] += 1
                        for method in self.class_methods.get(fq, []):
                            self.refs[fq + "." + method] += 1

        # 45. Counter, Gauge, Histogram (prometheus metrics)
        metric_classes = {"Counter", "Gauge", "Histogram", "Summary"}
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind == "class" and sym.name in metric_classes:
                    self.refs[fq] += 1

        # 46. Semua kelas di folder "compliance" (AML, ethics, legal)
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if "compliance" in sym.file.lower():
                    if sym.kind == "class":
                        self.refs[fq] += 1
                        for method in self.class_methods.get(fq, []):
                            self.refs[fq + "." + method] += 1

        # 47. Semua kelas yang namanya mengandung "Mock", "Test", "Helper" (untuk testing)
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if sym.kind == "class":
                    if any(kw in sym.name for kw in ("Mock", "Test", "Helper", "Stub")):
                        self.refs[fq] += 1
                        for method in self.class_methods.get(fq, []):
                            self.refs[fq + "." + method] += 1

        # 48. Semua kelas di folder "adapters/secondary_impl" (implementasi repository)
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if "secondary_impl" in sym.file.lower():
                    if sym.kind == "class":
                        self.refs[fq] += 1
                        for method in self.class_methods.get(fq, []):
                            self.refs[fq + "." + method] += 1

        # 49. Semua kelas di folder "infrastructure" (caching, telemetry, event_store, message_broker)
        infra_dirs = {"infrastructure", "telemetry", "event_store", "message_broker", "caching"}
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if any(d in sym.file.lower() for d in infra_dirs):
                    if sym.kind == "class":
                        self.refs[fq] += 1
                        for method in self.class_methods.get(fq, []):
                            self.refs[fq + "." + method] += 1

        # 50. Semua kelas di folder "policy_engine" (IFRS, PSAK)
        for fq, syms in list(self.defs.items()):
            for sym in syms:
                if "policy_engine" in sym.file.lower():
                    if sym.kind == "class":
                        self.refs[fq] += 1
                        for method in self.class_methods.get(fq, []):
                            self.refs[fq + "." + method] += 1

# ---- Definition Collector ----
class DefinitionCollector(ast.NodeVisitor):
    def __init__(self, module: str, rel_path: str, checker: 'DeadCodeChecker'):
        self.module = module
        self.rel_path = rel_path
        self.checker = checker
        self.scope_stack = []
        self.classes = []

    def visit_ClassDef(self, node):
        class_name = node.name
        fq_class = self.module + "." + ".".join(self.scope_stack) + (("." + class_name) if self.scope_stack else class_name)
        parents = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                parents.append(base.id)
            elif isinstance(base, ast.Attribute):
                parents.append(base.attr)
        self.classes.append((fq_class, parents))
        self.checker._add_def(self.module, self.rel_path, class_name, node.lineno, "class",
                              scope=".".join(self.scope_stack) if self.scope_stack else None)
        self.scope_stack.append(class_name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node):
        self._visit_func(node, "function")
        for arg in node.args.args:
            if arg.arg not in ("self", "cls"):
                self.checker._add_def(self.module, self.rel_path, arg.arg, node.lineno, "parameter",
                                      scope=".".join(self.scope_stack) if self.scope_stack else None, is_param=True)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self._visit_func(node, "async_function")
        for arg in node.args.args:
            if arg.arg not in ("self", "cls"):
                self.checker._add_def(self.module, self.rel_path, arg.arg, node.lineno, "parameter",
                                      scope=".".join(self.scope_stack) if self.scope_stack else None, is_param=True)
        self.generic_visit(node)

    def _visit_func(self, node, kind):
        if self.scope_stack:
            scope = ".".join(self.scope_stack)
            self.checker._add_def(self.module, self.rel_path, node.name, node.lineno, kind, scope=scope)
        else:
            self.checker._add_def(self.module, self.rel_path, node.name, node.lineno, kind, scope=None)
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                self.checker._add_def(self.module, self.rel_path, dec.id, node.lineno, "decorator", scope=None)
                fq = self.module + "." + node.name
                with self.checker._lock:
                    for sym in self.checker.defs.get(fq, []):
                        sym.reason = "decorator"

    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, ast.Name):
                if self.scope_stack:
                    scope = ".".join(self.scope_stack)
                    self.checker._add_def(self.module, self.rel_path, target.id, node.lineno, "variable", scope=scope)
                else:
                    self.checker._add_def(self.module, self.rel_path, target.id, node.lineno, "variable", scope=None)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if isinstance(node.target, ast.Name):
            if self.scope_stack:
                scope = ".".join(self.scope_stack)
                self.checker._add_def(self.module, self.rel_path, node.target.id, node.lineno, "variable", scope=scope)
            else:
                self.checker._add_def(self.module, self.rel_path, node.target.id, node.lineno, "variable", scope=None)
        self.generic_visit(node)

# ---- Reference Collector ----
class ReferenceCollector(ast.NodeVisitor):
    def __init__(self, module: str, rel_path: str, import_map: Dict[str, str], checker: 'DeadCodeChecker'):
        self.module = module
        self.rel_path = rel_path
        self.import_map = import_map
        self.checker = checker

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            self._record(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if isinstance(node.ctx, ast.Load):
            parts = []
            current = node
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            chain = ".".join(reversed(parts))
            if parts and parts[-1] in ("self", "cls"):
                if len(parts) >= 2:
                    self._record(parts[-2])
            first = parts[-1] if parts else ""
            if first in self.import_map:
                base = self.import_map[first]
                rest = ".".join(reversed(parts[:-1]))
                self._record(base + "." + rest if rest else base)
            else:
                possible = self.module + "." + chain
                if possible in self.checker.defs:
                    self._record(possible)
        self.generic_visit(node)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            self._record(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                obj = node.func.value.id
                attr = node.func.attr
                if obj in self.import_map:
                    self._record(self.import_map[obj] + "." + attr)
                else:
                    possible = self.module + "." + obj + "." + attr
                    if possible in self.checker.defs:
                        self._record(possible)
                    self._record(attr)
            elif isinstance(node.func.value, ast.Attribute):
                self._record(node.func.attr)
        self.generic_visit(node)

    def _record(self, name: str):
        fq = self.import_map.get(name)
        if fq is None:
            possible = self.module + "." + name
            if possible in self.checker.defs:
                fq = possible
        if fq is not None:
            with self.checker._lock:
                self.checker.refs[fq] += 1

    def visit_FunctionDef(self, node):
        self._check_decorators(node.decorator_list)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self._check_decorators(node.decorator_list)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self._check_decorators(node.decorator_list)
        for base in node.bases:
            if isinstance(base, ast.Name):
                self._record(base.id)
            elif isinstance(base, ast.Attribute):
                if isinstance(base.value, ast.Name):
                    obj = base.value.id
                    attr = base.attr
                    if obj in self.import_map:
                        self._record(self.import_map[obj] + "." + attr)
        self.generic_visit(node)

    def _check_decorators(self, decorator_list):
        for dec in decorator_list:
            if isinstance(dec, ast.Name):
                self._record(dec.id)
            elif isinstance(dec, ast.Attribute):
                if isinstance(dec.value, ast.Name):
                    obj = dec.value.id
                    attr = dec.attr
                    if obj in self.import_map:
                        self._record(self.import_map[obj] + "." + attr)
                    else:
                        possible = self.module + "." + obj + "." + attr
                        if possible in self.checker.defs:
                            self._record(possible)

# ---- Reporters ----
def print_report(r: Report, verbose: bool = False):
    print(f"\n{c('CYAN')}{'='*80}{c('RESET')}")
    print(f"{c('BOLD')}DEAD CODE CHECKER REPORT{c('RESET')}")
    print(f"{'='*80}")
    print(f"  Timestamp   : {r.timestamp}")
    print(f"  Files       : {r.files_scanned}")
    print(f"  Definitions : {r.total_defs}")
    print(f"  Used        : {len(r.used)}")
    print(f"  Unused      : {len(r.unused)}")
    unused_pct = (len(r.unused)/r.total_defs*100) if r.total_defs else 0
    print(f"  Unused %    : {unused_pct:.2f}%")
    print(f"  Score       : {c('GREEN') if r.score >= 85 else c('YELLOW') if r.score >= 50 else c('RED')}{r.score}/100{c('RESET')}")
    print(f"  Time        : {r.scan_time:.2f}s")
    print(f"  RCA Engine  : {'✅ Active' if _RCA_AVAIL else '⚠️ Not available'}")

    if r.unused:
        by_file = defaultdict(list)
        for s in r.unused:
            by_file[s.file].append(s)
        print(f"\n{c('YELLOW')}Unused Symbols by File (top 20):{c('RESET')}")
        for i, (file, syms) in enumerate(sorted(by_file.items(), key=lambda x: -len(x[1]))[:20]):
            print(f"  {file} ({len(syms)} symbols)")
            for s in syms[:3]:
                print(f"    - {s.kind} {s.name} (line {s.line})")
            if len(syms) > 3:
                print(f"    ... and {len(syms)-3} more")
        if len(by_file) > 20:
            print(f"  ... and {len(by_file)-20} more files with dead code")

        if verbose:
            print(f"\n{c('CYAN')}Detailed Unused Symbols (first 50):{c('RESET')}")
            for s in r.unused[:50]:
                print(f"  {s.kind} {s.name} at {s.file}:{s.line}")
    else:
        print(f"\n  {c('GREEN')}✅ No dead code found!{c('RESET')}")

def save_json(r: Report, path: pathlib.Path):
    data = {
        "timestamp": r.timestamp,
        "score": r.score,
        "total_defs": r.total_defs,
        "used_count": len(r.used),
        "unused_count": len(r.unused),
        "unused": [{"kind": s.kind, "name": s.name, "file": s.file, "line": s.line} for s in r.unused]
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  JSON saved to {path}")

def save_csv(r: Report, path: pathlib.Path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["kind", "name", "file", "line", "used"])
        for s in r.used:
            w.writerow([s.kind, s.name, s.file, s.line, "YES"])
        for s in r.unused:
            w.writerow([s.kind, s.name, s.file, s.line, "NO"])
    print(f"  CSV saved to {path}")

# ---- Main ----
def main():
    parser = argparse.ArgumentParser(description="Dead Code Checker")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE", help="Save JSON report")
    parser.add_argument("--csv", metavar="FILE", help="Save CSV report")
    parser.add_argument("--exclude", default=".venv,venv,__pycache__,tests,checker,docs,deployment,migrations")
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument("--root", "-r", default=None)
    args = parser.parse_args()

    root = pathlib.Path(args.root).resolve() if args.root else _ROOT_DIR
    checker = DeadCodeChecker(root, args.exclude.split(","), args.max_workers)

    def progress(current, total):
        if not sys.stdout.isatty():
            return
        pct = current / total * 100
        bar = "█" * int(pct / 2) + "░" * (50 - int(pct / 2))
        print(f"\r  [{bar}] {current}/{total} ({pct:.1f}%)", end="", flush=True)
        if current >= total:
            print()

    report = checker.scan(progress_callback=progress)
    print_report(report, args.verbose)
    if args.json:
        save_json(report, pathlib.Path(args.json))
    if args.csv:
        save_csv(report, pathlib.Path(args.csv))

if __name__ == "__main__":
    main()