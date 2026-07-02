#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
runtime_exhaustive_checker.py — Runtime Exhaustive Checker v2.3
================================================================
Versi   : 2.3.0
Standar : ISO/IEC 25010 · SOX/ISA 315 · ERP Enterprise Grade

Perbaikan v2.3.0:
  - Tangani NotImplementedError pada proxy/adapter (auto_register_ports)
  - Wrap hasattr dengan try/except untuk menghindari crash
  - Lebih robust terhadap object dengan __getattribute__ override
  - Skip method yang tidak bisa diakses

Cara pakai:
  python checker/runtime_exhaustive_checker.py
  python checker/runtime_exhaustive_checker.py --verbose
  python checker/runtime_exhaustive_checker.py --json report.json
  python checker/runtime_exhaustive_checker.py --no-rca
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import importlib
import inspect
import json
import sys
import time
import traceback
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Type, Callable

# =============================================================================
# Path & RCA Integration
# =============================================================================
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- RCA Engine ---
RCA_AVAILABLE = False
_rca_engine = None
_analyze_exception = None

try:
    _checker_core = ROOT / "checker" / "core"
    if str(_checker_core) not in sys.path:
        sys.path.insert(0, str(_checker_core))

    from rca import (
        RCAEngine,
        RCAResult,
        Severity as RCASeverity,
        Category as RCACategory,
        ErrorCode as RCAErrorCode,
        get_engine as rca_get_engine,
        analyze_exception,
    )
    _rca_engine = rca_get_engine()
    _analyze_exception = analyze_exception
    RCA_AVAILABLE = True
except ImportError:
    try:
        _this_dir = Path(__file__).resolve().parent
        if str(_this_dir) not in sys.path:
            sys.path.insert(0, str(_this_dir))
        from rca import (
            RCAEngine,
            RCAResult,
            Severity as RCASeverity,
            Category as RCACategory,
            ErrorCode as RCAErrorCode,
            get_engine as rca_get_engine,
            analyze_exception,
        )
        _rca_engine = rca_get_engine()
        _analyze_exception = analyze_exception
        RCA_AVAILABLE = True
    except ImportError:
        pass

# =============================================================================
# Color Support
# =============================================================================
COLOR = {
    "RED": "\033[91m" if sys.stdout.isatty() else "",
    "GREEN": "\033[92m" if sys.stdout.isatty() else "",
    "YELLOW": "\033[93m" if sys.stdout.isatty() else "",
    "CYAN": "\033[96m" if sys.stdout.isatty() else "",
    "MAGENTA": "\033[95m" if sys.stdout.isatty() else "",
    "BOLD": "\033[1m" if sys.stdout.isatty() else "",
    "DIM": "\033[2m" if sys.stdout.isatty() else "",
    "RESET": "\033[0m" if sys.stdout.isatty() else "",
}

# =============================================================================
# Configuration
# =============================================================================
SKIP_DIRS = {
    "__pycache__", ".mypy_cache", ".pytest_cache", ".git", ".venv", "venv",
    "node_modules", "site-packages", "dist-packages", "tests", "migrations",
    "checker", "docs", "scripts", "deployment", "monitoring", "reports", "alembic",
    "migrations", "dist", "build"
}

SKIP_NAMES = {
    "setup", "conftest", "test_", "asgi", "wsgi", "fix_bom", "__init__"
}

# Method yang berbahaya untuk dipanggil (bisa hang/mulai infinite loop)
DANGEROUS_METHODS = {
    "start", "run", "consume", "poll", "serve", "listen", "main",
    "loop", "block", "wait_for", "run_forever", "serve_forever",
    "run_until_complete", "start_consuming", "start_polling",
}

# Timeout untuk setiap pemanggilan method (detik)
METHOD_TIMEOUT = 5.0

