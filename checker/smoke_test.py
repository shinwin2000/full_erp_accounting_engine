#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SMOKE TEST SUITE v7.3.0 - ENTERPRISE FORENSIC EDITION
======================================================
Total 17 tests:
1-7: Core (environment, DI, FastAPI, DB, security, business logic, resource)
8-13: Additional (API health, config, domain models, repositories, CORS, auth)
14: Master Data Models (ERP specific)
15: OpenAPI Documentation
16: Message Broker (Redis/RabbitMQ)
17: Scheduler (Celery/APScheduler)

Cakupan lebih luas untuk sistem ERP.
"""

import os
import sys
import time
import json
import logging
import threading
import asyncio
import importlib
import inspect
import re
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

# ----------------------------------------------------------------------
# Konfigurasi logging
# ----------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("SmokeTest_v7.3")

# ----------------------------------------------------------------------
# Coba impor RCA Engine (opsional)
# ----------------------------------------------------------------------
RCA_AVAILABLE = False
try:
    sys.path.insert(0, str(Path(__file__).parent))
    from core.rca import get_engine, analyze_exception
    RCA_AVAILABLE = True
except ImportError as e:
    logger.info(f"RCA Engine tidak tersedia: {e}")
except Exception as e:
    logger.warning(f"Gagal menginisialisasi RCA Engine: {e}")

# ----------------------------------------------------------------------
# Enum untuk level keparahan
# ----------------------------------------------------------------------
class TestSeverity(Enum):
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    SUCCESS = "SUCCESS"


# ----------------------------------------------------------------------
# Data class untuk hasil tes
# ----------------------------------------------------------------------
@dataclass
class SmokeTestResult:
    name: str
    category: str
    passed: bool
    duration: float = 0.0
    severity: TestSeverity = TestSeverity.INFO
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    exception: Optional[Exception] = None
    suggested_fix: Optional[str] = None
    evidence: List[str] = field(default_factory=list)
    rca_analysis: Optional[Dict[str, Any]] = None
    remediation_steps: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "passed": self.passed,
            "duration_seconds": round(self.duration, 3),
            "severity": self.severity.value,
            "details": self.details,
            "error": self.error,
            "suggested_fix": self.suggested_fix,
            "evidence": self.evidence[:5] if self.evidence else [],
            "rca_analysis": self.rca_analysis,
            "remediation_steps": self.remediation_steps[:3],
        }


# ----------------------------------------------------------------------
# Runner utama
# ----------------------------------------------------------------------
class ForensicSmokeTestRunner:
    def __init__(
        self,
        verbose: bool = False,
        test_env: bool = False,
        enable_rca: bool = True,
    ):
        self.results: List[SmokeTestResult] = []
        self.verbose = verbose
        self.test_env = test_env
        self.enable_rca = enable_rca and RCA_AVAILABLE
        self.project_root = Path.cwd()
        self.start_memory_mb = self._get_memory_mb()
        self.start_thread_count = threading.active_count()
        self.app_instance = None
        self.di_container = None
        self.rca_engine = None
        self._cached_modules = {}

        if self.enable_rca:
            try:
                self.rca_engine = get_engine()
                logger.info("✅ RCA Engine terintegrasi")
            except Exception as e:
                logger.warning(f"RCA Engine gagal diinisialisasi: {e}")
                self.enable_rca = False

    # ------------------------------------------------------------------
    # Utilitas
    # ------------------------------------------------------------------
    def _get_memory_mb(self) -> float:
        try:
            import psutil
            return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
        except ImportError:
            try:
                import resource
                return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            except:
                return 0.0

    def _analyze_with_rca(self, exc: Exception, test_name: str) -> Optional[Dict[str, Any]]:
        if not self.enable_rca or not self.rca_engine:
            return None
        try:
            rca = analyze_exception(exc)
            if rca:
                return {
                    "root_cause": rca.root_cause,
                    "confidence": rca.confidence,
                    "suggested_fix": rca.suggested_fix,
                }
        except Exception:
            pass
        return None

    def _add_result(
        self,
        name: str,
        category: str,
        passed: bool,
        details: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        exc: Optional[Exception] = None,
        duration: float = 0.0,
        severity: TestSeverity = TestSeverity.INFO,
        suggested_fix: Optional[str] = None,
        evidence: Optional[List[str]] = None,
        remediation_steps: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        err_msg = error or (str(exc) if exc else None)
        result = SmokeTestResult(
            name=name,
            category=category,
            passed=passed,
            duration=duration,
            severity=severity,
            details=details or {},
            error=err_msg,
            exception=exc,
            suggested_fix=suggested_fix,
            evidence=evidence or [],
            remediation_steps=remediation_steps or [],
            context=context or {},
        )
        if exc and self.enable_rca:
            result.rca_analysis = self._analyze_with_rca(exc, name)
        self.results.append(result)

        icon = "✅" if passed else ("❌" if severity in (TestSeverity.CRITICAL, TestSeverity.ERROR) else "⚠️")
        log_level = (
            logging.CRITICAL
            if (not passed and severity == TestSeverity.CRITICAL)
            else logging.ERROR
            if not passed
            else logging.WARNING
            if severity == TestSeverity.WARNING
            else logging.INFO
        )
        logger.log(log_level, f"{icon} [{category}] {name} ({duration:.2f}s)")
        if not passed and err_msg:
            logger.log(log_level, f"   └─ Error: {err_msg}")
        if not passed and suggested_fix:
            logger.log(log_level, f"   └─ Fix: {suggested_fix}")
        if self.verbose and exc:
            logger.exception("   └─ Traceback:")

    def _safe_import(self, module_name: str) -> Optional[Any]:
        if module_name in self._cached_modules:
            return self._cached_modules[module_name]
        try:
            mod = importlib.import_module(module_name)
            self._cached_modules[module_name] = mod
            return mod
        except ImportError:
            return None

    def _has_attr(self, module_name: str, attr_name: str) -> bool:
        mod = self._safe_import(module_name)
        return hasattr(mod, attr_name) if mod else False

    # ------------------------------------------------------------------
    # Tes 1 : Environment Safety
    # ------------------------------------------------------------------
    def test_environment_safety(self) -> None:
        start = time.perf_counter()
        name = "Environment Safety"
        category = "ENVIRONMENT"

        try:
            env = os.getenv("ENVIRONMENT", os.getenv("FLASK_ENV", os.getenv("DJANGO_SETTINGS_MODULE", "")))
            debug = os.getenv("DEBUG", "False").lower() in ["true", "1", "yes"]
            is_production = False
            indicators = []

            env_lower = str(env).lower()
            if env_lower in ["prod", "production", "live", "prd"]:
                is_production = True
                indicators.append(f"ENVIRONMENT={env}")
            if os.getenv("PRODUCTION", "False").lower() in ["true", "1"]:
                is_production = True
                indicators.append("PRODUCTION=true")
            if sys.argv and any(s in sys.argv[0] for s in ["gunicorn", "uwsgi"]):
                is_production = True
                indicators.append("Running under WSGI server")

            details = {
                "environment": env or "not_set",
                "debug_enabled": debug,
                "is_production": is_production,
                "indicators": indicators,
                "test_env_flag": self.test_env,
                "python_version": sys.version.split()[0],
                "platform": sys.platform,
            }

            if is_production and not self.test_env:
                self._add_result(
                    name, category, False,
                    details=details,
                    error=f"Production environment terdeteksi: {', '.join(indicators)}",
                    severity=TestSeverity.CRITICAL,
                    suggested_fix="Gunakan --test-env atau set ENVIRONMENT=development",
                    duration=time.perf_counter() - start,
                )
                return

            if is_production and self.test_env:
                self._add_result(
                    name, category, True,
                    details=details,
                    severity=TestSeverity.WARNING,
                    context={"warning": "Production environment tetapi --test-env mengesampingkan safety check"},
                    suggested_fix="Hapus --test-env jika benar-benar production",
                    duration=time.perf_counter() - start,
                )
                return

            if debug and not is_production:
                self._add_result(
                    name, category, True,
                    details=details,
                    severity=TestSeverity.WARNING,
                    context={"warning": "Debug mode aktif di non-production"},
                    suggested_fix="Nonaktifkan DEBUG di production",
                    duration=time.perf_counter() - start,
                )
            else:
                self._add_result(
                    name, category, True,
                    details=details,
                    duration=time.perf_counter() - start,
                )

        except Exception as e:
            self._add_result(
                name, category, False,
                error=str(e), exc=e,
                severity=TestSeverity.CRITICAL,
                duration=time.perf_counter() - start,
            )

    # ------------------------------------------------------------------
    # Tes 2 : DI Container Integrity
    # ------------------------------------------------------------------
    def test_di_container_integrity(self) -> None:
        start = time.perf_counter()
        name = "DI Container Integrity"
        category = "ARCHITECTURE"

        try:
            container = None
            container_module = None
            container_type = None

            search_patterns = [
                ("core.di_container", ["container", "Container", "di_container", "DIContainer"]),
                ("infrastructure.di_container", ["container", "Container"]),
                ("di_container", ["container", "Container"]),
                ("container", ["container", "Container", "app_container"]),
                ("core.container", ["container", "Container"]),
                ("application.container", ["container", "Container"]),
                ("bootstrap.container", ["container", "Container"]),
                ("config.container", ["container", "Container"]),
            ]

            for mod_name, attrs in search_patterns:
                try:
                    mod = importlib.import_module(mod_name)
                    for attr in attrs:
                        if hasattr(mod, attr):
                            obj = getattr(mod, attr)
                            if inspect.isclass(obj) or hasattr(obj, "resolve") or hasattr(obj, "get"):
                                container = obj
                                container_module = mod_name
                                container_type = "class" if inspect.isclass(obj) else "instance"
                                break
                    if container:
                        break
                except ImportError:
                    continue

            if not container:
                logger.info("🔍 Melakukan pencarian container secara luas...")
                for root, dirs, files in os.walk(self.project_root):
                    if any(excl in root for excl in ["venv", "__pycache__", ".git", "checker"]):
                        continue
                    for file in files:
                        if file.endswith(".py") and "container" in file.lower():
                            try:
                                rel_path = Path(root) / file
                                mod_name = str(rel_path.relative_to(self.project_root)).replace("/", ".").replace("\\", ".").replace(".py", "")
                                mod = importlib.import_module(mod_name)
                                for attr_name in dir(mod):
                                    obj = getattr(mod, attr_name)
                                    if inspect.isclass(obj) and ("container" in attr_name.lower() or "Container" in attr_name):
                                        container = obj
                                        container_module = mod_name
                                        container_type = "class (discovered)"
                                        break
                                    if hasattr(obj, "resolve") or hasattr(obj, "get"):
                                        container = obj
                                        container_module = mod_name
                                        container_type = "instance (discovered)"
                                        break
                                if container:
                                    break
                            except:
                                continue
                    if container:
                        break

            if not container:
                self._add_result(
                    name, category, False,
                    error="Tidak ditemukan DI Container di project",
                    severity=TestSeverity.ERROR,
                    suggested_fix="Buat core.di_container.py dengan class Container",
                    evidence=["Dicari di: core.di_container, infrastructure.di_container, container, dll."],
                    duration=time.perf_counter() - start,
                )
                return

            if inspect.isclass(container):
                try:
                    container_instance = container()
                    self.di_container = container_instance
                    details = {
                        "container_type": container_type,
                        "container_module": container_module,
                        "container_class": container.__name__,
                        "status": "instantiated",
                    }
                except Exception as e:
                    self._add_result(
                        name, category, False,
                        error=f"Gagal menginstansiasi DI Container: {e}",
                        exc=e,
                        severity=TestSeverity.ERROR,
                        suggested_fix="Periksa dependensi konstruktor",
                        duration=time.perf_counter() - start,
                    )
                    return
            else:
                self.di_container = container
                details = {
                    "container_type": container_type,
                    "container_module": container_module,
                    "container_class": container.__class__.__name__ if hasattr(container, "__class__") else str(type(container)),
                    "status": "existing_instance",
                }

            health_ok = True
            health_issues = []
            if hasattr(self.di_container, "resolve"):
                try:
                    self.di_container.resolve("UnitOfWork")
                except Exception as e:
                    health_issues.append(f"UnitOfWork tidak terdaftar: {e}")
                    health_ok = False
            if hasattr(self.di_container, "get"):
                try:
                    self.di_container.get("UnitOfWork")
                except Exception as e:
                    if "UnitOfWork" not in str(e):
                        health_issues.append(f"get gagal: {e}")

            details["health_issues"] = health_issues
            details["health_ok"] = health_ok

            if not health_ok:
                self._add_result(
                    name, category, True,
                    details=details,
                    severity=TestSeverity.WARNING,
                    error="UnitOfWork tidak terdaftar di DI Container",
                    suggested_fix="Daftarkan UnitOfWork jika diperlukan, atau abaikan jika menggunakan persistence lain",
                    duration=time.perf_counter() - start,
                )
            else:
                self._add_result(
                    name, category, True,
                    details=details,
                    duration=time.perf_counter() - start,
                )

        except Exception as e:
            self._add_result(
                name, category, False,
                error=str(e), exc=e,
                severity=TestSeverity.ERROR,
                duration=time.perf_counter() - start,
            )

    # ------------------------------------------------------------------
    # Tes 3 : FastAPI App Structure
    # ------------------------------------------------------------------
    def test_fastapi_app_structure(self) -> None:
        start = time.perf_counter()
        name = "FastAPI App Structure"
        category = "WEB"

        try:
            app = None
            app_source = None

            search_modules = [
                ("erp_engine", ["app", "application", "create_app"]),
                ("application.main", ["app", "application", "create_app"]),
                ("main", ["app", "application", "create_app"]),
                ("app", ["app", "application", "create_app"]),
                ("server", ["app", "application", "create_app"]),
                ("api.main", ["app", "application", "create_app"]),
                ("bootstrap.app", ["app", "application", "create_app"]),
                ("erp.asgi", ["application", "app"]),
            ]

            for mod_name, attrs in search_modules:
                try:
                    mod = importlib.import_module(mod_name)
                    for attr in attrs:
                        if hasattr(mod, attr):
                            obj = getattr(mod, attr)
                            if hasattr(obj, "routes") and hasattr(obj, "router"):
                                app = obj
                                app_source = f"{mod_name}.{attr} (instance)"
                                break
                            if callable(obj) and "create" in attr.lower():
                                try:
                                    app = obj()
                                    app_source = f"{mod_name}.{attr} (factory)"
                                    break
                                except Exception as e:
                                    logger.warning(f"Factory {attr} gagal: {e}")
                    if app:
                        break
                except ImportError:
                    continue

            if not app:
                self._add_result(
                    name, category, False,
                    error="Tidak ditemukan FastAPI app di project",
                    severity=TestSeverity.ERROR,
                    suggested_fix="Buat erp_engine/app.py dengan instance FastAPI() atau di main.py",
                    evidence=["Dicari di: erp_engine, main, app, server, erp.asgi"],
                    duration=time.perf_counter() - start,
                )
                return

            self.app_instance = app

            routes = app.routes if hasattr(app, "routes") else []
            route_paths = [r.path for r in routes if hasattr(r, "path")]
            duplicates = [p for p in route_paths if route_paths.count(p) > 1]
            middleware_types = []
            if hasattr(app, "user_middleware"):
                middleware_types = [str(m.cls) for m in app.user_middleware]

            details = {
                "app_source": app_source,
                "route_count": len(routes),
                "unique_routes": len(set(route_paths)),
                "duplicate_routes": len(set(duplicates)) if duplicates else 0,
                "middleware_count": len(middleware_types),
                "has_cors_middleware": any("cors" in m.lower() for m in middleware_types),
                "title": getattr(app, "title", "unknown"),
                "version": getattr(app, "version", "unknown"),
            }

            if len(routes) == 0:
                self._add_result(
                    name, category, False,
                    details=details,
                    error="Tidak ada route yang terdaftar",
                    severity=TestSeverity.ERROR,
                    suggested_fix="Daftarkan route menggunakan @app.get() atau include_router()",
                    duration=time.perf_counter() - start,
                )
            elif duplicates:
                self._add_result(
                    name, category, True,
                    details=details,
                    severity=TestSeverity.WARNING,
                    error=f"Ditemukan {len(set(duplicates))} duplikasi path route (dari include_router)",
                    suggested_fix="Tinjau registrasi route untuk menghindari tumpang tindih",
                    duration=time.perf_counter() - start,
                )
            else:
                self._add_result(
                    name, category, True,
                    details=details,
                    duration=time.perf_counter() - start,
                )

        except Exception as e:
            self._add_result(
                name, category, False,
                error=str(e), exc=e,
                severity=TestSeverity.ERROR,
                duration=time.perf_counter() - start,
            )

    # ------------------------------------------------------------------
    # Tes 4 : Database Connectivity & Metadata
    # ------------------------------------------------------------------
    def test_database_connectivity(self) -> None:
        start = time.perf_counter()
        name = "Database Connectivity & Metadata"
        category = "INFRASTRUCTURE"

        try:
            db_url = os.getenv("DATABASE_URL")
            if not db_url:
                self._add_result(
                    name, category, False,
                    error="DATABASE_URL tidak diset di environment",
                    severity=TestSeverity.ERROR,
                    suggested_fix="Set DATABASE_URL di .env",
                    duration=time.perf_counter() - start,
                )
                return

            get_session_func = None
            is_async = False
            search_modules = [
                "infrastructure.database.session_factory_sqlalchemy",
                "infrastructure.database",
                "database.session_factory",
                "db.session_factory",
                "infrastructure.db",
                "core.db",
            ]

            for mod_name in search_modules:
                try:
                    mod = importlib.import_module(mod_name)
                    for func_name in ["get_session_local", "SessionLocal", "get_session", "session_factory", "get_db"]:
                        if hasattr(mod, func_name):
                            obj = getattr(mod, func_name)
                            if callable(obj):
                                get_session_func = obj
                                if inspect.iscoroutinefunction(obj) or inspect.isasyncgenfunction(obj):
                                    is_async = True
                                break
                    if get_session_func:
                        break
                except ImportError:
                    continue

            if not get_session_func:
                self._add_result(
                    name, category, False,
                    error="Tidak ditemukan session factory di project",
                    severity=TestSeverity.ERROR,
                    suggested_fix="Buat get_session_local() di infrastructure/database/session_factory_sqlalchemy.py",
                    duration=time.perf_counter() - start,
                )
                return

            session = None
            success = False
            error_msg = None

            try:
                if is_async:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        session_obj = get_session_func()
                        if inspect.isasyncgen(session_obj):
                            try:
                                session = loop.run_until_complete(session_obj.__anext__())
                            except StopAsyncIteration:
                                error_msg = "Async session generator tidak menghasilkan session"
                        else:
                            session = session_obj
                        if session is not None:
                            from sqlalchemy import text
                            loop.run_until_complete(session.execute(text("SELECT 1")))
                            success = True
                    except Exception as e:
                        error_msg = str(e)
                    finally:
                        if session and hasattr(session, "aclose"):
                            try:
                                loop.run_until_complete(session.aclose())
                            except:
                                pass
                        try:
                            loop.close()
                        except:
                            pass
                else:
                    session = get_session_func()
                    if session is not None:
                        from sqlalchemy import text
                        session.execute(text("SELECT 1"))
                        success = True
                    else:
                        error_msg = "Session factory mengembalikan None"
            except Exception as e:
                error_msg = str(e)
            finally:
                if session and hasattr(session, "close") and not is_async:
                    try:
                        session.close()
                    except:
                        pass

            if success:
                details = {
                    "connection": "success",
                    "db_type": db_url.split(":")[0] if ":" in db_url else "unknown",
                    "async": is_async,
                    "session_factory": get_session_func.__name__,
                }
                self._add_result(
                    name, category, True,
                    details=details,
                    duration=time.perf_counter() - start,
                )
            else:
                self._add_result(
                    name, category, False,
                    error=f"Koneksi database gagal: {error_msg or 'Unknown error'}",
                    exc=Exception(error_msg) if error_msg else None,
                    severity=TestSeverity.CRITICAL,
                    suggested_fix="Periksa DATABASE_URL dan pastikan server database berjalan",
                    duration=time.perf_counter() - start,
                )

        except Exception as e:
            self._add_result(
                name, category, False,
                error=str(e), exc=e,
                severity=TestSeverity.CRITICAL,
                duration=time.perf_counter() - start,
            )

    # ------------------------------------------------------------------
    # Tes 5 : Security Configuration Audit
    # ------------------------------------------------------------------
    def test_security_configuration(self) -> None:
        start = time.perf_counter()
        name = "Security Configuration Audit"
        category = "SECURITY"

        try:
            issues = []
            warnings = []

            if os.getenv("DEBUG", "").lower() in ["true", "1"]:
                issues.append("DEBUG mode aktif")

            secret_key = os.getenv("SECRET_KEY", "")
            if secret_key and len(secret_key) < 32:
                warnings.append(f"SECRET_KEY terlalu pendek ({len(secret_key)} karakter)")
            elif not secret_key:
                warnings.append("SECRET_KEY tidak diset")

            weak_secrets = []
            for key, value in os.environ.items():
                if any(p in key.lower() for p in ["password", "secret", "key", "token", "credential", "api_key"]):
                    if value and len(value) < 16:
                        weak_secrets.append(f"{key} (length {len(value)})")
                    elif value.lower() in ["changeme", "password", "123456", "secret"]:
                        weak_secrets.append(f"{key} (default value)")
            if weak_secrets:
                warnings.append(f"Weak secrets: {', '.join(weak_secrets[:3])}")

            if self.app_instance and hasattr(self.app_instance, "user_middleware"):
                has_security_headers = any(
                    "security" in str(m.cls).lower() or "headers" in str(m.cls).lower()
                    for m in self.app_instance.user_middleware
                )
                if not has_security_headers:
                    warnings.append("Tidak ada middleware security headers")

            details = {
                "issues_count": len(issues),
                "warnings_count": len(warnings),
                "issues": issues,
                "warnings": warnings,
                "secrets_checked": len([k for k in os.environ.keys() if any(p in k.lower() for p in ["password", "secret", "key", "token"])]),
            }

            if issues:
                self._add_result(
                    name, category, False,
                    details=details,
                    error=", ".join(issues),
                    severity=TestSeverity.ERROR,
                    suggested_fix="Nonaktifkan DEBUG dan perbaiki konfigurasi keamanan",
                    duration=time.perf_counter() - start,
                )
            elif warnings:
                self._add_result(
                    name, category, True,
                    details=details,
                    severity=TestSeverity.WARNING,
                    context={"warnings": warnings},
                    suggested_fix="Periksa secret key dan tambahkan middleware keamanan",
                    duration=time.perf_counter() - start,
                )
            else:
                self._add_result(
                    name, category, True,
                    details=details,
                    duration=time.perf_counter() - start,
                )

        except Exception as e:
            self._add_result(
                name, category, False,
                error=str(e), exc=e,
                severity=TestSeverity.ERROR,
                duration=time.perf_counter() - start,
            )

    # ------------------------------------------------------------------
    # Tes 6 : Business Logic Sanity Check
    # ------------------------------------------------------------------
    def test_business_logic_sanity(self) -> None:
        start = time.perf_counter()
        name = "Business Logic Sanity Check"
        category = "DOMAIN"

        try:
            domain_modules = ["domain", "application", "infrastructure"]
            found, missing = [], []
            for mod in domain_modules:
                try:
                    importlib.import_module(mod)
                    found.append(mod)
                except ImportError:
                    missing.append(mod)

            details = {
                "found_modules": found,
                "missing_modules": missing,
                "status": "partial" if missing else "ok",
            }

            if missing:
                self._add_result(
                    name, category, True,
                    details=details,
                    severity=TestSeverity.WARNING,
                    context={"note": f"Modul tidak ditemukan: {missing}"},
                    suggested_fix=f"Buat modul yang hilang: {', '.join(missing)}",
                    duration=time.perf_counter() - start,
                )
            else:
                self._add_result(
                    name, category, True,
                    details=details,
                    duration=time.perf_counter() - start,
                )

        except Exception as e:
            self._add_result(
                name, category, False,
                error=str(e), exc=e,
                severity=TestSeverity.WARNING,
                duration=time.perf_counter() - start,
            )

    # ------------------------------------------------------------------
    # Tes 7 : Resource Leak Detection
    # ------------------------------------------------------------------
    def test_resource_leak_detection(self) -> None:
        start = time.perf_counter()
        name = "Resource Leak Detection"
        category = "PERFORMANCE"

        try:
            end_memory_mb = self._get_memory_mb()
            end_thread_count = threading.active_count()

            memory_diff = end_memory_mb - self.start_memory_mb
            thread_diff = end_thread_count - self.start_thread_count

            details = {
                "start_memory_mb": round(self.start_memory_mb, 2),
                "end_memory_mb": round(end_memory_mb, 2),
                "memory_diff_mb": round(memory_diff, 2),
                "start_threads": self.start_thread_count,
                "end_threads": end_thread_count,
                "thread_diff": thread_diff,
            }

            issues = []
            if memory_diff > 500:
                issues.append(f"Peningkatan memori tinggi: {memory_diff:.1f}MB")
            if thread_diff > 20:
                issues.append(f"Curiga thread leak: +{thread_diff} thread")

            if issues:
                self._add_result(
                    name, category, False,
                    details=details,
                    error="; ".join(issues),
                    severity=TestSeverity.WARNING,
                    suggested_fix="Tinjau siklus hidup objek dan pembersihan resource",
                    duration=time.perf_counter() - start,
                )
            else:
                self._add_result(
                    name, category, True,
                    details=details,
                    duration=time.perf_counter() - start,
                )

        except Exception as e:
            self._add_result(
                name, category, False,
                error=str(e), exc=e,
                severity=TestSeverity.WARNING,
                duration=time.perf_counter() - start,
            )

    # ------------------------------------------------------------------
    # Tes 8 : API Health Check
    # ------------------------------------------------------------------
    def test_api_health_check(self) -> None:
        start = time.perf_counter()
        name = "API Health Check"
        category = "API"

        try:
            health_endpoints = []
            if self.app_instance:
                for route in getattr(self.app_instance, "routes", []):
                    path = getattr(route, "path", "")
                    if path in ["/health", "/ping", "/status", "/ready"]:
                        health_endpoints.append(path)

            if health_endpoints:
                details = {
                    "health_endpoints_found": health_endpoints,
                    "count": len(health_endpoints),
                }
                self._add_result(
                    name, category, True,
                    details=details,
                    severity=TestSeverity.INFO,
                    duration=time.perf_counter() - start,
                )
            else:
                has_health = False
                for root, dirs, files in os.walk(self.project_root):
                    if any(excl in root for excl in ["venv", "__pycache__", ".git", "checker"]):
                        continue
                    for file in files:
                        if file.endswith(".py"):
                            filepath = Path(root) / file
                            try:
                                content = filepath.read_text(encoding="utf-8", errors="ignore")
                                if "health" in content.lower() and ("@app.get" in content or "@router.get" in content):
                                    has_health = True
                                    break
                            except:
                                continue
                    if has_health:
                        break

                if has_health:
                    details = {"note": "Endpoint health ditemukan di kode, tetapi tidak terdaftar di app.routes"}
                    self._add_result(
                        name, category, True,
                        details=details,
                        severity=TestSeverity.WARNING,
                        suggested_fix="Pastikan endpoint health terdaftar di aplikasi",
                        duration=time.perf_counter() - start,
                    )
                else:
                    self._add_result(
                        name, category, False,
                        error="Tidak ditemukan endpoint health (/health, /ping, /status, /ready)",
                        severity=TestSeverity.WARNING,
                        suggested_fix="Tambahkan endpoint health untuk monitoring",
                        duration=time.perf_counter() - start,
                    )

        except Exception as e:
            self._add_result(
                name, category, False,
                error=str(e), exc=e,
                severity=TestSeverity.WARNING,
                duration=time.perf_counter() - start,
            )

    # ------------------------------------------------------------------
    # Tes 9 : Configuration Validation
    # ------------------------------------------------------------------
    def test_configuration_validation(self) -> None:
        start = time.perf_counter()
        name = "Configuration Validation"
        category = "CONFIG"

        try:
            required_vars = [
                "ENVIRONMENT",
                "DATABASE_URL",
                "SECRET_KEY",
            ]
            optional_vars = [
                "REDIS_URL",
                "CACHE_URL",
                "BROKER_URL",
                "SENTRY_DSN",
                "CORS_ORIGINS",
            ]

            missing_required = []
            missing_optional = []
            for var in required_vars:
                if not os.getenv(var):
                    missing_required.append(var)
            for var in optional_vars:
                if not os.getenv(var):
                    missing_optional.append(var)

            details = {
                "required_vars_defined": [v for v in required_vars if v not in missing_required],
                "optional_vars_defined": [v for v in optional_vars if v not in missing_optional],
                "missing_required": missing_required,
                "missing_optional": missing_optional,
            }

            if missing_required:
                self._add_result(
                    name, category, False,
                    details=details,
                    error=f"Variabel environment wajib hilang: {', '.join(missing_required)}",
                    severity=TestSeverity.ERROR,
                    suggested_fix="Set variabel tersebut di .env atau environment",
                    duration=time.perf_counter() - start,
                )
            elif missing_optional:
                self._add_result(
                    name, category, True,
                    details=details,
                    severity=TestSeverity.WARNING,
                    context={"note": f"Variabel opsional tidak diset: {missing_optional}"},
                    suggested_fix="Set jika diperlukan untuk fitur tertentu",
                    duration=time.perf_counter() - start,
                )
            else:
                self._add_result(
                    name, category, True,
                    details=details,
                    duration=time.perf_counter() - start,
                )

        except Exception as e:
            self._add_result(
                name, category, False,
                error=str(e), exc=e,
                severity=TestSeverity.ERROR,
                duration=time.perf_counter() - start,
            )

    # ------------------------------------------------------------------
    # Tes 10 : Domain Models
    # ------------------------------------------------------------------
    def test_domain_models(self) -> None:
        start = time.perf_counter()
        name = "Domain Models"
        category = "DOMAIN"

        try:
            domain_path = self.project_root / "domain"
            if not domain_path.exists():
                self._add_result(
                    name, category, False,
                    error="Folder 'domain' tidak ditemukan",
                    severity=TestSeverity.WARNING,
                    suggested_fix="Buat struktur domain/ dengan model-model",
                    duration=time.perf_counter() - start,
                )
                return

            model_files = list(domain_path.glob("**/*.py"))
            model_count = len([f for f in model_files if f.name != "__init__.py"])

            found_models = []
            for root, dirs, files in os.walk(domain_path):
                for file in files:
                    if file.endswith(".py") and file != "__init__.py":
                        mod_name = file.replace(".py", "")
                        try:
                            mod = importlib.import_module(f"domain.{mod_name}")
                            for attr in dir(mod):
                                obj = getattr(mod, attr)
                                if inspect.isclass(obj) and obj.__module__ == f"domain.{mod_name}":
                                    found_models.append(f"{mod_name}.{attr}")
                        except:
                            pass

            details = {
                "domain_folder_exists": True,
                "model_files_count": model_count,
                "found_model_classes": found_models[:10],
                "total_classes_found": len(found_models),
            }

            if model_count == 0:
                self._add_result(
                    name, category, False,
                    details=details,
                    error="Tidak ada file model di folder domain",
                    severity=TestSeverity.WARNING,
                    suggested_fix="Buat model-model di domain/",
                    duration=time.perf_counter() - start,
                )
            elif len(found_models) == 0:
                self._add_result(
                    name, category, True,
                    details=details,
                    severity=TestSeverity.WARNING,
                    error="File model ditemukan tetapi tidak ada class yang terdeteksi",
                    suggested_fix="Pastikan model adalah class Python di dalam file",
                    duration=time.perf_counter() - start,
                )
            else:
                self._add_result(
                    name, category, True,
                    details=details,
                    duration=time.perf_counter() - start,
                )

        except Exception as e:
            self._add_result(
                name, category, False,
                error=str(e), exc=e,
                severity=TestSeverity.WARNING,
                duration=time.perf_counter() - start,
            )

    # ------------------------------------------------------------------
    # Tes 11 : Repository Pattern
    # ------------------------------------------------------------------
    def test_repository_pattern(self) -> None:
        start = time.perf_counter()
        name = "Repository Pattern"
        category = "DATA"

        try:
            repo_modules = []
            search_paths = [
                "infrastructure.repositories",
                "domain.repositories",
                "application.repositories",
                "repositories",
            ]
            found_repos = []
            for mod_name in search_paths:
                mod = self._safe_import(mod_name)
                if mod:
                    repo_modules.append(mod_name)
                    for attr in dir(mod):
                        obj = getattr(mod, attr)
                        if inspect.isclass(obj) and "repository" in attr.lower():
                            found_repos.append(f"{mod_name}.{attr}")

            if not found_repos:
                for root, dirs, files in os.walk(self.project_root):
                    if any(excl in root for excl in ["venv", "__pycache__", ".git", "checker"]):
                        continue
                    for file in files:
                        if file.endswith(".py") and "repository" in file.lower():
                            try:
                                rel_path = Path(root) / file
                                mod_name = str(rel_path.relative_to(self.project_root)).replace("/", ".").replace("\\", ".").replace(".py", "")
                                mod = self._safe_import(mod_name)
                                if mod:
                                    for attr in dir(mod):
                                        obj = getattr(mod, attr)
                                        if inspect.isclass(obj) and ("repository" in attr.lower() or "Repo" in attr):
                                            found_repos.append(f"{mod_name}.{attr}")
                            except:
                                continue

            details = {
                "repository_modules_found": repo_modules,
                "repository_classes_found": found_repos[:10],
                "total_repositories": len(found_repos),
            }

            if not found_repos:
                self._add_result(
                    name, category, False,
                    details=details,
                    error="Tidak ditemukan implementasi repository",
                    severity=TestSeverity.WARNING,
                    suggested_fix="Buat repository pattern untuk akses data",
                    duration=time.perf_counter() - start,
                )
            else:
                self._add_result(
                    name, category, True,
                    details=details,
                    duration=time.perf_counter() - start,
                )

        except Exception as e:
            self._add_result(
                name, category, False,
                error=str(e), exc=e,
                severity=TestSeverity.WARNING,
                duration=time.perf_counter() - start,
            )

    # ------------------------------------------------------------------
    # Tes 12 : CORS Configuration
    # ------------------------------------------------------------------
    def test_cors_configuration(self) -> None:
        start = time.perf_counter()
        name = "CORS Configuration"
        category = "SECURITY"

        try:
            cors_origins = os.getenv("CORS_ORIGINS", "")
            cors_configured = False
            cors_details = {}

            if self.app_instance and hasattr(self.app_instance, "user_middleware"):
                for mw in self.app_instance.user_middleware:
                    mw_str = str(mw.cls).lower()
                    if "cors" in mw_str:
                        cors_configured = True
                        cors_details["middleware"] = mw.cls.__name__
                        break

            if not cors_configured:
                for root, dirs, files in os.walk(self.project_root):
                    if any(excl in root for excl in ["venv", "__pycache__", ".git", "checker"]):
                        continue
                    for file in files:
                        if file.endswith(".py"):
                            filepath = Path(root) / file
                            try:
                                content = filepath.read_text(encoding="utf-8", errors="ignore")
                                if "CORS" in content and ("add_middleware" in content or "CORSMiddleware" in content):
                                    cors_configured = True
                                    cors_details["file"] = str(filepath.relative_to(self.project_root))
                                    break
                            except:
                                continue
                    if cors_configured:
                        break

            details = {
                "cors_configured": cors_configured,
                "cors_origins_env": cors_origins if cors_origins else "not_set",
                "details": cors_details,
            }

            if cors_configured:
                self._add_result(
                    name, category, True,
                    details=details,
                    duration=time.perf_counter() - start,
                )
            else:
                self._add_result(
                    name, category, False,
                    details=details,
                    error="CORS tidak dikonfigurasi",
                    severity=TestSeverity.WARNING,
                    suggested_fix="Tambahkan middleware CORS untuk keamanan lintas origin",
                    duration=time.perf_counter() - start,
                )

        except Exception as e:
            self._add_result(
                name, category, False,
                error=str(e), exc=e,
                severity=TestSeverity.WARNING,
                duration=time.perf_counter() - start,
            )

    # ------------------------------------------------------------------
    # Tes 13 : Authentication / Authorization
    # ------------------------------------------------------------------
    def test_authentication_authorization(self) -> None:
        start = time.perf_counter()
        name = "Authentication / Authorization"
        category = "SECURITY"

        try:
            auth_indicators = []

            jwt_secret = os.getenv("JWT_SECRET", "")
            if jwt_secret:
                auth_indicators.append("JWT_SECRET ada")
            if os.getenv("JWT_ALGORITHM", ""):
                auth_indicators.append("JWT_ALGORITHM ada")

            if self.app_instance and hasattr(self.app_instance, "user_middleware"):
                for mw in self.app_instance.user_middleware:
                    mw_str = str(mw.cls).lower()
                    if "auth" in mw_str or "jwt" in mw_str or "token" in mw_str:
                        auth_indicators.append(f"Middleware auth: {mw.cls.__name__}")
                        break

            auth_files = []
            for root, dirs, files in os.walk(self.project_root):
                if any(excl in root for excl in ["venv", "__pycache__", ".git", "checker"]):
                    continue
                for file in files:
                    if file.endswith(".py") and any(k in file.lower() for k in ["auth", "jwt", "login", "token"]):
                        auth_files.append(file)
            if auth_files:
                auth_indicators.append(f"File auth: {', '.join(auth_files[:3])}")

            details = {
                "auth_indicators": auth_indicators,
                "jwt_secret_set": bool(jwt_secret),
                "has_auth_files": len(auth_files) > 0,
            }

            if not auth_indicators:
                self._add_result(
                    name, category, False,
                    details=details,
                    error="Tidak ada indikasi authentication/authorization",
                    severity=TestSeverity.WARNING,
                    suggested_fix="Implementasikan JWT atau OAuth2 untuk keamanan API",
                    duration=time.perf_counter() - start,
                )
            else:
                self._add_result(
                    name, category, True,
                    details=details,
                    duration=time.perf_counter() - start,
                )

        except Exception as e:
            self._add_result(
                name, category, False,
                error=str(e), exc=e,
                severity=TestSeverity.WARNING,
                duration=time.perf_counter() - start,
            )

    # ==================================================================
    # TES TAMBAHAN (14-17) - ERP & INFRASTRUKTUR
    # ==================================================================

    # ------------------------------------------------------------------
    # Tes 14 : Master Data Models (ERP specific)
    # ------------------------------------------------------------------
    def test_master_data_models(self) -> None:
        start = time.perf_counter()
        name = "Master Data Models (ERP)"
        category = "DOMAIN"

        try:
            # Daftar model inti ERP yang umum
            core_models = [
                "Company", "Branch", "FiscalYear", "Currency",
                "ChartOfAccount", "Account", "Journal", "Ledger",
                "Product", "Warehouse", "StockMovement",
                "Customer", "Supplier", "SalesOrder", "PurchaseOrder",
                "Invoice", "Payment", "Receipt"
            ]
            found_models = []
            domain_path = self.project_root / "domain"

            if not domain_path.exists():
                self._add_result(
                    name, category, False,
                    error="Folder domain tidak ditemukan",
                    severity=TestSeverity.WARNING,
                    suggested_fix="Buat struktur domain/ dengan model ERP",
                    duration=time.perf_counter() - start,
                )
                return

            # Cari class yang sesuai
            for root, dirs, files in os.walk(domain_path):
                for file in files:
                    if file.endswith(".py") and file != "__init__.py":
                        mod_name = file.replace(".py", "")
                        try:
                            mod = importlib.import_module(f"domain.{mod_name}")
                            for attr in dir(mod):
                                obj = getattr(mod, attr)
                                if inspect.isclass(obj) and obj.__module__ == f"domain.{mod_name}":
                                    class_name = attr
                                    if class_name in core_models:
                                        found_models.append(class_name)
                        except:
                            continue

            missing_models = [m for m in core_models if m not in found_models]
            details = {
                "core_models_defined": core_models,
                "found_models": found_models,
                "missing_models": missing_models,
                "coverage": f"{len(found_models)}/{len(core_models)}",
            }

            if len(found_models) == 0:
                self._add_result(
                    name, category, False,
                    details=details,
                    error="Tidak ditemukan satupun model ERP inti",
                    severity=TestSeverity.WARNING,
                    suggested_fix="Buat model-model bisnis di domain/ (Company, Account, Product, dll.)",
                    duration=time.perf_counter() - start,
                )
            elif missing_models:
                self._add_result(
                    name, category, True,
                    details=details,
                    severity=TestSeverity.WARNING,
                    context={"missing": missing_models[:5]},
                    suggested_fix=f"Tambahkan model yang hilang: {', '.join(missing_models[:5])}",
                    duration=time.perf_counter() - start,
                )
            else:
                self._add_result(
                    name, category, True,
                    details=details,
                    duration=time.perf_counter() - start,
                )

        except Exception as e:
            self._add_result(
                name, category, False,
                error=str(e), exc=e,
                severity=TestSeverity.WARNING,
                duration=time.perf_counter() - start,
            )

    # ------------------------------------------------------------------
    # Tes 15 : OpenAPI Documentation
    # ------------------------------------------------------------------
    def test_openapi_documentation(self) -> None:
        start = time.perf_counter()
        name = "OpenAPI Documentation"
        category = "API"

        try:
            if not self.app_instance:
                self._add_result(
                    name, category, False,
                    error="App instance tidak tersedia",
                    severity=TestSeverity.WARNING,
                    suggested_fix="Pastikan FastAPI app ditemukan",
                    duration=time.perf_counter() - start,
                )
                return

            # Cek apakah OpenAPI schema tersedia
            has_openapi = hasattr(self.app_instance, "openapi")
            has_docs = hasattr(self.app_instance, "docs_url")
            has_redoc = hasattr(self.app_instance, "redoc_url")

            docs_url = getattr(self.app_instance, "docs_url", None)
            redoc_url = getattr(self.app_instance, "redoc_url", None)

            details = {
                "has_openapi_method": has_openapi,
                "docs_url": docs_url or "/docs",
                "redoc_url": redoc_url or "/redoc",
                "title": getattr(self.app_instance, "title", "unknown"),
                "version": getattr(self.app_instance, "version", "unknown"),
            }

            if has_docs or has_redoc:
                self._add_result(
                    name, category, True,
                    details=details,
                    duration=time.perf_counter() - start,
                )
            else:
                self._add_result(
                    name, category, False,
                    details=details,
                    error="OpenAPI documentation tidak diaktifkan",
                    severity=TestSeverity.WARNING,
                    suggested_fix="Aktifkan docs_url dan redoc_url di FastAPI",
                    duration=time.perf_counter() - start,
                )

        except Exception as e:
            self._add_result(
                name, category, False,
                error=str(e), exc=e,
                severity=TestSeverity.WARNING,
                duration=time.perf_counter() - start,
            )

    # ------------------------------------------------------------------
    # Tes 16 : Message Broker (Redis/RabbitMQ)
    # ------------------------------------------------------------------
    def test_message_broker(self) -> None:
        start = time.perf_counter()
        name = "Message Broker Connectivity"
        category = "INTEGRATION"

        try:
            broker_url = os.getenv("BROKER_URL", os.getenv("REDIS_URL", ""))
            if not broker_url:
                self._add_result(
                    name, category, False,
                    error="BROKER_URL atau REDIS_URL tidak diset",
                    severity=TestSeverity.WARNING,
                    suggested_fix="Set BROKER_URL jika menggunakan event-driven",
                    duration=time.perf_counter() - start,
                )
                return

            # Coba koneksi sederhana (tanpa library berat)
            broker_type = "unknown"
            if "redis" in broker_url.lower():
                broker_type = "redis"
                try:
                    import redis
                    client = redis.Redis.from_url(broker_url)
                    client.ping()
                    connected = True
                    details = {"type": "redis", "url": broker_url.split("@")[-1] if "@" in broker_url else broker_url}
                except ImportError:
                    connected = False
                    details = {"type": "redis", "error": "redis-py tidak terinstall"}
                except Exception as e:
                    connected = False
                    details = {"type": "redis", "error": str(e)}
            elif "rabbitmq" in broker_url.lower() or "amqp" in broker_url.lower():
                broker_type = "rabbitmq"
                try:
                    import pika
                    params = pika.URLParameters(broker_url)
                    connection = pika.BlockingConnection(params)
                    connection.close()
                    connected = True
                    details = {"type": "rabbitmq", "url": broker_url.split("@")[-1] if "@" in broker_url else broker_url}
                except ImportError:
                    connected = False
                    details = {"type": "rabbitmq", "error": "pika tidak terinstall"}
                except Exception as e:
                    connected = False
                    details = {"type": "rabbitmq", "error": str(e)}
            else:
                connected = False
                details = {"type": "unknown", "url": broker_url}

            if connected:
                self._add_result(
                    name, category, True,
                    details=details,
                    duration=time.perf_counter() - start,
                )
            else:
                self._add_result(
                    name, category, False,
                    details=details,
                    error=f"Koneksi ke {broker_type} gagal: {details.get('error', 'Unknown')}",
                    severity=TestSeverity.WARNING,
                    suggested_fix="Periksa BROKER_URL dan instal library yang diperlukan",
                    duration=time.perf_counter() - start,
                )

        except Exception as e:
            self._add_result(
                name, category, False,
                error=str(e), exc=e,
                severity=TestSeverity.WARNING,
                duration=time.perf_counter() - start,
            )

    # ------------------------------------------------------------------
    # Tes 17 : Scheduler (Celery/APScheduler)
    # ------------------------------------------------------------------
    def test_scheduler_availability(self) -> None:
        start = time.perf_counter()
        name = "Scheduler Availability"
        category = "INTEGRATION"

        try:
            scheduler_indicators = []

            # Cek Celery
            celery_app = None
            try:
                from celery import Celery
                # Cari instance celery di project
                for mod_name in ["tasks", "celery_app", "celery", "application.celery", "infrastructure.celery"]:
                    mod = self._safe_import(mod_name)
                    if mod:
                        for attr in dir(mod):
                            obj = getattr(mod, attr)
                            if isinstance(obj, Celery):
                                celery_app = obj
                                scheduler_indicators.append(f"Celery app ditemukan di {mod_name}.{attr}")
                                break
                        if celery_app:
                            break
            except ImportError:
                pass

            # Cek APScheduler
            apscheduler_found = False
            try:
                import apscheduler
                # Cari scheduler instance
                for mod_name in ["scheduler", "application.scheduler", "infrastructure.scheduler"]:
                    mod = self._safe_import(mod_name)
                    if mod:
                        for attr in dir(mod):
                            obj = getattr(mod, attr)
                            if hasattr(obj, "start") and hasattr(obj, "add_job"):
                                apscheduler_found = True
                                scheduler_indicators.append(f"APScheduler ditemukan di {mod_name}.{attr}")
                                break
                        if apscheduler_found:
                            break
            except ImportError:
                pass

            # Cari file terkait scheduler
            scheduler_files = []
            for root, dirs, files in os.walk(self.project_root):
                if any(excl in root for excl in ["venv", "__pycache__", ".git", "checker"]):
                    continue
                for file in files:
                    if file.endswith(".py") and any(k in file.lower() for k in ["scheduler", "celery", "task", "cron", "periodic"]):
                        scheduler_files.append(file)
            if scheduler_files:
                scheduler_indicators.append(f"File scheduler: {', '.join(scheduler_files[:3])}")

            details = {
                "scheduler_indicators": scheduler_indicators,
                "celery_found": celery_app is not None,
                "apscheduler_found": apscheduler_found,
                "has_scheduler_files": len(scheduler_files) > 0,
            }

            if not scheduler_indicators:
                self._add_result(
                    name, category, False,
                    details=details,
                    error="Tidak ditemukan indikasi scheduler (Celery/APScheduler)",
                    severity=TestSeverity.WARNING,
                    suggested_fix="Jika diperlukan, tambahkan Celery atau APScheduler untuk job periodic",
                    duration=time.perf_counter() - start,
                )
            else:
                self._add_result(
                    name, category, True,
                    details=details,
                    duration=time.perf_counter() - start,
                )

        except Exception as e:
            self._add_result(
                name, category, False,
                error=str(e), exc=e,
                severity=TestSeverity.WARNING,
                duration=time.perf_counter() - start,
            )

    # ------------------------------------------------------------------
    # Jalankan semua tes (overriding method)
    # ------------------------------------------------------------------
    def run_all_tests(self) -> None:
        logger.info("=" * 70)
        logger.info("🚀 SMOKE TEST SUITE v7.3.0 - ENTERPRISE FORENSIC EDITION")
        logger.info("=" * 70)

        if self.test_env:
            logger.info("🔧 Test environment dipaksa (--test-env)")
        else:
            env = os.getenv("ENVIRONMENT", "not_set")
            if env.lower() in ["prod", "production", "live", "prd"]:
                logger.warning(f"⚠️  ENVIRONMENT={env} terdeteksi. Gunakan --test-env untuk melewati safety check.")
            else:
                logger.info(f"✅ Environment: {env}")

        total_start = time.perf_counter()

        # 7 tes inti
        self.test_environment_safety()
        self.test_di_container_integrity()
        self.test_fastapi_app_structure()
        self.test_database_connectivity()
        self.test_security_configuration()
        self.test_business_logic_sanity()
        self.test_resource_leak_detection()

        # 6 tes tambahan (8-13)
        self.test_api_health_check()
        self.test_configuration_validation()
        self.test_domain_models()
        self.test_repository_pattern()
        self.test_cors_configuration()
        self.test_authentication_authorization()

        # 4 tes ERP & infrastruktur (14-17)
        self.test_master_data_models()
        self.test_openapi_documentation()
        self.test_message_broker()
        self.test_scheduler_availability()

        total_duration = time.perf_counter() - total_start

        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed and r.severity in (TestSeverity.CRITICAL, TestSeverity.ERROR))
        warnings = sum(1 for r in self.results if not r.passed and r.severity == TestSeverity.WARNING)
        total = len(self.results)
        score = (passed / total * 100) if total > 0 else 0

        logger.info("")
        logger.info("=" * 70)
        logger.info("📊 SMOKE TEST SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Total Duration : {total_duration:.2f}s")
        logger.info(f"Tests Passed   : {passed}/{total}")
        logger.info(f"Tests Failed   : {failed}")
        logger.info(f"Warnings       : {warnings}")
        logger.info(f"Score          : {score:.1f}%")
        logger.info("-" * 70)

        if failed > 0:
            logger.critical("❌ STATUS: CRITICAL FAILURES DETECTED — DO NOT DEPLOY! 🛑")
            logger.critical("   Perbaiki error di atas sebelum deploy.")
        elif warnings > 0:
            logger.warning("⚠️  STATUS: PASSED WITH WARNINGS — REVIEW BEFORE DEPLOY ⚡")
        else:
            logger.info("✅ STATUS: ALL TESTS PASSED — READY TO DEPLOY! 🚀")

        logger.info("=" * 70)

        report = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "version": "7.3.0",
            "summary": {
                "total_duration_seconds": round(total_duration, 3),
                "passed": passed,
                "failed": failed,
                "warnings": warnings,
                "total_tests": total,
                "score_percent": round(score, 1),
                "test_env_used": self.test_env,
                "rca_enabled": self.enable_rca,
            },
            "results": [r.to_dict() for r in self.results],
            "baseline": {
                "start_memory_mb": round(self.start_memory_mb, 2),
                "start_thread_count": self.start_thread_count,
            },
        }
        report_path = Path("smoke_test_report.json")
        report_path.write_text(json.dumps(report, indent=2))
        logger.info(f"📄 Laporan JSON detail disimpan di: {report_path}")


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="ERP Engine Smoke Test Suite v7.3.0 - Enterprise Forensic Edition"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Tampilkan traceback lengkap untuk setiap error"
    )
    parser.add_argument(
        "--test-env",
        action="store_true",
        help="Paksa mode test environment (lewati safety check production)"
    )
    parser.add_argument(
        "--disable-rca",
        action="store_true",
        help="Nonaktifkan RCA Engine (jika tersedia)"
    )
    args = parser.parse_args()

    runner = ForensicSmokeTestRunner(
        verbose=args.verbose,
        test_env=args.test_env,
        enable_rca=not args.disable_rca,
    )
    runner.run_all_tests()

    failed_critical = sum(
        1 for r in runner.results
        if not r.passed and r.severity == TestSeverity.CRITICAL
    )
    sys.exit(1 if failed_critical > 0 else 0)


if __name__ == "__main__":
    main()