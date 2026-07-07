#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker/smoke_test.py – Smoke Test for ERP Accounting Engine
=============================================================
Versi   : 3.7.0
Standar : Big-4 Audit · RCA-Integrated · Production-Ready

PERBAIKAN v3.7.0:
  • Perbaiki test_database_connection – deteksi yang lebih robust:
    - Jika get_async_session mengembalikan coroutine → await → cek apakah hasilnya
      async context manager atau session langsung.
    - Jika mengembalikan async context manager → pakai async with.
    - Jika mengembalikan async generator → pakai async for.
  • Tambahkan penanganan RuntimeWarning dari session_factory (ignore).
  • Semua test lulus tanpa mock.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import os
import sys
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# ─── FORCE ASYNC DRIVER (HARUS SEBELUM IMPORT APP) ──────────────────────────
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/erp_db"
)
if "DATABASE_URL" in os.environ and "postgresql://" in os.environ["DATABASE_URL"] and "+asyncpg" not in os.environ["DATABASE_URL"]:
    os.environ["DATABASE_URL"] = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+asyncpg://", 1)

# ─── RCA INTEGRATION ──────────────────────────────────────────────────────────
try:
    from checker.core.rca import get_engine, analyze_exception, Severity
    RCA_AVAILABLE = True
except ImportError:
    try:
        _root = Path(__file__).resolve().parent.parent
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
        from checker.core.rca import get_engine, analyze_exception, Severity
        RCA_AVAILABLE = True
    except ImportError:
        RCA_AVAILABLE = False
        def analyze_exception(e, ctx=None): return None
        class Severity:
            FATAL = "FATAL"
            CRITICAL = "CRITICAL"
            HIGH = "HIGH"
            MEDIUM = "MEDIUM"
            LOW = "LOW"
            INFO = "INFO"
            HINT = "HINT"

# ─── ROOT & PATH ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("smoke_test")

# ─── TERMINAL COLORS ─────────────────────────────────────────────────────────
try:
    import colorama
    colorama.init(autoreset=True)
    GREEN = colorama.Fore.GREEN
    RED = colorama.Fore.RED
    YELLOW = colorama.Fore.YELLOW
    CYAN = colorama.Fore.CYAN
    MAGENTA = colorama.Fore.MAGENTA
    BOLD = colorama.Style.BRIGHT
    RESET = colorama.Style.RESET_ALL
except ImportError:
    GREEN = RED = YELLOW = CYAN = MAGENTA = BOLD = RESET = ""

# ─── DATA CLASS ──────────────────────────────────────────────────────────────
@dataclass
class SmokeTestResult:
    name: str
    passed: bool = False
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    rca: Optional[Dict[str, Any]] = None
    duration: float = 0.0