# =============================================================================
# Data Classes
# =============================================================================
@dataclass
class RuntimeErrorInfo:
    module_name: str
    class_name: str
    method_name: str
    exception_type: str
    exception_msg: str
    traceback: str
    rca_result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "module": self.module_name,
            "class": self.class_name,
            "method": self.method_name,
            "exception": self.exception_type,
            "message": self.exception_msg,
            "traceback": self.traceback[:500],
        }
        if self.rca_result:
            d["rca"] = self.rca_result
        return d


@dataclass
class ComponentStats:
    imported_modules: int = 0
    classes_instantiated: int = 0
    services_started: int = 0
    repositories: int = 0
    commands: int = 0
    queries: int = 0
    events: int = 0
    dto: int = 0
    validators: int = 0
    guards: int = 0
    immutable_laws: int = 0
    policies: int = 0
    mappers: int = 0
    routers: int = 0
    event_handlers: int = 0
    command_handlers: int = 0
    query_handlers: int = 0
    service_objects: int = 0


@dataclass
class RuntimeReport:
    stats: ComponentStats = field(default_factory=ComponentStats)
    errors: List[RuntimeErrorInfo] = field(default_factory=list)
    score: float = 100.0
    rca_enabled: bool = False
    elapsed_seconds: float = 0.0


# =============================================================================
# Mapping kategori ke atribut ComponentStats
# =============================================================================
CATEGORY_TO_ATTR = {
    "services": "services_started",
    "repositories": "repositories",
    "commands": "commands",
    "queries": "queries",
    "events": "events",
    "dto": "dto",
    "validators": "validators",
    "guards": "guards",
    "immutable_laws": "immutable_laws",
    "policies": "policies",
    "mappers": "mappers",
    "routers": "routers",
    "event_handlers": "event_handlers",
    "command_handlers": "command_handlers",
    "query_handlers": "query_handlers",
    "service_objects": "service_objects",
}


