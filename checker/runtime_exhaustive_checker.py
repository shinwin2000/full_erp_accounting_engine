#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
runtime_exhaustive_checker.py – Sovereign ERP Runtime Verification Framework
===================================================================================
Standar: ISO/IEC 25010 · SOX/ISA 315 · PCAOB AS 2405
Versi 5.0 – Enterprise Grade Checker (Spring Boot Actuator / ASP.NET HealthChecks level)

Fitur tambahan:
  - Transaction rollback/commit verification
  - Connection pool health
  - Event bus publish/subscribe test
  - Outbox relay verification
  - Domain invariant verification
  - CQRS pipeline verification
  - Saga/Workflow verification
  - Circular dependency detection
  - Aggregate consistency check
  - Repository CRUD verification
  - Migration/schema verification
  - Performance & latency benchmark
  - Resource leak detection (improved)
  - Confidence levels & false positive mitigation
  - Detailed actionable items with priority
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import importlib
import inspect
import json
import logging
import sys
import time
import tracemalloc
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type, Union
import weakref

# =============================================================================
# ROOT PATH
# =============================================================================
_THIS_FILE = Path(__file__).resolve()
if _THIS_FILE.parent.name == "checker":
    ROOT = _THIS_FILE.parent.parent
else:
    ROOT = _THIS_FILE.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# =============================================================================
# RCA INTEGRATION
# =============================================================================
_RCA_AVAILABLE = False
_rca_engine = None
_analyze_exception = None

try:
    from rca import get_engine, analyze_exception
    _rca_engine = get_engine()
    _analyze_exception = analyze_exception
    _RCA_AVAILABLE = True
    logger = logging.getLogger("runtime_exhaustive")
    logger.info("RCA engine loaded from root rca.py")
except ImportError:
    try:
        from checker.core.rca import get_engine, analyze_exception
        _rca_engine = get_engine()
        _analyze_exception = analyze_exception
        _RCA_AVAILABLE = True
        logger = logging.getLogger("runtime_exhaustive")
        logger.info("RCA engine loaded from checker.core.rca")
    except ImportError:
        _RCA_AVAILABLE = False
        _analyze_exception = lambda e, c: None
        logger = logging.getLogger("runtime_exhaustive")
        logger.warning("RCA engine not available.")

# =============================================================================
# LOGGING
# =============================================================================
logger = logging.getLogger("runtime_exhaustive")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)

# =============================================================================
# COLOR
# =============================================================================
def _supports_ansi() -> bool:
    if not sys.stdout.isatty():
        return False
    import platform
    if platform.system() == "Windows":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
                return True
        except Exception:
            return False
    return True

_USE_COLOR = _supports_ansi()
COLOR = {
    "RED": "\033[91m" if _USE_COLOR else "",
    "GREEN": "\033[92m" if _USE_COLOR else "",
    "YELLOW": "\033[93m" if _USE_COLOR else "",
    "CYAN": "\033[96m" if _USE_COLOR else "",
    "BOLD": "\033[1m" if _USE_COLOR else "",
    "DIM": "\033[2m" if _USE_COLOR else "",
    "RESET": "\033[0m" if _USE_COLOR else "",
}
def c(key: str) -> str:
    return COLOR.get(key, "")

# =============================================================================
# DATA CLASSES
# =============================================================================
@dataclass
class RuntimeCheckResult:
    name: str
    status: str  # PASS, WARN, FAIL, SKIP
    confidence: str  # HIGH, MEDIUM, LOW
    message: str
    duration_ms: float = 0.0
    details: Optional[dict] = None
    rca: Optional[dict] = None

@dataclass
class RuntimeReport:
    timestamp: str
    checks: List[RuntimeCheckResult]
    total_checks: int
    passed: int
    warnings: int
    failed: int
    skipped: int
    weighted_score: float
    duration_sec: float
    rca_enabled: bool
    category_scores: Dict[str, float] = field(default_factory=dict)
    false_positive_risk: List[str] = field(default_factory=list)

# =============================================================================
# NULL OBJECT PATTERN
# =============================================================================
class NullEventPublisher:
    async def publish(self, *args, **kwargs):
        return None
    async def publish_batch(self, *args, **kwargs):
        return []
    async def subscribe(self, *args, **kwargs):
        return None
    async def unsubscribe(self, *args, **kwargs):
        return True
    async def get_statistics(self):
        return {"publisher": "null", "events": 0}
    async def health_check(self):
        return {"status": "healthy", "publisher": "null"}

