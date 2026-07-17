"""
🚀 SMOKE TEST SUITE v6.3.0 - FINAL EDITION
===========================================
Perbaikan final:
- Environment Safety: Hanya CRITICAL jika production DAN tidak ada --test-env.
- DI Container: UnitOfWork tidak wajib (hanya WARNING jika tidak ada).
- Resource Leak: Threshold memory dinaikkan ke 500MB.
- Skor akhir berdasarkan persentase PASS.
"""

import os
import sys
import time
import json
import logging
import threading
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
import importlib
import inspect
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("SmokeTest_v6")


class Severity(Enum):
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    SUCCESS = "SUCCESS"


@dataclass
class SmokeTestResult:
    name: str
    passed: bool
    duration: float = 0.0
    severity: Severity = Severity.INFO
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    exception: Optional[Exception] = None
    context: Dict[str, Any] = field(default_factory=dict)
    suggested_fix: Optional[str] = None
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "duration_seconds": round(self.duration, 3),
            "severity": self.severity.value,
            "details": self.details,
            "error": self.error,
            "context": self.context,
            "suggested_fix": self.suggested_fix,
            "evidence": self.evidence[:5] if self.evidence else []
        }


class SmokeTestRunner:
    def __init__(self, verbose: bool = False, test_env: bool = False):
        self.results: List[SmokeTestResult] = []
        self.verbose = verbose
        self.test_env = test_env
        self.start_memory_mb = 0.0
        self.start_thread_count = 0
        self.app_instance = None
        self.di_container = None
        self.project_root = Path.cwd()
        self._container_found = False
        self._app_found = False

    def _get_memory_mb(self) -> float:
        try:
            import psutil
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            try:
                import resource
                return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            except:
                return 0.0

    def _get_thread_count(self) -> int:
        return threading.active_count()

    def _add_result(self, name: str, passed: bool,
                    details: Optional[Dict[str, Any]] = None,
                    error: Optional[str] = None,
                    exc: Optional[Exception] = None,
                    duration: float = 0.0,
                    severity: Severity = Severity.INFO,
                    context: Optional[Dict[str, Any]] = None,
                    suggested_fix: Optional[str] = None,
                    evidence: Optional[List[str]] = None):
        result = SmokeTestResult(
            name=name,
            passed=passed,
            duration=duration,
            severity=severity,
            details=details or {},
            error=error,
            exception=exc,
            context=context or {},
            suggested_fix=suggested_fix,
            evidence=evidence or []
        )
        self.results.append(result)

        status_icon = "✅" if passed else ("❌" if severity in [Severity.CRITICAL, Severity.ERROR] else "⚠️")
        log_level = logging.ERROR if not passed else logging.INFO
        if severity == Severity.CRITICAL and not passed:
            log_level = logging.CRITICAL

        logger.log(log_level, f"{status_icon} {name} ({duration:.2f}s)")
        if not passed:
            if error:
                logger.log(log_level, f"   └─ Error: {error}")
            if suggested_fix:
                logger.log(log_level, f"   └─ Fix: {suggested_fix}")
            if self.verbose and exc:
                logger.exception("Full traceback:")

    # ─── TEST 1: ENVIRONMENT SAFETY ──────────────────────────────────────
    def test_environment_safety(self) -> None:
        start = time.perf_counter()
        name = "Environment Safety"

        try:
            env = os.getenv("ENVIRONMENT", os.getenv("FLASK_ENV", os.getenv("DJANGO_SETTINGS_MODULE", "")))
            debug_enabled = os.getenv("DEBUG", "False").lower() in ["true", "1", "yes"]

            is_production = False
            production_indicators = []

            env_lower = str(env).lower()
            if env_lower in ["prod", "production", "live", "prd"]:
                is_production = True
                production_indicators.append(f"ENVIRONMENT={env}")

            if os.getenv("PRODUCTION", "False").lower() in ["true", "1"]:
                is_production = True
                production_indicators.append("PRODUCTION=true")

            if sys.argv and any(s in sys.argv[0] for s in ["gunicorn", "uwsgi"]):
                is_production = True
                production_indicators.append("Running under production WSGI server")

            details = {
                "environment": env or "not_set",
                "debug_enabled": debug_enabled,
                "is_production": is_production,
                "production_indicators": production_indicators,
                "test_env_flag": self.test_env,
                "python_version": sys.version.split()[0],
                "platform": sys.platform,
            }

            # Jika production dan tidak ada test_env flag, CRITICAL
            if is_production and not self.test_env:
                self._add_result(
                    name, False,
                    details=details,
                    error=f"Production environment detected: {', '.join(production_indicators)}",
                    severity=Severity.CRITICAL,
                    suggested_fix="Set ENVIRONMENT=development or run with --test-env flag",
                    duration=time.perf_counter() - start
                )
                return

            # Jika production tapi test_env=True, hanya WARNING
            if is_production and self.test_env:
                self._add_result(
                    name, True,
                    details=details,
                    severity=Severity.WARNING,
                    context={"warning": "Production environment but --test-env flag overrides safety check"},
                    suggested_fix="Remove --test-env when running in real production",
                    duration=time.perf_counter() - start
                )
                return

            if debug_enabled and not is_production:
                self._add_result(
                    name, True,
                    details=details,
                    severity=Severity.WARNING,
                    context={"warning": "Debug mode is enabled in non-production"},
                    suggested_fix="Disable DEBUG in production",
                    duration=time.perf_counter() - start
                )
            else:
                self._add_result(name, True, details=details, duration=time.perf_counter() - start)

        except Exception as e:
            self._add_result(
                name, False,
                error=str(e),
                exc=e,
                severity=Severity.CRITICAL,
                duration=time.perf_counter() - start
            )

    # ─── TEST 2: DI CONTAINER ────────────────────────────────────────────
    def test_di_container_integrity(self) -> None:
        start = time.perf_counter()
        name = "DI Container Integrity"

        try:
            container = None
            container_module_name = None
            container_type = None

            search_patterns = [
                ("core.di_container", ["container", "Container", "di_container", "DIContainer"]),
                ("infrastructure.di_container", ["container", "Container", "di_container"]),
                ("di_container", ["container", "Container"]),
                ("container", ["container", "Container", "app_container"]),
                ("core.container", ["container", "Container"]),
                ("application.container", ["container", "Container"]),
                ("bootstrap.container", ["container", "Container"]),
                ("config.container", ["container", "Container"]),
            ]

            for module_name, attr_names in search_patterns:
                try:
                    module = importlib.import_module(module_name)
                    for attr_name in attr_names:
                        if hasattr(module, attr_name):
                            obj = getattr(module, attr_name)
                            if inspect.isclass(obj):
                                container = obj
                                container_type = "class"
                                container_module_name = module_name
                                break
                            elif callable(obj) or hasattr(obj, "resolve") or hasattr(obj, "get"):
                                container = obj
                                container_type = "instance"
                                container_module_name = module_name
                                break
                    if container:
                        break
                except ImportError:
                    continue

            if not container:
                logger.info("Searching for DI container in codebase...")
                for root, dirs, files in os.walk(self.project_root):
                    if any(excl in root for excl in ["venv", "__pycache__", ".git", "checker"]):
                        continue
                    for file in files:
                        if file.endswith(".py") and "container" in file.lower():
                            filepath = Path(root) / file
                            try:
                                rel_path = str(filepath.relative_to(self.project_root))
                                mod_name = rel_path.replace("/", ".").replace("\\", ".").replace(".py", "")
                                module = importlib.import_module(mod_name)
                                for attr_name in dir(module):
                                    obj = getattr(module, attr_name)
                                    if inspect.isclass(obj) and ("container" in attr_name.lower() or "Container" in attr_name):
                                        container = obj
                                        container_type = "class (discovered)"
                                        container_module_name = mod_name
                                        break
                                    elif hasattr(obj, "resolve") or hasattr(obj, "get"):
                                        container = obj
                                        container_type = "instance (discovered)"
                                        container_module_name = mod_name
                                        break
                                if container:
                                    break
                            except:
                                continue
                    if container:
                        break

            if not container:
                self._add_result(
                    name, False,
                    error="No DI Container found in project",
                    severity=Severity.CRITICAL,
                    suggested_fix="Create core.di_container.py with a Container class or instance",
                    evidence=["Searched in: core.di_container, infrastructure.di_container, container, etc."],
                    duration=time.perf_counter() - start
                )
                return

            if inspect.isclass(container):
                try:
                    container_instance = container()
                    self.di_container = container_instance
                    details = {
                        "container_type": container_type,
                        "container_module": container_module_name,
                        "container_class": container.__name__,
                        "status": "instantiated"
                    }
                except Exception as e:
                    self._add_result(
                        name, False,
                        error=f"Failed to instantiate DI container: {e}",
                        exc=e,
                        severity=Severity.CRITICAL,
                        suggested_fix="Check DI container constructor dependencies",
                        duration=time.perf_counter() - start
                    )
                    return
            else:
                self.di_container = container
                details = {
                    "container_type": container_type,
                    "container_module": container_module_name,
                    "container_class": container.__class__.__name__ if hasattr(container, "__class__") else str(type(container)),
                    "status": "existing_instance"
                }

            self._container_found = True

            # Health check: UnitOfWork tidak wajib, hanya WARNING jika tidak ada
            health_issues = []
            health_ok = True

            if hasattr(self.di_container, "resolve"):
                try:
                    self.di_container.resolve("UnitOfWork")
                except Exception as e:
                    health_issues.append(f"UnitOfWork not registered: {e}")
                    health_ok = False

            if hasattr(self.di_container, "get"):
                try:
                    self.di_container.get("UnitOfWork")
                except Exception as e:
                    if "UnitOfWork" not in str(e):
                        health_issues.append(f"get failed: {e}")

            details["health_issues"] = health_issues
            details["health_ok"] = health_ok

            if not health_ok:
                # WARNING, bukan ERROR (UnitOfWork tidak wajib untuk smoke test)
                self._add_result(
                    name, True,  # PASS dengan warning
                    details=details,
                    severity=Severity.WARNING,
                    error="UnitOfWork not registered in DI container",
                    suggested_fix="Register UnitOfWork if needed, or ignore if using other persistence",
                    duration=time.perf_counter() - start
                )
            else:
                self._add_result(name, True, details=details, duration=time.perf_counter() - start)

        except Exception as e:
            self._add_result(
                name, False,
                error=str(e),
                exc=e,
                severity=Severity.ERROR,
                duration=time.perf_counter() - start
            )

    # ─── TEST 3: FASTAPI APP ─────────────────────────────────────────────
    def test_fastapi_app_structure(self) -> None:
        start = time.perf_counter()
        name = "FastAPI App Structure"

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

            for module_name, attr_names in search_modules:
                try:
                    module = importlib.import_module(module_name)
                    for attr_name in attr_names:
                        if hasattr(module, attr_name):
                            obj = getattr(module, attr_name)
                            if hasattr(obj, "routes") and hasattr(obj, "router"):
                                app = obj
                                app_source = f"{module_name}.{attr_name} (instance)"
                                break
                            if callable(obj) and "create" in attr_name.lower():
                                try:
                                    app = obj()
                                    app_source = f"{module_name}.{attr_name} (factory)"
                                    break
                                except Exception as e:
                                    logger.warning(f"Factory {attr_name} failed: {e}")
                    if app:
                        break
                except ImportError:
                    continue

            if not app:
                logger.info("Searching for FastAPI app in codebase...")
                for root, dirs, files in os.walk(self.project_root):
                    if any(excl in root for excl in ["venv", "__pycache__", ".git", "checker"]):
                        continue
                    for file in files:
                        if file.endswith(".py"):
                            filepath = Path(root) / file
                            try:
                                rel_path = str(filepath.relative_to(self.project_root))
                                mod_name = rel_path.replace("/", ".").replace("\\", ".").replace(".py", "")
                                module = importlib.import_module(mod_name)
                                for attr_name in dir(module):
                                    obj = getattr(module, attr_name)
                                    if hasattr(obj, "routes") and hasattr(obj, "router"):
                                        if "fastapi" in str(type(obj)).lower():
                                            app = obj
                                            app_source = f"{mod_name}.{attr_name} (discovered)"
                                            break
                                if app:
                                    break
                            except:
                                continue
                    if app:
                        break

            if not app:
                self._add_result(
                    name, False,
                    error="No FastAPI app found in project",
                    severity=Severity.CRITICAL,
                    suggested_fix="Create erp_engine/app.py with FastAPI() instance or main.py",
                    evidence=["Searched in: erp_engine, main, app, server, erp.asgi"],
                    duration=time.perf_counter() - start
                )
                return

            self._app_found = True
            self.app_instance = app

            routes = app.routes if hasattr(app, "routes") else []
            route_paths = [r.path for r in routes if hasattr(r, "path")]
            duplicates = [p for p in route_paths if route_paths.count(p) > 1]

            middleware_types = []
            if hasattr(app, "user_middleware"):
                middleware_types = [str(m.cls) for m in app.user_middleware]

            details = {
                "app_type": "FastAPI",
                "app_source": app_source,
                "route_count": len(routes),
                "unique_routes": len(set(route_paths)),
                "duplicate_routes": len(set(duplicates)) if duplicates else 0,
                "middleware_count": len(middleware_types),
                "has_cors_middleware": any("cors" in m.lower() for m in middleware_types),
                "has_exception_handlers": len(getattr(app, "exception_handlers", {})) > 0,
                "title": getattr(app, "title", "unknown"),
                "version": getattr(app, "version", "unknown"),
            }

            if len(routes) == 0:
                self._add_result(
                    name, False,
                    details=details,
                    error="No routes registered in FastAPI app",
                    severity=Severity.CRITICAL,
                    suggested_fix="Register routes using @app.get() or include_router()",
                    duration=time.perf_counter() - start
                )
            elif duplicates:
                self._add_result(
                    name, True,
                    details=details,
                    severity=Severity.WARNING,
                    error=f"Found {len(set(duplicates))} duplicate route paths (from include_router)",
                    suggested_fix="Review route registration to avoid unintended overlaps",
                    duration=time.perf_counter() - start
                )
            else:
                self._add_result(name, True, details=details, duration=time.perf_counter() - start)

        except Exception as e:
            self._add_result(
                name, False,
                error=str(e),
                exc=e,
                severity=Severity.CRITICAL,
                duration=time.perf_counter() - start
            )

    # ─── TEST 4: DATABASE ────────────────────────────────────────────────
    def test_database_connectivity(self) -> None:
        start = time.perf_counter()
        name = "Database Connectivity & Metadata"

        try:
            db_url = os.getenv("DATABASE_URL")
            if not db_url:
                self._add_result(
                    name, False,
                    error="DATABASE_URL environment variable not set",
                    severity=Severity.CRITICAL,
                    suggested_fix="Set DATABASE_URL in .env",
                    duration=time.perf_counter() - start
                )
                return

            # Cari session factory
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

            for module_name in search_modules:
                try:
                    module = importlib.import_module(module_name)
                    for func_name in ["get_session_local", "SessionLocal", "get_session", "session_factory", "get_db"]:
                        if hasattr(module, func_name):
                            obj = getattr(module, func_name)
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
                    name, False,
                    error="No session factory found in project",
                    severity=Severity.CRITICAL,
                    suggested_fix="Create get_session_local() in infrastructure/database/session_factory_sqlalchemy.py",
                    duration=time.perf_counter() - start
                )
                return

            # Execute test
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
                                error_msg = "Async session generator yielded no session"
                        else:
                            session = session_obj

                        if session is not None:
                            # Use text() for raw SQL
                            from sqlalchemy import text
                            result = loop.run_until_complete(session.execute(text("SELECT 1")))
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
                        result = session.execute(text("SELECT 1"))
                        success = True
                    else:
                        error_msg = "Session factory returned None"

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
                self._add_result(name, True, details=details, duration=time.perf_counter() - start)
            else:
                self._add_result(
                    name, False,
                    error=f"Database connection failed: {error_msg or 'Unknown error'}",
                    exc=Exception(error_msg) if error_msg else None,
                    severity=Severity.CRITICAL,
                    suggested_fix="Check DATABASE_URL and ensure database server is running",
                    duration=time.perf_counter() - start
                )

        except Exception as e:
            self._add_result(
                name, False,
                error=str(e),
                exc=e,
                severity=Severity.CRITICAL,
                duration=time.perf_counter() - start
            )

    # ─── TEST 5: SECURITY ────────────────────────────────────────────────
    def test_security_configuration(self) -> None:
        start = time.perf_counter()
        name = "Security Configuration Audit"

        try:
            issues = []
            warnings = []

            secret_patterns = ["password", "secret", "key", "token", "credential", "api_key"]
            weak_secrets = []

            for key, value in os.environ.items():
                if any(p in key.lower() for p in secret_patterns):
                    if value and len(value) < 16:
                        weak_secrets.append(f"{key} (length {len(value)})")
                    elif value.lower() in ["changeme", "password", "123456", "secret"]:
                        weak_secrets.append(f"{key} (default value)")

            if weak_secrets:
                warnings.append(f"Weak secrets: {', '.join(weak_secrets[:3])}")

            if os.getenv("DEBUG", "").lower() in ["true", "1"]:
                issues.append("DEBUG mode enabled")

            if self.app_instance and hasattr(self.app_instance, "user_middleware"):
                has_security_headers = any(
                    "security" in str(m.cls).lower() or "headers" in str(m.cls).lower()
                    for m in self.app_instance.user_middleware
                )
                if not has_security_headers:
                    warnings.append("No security headers middleware detected")

            details = {
                "issues_found": len(issues),
                "warnings_found": len(warnings),
                "issues": issues,
                "warnings": warnings,
                "secrets_checked": len([k for k in os.environ.keys() if any(p in k.lower() for p in secret_patterns)])
            }

            if issues:
                self._add_result(
                    name, False,
                    details=details,
                    error=", ".join(issues),
                    severity=Severity.ERROR,
                    suggested_fix="Disable DEBUG mode and review security settings",
                    duration=time.perf_counter() - start
                )
            elif warnings:
                self._add_result(
                    name, True,
                    details=details,
                    severity=Severity.WARNING,
                    context={"warnings": warnings},
                    suggested_fix="Review secrets and add security middleware",
                    duration=time.perf_counter() - start
                )
            else:
                self._add_result(name, True, details=details, duration=time.perf_counter() - start)

        except Exception as e:
            self._add_result(
                name, False,
                error=str(e),
                exc=e,
                severity=Severity.ERROR,
                duration=time.perf_counter() - start
            )

    # ─── TEST 6: BUSINESS LOGIC ──────────────────────────────────────────
    def test_business_logic_sanity(self) -> None:
        start = time.perf_counter()
        name = "Business Logic Sanity Check"

        try:
            domain_modules = ["domain", "application", "infrastructure"]
            found = []
            missing = []

            for mod in domain_modules:
                try:
                    importlib.import_module(mod)
                    found.append(mod)
                except ImportError:
                    missing.append(mod)

            details = {
                "found_modules": found,
                "missing_modules": missing,
                "status": "partial" if missing else "ok"
            }

            if missing:
                self._add_result(
                    name, True,
                    details=details,
                    severity=Severity.WARNING,
                    context={"note": f"Modules not found: {missing}"},
                    suggested_fix=f"Create missing modules: {', '.join(missing)}",
                    duration=time.perf_counter() - start
                )
            else:
                self._add_result(name, True, details=details, duration=time.perf_counter() - start)

        except Exception as e:
            self._add_result(
                name, False,
                error=str(e),
                exc=e,
                severity=Severity.WARNING,
                duration=time.perf_counter() - start
            )

    # ─── TEST 7: RESOURCE LEAK ───────────────────────────────────────────
    def test_resource_leak_detection(self) -> None:
        start = time.perf_counter()
        name = "Resource Leak Detection"

        try:
            end_memory_mb = self._get_memory_mb()
            end_thread_count = self._get_thread_count()

            memory_diff = end_memory_mb - self.start_memory_mb
            thread_diff = end_thread_count - self.start_thread_count

            details = {
                "start_memory_mb": round(self.start_memory_mb, 2),
                "end_memory_mb": round(end_memory_mb, 2),
                "memory_diff_mb": round(memory_diff, 2),
                "start_threads": self.start_thread_count,
                "end_threads": end_thread_count,
                "thread_diff": thread_diff
            }

            # Threshold dinaikkan ke 500MB karena loading banyak modul
            issues = []
            if memory_diff > 500:
                issues.append(f"High memory increase: {memory_diff:.1f}MB")
            if thread_diff > 20:
                issues.append(f"Thread leak suspected: +{thread_diff} threads")

            if issues:
                self._add_result(
                    name, False,
                    details=details,
                    error="; ".join(issues),
                    severity=Severity.WARNING,
                    suggested_fix="Review object lifecycle and cleanup",
                    duration=time.perf_counter() - start
                )
            else:
                self._add_result(name, True, details=details, duration=time.perf_counter() - start)

        except Exception as e:
            self._add_result(
                name, False,
                error=str(e),
                exc=e,
                severity=Severity.WARNING,
                duration=time.perf_counter() - start
            )

    # ─── RUN ALL ──────────────────────────────────────────────────────────
    def run_all_tests(self) -> None:
        logger.info("=" * 70)
        logger.info(f"🚀 STARTING SMOKE TEST SUITE v6.3.0 (FINAL)")
        logger.info("=" * 70)

        if self.test_env:
            logger.info("🔧 Test environment forced (--test-env)")
        else:
            env = os.getenv("ENVIRONMENT", "not_set")
            if env.lower() in ["prod", "production", "live", "prd"]:
                logger.warning(f"⚠️  ENVIRONMENT={env} detected. Use --test-env to bypass safety check.")
            else:
                logger.info(f"✅ Environment: {env}")

        self.start_memory_mb = self._get_memory_mb()
        self.start_thread_count = self._get_thread_count()

        total_start = time.perf_counter()

        self.test_environment_safety()
        self.test_di_container_integrity()
        self.test_fastapi_app_structure()
        self.test_database_connectivity()
        self.test_security_configuration()
        self.test_business_logic_sanity()
        self.test_resource_leak_detection()

        total_duration = time.perf_counter() - total_start

        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed and r.severity in [Severity.CRITICAL, Severity.ERROR])
        warnings = sum(1 for r in self.results if not r.passed and r.severity == Severity.WARNING)
        total_tests = len(self.results)

        # Score = persentase PASS dari total
        score = (passed / total_tests * 100) if total_tests > 0 else 0

        logger.info("")
        logger.info("=" * 70)
        logger.info("📊 SMOKE TEST SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Total Duration : {total_duration:.2f}s")
        logger.info(f"Tests Passed   : {passed}")
        logger.info(f"Tests Failed   : {failed}")
        logger.info(f"Tests Warning  : {warnings}")
        logger.info(f"Score          : {score:.1f}%")
        logger.info("-" * 70)

        if failed > 0:
            logger.critical("❌ STATUS: CRITICAL FAILURES DETECTED — DO NOT DEPLOY! 🛑")
            logger.critical("   Review the errors above.")
        elif warnings > 0:
            logger.warning("⚠️  STATUS: PASSED WITH WARNINGS — REVIEW BEFORE DEPLOY ⚡")
        else:
            logger.info("✅ STATUS: ALL TESTS PASSED — READY TO DEPLOY! 🚀")

        logger.info("=" * 70)

        report = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "version": "6.3.0",
            "summary": {
                "total_duration_seconds": round(total_duration, 3),
                "passed": passed,
                "failed": failed,
                "warnings": warnings,
                "total_tests": total_tests,
                "score_percent": round(score, 1),
                "test_env_used": self.test_env
            },
            "results": [r.to_dict() for r in self.results],
            "baseline": {
                "start_memory_mb": round(self.start_memory_mb, 2),
                "start_thread_count": self.start_thread_count
            }
        }

        report_path = Path("smoke_test_report.json")
        report_path.write_text(json.dumps(report, indent=2))
        logger.info(f"📄 Detailed JSON report saved to: {report_path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="ERP Engine Smoke Test Suite v6.3.0")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed tracebacks")
    parser.add_argument("--test-env", action="store_true", help="Force test environment mode (skip production safety check)")
    args = parser.parse_args()

    runner = SmokeTestRunner(verbose=args.verbose, test_env=args.test_env)
    runner.run_all_tests()

    # Exit code: 0 jika tidak ada critical failure
    failed_critical = sum(1 for r in runner.results if not r.passed and r.severity == Severity.CRITICAL)
    sys.exit(1 if failed_critical > 0 else 0)


if __name__ == "__main__":
    main()