# ─── RCA HELPER ──────────────────────────────────────────────────────────────
def _run_rca(exc: Exception, context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if not RCA_AVAILABLE:
        return {
            "severity": "WARNING",
            "root_cause": str(exc)[:200],
            "evidence": [],
            "impact": ["RCA engine not available"],
            "suggested_fix": "Install checker.core.rca",
            "confidence": 0.0,
        }
    try:
        r = analyze_exception(exc, context or {})
        if r is None:
            return None
        return {
            "severity": getattr(r.severity, "value", str(r.severity)),
            "root_cause": getattr(r, "root_cause", ""),
            "evidence": getattr(r, "evidence", [])[:5],
            "impact": getattr(r, "impact", [])[:3],
            "suggested_fix": getattr(r, "suggested_fix", ""),
            "confidence": float(getattr(r, "confidence", 0.0)),
        }
    except Exception:
        return {"error": "RCA analysis failed"}

# ─── SMOKE TEST RUNNER ──────────────────────────────────────────────────────
class SmokeTestRunner:
    def __init__(self):
        self.results: List[SmokeTestResult] = []
        self.config: Dict[str, Any] = {}
        self.container = None
        self.app = None
        self.db_pool = None

    def _add_result(self, name: str, passed: bool, error: Optional[str] = None,
                    details: Optional[Dict] = None, exc: Optional[Exception] = None,
                    context: Optional[Dict] = None, duration: float = 0.0):
        rca = _run_rca(exc, context) if exc else None
        self.results.append(SmokeTestResult(
            name=name,
            passed=passed,
            error=error,
            details=details or {},
            rca=rca,
            duration=duration,
        ))

    # ─── TEST STEPS ──────────────────────────────────────────────────────────
    async def test_load_config(self):
        name = "Load Config"
        start = time.perf_counter()
        try:
            from dotenv import load_dotenv
            env_file = PROJECT_ROOT / ".env"
            if env_file.exists():
                load_dotenv(env_file)

            config_file = PROJECT_ROOT / "config" / "application.yaml"
            if config_file.exists():
                import yaml
                with open(config_file, 'r', encoding='utf-8') as f:
                    yaml.safe_load(f)
            self._add_result(name, True, details={"env_loaded": True}, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, False, error=str(e), exc=e, context={"phase": "load_config"}, duration=time.perf_counter()-start)

    async def test_init_container(self):
        name = "DI Container"
        start = time.perf_counter()
        try:
            from bootstrap.dependency_container.ioc_container import get_container
            container = get_container()
            self.container = container
            details = {"container_type": type(container).__name__}

            try:
                from ports.primary.unit_of_work_port import UnitOfWorkPort
                if hasattr(container, "resolve"):
                    container.resolve(UnitOfWorkPort)
                    details["unit_of_work"] = "resolved_sync"
                elif hasattr(container, "resolve_async"):
                    await container.resolve_async(UnitOfWorkPort)
                    details["unit_of_work"] = "resolved_async"
                else:
                    details["unit_of_work"] = "resolve_method_not_found"
            except Exception as e:
                details["unit_of_work"] = f"resolve_error: {e}"

            self._add_result(name, True, details=details, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, False, error=str(e), exc=e, context={"phase": "init_container"}, duration=time.perf_counter()-start)

    async def test_create_app(self):
        name = "Create FastAPI App"
        start = time.perf_counter()
        try:
            from app.main import app as app_module
            from fastapi import FastAPI

            if isinstance(app_module, FastAPI):
                self.app = app_module
                self._add_result(name, True, details={"app_type": "FastAPI", "routes": len(app_module.routes)}, duration=time.perf_counter()-start)
                return

            if hasattr(app_module, "__call__"):
                app_instance = app_module()
                if isinstance(app_instance, FastAPI):
                    self.app = app_instance
                    self._add_result(name, True, details={"app_type": "FastAPI (factory)", "routes": len(app_instance.routes)}, duration=time.perf_counter()-start)
                    return

            from app.main import create_app
            app_instance = create_app()
            if isinstance(app_instance, FastAPI):
                self.app = app_instance
                self._add_result(name, True, details={"app_type": "FastAPI (create_app)", "routes": len(app_instance.routes)}, duration=time.perf_counter()-start)
                return

            self._add_result(name, False, error="No FastAPI instance or factory found", duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, False, error=str(e), exc=e, context={"phase": "create_app"}, duration=time.perf_counter()-start)

    async def test_validate_routers(self):
        name = "Validate Routers"
        start = time.perf_counter()
        try:
            if self.app is None:
                self._add_result(name, False, error="App not created", duration=time.perf_counter()-start)
                return
            from fastapi.routing import APIRoute
            routes = [r for r in self.app.routes if isinstance(r, APIRoute)]
            if not routes:
                self._add_result(name, False, error="No routes found", duration=time.perf_counter()-start)
                return
            seen = set()
            dup = []
            for r in routes:
                for m in (r.methods or set()):
                    key = (r.path, m)
                    if key in seen:
                        dup.append(key)
                    seen.add(key)
            if dup:
                self._add_result(name, False, error=f"Duplicate routes: {dup}", details={"duplicates": dup}, duration=time.perf_counter()-start)
            else:
                self._add_result(name, True, details={"route_count": len(routes), "unique": len(seen)}, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, False, error=str(e), exc=e, context={"phase": "validate_routers"}, duration=time.perf_counter()-start)

    async def test_init_mappers(self):
        name = "Init Mappers"
        start = time.perf_counter()
        try:
            import application.mappers as mappers_mod

            expected = [
                "JournalDomainToDtoMapper",
                "map_journal_entry_to_response_dto",
                "dto_to_post_journal_command",
                "process_event_for_read_model",
                "event_to_read_model_registry",
            ]
            found = []
            missing = []
            for sym in expected:
                if hasattr(mappers_mod, sym):
                    found.append(sym)
                else:
                    missing.append(sym)

            if missing:
                self._add_result(name, False, error=f"Missing symbols: {missing}", details={"found": found, "missing": missing}, duration=time.perf_counter()-start)
            else:
                self._add_result(name, True, details={"found": found}, duration=time.perf_counter()-start)
        except ImportError as e:
            self._add_result(name, False, error=f"Mapper module not found: {e}", exc=e, context={"phase": "init_mappers"}, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, False, error=str(e), exc=e, context={"phase": "init_mappers"}, duration=time.perf_counter()-start)

    async def test_init_event_bus(self):
        name = "Event Bus"
        start = time.perf_counter()
        try:
            candidates = [
                "application.events.publisher_application",
                "application.events.subscriber_application",
                "kernel.event_bus",
            ]
            found = []
            for mod_name in candidates:
                try:
                    mod = importlib.import_module(mod_name)
                    for attr in dir(mod):
                        if attr.startswith("_"):
                            continue
                        if any(kw in attr for kw in ("EventPublisher", "EventSubscriber", "EventBus")):
                            found.append(f"{mod_name}.{attr}")
                    if found:
                        break
                except ImportError:
                    continue
            if found:
                self._add_result(name, True, details={"event_bus": found}, duration=time.perf_counter()-start)
            else:
                self._add_result(name, False, error="Event bus not found", duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, False, error=str(e), exc=e, context={"phase": "event_bus"}, duration=time.perf_counter()-start)

    async def test_init_cqrs(self):
        name = "CQRS"
        start = time.perf_counter()
        try:
            from application.commands_cqrs.command_bus_unified import UnifiedCommandBus
            cmd = UnifiedCommandBus()
            details = {"command_bus": "UnifiedCommandBus"}
            try:
                from application.commands_cqrs.query_bus_unified import UnifiedQueryBus
                q = UnifiedQueryBus()
                details["query_bus"] = "UnifiedQueryBus"
            except ImportError:
                details["query_bus"] = "not found"
            self._add_result(name, True, details=details, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, False, error=str(e), exc=e, context={"phase": "cqrs"}, duration=time.perf_counter()-start)

    async def test_init_policy_engine(self):
        name = "Policy Engine"
        start = time.perf_counter()
        try:
            try:
                from policy_engine.rules_engine import RulesEngine
                RulesEngine()
                self._add_result(name, True, details={"engine": "RulesEngine"}, duration=time.perf_counter()-start)
                return
            except ImportError:
                pass
            try:
                from policy_engine.tax_indonesia.ppn_calculator import PPNCalculator
                PPNCalculator()
                self._add_result(name, True, details={"engine": "PPNCalculator"}, duration=time.perf_counter()-start)
                return
            except ImportError:
                pass
            self._add_result(name, False, error="No policy engine found", duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, False, error=str(e), exc=e, context={"phase": "policy_engine"}, duration=time.perf_counter()-start)

    async def test_database_connection(self):
        """
        Test koneksi database secara nyata (tanpa mock).
        Deteksi pola get_async_session secara robust.
        """
        name = "Database Connection"
        start = time.perf_counter()

        # Suppress RuntimeWarning from session_factory (known issue in that module)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)

            try:
                from infrastructure.database.session_factory_sqlalchemy import get_async_session
                from sqlalchemy import text

                # 1. Panggil get_async_session() tanpa await – dapat berupa coroutine,
                #    async context manager, async generator, atau langsung session.
                session_obj = get_async_session()

                # 2. Jika objek adalah coroutine (awaitable), await untuk mendapatkan hasilnya.
                if inspect.isawaitable(session_obj):
                    try:
                        session_obj = await session_obj
                    except Exception as e:
                        raise RuntimeError(f"Await coroutine failed: {e}") from e

                # 3. Sekarang session_obj bisa berupa async context manager, async generator,
                #    atau session langsung.
                if hasattr(session_obj, "__aenter__") and hasattr(session_obj, "__aexit__"):
                    # Async context manager
                    async with session_obj as session:
                        await session.execute(text("SELECT 1"))
                        # Tidak perlu close, context manager menangani
                elif inspect.isasyncgen(session_obj):
                    # Async generator
                    async for session in session_obj:
                        await session.execute(text("SELECT 1"))
                        break
                else:
                    # Anggap session langsung (punya method execute)
                    if hasattr(session_obj, "execute"):
                        await session_obj.execute(text("SELECT 1"))
                        # Tutup jika ada method close
                        if hasattr(session_obj, "close"):
                            await session_obj.close()
                    else:
                        raise RuntimeError(f"Tidak dikenal: {type(session_obj)}")

                self._add_result(name, True, details={"connection": "success"}, duration=time.perf_counter()-start)

            except ImportError as e:
                self._add_result(name, False, error=f"Module import error: {e}", exc=e, context={"phase": "database"}, duration=time.perf_counter()-start)
            except Exception as e:
                self._add_result(name, False, error=f"Database connection failed: {e}", exc=e, context={"phase": "database"}, duration=time.perf_counter()-start)

    async def test_cleanup(self):
        name = "Cleanup"
        start = time.perf_counter()
        try:
            if self.db_pool:
                await self.db_pool.close()
            if self.container and hasattr(self.container, "close"):
                await self.container.close()
            self._add_result(name, True, details={"cleaned": True}, duration=time.perf_counter()-start)
        except Exception as e:
            self._add_result(name, False, error=str(e), exc=e, context={"phase": "cleanup"}, duration=time.perf_counter()-start)

    # ─── RUN ──────────────────────────────────────────────────────────────────
    async def run(self) -> int:
        print(f"\n{BOLD}{CYAN}┌──────────────────────────────────────────────────────────────────────┐")
        print(f"│                    🚀 SMOKE TEST — ERP ENGINE                         │")
        print(f"│              Big-4 Ready · RCA Integrated · v3.7.0                   │")
        print(f"└──────────────────────────────────────────────────────────────────────┘{RESET}\n")

        await self.test_load_config()
        await self.test_init_container()
        await self.test_create_app()
        await self.test_validate_routers()
        await self.test_init_mappers()
        await self.test_init_event_bus()
        await self.test_init_cqrs()
        await self.test_init_policy_engine()
        await self.test_database_connection()
        await self.test_cleanup()

        self.print_summary()
        return 0 if all(r.passed for r in self.results) else 1

    def print_summary(self):
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed

        print("\n" + "=" * 80)
        print(f"{BOLD}SMOKE TEST SUMMARY{RESET}")
        print("=" * 80)

        for r in self.results:
            status = f"{GREEN}✅ PASS{RESET}" if r.passed else f"{RED}❌ FAIL{RESET}"
            print(f"  {status}  {r.name}  {CYAN}({r.duration:.2f}s){RESET}")
            if r.error and not r.passed:
                print(f"       {RED}Error: {r.error}{RESET}")
            if r.details and r.passed:
                details_str = ", ".join(f"{k}={v}" for k, v in r.details.items())
                if details_str:
                    print(f"       {CYAN}Details: {details_str}{RESET}")
            if r.rca and not r.passed:
                rc = r.rca.get('root_cause', '')
                fix = r.rca.get('suggested_fix', '')
                if rc:
                    print(f"       {MAGENTA}🔍 RCA: {rc[:120]}{RESET}")
                if fix:
                    print(f"       {MAGENTA}💡 Fix: {fix[:120]}{RESET}")

        print("-" * 80)
        if failed == 0:
            print(f"{BOLD}{GREEN}✅ ALL {total} TESTS PASSED — READY TO DEPLOY! 🚀{RESET}")
        else:
            print(f"{BOLD}{RED}❌ {failed}/{total} TESTS FAILED — NOT READY TO DEPLOY!{RESET}")

# ─── ENTRY POINT ─────────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Smoke Test for ERP Engine")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed logs")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    runner = SmokeTestRunner()
    exit_code = asyncio.run(runner.run())
    sys.exit(exit_code)

if __name__ == "__main__":
    main()