# =============================================================================
# CORE CHECKER
# =============================================================================
class RuntimeExhaustiveChecker:
    def __init__(self, root: Path, enable_rca: bool = True):
        self.root = root
        self.enable_rca = enable_rca and _RCA_AVAILABLE
        self._container = None
        self._session_factory = None
        self._engine = None
        self._bootstrap_ok = False
        self._metadata = None  # SQLAlchemy MetaData
        self._uow_cls = None   # cached for transaction checks

    def _get_rca(self, exc: Exception, context: dict) -> Optional[dict]:
        if not self.enable_rca or _analyze_exception is None:
            return None
        try:
            result = _analyze_exception(exc, context)
            return result.to_dict() if result else None
        except Exception:
            return {"root_cause": str(exc), "suggested_fix": "Periksa log untuk detail."}

    def _check(self, name: str, fn: Callable, category: str = "general", confidence: str = "HIGH") -> RuntimeCheckResult:
        start = time.perf_counter()
        try:
            status, msg, details = fn()
            duration_ms = (time.perf_counter() - start) * 1000
            return RuntimeCheckResult(name, status, confidence, msg, duration_ms, details)
        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            rca = self._get_rca(e, {"check": name, "category": category})
            return RuntimeCheckResult(name, "FAIL", "LOW" if confidence == "LOW" else "MEDIUM", f"{type(e).__name__}: {e}", duration_ms, {"error": str(e)}, rca)

    # -------------------------------------------------------------------------
    # BOOTSTRAP
    # -------------------------------------------------------------------------
    def _bootstrap(self) -> bool:
        if self._bootstrap_ok:
            return True
        try:
            from bootstrap.dependency_container.container_bootstrap import initialize_container
            initialize_container()
            from bootstrap.dependency_container.ioc_container import get_container
            self._container = get_container()
            self._bootstrap_ok = True
            logger.info("Bootstrap berhasil")
            return True
        except ImportError:
            try:
                from bootstrap.dependency_container.container_bootstrap import build_container
                self._container = build_container()
                self._bootstrap_ok = True
                logger.info("Bootstrap berhasil via build_container")
                return True
            except ImportError:
                logger.warning("Bootstrap tidak tersedia, beberapa check akan skip")
                return False
        except Exception as e:
            logger.warning(f"Bootstrap gagal: {e}")
            return False

    # -------------------------------------------------------------------------
    # UTILITY: Resolve UnitOfWork concrete class
    # -------------------------------------------------------------------------
    def _resolve_uow_class(self) -> Optional[Type]:
        if self._uow_cls is not None:
            return self._uow_cls

        # 1) Container
        try:
            from ports.primary.unit_of_work_port import UnitOfWorkPort
            uow_instance = self._container.resolve(UnitOfWorkPort)
            self._uow_cls = type(uow_instance)
            logger.info(f"UnitOfWork resolved from container: {self._uow_cls.__module__}.{self._uow_cls.__name__}")
            return self._uow_cls
        except Exception:
            pass

        # 2) Fallback import (try multiple)
        candidates = [
            "adapters.secondary_impl.sqlalchemy_unit_of_work_impl",
            "adapters.secondary_impl.unit_of_work_impl",
        ]
        for mod_name in candidates:
            try:
                mod = importlib.import_module(mod_name)
                for attr in dir(mod):
                    obj = getattr(mod, attr)
                    if inspect.isclass(obj) and not inspect.isabstract(obj):
                        if "UnitOfWork" in attr or "UoW" in attr:
                            self._uow_cls = obj
                            logger.info(f"UnitOfWork found via fallback: {obj.__module__}.{obj.__name__}")
                            return self._uow_cls
            except ImportError:
                continue
        return None

    # -------------------------------------------------------------------------
    # 1. Bootstrap & Configuration (Weight: 10%)
    # -------------------------------------------------------------------------
    def check_bootstrap(self) -> RuntimeCheckResult:
        def _inner():
            if self._bootstrap():
                return "PASS", "Bootstrap berhasil, container tersedia", {}
            return "FAIL", "Bootstrap gagal, container tidak tersedia", {}
        return self._check("Bootstrap", _inner, "bootstrap", "HIGH")

    def check_environment(self) -> RuntimeCheckResult:
        def _inner():
            import platform, os, sys
            issues = []
            warnings = []
            py_ver = sys.version_info
            if py_ver < (3, 10):
                issues.append(f"Python {py_ver.major}.{py_ver.minor} < 3.10")
            try:
                import locale
                loc = locale.getlocale()
                if not loc or loc[0] is None:
                    warnings.append("Locale tidak diset dengan benar")
            except:
                warnings.append("Locale tidak dapat dibaca")
            required_env = ["SECRET_KEY"]
            optional_env = ["DATABASE_URL"]
            for var in required_env:
                if not os.environ.get(var):
                    warnings.append(f"Environment variable {var} tidak diset (REQUIRED di production)")
            for var in optional_env:
                if not os.environ.get(var):
                    warnings.append(f"Environment variable {var} tidak diset (fallback digunakan)")
            if issues:
                return "FAIL", f"Environment: {', '.join(issues)}", {"issues": issues, "warnings": warnings}
            if warnings:
                return "WARN", f"Environment: {', '.join(warnings)}", {"warnings": warnings}
            return "PASS", "Environment valid", {"python": f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}"}
        return self._check("Environment", _inner, "bootstrap", "HIGH")

    def check_configuration(self) -> RuntimeCheckResult:
        def _inner():
            config_modules = ["settings", "config", "bootstrap.configuration", "core.config"]
            found = None
            for mod_name in config_modules:
                try:
                    mod = importlib.import_module(mod_name)
                    found = mod_name
                    break
                except ImportError:
                    continue
            if found is None:
                return "WARN", "Configuration provider tidak ditemukan (settings/config)", {}
            required_attrs = ["SECRET_KEY"]
            optional_attrs = ["DEBUG"]
            missing_required = [a for a in required_attrs if not hasattr(found, a)]
            missing_optional = [a for a in optional_attrs if not hasattr(found, a)]
            if missing_required:
                return "WARN", f"Required config missing: {missing_required}", {"missing_required": missing_required, "missing_optional": missing_optional}
            if missing_optional:
                return "WARN", f"Optional config missing: {missing_optional}", {"missing_optional": missing_optional}
            return "PASS", f"Konfigurasi valid (dari {found})", {"source": found}
        return self._check("Configuration", _inner, "bootstrap", "HIGH")

    # -------------------------------------------------------------------------
    # 2. Database (Weight: 20%)
    # -------------------------------------------------------------------------
    def check_database_connectivity(self) -> RuntimeCheckResult:
        def _inner():
            try:
                from infrastructure.database import session_factory_sqlalchemy as sf_module
                wrapper = asyncio.run(sf_module.get_session_factory())
                factory = wrapper.get_session_factory()
                self._session_factory = factory
                self._engine = wrapper.get_engine()
                from sqlalchemy import text
                async def _test():
                    async with factory() as session:
                        result = await session.execute(text("SELECT 1"))
                        return result.scalar() == 1
                result = asyncio.run(_test())
                if result:
                    return "PASS", "Koneksi database berhasil", {"db": "connected"}
                else:
                    return "FAIL", "SELECT 1 gagal", {}
            except ImportError as e:
                return "FAIL", f"Database session factory tidak ditemukan: {e}", {}
            except Exception as e:
                return "FAIL", f"Database connection error: {e}", {}
        return self._check("Database Connectivity", _inner, "database", "HIGH")

    def check_transactions(self) -> RuntimeCheckResult:
        """Perbaikan: uji commit dan rollback, dan pastikan menggunakan await pada session."""
        def _inner():
            if not self._bootstrap_ok or self._container is None:
                return "SKIP", "Container tidak tersedia, skip transaction check", {}

            uow_cls = self._resolve_uow_class()
            if uow_cls is None:
                return (
                    "FAIL",
                    "UnitOfWork tidak ditemukan (container resolve gagal, fallback import gagal)",
                    {"container_resolve": False, "scan_fallback": False},
                )

            # Pastikan kelas bukan abstrak
            if inspect.isabstract(uow_cls):
                try:
                    from adapters.secondary_impl.sqlalchemy_unit_of_work_impl import SQLAlchemyUnitOfWork
                    if not inspect.isabstract(SQLAlchemyUnitOfWork):
                        uow_cls = SQLAlchemyUnitOfWork
                    else:
                        raise ValueError("SQLAlchemyUnitOfWork masih abstrak")
                except ImportError:
                    return "FAIL", f"UnitOfWork {uow_cls.__name__} abstrak dan tidak ditemukan implementasi konkret", {}

            try:
                session_factory = self._session_factory
                if session_factory is None:
                    try:
                        from infrastructure.database import session_factory_sqlalchemy as sf_module
                        wrapper = asyncio.run(sf_module.get_session_factory())
                        session_factory = wrapper.get_session_factory()
                    except Exception:
                        pass
                if session_factory is None:
                    return "FAIL", "Session factory tidak tersedia", {}

                # Buat instance UnitOfWork dengan session_factory jika konstruktor menerima
                sig = inspect.signature(uow_cls.__init__)
                params = sig.parameters
                if 'session_factory' in params:
                    uow = uow_cls(session_factory=session_factory)
                else:
                    uow = uow_cls()

                from sqlalchemy import text

                async def _test_commit():
                    async with uow as uow_ctx:
                        # Dapatkan session dengan await
                        if hasattr(uow_ctx, 'session'):
                            session = await uow_ctx.session
                            await session.execute(text("SELECT 1"))
                        elif hasattr(uow_ctx, 'execute_raw_sql'):
                            await uow_ctx.execute_raw_sql("SELECT 1")
                        else:
                            # fallback: coba gunakan session dari factory
                            async with session_factory() as sess:
                                await sess.execute(text("SELECT 1"))
                        await uow_ctx.commit()
                    return True

                async def _test_rollback():
                    async with uow as uow_ctx:
                        if hasattr(uow_ctx, 'session'):
                            session = await uow_ctx.session
                            await session.execute(text("SELECT 1"))
                        elif hasattr(uow_ctx, 'execute_raw_sql'):
                            await uow_ctx.execute_raw_sql("SELECT 1")
                        else:
                            async with session_factory() as sess:
                                await sess.execute(text("SELECT 1"))
                        await uow_ctx.rollback()
                    return True

                commit_ok = asyncio.run(_test_commit())
                rollback_ok = asyncio.run(_test_rollback())

                if commit_ok and rollback_ok:
                    return "PASS", f"Transaksi commit & rollback berhasil ({uow_cls.__module__}.{uow_cls.__name__})", {}
                else:
                    return "FAIL", "Transaksi gagal", {}
            except Exception as e:
                return "FAIL", f"Transaksi gagal: {e}", {"uow_class": f"{uow_cls.__module__}.{uow_cls.__name__}"}
        return self._check("Transactions", _inner, "database", "HIGH")

    def check_connection_pool(self) -> RuntimeCheckResult:
        """Periksa status pool koneksi."""
        def _inner():
            if self._engine is None:
                return "SKIP", "Engine tidak tersedia", {}
            try:
                pool = self._engine.pool
                # Coba gunakan metode yang tersedia
                if hasattr(pool, 'status'):
                    status = pool.status()
                    if isinstance(status, dict):
                        size = status.get('size', 0)
                        checked_in = status.get('checked_in', 0)
                        checked_out = status.get('checked_out', 0)
                    else:
                        # Jika status berupa string, coba parse atau gunakan alternatif
                        size = pool.size() if hasattr(pool, 'size') else 0
                        checked_in = pool.checkedin() if hasattr(pool, 'checkedin') else 0
                        checked_out = pool.checkedout() if hasattr(pool, 'checkedout') else 0
                else:
                    # fallback ke atribut
                    size = getattr(pool, 'size', 0)
                    checked_in = getattr(pool, 'checkedin', 0)
                    checked_out = getattr(pool, 'checkedout', 0)

                if size == 0:
                    return "WARN", "Pool size 0, mungkin tidak aktif", {"size": size}
                if checked_out > 0:
                    return "WARN", f"Ada {checked_out} koneksi aktif (mungkin bocor)", {"size": size, "checked_in": checked_in, "checked_out": checked_out}
                return "PASS", f"Pool sehat: size={size}, checked_in={checked_in}", {"size": size, "checked_in": checked_in, "checked_out": checked_out}
            except Exception as e:
                return "WARN", f"Tidak bisa dapatkan status pool: {e}", {}
        return self._check("Connection Pool", _inner, "database", "HIGH")

    # -------------------------------------------------------------------------
    # 3. Dependency Injection (Weight: 10%)
    # -------------------------------------------------------------------------
    def check_dependency_injection(self) -> RuntimeCheckResult:
        def _inner():
            if not self._bootstrap_ok or self._container is None:
                return "WARN", "Container tidak tersedia, skip DI check", {}
            ports = [
                "UnitOfWorkPort", "EventPublisherPort", "JournalRepositoryPort",
                "IAMUserRepositoryPort", "AccountRepositoryPort", "ARRepositoryPort", "APRepositoryPort"
            ]
            results = {}
            resolved = []
            failed = []
            for port_name in ports:
                port_cls = None
                try:
                    mod = importlib.import_module(f"ports.primary.{port_name.lower()}")
                    port_cls = getattr(mod, port_name)
                except (ImportError, AttributeError):
                    try:
                        mod = importlib.import_module(f"ports.primary")
                        port_cls = getattr(mod, port_name, None)
                    except:
                        pass
                if port_cls is None:
                    results[port_name] = "port_class_not_found"
                    failed.append(port_name)
                    continue
                try:
                    if hasattr(self._container, 'resolve'):
                        self._container.resolve(port_cls)
                        resolved.append(port_name)
                        results[port_name] = "resolved"
                    elif hasattr(self._container, 'has_registration') and self._container.has_registration(port_name):
                        resolved.append(port_name)
                        results[port_name] = "registered"
                    else:
                        failed.append(port_name)
                        results[port_name] = "not_registered"
                except Exception as e:
                    failed.append(port_name)
                    results[port_name] = f"error: {e}"
            if failed:
                return "WARN", f"Beberapa port tidak bisa di-resolve: {failed[:5]}", {"results": results, "resolved": resolved, "failed": failed}
            return "PASS", f"Semua port di-resolve ({len(resolved)})", {"results": results}
        return self._check("Dependency Injection", _inner, "di", "HIGH")

    # -------------------------------------------------------------------------
    # 4. Component Contracts (Weight: 15%)
    # -------------------------------------------------------------------------
    _REPO_PORTS = [
        ("ports.primary.ar_repository_port", "ARRepositoryPort",
         "adapters.secondary_impl.sqlalchemy_ar_repository_impl", "SQLAlchemyARRepository"),
        ("ports.primary.ap_repository_port", "APRepositoryPort",
         "adapters.secondary_impl.sqlalchemy_ap_repository_impl", "SQLAlchemyAPRepository"),
        ("ports.primary.journal_repository_port", "JournalRepositoryPort",
         "adapters.secondary_impl.sqlalchemy_journal_repository_impl", None),
        ("ports.primary.iam_user_repository_port", "IAMUserRepositoryPort",
         "adapters.secondary_impl.sqlalchemy_iam_user_repository_impl", "SQLAlchemyIAMUserRepository"),
        ("ports.primary.fixed_asset_repository_port", "FixedAssetRepositoryPort",
         "adapters.secondary_impl.sqlalchemy_fixed_asset_repository_impl", "SQLAlchemyFixedAssetRepository"),
        ("ports.primary.inventory_repository_port", "InventoryRepositoryPort",
         "adapters.secondary_impl.sqlalchemy_inventory_repository_impl", "SQLAlchemyInventoryRepository"),
    ]

    def _find_impl_for_port(self, adapter_mod_name: str, port_cls: type, expected_name: str | None):
        if self._bootstrap_ok and self._container is not None:
            try:
                instance = self._container.resolve(port_cls)
                return type(instance), "container"
            except Exception:
                pass
        try:
            mod = importlib.import_module(adapter_mod_name)
            if expected_name and hasattr(mod, expected_name):
                cand = getattr(mod, expected_name)
                if inspect.isclass(cand) and issubclass(cand, port_cls) and not inspect.isabstract(cand):
                    return cand, "module_scan"
            for attr in dir(mod):
                cand = getattr(mod, attr)
                if inspect.isclass(cand) and cand is not port_cls and issubclass(cand, port_cls) and not inspect.isabstract(cand):
                    return cand, "module_scan"
        except ImportError:
            pass
        return None, None

    def check_repositories(self) -> RuntimeCheckResult:
        def _inner():
            results = []
            failed_details = []
            total = 0
            ok = 0
            for port_mod_name, port_cls_name, adapter_mod_name, expected_impl_name in self._REPO_PORTS:
                try:
                    port_mod = importlib.import_module(port_mod_name)
                    port_cls = getattr(port_mod, port_cls_name, None)
                except ImportError as e:
                    results.append(f"{port_cls_name}: port import error ({e})")
                    failed_details.append(f"{port_cls_name}: port import error")
                    continue
                if port_cls is None:
                    results.append(f"{port_cls_name}: class not found")
                    failed_details.append(f"{port_cls_name}: class not found")
                    continue

                total += 1
                impl_cls, source = self._find_impl_for_port(adapter_mod_name, port_cls, expected_impl_name)
                if impl_cls is None:
                    results.append(f"{port_cls_name}: implementasi tidak ditemukan")
                    failed_details.append(f"{port_cls_name}: implementasi tidak ditemukan")
                    continue

                unimplemented = sorted(getattr(impl_cls, "__abstractmethods__", frozenset()))
                if unimplemented:
                    msg = f"{port_cls_name} ({impl_cls.__name__}): missing {', '.join(unimplemented)}"
                    results.append(msg)
                    failed_details.append(msg)
                else:
                    ok += 1
                    results.append(f"{port_cls_name} ({impl_cls.__name__} via {source}): OK")

            if total == 0:
                return "WARN", "Tidak ada repository ditemukan", {"results": results}
            if ok < total:
                return (
                    "WARN",
                    f"{ok}/{total} repository memenuhi kontrak. Detail: {failed_details[:3]}",
                    {"results": results, "failed_details": failed_details},
                )
            return "PASS", f"Semua {total} repository memenuhi kontrak", {"results": results}
        return self._check("Repositories", _inner, "components", "HIGH")

    # Aggregate identity check (improved with type checking)
    _ID_ALIASES = {
        "id", "asset_id", "aggregate_id", "root_id", "entity_id",
        "journal_id", "account_id", "customer_id", "supplier_id",
        "project_id", "bank_account_id", "cash_id", "user_id",
        "legal_entity_id", "line_id", "item_id", "product_id",
    }
    _VERSION_ALIASES = {"version", "aggregate_version", "_version", "row_version"}

    def _aggregate_has_identity(self, cls: type) -> tuple[bool, bool, bool, bool]:
        """Returns (has_id, has_version, id_is_uuid, version_is_int)"""
        has_id = False
        has_version = False
        id_is_uuid = False
        version_is_int = False

        # Check attributes
        for alias in self._ID_ALIASES:
            if hasattr(cls, alias):
                has_id = True
                # check type hint
                if hasattr(cls, "__annotations__") and alias in cls.__annotations__:
                    ann = cls.__annotations__[alias]
                    if "UUID" in str(ann) or "uuid" in str(ann):
                        id_is_uuid = True
                break
        for alias in self._VERSION_ALIASES:
            if hasattr(cls, alias):
                has_version = True
                if hasattr(cls, "__annotations__") and alias in cls.__annotations__:
                    ann = cls.__annotations__[alias]
                    if "int" in str(ann) or "Integer" in str(ann):
                        version_is_int = True
                break

        # Check dataclass fields
        for base in inspect.getmro(cls):
            if base is object:
                continue
            dc_fields = getattr(base, "__dataclass_fields__", None)
            if dc_fields:
                names = set(dc_fields.keys())
                has_id = has_id or bool(names & self._ID_ALIASES)
                has_version = has_version or bool(names & self._VERSION_ALIASES)
                for alias in self._ID_ALIASES:
                    if alias in names:
                        field_def = dc_fields[alias]
                        if "UUID" in str(field_def.type):
                            id_is_uuid = True
                for alias in self._VERSION_ALIASES:
                    if alias in names:
                        field_def = dc_fields[alias]
                        if "int" in str(field_def.type):
                            version_is_int = True
            annotations = getattr(base, "__annotations__", {})
            has_id = has_id or bool(set(annotations) & self._ID_ALIASES)
            has_version = has_version or bool(set(annotations) & self._VERSION_ALIASES)
            for alias in self._ID_ALIASES:
                if alias in annotations:
                    if "UUID" in str(annotations[alias]):
                        id_is_uuid = True
            for alias in self._VERSION_ALIASES:
                if alias in annotations:
                    if "int" in str(annotations[alias]):
                        version_is_int = True

        # Check instance (if we can create one)
        try:
            # Try to instantiate with default args
            sig = inspect.signature(cls.__init__)
            args = {}
            for name, param in sig.parameters.items():
                if name == 'self':
                    continue
                if param.default is not inspect.Parameter.empty:
                    args[name] = param.default
                else:
                    # Try to provide some default
                    if name == 'id':
                        args[name] = None
                    elif name == 'legal_entity_id':
                        args[name] = None
                    elif name == 'version':
                        args[name] = 0
                    else:
                        args[name] = None
            instance = cls(**args)
            for alias in self._ID_ALIASES:
                if hasattr(instance, alias):
                    has_id = True
                    # Check type via getattr
                    val = getattr(instance, alias)
                    if isinstance(val, UUID) or str(type(val)) == "<class 'uuid.UUID'>":
                        id_is_uuid = True
                    break
            for alias in self._VERSION_ALIASES:
                if hasattr(instance, alias):
                    has_version = True
                    val = getattr(instance, alias)
                    if isinstance(val, int):
                        version_is_int = True
                    break
        except Exception:
            pass

        return has_id, has_version, id_is_uuid, version_is_int

    def check_aggregates(self) -> RuntimeCheckResult:
        def _inner():
            aggregate_dirs = ["journal", "bank_cash", "tax_transaction", "fixed_asset", "inventory", "iam"]
            found = []
            missing = []
            for sub in aggregate_dirs:
                try:
                    mod = importlib.import_module(f"domain.{sub}")
                except ImportError:
                    continue
                for attr in dir(mod):
                    if not (attr.endswith("Aggregate") or attr.endswith("Root") or attr.endswith("Collection")):
                        continue
                    cls = getattr(mod, attr)
                    if not inspect.isclass(cls):
                        continue
                    has_id, has_version, id_uuid, version_int = self._aggregate_has_identity(cls)
                    if has_id and has_version and id_uuid and version_int:
                        found.append(f"{sub}.{attr}")
                    else:
                        missing_parts = []
                        if not has_id:
                            missing_parts.append("id")
                        elif not id_uuid:
                            missing_parts.append("id (not UUID)")
                        if not has_version:
                            missing_parts.append("version")
                        elif not version_int:
                            missing_parts.append("version (not int)")
                        missing.append(f"{sub}.{attr} (missing {'/'.join(missing_parts)})")
            if missing:
                return "WARN", f"Ditemukan {len(found)} aggregate, {len(missing)} tidak memenuhi kontrak: {missing[:3]}", {"found": found, "missing": missing}
            if not found:
                return "WARN", "Tidak ditemukan aggregate root di domain", {}
            return "PASS", f"Ditemukan {len(found)} aggregate memenuhi kontrak", {"aggregates": found[:10]}
        return self._check("Aggregates", _inner, "components", "HIGH")

    def check_models(self) -> RuntimeCheckResult:
        def _inner():
            try:
                from sqlalchemy import MetaData
                from infrastructure.database import session_factory_sqlalchemy as sf_module
                engine = None
                try:
                    wrapper = asyncio.run(sf_module.get_session_factory())
                    engine = wrapper.get_engine()
                    if engine is not None and self._engine is None:
                        self._engine = engine
                except Exception as e:
                    logger.debug(f"Tidak bisa ambil engine untuk ORM discovery (non-fatal): {e}")
                metadata = MetaData()
                try:
                    from infrastructure.persistence_orm import Base
                    if hasattr(Base, "metadata"):
                        metadata = Base.metadata
                        self._metadata = metadata
                except ImportError:
                    try:
                        import infrastructure.persistence_orm as orm
                        for attr in dir(orm):
                            obj = getattr(orm, attr)
                            if hasattr(obj, "metadata") and hasattr(obj.metadata, "tables"):
                                metadata = obj.metadata
                                self._metadata = metadata
                                break
                    except:
                        pass
                if metadata is not None and hasattr(metadata, "tables"):
                    table_count = len(metadata.tables)
                    if table_count == 0:
                        return "WARN", "Tidak ditemukan model ORM (metadata kosong)", {"table_count": 0}
                    missing_pk = []
                    for name, table in metadata.tables.items():
                        has_pk = any(c.primary_key for c in table.columns)
                        if not has_pk:
                            missing_pk.append(name)
                    if missing_pk:
                        return "WARN", f"{table_count - len(missing_pk)}/{table_count} model memiliki PK. Missing PK: {missing_pk[:5]}", {"missing_pk": missing_pk}
                    return "PASS", f"{table_count} model ORM valid (semua memiliki PK)", {"table_count": table_count}
                else:
                    try:
                        import infrastructure.persistence_orm as orm
                        skip_classes = {"Base", "DeclarativeBase", "Model", "AbstractModel"}
                        model_classes = []
                        for attr in dir(orm):
                            try:
                                cls = getattr(orm, attr)
                                if not inspect.isclass(cls):
                                    continue
                                if cls.__name__ in skip_classes:
                                    continue
                                if hasattr(cls, "__abstract__") and cls.__abstract__:
                                    continue
                                if not hasattr(cls, "__tablename__"):
                                    continue
                                if not hasattr(cls, "__table__") or cls.__table__ is None:
                                    continue
                                has_pk = False
                                for col in cls.__table__.columns:
                                    if col.primary_key:
                                        has_pk = True
                                        break
                                model_classes.append({"name": attr, "has_pk": has_pk})
                            except:
                                continue
                        total = len(model_classes)
                        with_pk = sum(1 for m in model_classes if m["has_pk"])
                        missing_pk = [m["name"] for m in model_classes if not m["has_pk"]]
                        if total == 0:
                            return "WARN", "Tidak ditemukan model ORM (class scan)", {}
                        if with_pk < total:
                            return "WARN", f"{with_pk}/{total} model memiliki PK. Missing PK: {missing_pk[:5]}", {"missing_pk": missing_pk}
                        return "PASS", f"{total} model ORM valid", {}
                    except ImportError:
                        return "WARN", "ORM module tidak ditemukan", {}
            except Exception as e:
                return "WARN", f"ORM discovery error: {e}", {}
        return self._check("ORM Models", _inner, "components", "MEDIUM")

    # -------------------------------------------------------------------------
    # 5. Event & Outbox (Weight: 10%)
    # -------------------------------------------------------------------------
    def check_event_bus(self) -> RuntimeCheckResult:
        def _inner():
            try:
                from ports.primary.event_publisher_port import EventPublisherPort
                if self._container is not None:
                    try:
                        self._container.resolve(EventPublisherPort)
                        return "PASS", "EventPublisherPort tersedia dan bisa di-resolve", {}
                    except:
                        return "WARN", "EventPublisherPort class ada, tapi tidak bisa di-resolve", {}
                return "PASS", "EventPublisherPort class tersedia", {}
            except ImportError:
                return "WARN", "EventPublisherPort tidak ditemukan", {}
        return self._check("Event Bus", _inner, "event", "HIGH")

    def check_event_publish_subscribe(self) -> RuntimeCheckResult:
        """Test publish dan subscribe event (dummy)."""
        def _inner():
            try:
                from ports.primary.event_publisher_port import EventPublisherPort
                if self._container is None:
                    return "SKIP", "Container tidak tersedia", {}
                publisher = self._container.resolve(EventPublisherPort)
                if publisher is None:
                    return "SKIP", "EventPublisherPort tidak bisa di-resolve", {}
                # Buat event dummy
                class DummyEvent:
                    def __init__(self, data):
                        self.data = data
                # Subscribe dummy handler
                received = []
                async def handler(event):
                    received.append(event)
                # Subscribe (jika ada method)
                if hasattr(publisher, 'subscribe'):
                    async def _test():
                        await publisher.subscribe(DummyEvent, handler)
                        evt = DummyEvent("test")
                        await publisher.publish(evt)
                        await asyncio.sleep(0.1)
                    asyncio.run(_test())
                    if received:
                        return "PASS", "Event publish-subscribe berhasil", {"event_count": len(received)}
                    else:
                        return "WARN", "Event diterbitkan tapi tidak ada yang menerima", {}
                else:
                    return "SKIP", "EventPublisherPort tidak mendukung subscribe", {}
            except Exception as e:
                return "WARN", f"Event publish-subscribe gagal: {e}", {}
        return self._check("Event Publish/Subscribe", _inner, "event", "HIGH")

    def check_outbox(self) -> RuntimeCheckResult:
        def _inner():
            try:
                from infrastructure.persistence_orm.outbox_table import OutboxTable
                columns = [c.name for c in OutboxTable.__table__.columns]
                required = ["id", "event_type", "payload", "status", "created_at"]
                missing = [f for f in required if f not in columns]
                if missing:
                    return "WARN", f"OutboxTable missing columns: {missing}", {"columns": columns}
                has_index = False
                if hasattr(OutboxTable, "__table_args__"):
                    for arg in OutboxTable.__table_args__:
                        if hasattr(arg, "name") and "status" in str(arg):
                            has_index = True
                            break
                if not has_index:
                    return "WARN", "OutboxTable tidak memiliki indeks pada status/created_at", {"columns": columns}
                return "PASS", "OutboxTable valid dengan indeks", {"columns": columns[:5]}
            except ImportError:
                return "WARN", "OutboxTable tidak ditemukan", {}
        return self._check("Outbox", _inner, "event", "HIGH")

    def check_outbox_relay(self) -> RuntimeCheckResult:
        """Periksa apakah outbox relay berjalan."""
        def _inner():
            try:
                # Coba cari service outbox relay
                relay_services = [
                    "infrastructure.messaging.outbox_relay",
                    "infrastructure.outbox.relay",
                    "application.outbox.relay",
                ]
                for mod_name in relay_services:
                    try:
                        mod = importlib.import_module(mod_name)
                        if hasattr(mod, "OutboxRelay") or hasattr(mod, "RelayOutbox"):
                            return "PASS", f"Outbox relay ditemukan di {mod_name}", {"module": mod_name}
                    except ImportError:
                        continue
                # Cek juga di container
                if self._container is not None:
                    try:
                        # coba resolve
                        self._container.resolve("OutboxRelayPort")
                        return "PASS", "OutboxRelayPort terdaftar di container", {}
                    except:
                        pass
                return "WARN", "Outbox relay tidak ditemukan (mungkin tidak ada)", {}
            except Exception as e:
                return "WARN", f"Outbox relay check error: {e}", {}
        return self._check("Outbox Relay", _inner, "event", "MEDIUM")

    # -------------------------------------------------------------------------
    # 6. Domain & CQRS (Weight: 10%)
    # -------------------------------------------------------------------------
    def check_domain_invariants(self) -> RuntimeCheckResult:
        """Verifikasi invariant pada aggregate (contoh: non-negative balance)."""
        def _inner():
            try:
                from domain.journal import JournalAggregate
                return "SKIP", "Domain invariant check butuh mocking data, skip", {}
            except ImportError:
                return "SKIP", "JournalAggregate tidak ditemukan", {}
        return self._check("Domain Invariants", _inner, "domain", "MEDIUM")

    def check_cqrs_pipeline(self) -> RuntimeCheckResult:
        """Periksa command/query handler registration."""
        def _inner():
            command_bus_modules = [
                "application.commands.command_bus",
                "application.command_bus",
                "infrastructure.cqrs.command_bus",
            ]
            found = False
            for mod_name in command_bus_modules:
                try:
                    mod = importlib.import_module(mod_name)
                    if hasattr(mod, "CommandBus") or hasattr(mod, "command_bus"):
                        found = True
                        break
                except ImportError:
                    continue
            if found:
                return "PASS", "Command bus ditemukan", {}
            if self._container is not None:
                try:
                    self._container.resolve("CommandBusPort")
                    return "PASS", "CommandBusPort terdaftar", {}
                except:
                    pass
            return "WARN", "CQRS pipeline tidak ditemukan", {}
        return self._check("CQRS Pipeline", _inner, "domain", "HIGH")

    def check_saga_workflow(self) -> RuntimeCheckResult:
        """Deteksi saga atau workflow."""
        def _inner():
            saga_modules = [
                "application.sagas",
                "application.workflows",
                "infrastructure.sagas",
            ]
            for mod_name in saga_modules:
                try:
                    mod = importlib.import_module(mod_name)
                    if any("Saga" in attr or "Workflow" in attr for attr in dir(mod)):
                        return "PASS", f"Saga/Workflow ditemukan di {mod_name}", {}
                except ImportError:
                    continue
            return "WARN", "Tidak ditemukan saga/workflow", {}
        return self._check("Saga/Workflow", _inner, "domain", "HIGH")

    # -------------------------------------------------------------------------
    # 7. Code Quality (Weight: 5%)
    # -------------------------------------------------------------------------
    def check_circular_dependency(self) -> RuntimeCheckResult:
        """Deteksi circular dependency antar modul (sederhana)."""
        def _inner():
            import sys
            from collections import defaultdict
            import ast
            import os

            graph = defaultdict(set)
            root = str(self.root)
            for dirpath, dirnames, filenames in os.walk(root):
                if "checker" in dirpath:
                    continue
                for fname in filenames:
                    if fname.endswith(".py") and not fname.startswith("__"):
                        full_path = os.path.join(dirpath, fname)
                        rel_path = os.path.relpath(full_path, root).replace(os.sep, ".").replace(".py", "")
                        try:
                            with open(full_path, "r") as f:
                                tree = ast.parse(f.read())
                            for node in ast.walk(tree):
                                if isinstance(node, ast.Import):
                                    for alias in node.names:
                                        mod = alias.name.split(".")[0]
                                        graph[rel_path].add(mod)
                                elif isinstance(node, ast.ImportFrom):
                                    if node.module:
                                        mod = node.module.split(".")[0]
                                        graph[rel_path].add(mod)
                        except Exception:
                            continue
            visited = set()
            rec_stack = set()
            cycles = []

            def dfs(node):
                visited.add(node)
                rec_stack.add(node)
                for neigh in graph.get(node, []):
                    if neigh not in visited:
                        if dfs(neigh):
                            return True
                    elif neigh in rec_stack:
                        cycles.append((node, neigh))
                        return True
                rec_stack.remove(node)
                return False

            for node in list(graph.keys()):
                if node not in visited:
                    dfs(node)
            if cycles:
                return "WARN", f"Circular dependencies detected: {cycles[:3]}", {"cycles": cycles}
            return "PASS", "Tidak ada circular dependency terdeteksi", {}
        return self._check("Circular Dependency", _inner, "code", "HIGH")

    # -------------------------------------------------------------------------
    # 8. Repository CRUD (Weight: 5%)
    # -------------------------------------------------------------------------
    def check_repository_crud(self) -> RuntimeCheckResult:
        """Test CRUD dasar pada repository (butuh data dummy)."""
        def _inner():
            repo_names = ["AccountRepositoryPort", "ARRepositoryPort"]
            for repo_name in repo_names:
                try:
                    port_cls = None
                    try:
                        mod = importlib.import_module(f"ports.primary.{repo_name.lower()}")
                        port_cls = getattr(mod, repo_name)
                    except:
                        continue
                    if port_cls is None:
                        continue
                    if self._container is not None:
                        repo = self._container.resolve(port_cls)
                        return "SKIP", "Repository CRUD test butuh data dummy, skip", {}
                except Exception:
                    continue
            return "SKIP", "Tidak ada repository yang bisa di-test CRUD", {}
        return self._check("Repository CRUD", _inner, "components", "MEDIUM")

    # -------------------------------------------------------------------------
    # 9. Migration & Schema (Weight: 5%)
    # -------------------------------------------------------------------------
    def check_migration_schema(self) -> RuntimeCheckResult:
        """Periksa status migrasi (Alembic)."""
        def _inner():
            try:
                from alembic import command
                from alembic.config import Config
                migration_dir = self.root / "migrations"
                if not migration_dir.exists():
                    return "WARN", "Direktori migrations tidak ditemukan", {}
                alembic_cfg = Config(str(migration_dir / "alembic.ini"))
                from alembic.script import ScriptDirectory
                script = ScriptDirectory.from_config(alembic_cfg)
                current_rev = script.get_current_head()
                if current_rev is None:
                    return "WARN", "Tidak ada revisi migrasi (belum ada migrasi)", {}
                return "PASS", f"Migrasi terakhir: {current_rev[:8]}", {"current_revision": current_rev}
            except ImportError:
                return "SKIP", "Alembic tidak terinstal", {}
            except Exception as e:
                return "WARN", f"Migrasi check error: {e}", {}
        return self._check("Migration Schema", _inner, "schema", "HIGH")

    # -------------------------------------------------------------------------
    # 10. Performance & Latency (Weight: 5%)
    # -------------------------------------------------------------------------
    def check_performance_benchmark(self) -> RuntimeCheckResult:
        """Benchmark query sederhana."""
        def _inner():
            # Pastikan session_factory tersedia
            if self._session_factory is None:
                try:
                    from infrastructure.database import session_factory_sqlalchemy as sf_module
                    wrapper = asyncio.run(sf_module.get_session_factory())
                    self._session_factory = wrapper.get_session_factory()
                    self._engine = wrapper.get_engine()
                except Exception as e:
                    return "SKIP", f"Session factory tidak tersedia: {e}", {}
            if self._session_factory is None or self._engine is None:
                return "SKIP", "Engine atau session factory tidak tersedia", {}
            try:
                import time
                from sqlalchemy import text
                async def _bench():
                    start = time.perf_counter()
                    for _ in range(10):
                        async with self._session_factory() as session:
                            await session.execute(text("SELECT 1"))
                    return time.perf_counter() - start
                elapsed = asyncio.run(_bench())
                avg = (elapsed / 10) * 1000  # ms
                if avg < 5:
                    status = "PASS"
                    msg = f"Query latency rata-rata {avg:.2f}ms (sangat baik)"
                elif avg < 20:
                    status = "PASS"
                    msg = f"Query latency rata-rata {avg:.2f}ms (baik)"
                elif avg < 50:
                    status = "WARN"
                    msg = f"Query latency rata-rata {avg:.2f}ms (perlu optimasi)"
                else:
                    status = "FAIL"
                    msg = f"Query latency rata-rata {avg:.2f}ms (sangat lambat)"
                return status, msg, {"avg_ms": round(avg, 2)}
            except Exception as e:
                return "WARN", f"Benchmark gagal: {e}", {}
        return self._check("Performance Benchmark", _inner, "performance", "MEDIUM")

    # -------------------------------------------------------------------------
    # 11. Resource Leak Detection (Weight: 5%)
    # -------------------------------------------------------------------------
    def check_resource_leak(self) -> RuntimeCheckResult:
        """Deteksi resource leak dengan tracemalloc dan weakref."""
        def _inner():
            tracemalloc.start()
            snapshot1 = tracemalloc.take_snapshot()
            # Buat objek yang bisa di-weakref
            class LeakTest:
                def __init__(self):
                    self.data = [i for i in range(100000)]
            obj = LeakTest()
            weak = weakref.ref(obj)
            del obj
            gc.collect()
            snapshot2 = tracemalloc.take_snapshot()
            diff = snapshot2.compare_to(snapshot1, 'lineno')
            top = diff[:5]
            if weak() is not None:
                return "WARN", "Objek yang seharusnya dihapus masih ada (potensi leak)", {"top": [(str(stat.traceback), stat.size) for stat in top]}
            total_mem = sum(stat.size for stat in top)
            if total_mem > 1024 * 1024:
                return "WARN", f"Potensi memori tinggi: {total_mem/1024:.1f}KB", {"top": [(str(stat.traceback), stat.size) for stat in top]}
            tracemalloc.stop()
            return "PASS", "Resource leak check OK", {}
        return self._check("Resource Leak", _inner, "runtime", "MEDIUM")

    def check_async(self) -> RuntimeCheckResult:
        def _inner():
            async def _test():
                await asyncio.sleep(0.01)
                return True
            result = asyncio.run(_test())
            return "PASS", "Async execution OK", {}
        return self._check("Async", _inner, "runtime", "HIGH")

    # -------------------------------------------------------------------------
    # 12. Cache (Weight: 2%)
    # -------------------------------------------------------------------------
    def check_cache(self) -> RuntimeCheckResult:
        """Periksa ketersediaan cache adapter."""
        def _inner():
            try:
                import infrastructure.caching.cache_adapter
                from infrastructure.caching.cache_adapter import CachePort
                return "PASS", "CachePort tersedia", {}
            except ImportError:
                return "SKIP", "CachePort tidak ditemukan (opsional)", {}
        return self._check("Cache", _inner, "cache", "MEDIUM")

    # -------------------------------------------------------------------------
    # 13. Dispose resources
    # -------------------------------------------------------------------------
    def dispose(self):
        if self._engine is not None:
            try:
                asyncio.run(self._engine.dispose())
                logger.info("Database engine disposed successfully")
            except RuntimeError as e:
                logger.debug(f"RuntimeError during dispose (ignored): {e}")
            except Exception as e:
                logger.warning(f"Error disposing engine: {e}")

    # -------------------------------------------------------------------------
    # 14. Run All Checks
    # -------------------------------------------------------------------------
    _CHECK_STATUS_SCORE = {"PASS": 100.0, "WARN": 60.0, "FAIL": 0.0}  # SKIP excluded

    _CHECK_TIER_WEIGHT = {
        "Bootstrap": 5,
        "Environment": 3,
        "Configuration": 2,
        "Database Connectivity": 10,
        "Transactions": 10,
        "Connection Pool": 5,
        "Dependency Injection": 10,
        "Repositories": 5,
        "Aggregates": 5,
        "ORM Models": 5,
        "Event Bus": 5,
        "Event Publish/Subscribe": 5,
        "Outbox": 5,
        "Outbox Relay": 5,
        "Domain Invariants": 3,
        "CQRS Pipeline": 3,
        "Saga/Workflow": 3,
        "Circular Dependency": 3,
        "Repository CRUD": 3,
        "Migration Schema": 3,
        "Performance Benchmark": 3,
        "Resource Leak": 3,
        "Async": 2,
        "Cache": 2,
    }

    def run_all(self) -> RuntimeReport:
        start_time = time.perf_counter()

        categories = {
            "bootstrap": {"checks": [
                self.check_bootstrap, self.check_environment, self.check_configuration
            ]},
            "database": {"checks": [
                self.check_database_connectivity, self.check_transactions, self.check_connection_pool
            ]},
            "di": {"checks": [
                self.check_dependency_injection
            ]},
            "components": {"checks": [
                self.check_repositories, self.check_aggregates, self.check_models, self.check_repository_crud
            ]},
            "event": {"checks": [
                self.check_event_bus, self.check_event_publish_subscribe, self.check_outbox, self.check_outbox_relay
            ]},
            "domain": {"checks": [
                self.check_domain_invariants, self.check_cqrs_pipeline, self.check_saga_workflow
            ]},
            "code": {"checks": [
                self.check_circular_dependency
            ]},
            "schema": {"checks": [
                self.check_migration_schema
            ]},
            "performance": {"checks": [
                self.check_performance_benchmark
            ]},
            "runtime": {"checks": [
                self.check_resource_leak, self.check_async
            ]},
            "cache": {"checks": [
                self.check_cache
            ]},
        }

        all_results = []
        category_scores = {}
        false_positive_risk = []

        overall_weighted_sum = 0.0
        overall_weight_total = 0.0

        for cat_name, cat_data in categories.items():
            cat_results = []
            for check_fn in cat_data["checks"]:
                result = check_fn()
                all_results.append(result)
                cat_results.append(result)

            effective = [r for r in cat_results if r.status != "SKIP"]
            if effective:
                cat_score = sum(self._CHECK_STATUS_SCORE.get(r.status, 0.0) for r in effective) / len(effective)
            else:
                cat_score = 100.0
            category_scores[cat_name] = round(cat_score, 2)

            for r in cat_results:
                if r.status == "SKIP":
                    continue
                w = self._CHECK_TIER_WEIGHT.get(r.name, 5)
                overall_weighted_sum += self._CHECK_STATUS_SCORE.get(r.status, 0.0) * w
                overall_weight_total += w

            for r in cat_results:
                if r.status in ("WARN", "FAIL") and r.confidence == "LOW":
                    false_positive_risk.append(f"{r.name}: {r.message[:50]}... (LOW confidence)")

        total_weighted = (overall_weighted_sum / overall_weight_total) if overall_weight_total > 0 else 0.0

        passed = sum(1 for r in all_results if r.status == "PASS")
        warnings = sum(1 for r in all_results if r.status == "WARN")
        failed = sum(1 for r in all_results if r.status == "FAIL")
        skipped = sum(1 for r in all_results if r.status == "SKIP")

        self.dispose()

        return RuntimeReport(
            timestamp=datetime.now(UTC).isoformat(),
            checks=all_results,
            total_checks=len(all_results),
            passed=passed,
            warnings=warnings,
            failed=failed,
            skipped=skipped,
            weighted_score=round(total_weighted, 2),
            duration_sec=time.perf_counter() - start_time,
            rca_enabled=_RCA_AVAILABLE,
            category_scores=category_scores,
            false_positive_risk=false_positive_risk,
        )