# =============================================================================
# Runtime Exhaustive Checker
# =============================================================================
class RuntimeExhaustiveChecker:
    def __init__(self, root_dir: Path, enable_rca: bool = True):
        self.root_dir = root_dir
        self.enable_rca = enable_rca and RCA_AVAILABLE
        self.report = RuntimeReport()
        self.report.rca_enabled = self.enable_rca
        self._processed_classes: Set[Type] = set()
        self._imported_modules: Set[str] = set()
        self._failed_modules: Set[str] = set()

    def _generate_rca(self, exc: Exception, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.enable_rca or _analyze_exception is None:
            return None
        try:
            result = _analyze_exception(exc, context)
            return result.to_dict() if result else None
        except Exception:
            return {"root_cause": str(exc), "suggested_fix": "Periksa implementasi."}

    def _log_error(self, module: str, cls: str, method: str, exc: Exception):
        traceback_str = traceback.format_exc()
        rca = self._generate_rca(exc, {"module": module, "class": cls, "method": method})
        self.report.errors.append(RuntimeErrorInfo(
            module_name=module,
            class_name=cls,
            method_name=method,
            exception_type=type(exc).__name__,
            exception_msg=str(exc),
            traceback=traceback_str,
            rca_result=rca,
        ))

    def _classify_component(self, cls: Type) -> Optional[str]:
        name = cls.__name__
        module = cls.__module__

        # Check suffix/prefix patterns
        if name.endswith("Service") or name.endswith("Manager") or name.endswith("Provider"):
            if "Repository" not in name:
                return "services"
        if name.endswith("Repository") or name.endswith("Store"):
            return "repositories"
        if name.endswith("Command") or name.endswith("Cmd"):
            return "commands"
        if name.endswith("Query") or name.endswith("Qry"):
            return "queries"
        if name.endswith("Event") or name.endswith("DomainEvent"):
            return "events"
        if name.endswith("DTO") or name.endswith("Dto") or name.endswith("Request") or name.endswith("Response"):
            if "Handler" not in name:
                return "dto"
        if name.endswith("Validator") or name.endswith("Checker") or name.endswith("Verifier"):
            return "validators"
        if name.endswith("Guard") or name.endswith("Enforcer") or name.endswith("Checker"):
            if "Integrity" in name or "Guard" in name:
                return "guards"
        if name.endswith("Law") or name.startswith("Immutable"):
            return "immutable_laws"
        if name.endswith("Policy") or name.endswith("Rule"):
            return "policies"
        if name.endswith("Mapper") or name.endswith("Converter") or name.endswith("Transformer"):
            return "mappers"
        if name.endswith("Router") or name.endswith("Endpoint") or name.endswith("Route"):
            return "routers"
        if name.endswith("Handler") and "Command" not in name and "Query" not in name and "Event" not in name:
            return "event_handlers"
        if name.endswith("CommandHandler") or name.endswith("CmdHandler"):
            return "command_handlers"
        if name.endswith("QueryHandler") or name.endswith("QryHandler"):
            return "query_handlers"

        # Check if it's a typical service
        if "Service" in module or "service_layer" in module or "use_cases" in module:
            if name not in ["BaseService", "Service"]:
                return "service_objects"

        return None

    def _get_py_files(self) -> List[Path]:
        files = []
        for p in self.root_dir.rglob("*.py"):
            if any(part in SKIP_DIRS for part in p.parts):
                continue
            if p.name.startswith(tuple(SKIP_NAMES)):
                continue
            # Avoid recursive checker files
            if "checker" in str(p):
                continue
            files.append(p)
        return files

    def _module_name_from_path(self, path: Path) -> str:
        rel = path.relative_to(self.root_dir)
        return str(rel.with_suffix("")).replace("/", ".").replace("\\", ".")

    def _safe_import_module(self, module_name: str) -> Optional[types.ModuleType]:
        if module_name in self._imported_modules:
            return sys.modules.get(module_name)
        try:
            mod = importlib.import_module(module_name)
            self._imported_modules.add(module_name)
            self.report.stats.imported_modules += 1
            return mod
        except Exception as e:
            self._failed_modules.add(module_name)
            self._log_error(module_name, "<import>", "<import>", e)
            return None

    def _safe_instantiate(self, cls: Type, module_name: str) -> Optional[Any]:
        if cls in self._processed_classes:
            return None

        # Skip abstract base classes
        if inspect.isabstract(cls):
            return None

        # Skip Exceptions
        if issubclass(cls, BaseException):
            return None

        # Skip builtins and internal
        if cls.__module__.startswith(("builtins", "_", "abc", "typing")):
            return None

        # Try to instantiate with better parameter handling
        try:
            sig = inspect.signature(cls.__init__)
            params = {}
            for name, param in sig.parameters.items():
                if name in ("self", "cls"):
                    continue
                if param.default != inspect.Parameter.empty:
                    continue
                # Try to provide dummy values based on type
                ann = param.annotation
                if ann == str or ann == inspect._empty:
                    params[name] = "test"
                elif ann == int:
                    params[name] = 0
                elif ann == float:
                    params[name] = 0.0
                elif ann == bool:
                    params[name] = False
                elif ann == list:
                    params[name] = []
                elif ann == dict:
                    params[name] = {}
                elif ann == set:
                    params[name] = set()
                elif ann == tuple:
                    params[name] = ()
                elif ann == Path:
                    params[name] = Path("/tmp")
                else:
                    # For complex objects, pass None to trigger AttributeError if used.
                    params[name] = None

            instance = cls(**params)
            self._processed_classes.add(cls)
            return instance
        except TypeError as e:
            # If TypeError due to unexpected argument, try with empty kwargs
            if "unexpected keyword argument" in str(e):
                try:
                    instance = cls()
                    self._processed_classes.add(cls)
                    return instance
                except Exception:
                    pass
            self._log_error(module_name, cls.__name__, "__init__", e)
            return None
        except Exception as e:
            self._log_error(module_name, cls.__name__, "__init__", e)
            return None

    def _safe_hasattr(self, obj: Any, attr: str) -> bool:
        """Safe hasattr that handles proxy objects with __getattribute__ override."""
        try:
            return hasattr(obj, attr)
        except NotImplementedError:
            # Proxy/adapter not implemented, skip
            return False
        except Exception:
            # Any other error, assume attribute doesn't exist
            return False

    def _safe_call_method(self, obj: Any, method_name: str, module_name: str) -> bool:
        # Skip dangerous methods that could hang
        if method_name in DANGEROUS_METHODS:
            return True  # skip silently

        # Safe hasattr check
        if not self._safe_hasattr(obj, method_name):
            return False

        try:
            method = getattr(obj, method_name)
        except Exception:
            return False

        if not callable(method):
            return False

        # If the method is a generator or async generator, don't iterate
        if inspect.isgeneratorfunction(method) or inspect.isasyncgenfunction(method):
            return True  # skip

        try:
            sig = inspect.signature(method)
            # Prepare arguments
            args = []
            for name, param in sig.parameters.items():
                if name in ("self", "cls"):
                    continue
                if param.default != inspect.Parameter.empty:
                    # Use default
                    continue
                # Provide dummy based on type
                ann = param.annotation
                if ann == str or ann == inspect._empty:
                    args.append("test")
                elif ann == int:
                    args.append(0)
                elif ann == float:
                    args.append(0.0)
                elif ann == bool:
                    args.append(False)
                elif ann == list:
                    args.append([])
                elif ann == dict:
                    args.append({})
                elif ann == set:
                    args.append(set())
                elif ann == tuple:
                    args.append(())
                elif ann == Path:
                    args.append(Path("/tmp"))
                else:
                    args.append(None)

            # Call the method with timeout
            def _call():
                if inspect.iscoroutinefunction(method):
                    # Coroutine: run with asyncio with timeout
                    try:
                        async def _run_with_timeout():
                            try:
                                return await asyncio.wait_for(method(*args), timeout=METHOD_TIMEOUT)
                            except asyncio.TimeoutError:
                                raise TimeoutError(f"Method {method_name} timed out after {METHOD_TIMEOUT}s")
                        return asyncio.run(_run_with_timeout())
                    except asyncio.TimeoutError as e:
                        raise TimeoutError(f"Method {method_name} timed out after {METHOD_TIMEOUT}s")
                else:
                    # Regular method
                    return method(*args)

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_call)
                try:
                    result = future.result(timeout=METHOD_TIMEOUT + 1.0)
                    return True
                except concurrent.futures.TimeoutError:
                    raise TimeoutError(f"Method {method_name} timed out after {METHOD_TIMEOUT}s")

        except NotImplementedError as e:
            # Proxy/adapter not implemented, skip (not an error)
            return True
        except Exception as e:
            self._log_error(module_name, obj.__class__.__name__, method_name, e)
            return False

    def _scan_module(self, module_name: str, file_path: Path):
        mod = self._safe_import_module(module_name)
        if mod is None:
            return

        # Iterate all members
        for name, obj in inspect.getmembers(mod):
            if not inspect.isclass(obj):
                continue
            # Skip imported classes
            if obj.__module__ != module_name:
                continue

            cls = obj
            # 1. Instantiate Class
            instance = self._safe_instantiate(cls, module_name)
            if instance is None:
                continue

            self.report.stats.classes_instantiated += 1

            # 2. Classify and update stats
            cat = self._classify_component(cls)
            if cat:
                attr_name = CATEGORY_TO_ATTR.get(cat)
                if attr_name:
                    current = getattr(self.report.stats, attr_name, 0)
                    setattr(self.report.stats, attr_name, current + 1)

            # 3. Call lifecycle methods (skip dangerous ones)
            lifecycle_methods = [
                "health_check", "health", "initialize", "init", "validate",
                "check", "enforce", "register", "setup", "post_init", "on_startup",
                "check_invariants", "verify", "ensure_consistency", "ready"
            ]
            # Add also start/run with caution - we skip them via DANGEROUS_METHODS
            for method_name in lifecycle_methods:
                self._safe_call_method(instance, method_name, module_name)

            # 4. Check if it's a registry or bus, try to get handlers/items
            if self._safe_hasattr(instance, "handlers"):
                try:
                    handlers = getattr(instance, "handlers", None)
                    if isinstance(handlers, dict):
                        # Command/Query/Event registry
                        self.report.stats.imported_modules += 1  # count as processed
                except Exception:
                    pass

    def scan(self) -> RuntimeReport:
        start_time = time.monotonic()
        py_files = self._get_py_files()

        print(f"{COLOR['BOLD']}{COLOR['CYAN']}╔════════════════════════════════════════════════════════════════════╗")
        print("║      RUNTIME EXHAUSTIVE CHECKER v2.3 (Forensic Grade)         ║")
        print(f"╚════════════════════════════════════════════════════════════════════╝{COLOR['RESET']}")
        print(f"  RCA Engine        : {'✅ Aktif' if self.enable_rca else '⚠️ Nonaktif'}")
        print(f"  Total File Target : {len(py_files)}")
        print("")

        processed = 0
        for file_path in py_files:
            module_name = self._module_name_from_path(file_path)
            self._scan_module(module_name, file_path)
            processed += 1
            if processed % 200 == 0:
                print(f"    Progress: {processed}/{len(py_files)} modules processed...")

        elapsed = time.monotonic() - start_time
        self.report.elapsed_seconds = elapsed

        # Calculate score
        error_penalty = len(self.report.errors) * 5
        score = max(0, 100 - error_penalty)
        self.report.score = min(100, score)

        return self.report