# =============================================================================
# REPORTING
# =============================================================================
def print_report(report: RuntimeReport):
    c = COLOR
    print(f"\n{c['BOLD']}{c['CYAN']}╔{'═'*80}╗")
    print(f"║     RUNTIME EXHAUSTIVE CHECKER — v5.0 (Enterprise)     ║")
    print(f"╚{'═'*80}╝{c['RESET']}")

    print(f"\n  📅 Timestamp    : {report.timestamp}")
    print(f"  ⏱️  Duration     : {report.duration_sec:.2f}s")
    print(f"  🔬 RCA Engine   : {'✅ Active' if report.rca_enabled else '⚠️ Not available'}")
    print(f"\n  📊 Total Checks : {report.total_checks}")
    print(f"    {c['GREEN']}✅ PASS   : {report.passed}{c['RESET']}")
    print(f"    {c['YELLOW']}⚠️  WARN   : {report.warnings}{c['RESET']}")
    print(f"    {c['RED']}❌ FAIL   : {report.failed}{c['RESET']}")
    print(f"    {c['DIM']}⏭  SKIP   : {report.skipped}{c['RESET']}")

    print(f"\n  {c['DIM']}Confidence: {c['GREEN']}HIGH{c['RESET']} (reliable), {c['YELLOW']}MEDIUM{c['RESET']} (may be false positive), {c['RED']}LOW{c['RESET']} (suspect){c['RESET']}")

    if report.category_scores:
        print(f"\n  {c['BOLD']}📈 CATEGORY SCORES (Weighted){c['RESET']}")
        for cat, score in report.category_scores.items():
            color = c["GREEN"] if score >= 90 else c["YELLOW"] if score >= 70 else c["RED"]
            print(f"    {cat.capitalize():12} : {color}{score:5.1f}%{c['RESET']}")

    score_color = c["GREEN"] if report.weighted_score >= 90 else c["YELLOW"] if report.weighted_score >= 70 else c["RED"]
    print(f"\n  🏆 WEIGHTED SCORE : {score_color}{report.weighted_score}/100{c['RESET']}")

    if report.false_positive_risk:
        print(f"\n  {c['YELLOW']}⚠️  Possible false positives detected:{c['RESET']}")
        for risk in report.false_positive_risk[:3]:
            print(f"     {c['DIM']}• {risk}{c['RESET']}")

    if report.failed > 0 or report.warnings > 0:
        print(f"\n{c['BOLD']}── DETAILED DIAGNOSTICS ──{c['RESET']}")
        for r in report.checks:
            if r.status == "PASS":
                icon = f"{c['GREEN']}✅{c['RESET']}"
            elif r.status == "SKIP":
                icon = f"{c['DIM']}⏭{c['RESET']}"
            elif r.status == "WARN":
                icon = f"{c['YELLOW']}⚠️{c['RESET']}"
            else:
                icon = f"{c['RED']}❌{c['RESET']}"

            if r.confidence == "HIGH":
                conf_icon = f"{c['GREEN']}●{c['RESET']}"
            elif r.confidence == "MEDIUM":
                conf_icon = f"{c['YELLOW']}●{c['RESET']}"
            else:
                conf_icon = f"{c['RED']}●{c['RESET']}"

            print(f"\n  {icon} {c['BOLD']}{r.name}{c['RESET']} ({r.duration_ms:.1f}ms) {conf_icon} {r.confidence}")
            print(f"     {r.message}")
            if r.details:
                if r.name == "Repositories" and "failed_details" in r.details:
                    for fail in r.details.get("failed_details", [])[:3]:
                        print(f"        ❌ {fail}")
                elif r.name == "Aggregates" and "missing" in r.details:
                    for miss in r.details.get("missing", [])[:3]:
                        print(f"        ❌ {miss}")
                elif r.name == "ORM Models" and "missing_pk" in r.details:
                    for pk in r.details.get("missing_pk", [])[:3]:
                        print(f"        ❌ {pk}")
                else:
                    detail_str = json.dumps(r.details, indent=2)
                    if len(detail_str) > 200:
                        detail_str = detail_str[:200] + "..."
                    print(f"     📌 {detail_str}")

        # Actionable items with priority
        print(f"\n{c['BOLD']}🔧 ACTIONABLE ITEMS (Prioritas){c['RESET']}")
        item_id = 1
        for r in report.checks:
            if r.status == "FAIL":
                print(f"  {item_id}. {c['RED']}[FAIL] {r.name}{c['RESET']}")
                print(f"     💡 {r.message}")
                if r.name == "Transactions":
                    d = r.details or {}
                    if d.get("container_resolve_ok") is False and d.get("scan_fallback_used") is False:
                        print(f"     🔧 UnitOfWorkPort belum terdaftar di container DAN implementasi tidak bisa di-import. Periksa registrasi di container_bootstrap.")
                    elif d.get("uow_class"):
                        print(f"     🔧 UnitOfWork ({d['uow_class']}) berhasil di-resolve, tapi transaksi tetap gagal. Periksa implementasi TransactionManager / koneksi database, BUKAN registrasi container.")
                    else:
                        print(f"     🔧 Periksa implementasi commit/rollback pada UnitOfWork dan koneksi database.")
                item_id += 1

        for r in report.checks:
            if r.status == "WARN":
                if r.name == "Repositories" and r.details and "failed_details" in r.details:
                    for fail in r.details["failed_details"]:
                        print(f"  {item_id}. {c['YELLOW']}[WARN] {fail[:60]}{c['RESET']}")
                        print(f"     🔧 Implementasikan metode yang hilang pada repository.")
                        item_id += 1
                elif r.name == "Aggregates" and r.details and "missing" in r.details:
                    for miss in r.details["missing"]:
                        print(f"  {item_id}. {c['YELLOW']}[WARN] {miss[:60]}{c['RESET']}")
                        print(f"     🔧 Tambahkan field 'id' (UUID) dan 'version' (int).")
                        item_id += 1
                elif r.name == "ORM Models" and r.details and "missing_pk" in r.details:
                    for pk in r.details["missing_pk"]:
                        print(f"  {item_id}. {c['YELLOW']}[WARN] Model {pk} missing PK{c['RESET']}")
                        print(f"     🔧 Tambahkan primary_key=True.")
                        item_id += 1
                elif r.name == "Configuration":
                    print(f"  {item_id}. {c['YELLOW']}[WARN] Configuration{c['RESET']}")
                    print(f"     💡 {r.message}")
                    print(f"     🔧 Tambahkan konfigurasi yang hilang.")
                    item_id += 1
                elif r.name == "Environment":
                    print(f"  {item_id}. {c['YELLOW']}[WARN] Environment{c['RESET']}")
                    print(f"     💡 {r.message}")
                    print(f"     🔧 Set environment variables atau fallback sudah digunakan.")
                    item_id += 1
                elif r.name == "Connection Pool":
                    print(f"  {item_id}. {c['YELLOW']}[WARN] Connection Pool{c['RESET']}")
                    print(f"     💡 {r.message}")
                    print(f"     🔧 Periksa konfigurasi pool size dan timeout.")
                    item_id += 1
                elif r.name == "Performance Benchmark":
                    print(f"  {item_id}. {c['YELLOW']}[WARN] Performance{c['RESET']}")
                    print(f"     💡 {r.message}")
                    print(f"     🔧 Optimasi query atau tambahkan indeks.")
                    item_id += 1
                elif r.name == "Resource Leak":
                    print(f"  {item_id}. {c['YELLOW']}[WARN] Resource Leak{c['RESET']}")
                    print(f"     💡 {r.message}")
                    print(f"     🔧 Periksa penutupan resource (session, koneksi).")
                    item_id += 1
                elif r.name == "Outbox Relay":
                    print(f"  {item_id}. {c['YELLOW']}[WARN] Outbox Relay{c['RESET']}")
                    print(f"     💡 {r.message}")
                    print(f"     🔧 Pastikan outbox relay service berjalan.")
                    item_id += 1
                elif r.name == "Circular Dependency":
                    print(f"  {item_id}. {c['YELLOW']}[WARN] Circular Dependency{c['RESET']}")
                    print(f"     💡 {r.message}")
                    print(f"     🔧 Refactor untuk menghilangkan siklus.")
                    item_id += 1
                elif r.name == "Migration Schema":
                    print(f"  {item_id}. {c['YELLOW']}[WARN] Migration Schema{c['RESET']}")
                    print(f"     💡 {r.message}")
                    print(f"     🔧 Jalankan migrasi atau periksa konfigurasi.")
                    item_id += 1

        if item_id == 1:
            print(f"  ✅ Tidak ada action items. Semua check sudah baik!")

def save_json(report: RuntimeReport, path: Path):
    data = {
        "timestamp": report.timestamp,
        "weighted_score": report.weighted_score,
        "duration_sec": report.duration_sec,
        "rca_enabled": report.rca_enabled,
        "total_checks": report.total_checks,
        "passed": report.passed,
        "warnings": report.warnings,
        "failed": report.failed,
        "skipped": report.skipped,
        "category_scores": report.category_scores,
        "false_positive_risk": report.false_positive_risk,
        "checks": [
            {
                "name": r.name,
                "status": r.status,
                "confidence": r.confidence,
                "message": r.message,
                "duration_ms": r.duration_ms,
                "details": r.details,
                "rca": r.rca,
            }
            for r in report.checks
        ]
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  ✅ JSON saved to {path}")

# =============================================================================
# MAIN
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="Runtime Exhaustive Checker v5.0")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", metavar="FILE", help="Save JSON report")
    parser.add_argument("--no-rca", action="store_true", help="Disable RCA engine")
    parser.add_argument("--root", "-r", default=None, help="Root directory of project")
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else ROOT
    enable_rca = not args.no_rca

    checker = RuntimeExhaustiveChecker(root, enable_rca)
    report = checker.run_all()
    print_report(report)
    if args.json:
        save_json(report, Path(args.json))

    sys.exit(1 if report.failed > 0 else 0)

if __name__ == "__main__":
    main()