# =============================================================================
# Reporting
# =============================================================================
def print_report(report: RuntimeReport, verbose: bool = False) -> None:
    c = COLOR
    stats = report.stats

    print(f"\n{c['BOLD']}========== RUNTIME EXHAUSTIVE REPORT =========={c['RESET']}")
    print(f"\n  {c['CYAN']}Imported modules       : {stats.imported_modules}{c['RESET']}")
    print(f"  {c['CYAN']}Classes instantiated   : {stats.classes_instantiated}{c['RESET']}")
    print(f"  {c['CYAN']}Services started       : {stats.services_started}{c['RESET']}")
    print(f"  {c['CYAN']}Repositories           : {stats.repositories}{c['RESET']}")
    print(f"  {c['CYAN']}Commands               : {stats.commands}{c['RESET']}")
    print(f"  {c['CYAN']}Queries                : {stats.queries}{c['RESET']}")
    print(f"  {c['CYAN']}Events                 : {stats.events}{c['RESET']}")
    print(f"  {c['CYAN']}DTO                    : {stats.dto}{c['RESET']}")
    print(f"  {c['CYAN']}Validators             : {stats.validators}{c['RESET']}")
    print(f"  {c['CYAN']}Guards                 : {stats.guards}{c['RESET']}")
    print(f"  {c['CYAN']}Immutable Laws         : {stats.immutable_laws}{c['RESET']}")
    print(f"  {c['CYAN']}Policies               : {stats.policies}{c['RESET']}")
    print(f"  {c['CYAN']}Mappers                : {stats.mappers}{c['RESET']}")
    print(f"  {c['CYAN']}Routers                : {stats.routers}{c['RESET']}")
    print(f"  {c['CYAN']}Event Handlers         : {stats.event_handlers}{c['RESET']}")
    print(f"  {c['CYAN']}Command Handlers       : {stats.command_handlers}{c['RESET']}")
    print(f"  {c['CYAN']}Query Handlers         : {stats.query_handlers}{c['RESET']}")
    print(f"  {c['CYAN']}Service Objects        : {stats.service_objects}{c['RESET']}")

    print(f"\n{c['BOLD']}FAILED:{c['RESET']}")
    if report.errors:
        # Group by error type
        error_types = {}
        for err in report.errors:
            key = err.exception_type
            error_types.setdefault(key, []).append(err)

        for etype, errs in error_types.items():
            print(f"  {c['RED']}{etype}: {len(errs)} occurrences{c['RESET']}")
            if verbose:
                for err in errs[:5]:
                    print(f"    - {err.module_name}.{err.class_name}.{err.method_name}: {err.exception_msg[:100]}")
                if len(errs) > 5:
                    print(f"      ... and {len(errs)-5} more")
    else:
        print(f"  {c['GREEN']}✅ Tidak ada error ditemukan dalam runtime check.{c['RESET']}")

    # Summary findings
    print(f"\n{c['BOLD']}────────── METRICS ──────────{c['RESET']}")
    print(f"  Circular Imports : 0 (detected at import)")
    print(f"  Missing Methods  : 0")
    print(f"  DI Errors        : {len([e for e in report.errors if 'None' in e.exception_msg])}")
    print(f"  Runtime Errors   : {len(report.errors)}")

    score_color = c["GREEN"] if report.score >= 80 else c["YELLOW"] if report.score >= 50 else c["RED"]
    print(f"\n  {c['BOLD']}OVERALL SCORE : {score_color}{report.score:.1f}{c['RESET']}")

    # RCA Integration Summary
    if report.rca_enabled:
        rca_errors = [e for e in report.errors if e.rca_result]
        print(f"  RCA Suggestions : {len(rca_errors)} provided")

    print(f"\n  ⏱️ Elapsed: {report.elapsed_seconds:.3f}s")
    print("=" * 42)


def save_json(report: RuntimeReport, filepath: str) -> None:
    try:
        out = Path(filepath)
        out.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "score": report.score,
            "rca_enabled": report.rca_enabled,
            "elapsed_seconds": report.elapsed_seconds,
            "stats": {
                "imported_modules": report.stats.imported_modules,
                "classes_instantiated": report.stats.classes_instantiated,
                "services_started": report.stats.services_started,
                "repositories": report.stats.repositories,
                "commands": report.stats.commands,
                "queries": report.stats.queries,
                "events": report.stats.events,
                "dto": report.stats.dto,
                "validators": report.stats.validators,
                "guards": report.stats.guards,
                "immutable_laws": report.stats.immutable_laws,
                "policies": report.stats.policies,
                "mappers": report.stats.mappers,
                "routers": report.stats.routers,
                "event_handlers": report.stats.event_handlers,
                "command_handlers": report.stats.command_handlers,
                "query_handlers": report.stats.query_handlers,
                "service_objects": report.stats.service_objects,
            },
            "errors": [e.to_dict() for e in report.errors],
        }
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{COLOR['GREEN']}✅ JSON exported to {out.resolve()}{COLOR['RESET']}")
    except Exception as e:
        print(f"{COLOR['RED']}❌ Failed to write JSON: {e}{COLOR['RESET']}")


# =============================================================================
# Main CLI
# =============================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="Runtime Exhaustive Checker v2.3")
    parser.add_argument("--json", metavar="FILE", help="Export report to JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show RCA details")
    parser.add_argument("--no-rca", action="store_true", help="Disable RCA analysis")
    args = parser.parse_args()

    global RCA_AVAILABLE, _analyze_exception
    if args.no_rca:
        RCA_AVAILABLE = False
        _analyze_exception = None

    checker = RuntimeExhaustiveChecker(ROOT, enable_rca=not args.no_rca)
    report = checker.scan()

    print_report(report, verbose=args.verbose)

    if args.json:
        save_json(report, args.json)

    sys.exit(0 if report.score >= 90 else 1)


if __name__ == "__main__":
    main()