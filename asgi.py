#!/usr/bin/env python3
"""
asgi.py
=======
ASGI Application Factory — ERP Accounting Engine

Entry point untuk server ASGI (Uvicorn / Gunicorn).
Semua komponen di-import secara statis. Tidak ada dynamic import.
Komponen yang gagal diimport (kecuali yang benar-benar opsional) akan menyebabkan aplikasi gagal start.
"""

from __future__ import annotations
from fastapi import Request


import asyncio
import logging
import os
import re
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# ============================================================================
# 1. Setup dasar: path, logging awal, dan imports wajib
# ============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Logging sementara (akan di-replace dengan structlog jika tersedia)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_raw_log = logging.getLogger("erp.asgi")

# FastAPI dan dependencies (wajib)
try:
    from fastapi import FastAPI, Request, Response
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.middleware.gzip import GZipMiddleware
    from fastapi.openapi.utils import get_openapi
    from fastapi.responses import JSONResponse
except ImportError as exc:
    _raw_log.critical(f"FastAPI tidak terinstall: {exc}")
    _raw_log.critical("Jalankan: pip install fastapi uvicorn[standard]")
    sys.exit(1)

# ============================================================================
# 2. Konfigurasi dari application.yaml (dengan resolusi environment variable)
# ============================================================================

_CONFIG_CACHE: dict[str, Any] = {}
_ENV_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")


def _resolve_env_placeholder(value: Any) -> Any:
    """Rekursif mengganti ${VAR:default} dengan nilai environment."""
    if isinstance(value, str):

        def replacer(match):
            var = match.group(1)
            default = match.group(2) if match.group(2) is not None else ""
            return os.environ.get(var, default)

        return _ENV_PLACEHOLDER.sub(replacer, value)
    elif isinstance(value, dict):
        return {k: _resolve_env_placeholder(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_env_placeholder(i) for i in value]
    return value


def _load_app_config() -> dict[str, Any]:
    """Muat dan cache konfigurasi dari config_files/application.yaml."""
    if _CONFIG_CACHE:
        return _CONFIG_CACHE
    config_path = PROJECT_ROOT / "config_files" / "application.yaml"
    if not config_path.exists():
        _raw_log.warning(
            "File config_files/application.yaml tidak ditemukan. Gunakan env var saja."
        )
        return {}
    try:
        import yaml

        with open(config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        resolved = _resolve_env_placeholder(raw)
        _CONFIG_CACHE.update(resolved)
        return _CONFIG_CACHE
    except Exception as e:
        _raw_log.error(f"Gagal load application.yaml: {e}")
        return {}


def get_config(key: str, default: Any = None) -> Any:
    """
    Ambil nilai dari YAML (dengan dot notation) atau fallback ke env var.
    Contoh: get_config("app.env") -> ambil dari ['app']['env'].
    Jika tidak ada, cari env var APP_ENV.
    """
    data = _load_app_config()
    parts = key.split(".")
    value = data
    for p in parts:
        if isinstance(value, dict):
            value = value.get(p)
        else:
            value = None
            break
    if value is not None:
        return value
    env_key = key.upper().replace(".", "_")
    return os.environ.get(env_key, default)


# ============================================================================
# 3. Structured logging (structlog dengan fallback)
# ============================================================================

_LOGGER = None


def get_logger(name: str = "erp.asgi"):
    global _LOGGER
    if _LOGGER is None:
        try:
            import structlog

            fmt = get_config("logging.format", "json")
            structlog.configure(
                processors=[
                    structlog.stdlib.filter_by_level,
                    structlog.stdlib.add_logger_name,
                    structlog.stdlib.add_log_level,
                    structlog.stdlib.PositionalArgumentsFormatter(),
                    structlog.processors.TimeStamper(fmt="iso"),
                    structlog.processors.StackInfoRenderer(),
                    structlog.processors.format_exc_info,
                    structlog.processors.UnicodeDecoder(),
                    (
                        structlog.processors.JSONRenderer()
                        if fmt == "json"
                        else structlog.dev.ConsoleRenderer()
                    ),
                ],
                context_class=dict,
                logger_factory=structlog.stdlib.LoggerFactory(),
                wrapper_class=structlog.stdlib.BoundLogger,
                cache_logger_on_first_use=True,
            )
            _LOGGER = structlog.get_logger(name)
        except ImportError:
            _LOGGER = _raw_log
    return _LOGGER


# ============================================================================
# 4. Import statis untuk semua komponen yang diperlukan (wajib)
# ============================================================================

# Import konfigurasi dan komponen kernel (wajib)
try:
    from config.loader_yaml import initialize as init_config
    from kernel.audit_hook_injector import get_audit_hook_injector
    from kernel.circuit_breaker import get_circuit_breaker_registry
    from kernel.command_dispatcher import get_command_dispatcher
    from kernel.command_handler_registry import get_handler_registry
    from kernel.context_holder import get_context_holder
    from kernel.dependency_injector import get_dependency_injector
    from kernel.distributed_lock_redis import get_distributed_lock
    from kernel.health_indicator import get_kernel_health_indicator_sync
    from kernel.lifecycle_listener import get_lifecycle_listener
    from kernel.metric_collector import get_metric_collector
    from kernel.retry_policy import get_retry_policy
    from kernel.sealed_gate import get_sealed_gate
    from kernel.transactional_executor import get_transactional_executor
    from kernel.validation_pipeline import get_validation_pipeline
except ImportError as exc:
    _raw_log.critical(f"Kernel component import failed: {exc}")
    sys.exit(1)

# Import infrastruktur (wajib)
try:
    from infrastructure.caching.redis_manager import close as close_redis
    from infrastructure.caching.redis_manager import get_redis_client
    from infrastructure.database.session_factory_sqlalchemy import create_session_factory, dispose
    from bootstrap.dependency_container.ioc_container import build_container
    from infrastructure.event_store.append_only_store import get_event_store
    from infrastructure.event_store.hash_chain_builder import get_hash_chain_builder
    from infrastructure.telemetry.opentelemetry_setup import setup_telemetry
    from infrastructure.telemetry.prometheus_registry import flush as flush_metrics
    from infrastructure.telemetry.structured_json_logging import setup_logging
except ImportError as exc:
    _raw_log.critical(f"Infrastructure import failed: {exc}")
    sys.exit(1)

# Import policy engine (wajib)
try:
    from policy_engine.loader_yaml import load_policies
except ImportError as exc:
    _raw_log.critical(f"Policy engine import failed: {exc}")
    sys.exit(1)

# Import event gateway (wajib)
try:
    from event_gateway.event_gate_singleton import get_instance as get_event_gate_instance
    from event_gateway.event_gate_singleton import shutdown as shutdown_event_gate
except ImportError as exc:
    _raw_log.critical(f"Event gateway import failed: {exc}")
    sys.exit(1)

# Import outbox relay (wajib)
try:
    from application.outbox.outbox_relay_service import start_relay, stop_relay
except ImportError as exc:
    _raw_log.critical(f"Outbox relay import failed: {exc}")
    sys.exit(1)

# Import service registrar (untuk registrasi dependency)
try:
    from bootstrap.dependency_container.service_registry import ServiceRegistrar
except ImportError as exc:
    _raw_log.critical(f"ServiceRegistrar import failed: {exc}")
    sys.exit(1)

# Import middleware (opsional, tapi jika ada yang gagal tetap lanjutkan dengan warning)
try:
    from adapters.primary_api.common.fastapi_request_id_middleware import RequestIDMiddleware

    MIDDLEWARE_REQUEST_ID_AVAILABLE = True
except ImportError:
    MIDDLEWARE_REQUEST_ID_AVAILABLE = False
    _raw_log.warning("RequestIDMiddleware not available")

try:
    from adapters.primary_api.common.fastapi_audit_middleware import AuditMiddleware

    MIDDLEWARE_AUDIT_AVAILABLE = True
except ImportError:
    MIDDLEWARE_AUDIT_AVAILABLE = False
    _raw_log.warning("AuditMiddleware not available")

try:
    from adapters.primary_api.common.fastapi_rate_limit_middleware import RateLimitMiddleware

    MIDDLEWARE_RATE_LIMIT_AVAILABLE = True
except ImportError:
    MIDDLEWARE_RATE_LIMIT_AVAILABLE = False
    _raw_log.warning("RateLimitMiddleware not available")

# Import router V1 (wajib, karena API utama)
try:
    from adapters.primary_api.v1.fastapi_ap_router import router as ap_router
    from adapters.primary_api.v1.fastapi_ar_router import router as ar_router
    from adapters.primary_api.v1.fastapi_bank_cash_router import router as bank_cash_router
    from adapters.primary_api.v1.fastapi_coa_router import router as coa_router
    from adapters.primary_api.v1.fastapi_fixed_asset_router import router as fixed_asset_router
    from adapters.primary_api.v1.fastapi_inventory_router import router as inventory_router
    from adapters.primary_api.v1.fastapi_journal_router import router as journal_router
    from adapters.primary_api.v1.fastapi_ledger_router import router as ledger_router
    from adapters.primary_api.v1.fastapi_report_router import router as report_router
    from adapters.primary_api.v1.fastapi_tax_coretax_router import router as tax_router
except ImportError as exc:
    _raw_log.critical(f"Router V1 import failed: {exc}")
    sys.exit(1)

# ============================================================================
# 5. IoC Container singleton (agar bisa diakses di lifespan)
# ============================================================================

_CONTAINER = None


def _get_container():
    global _CONTAINER
    if _CONTAINER is None:
        _CONTAINER = build_container()
    return _CONTAINER


# ============================================================================
# 6. Lifespan (startup & shutdown) dengan inisialisasi komponen
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifecycle manager: startup sebelum server mulai, shutdown setelah server berhenti."""
    logger = get_logger()
    logger.info("=" * 60)
    logger.info(
        f"{get_config('app.name', 'ERP Accounting Engine')} v{get_config('app.version', '2.0.0')} — STARTUP",
        env=get_config("app.env", "development"),
    )
    logger.info("=" * 60)
    start_ts = time.monotonic()
    startup_errors = 0

    # Inisialisasi komponen secara berurutan (semua wajib sukses)
    try:
        init_config()
        logger.info("✅ Config Loader")
    except Exception as exc:
        logger.error(f"❌ Config Loader — {type(exc).__name__}: {exc}")
        startup_errors += 1

    try:
        await create_session_factory()
        logger.info("✅ Database Session")
    except Exception as exc:
        logger.error(f"❌ Database Session — {type(exc).__name__}: {exc}")
        startup_errors += 1

    try:
        await get_redis_client()
        logger.info("✅ Redis Manager")
    except Exception as exc:
        logger.error(f"❌ Redis Manager — {type(exc).__name__}: {exc}")
        startup_errors += 1

    try:
        container = _get_container()  # inisialisasi container
        logger.info("✅ IoC Container")
    except Exception as exc:
        logger.error(f"❌ IoC Container — {type(exc).__name__}: {exc}")
        startup_errors += 1

    # ==================== REGISTRASI SEMUA SERVICE KE CONTAINER ====================
    try:
        await ServiceRegistrar.register_all()
        logger.info("✅ Service Registrations (including outbox_repository)")
    except Exception as exc:
        logger.error(f"❌ Service Registration — {type(exc).__name__}: {exc}")
        startup_errors += 1
    # ============================================================================

    try:
        load_policies()
        logger.info("✅ Policy Engine")
    except Exception as exc:
        logger.error(f"❌ Policy Engine — {type(exc).__name__}: {exc}")
        startup_errors += 1

    try:
        get_sealed_gate()
        logger.info("✅ Kernel SealedGate")
    except Exception as exc:
        logger.error(f"❌ Kernel SealedGate — {type(exc).__name__}: {exc}")
        startup_errors += 1

    try:
        get_event_gate_instance()
        logger.info("✅ Event Gateway")
    except Exception as exc:
        logger.error(f"❌ Event Gateway — {type(exc).__name__}: {exc}")
        startup_errors += 1

    # ==================== OUTBOX RELAY (menggunakan dependency yang sudah terdaftar) ====================
    try:
        container = _get_container()

        # Fungsi helper untuk resolve dependency secara async (dari container yang sudah terisi)
        async def resolve_async_dependency(dep_name: str):
            # Coba berbagai cara yang umum digunakan di container
            if hasattr(container, "resolve_async"):
                return await container.resolve_async(dep_name)
            elif hasattr(container, "aget"):
                return await container.aget(dep_name)
            elif hasattr(container, "get"):
                # Jika container.get adalah async callable
                if callable(container.get) and asyncio.iscoroutinefunction(container.get):
                    return await container.get(dep_name)
                else:
                    return container.get(dep_name)
            else:
                # Fallback terakhir: coba langsung attribute (mungkin sync)
                attr = getattr(container, dep_name, None)
                if attr is None:
                    raise RuntimeError(f"Dependency {dep_name} tidak ditemukan di container")
                if callable(attr):
                    return attr() if not asyncio.iscoroutinefunction(attr) else await attr()
                return attr

        outbox_repo = await resolve_async_dependency("outbox_repository")
        message_broker = await resolve_async_dependency("message_broker")

        # Inject session_factory ke outbox_repo agar relay loop bisa membuat
        # session baru per-batch tanpa perlu session eksplisit dari luar
        try:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session_factory

            session_factory = await get_async_session_factory()
            if hasattr(outbox_repo, "set_session_factory") and session_factory is not None:
                outbox_repo.set_session_factory(session_factory)
                logger.info("✅ Outbox Relay — session_factory injected")
        except Exception as sf_exc:
            logger.warning(f"⚠️ Outbox Relay — session_factory tidak tersedia: {sf_exc}")

        await start_relay(outbox_repository=outbox_repo, message_broker=message_broker)
        logger.info("✅ Outbox Relay")
    except Exception as exc:
        logger.error(f"❌ Outbox Relay — {type(exc).__name__}: {exc}")
        startup_errors += 1
    # ==============================================================================

    # Telemetry opsional, tapi gagal tidak dianggap fatal
    try:
        setup_telemetry()
        logger.info("✅ Telemetry (OpenTelemetry)")
    except Exception as exc:
        logger.warning(f"⚠️ Telemetry setup failed: {exc}")

    elapsed = time.monotonic() - start_ts
    if startup_errors == 0:
        logger.info(f"Startup selesai — semua komponen aktif ({elapsed:.2f}s).")
    else:
        logger.warning(
            f"Startup selesai dengan {startup_errors} error dalam {elapsed:.2f}s. Sistem berjalan terbatas."
        )

    app.state.started_at = time.time()
    app.state.startup_errors = startup_errors

    yield  # Aplikasi berjalan

    # ---------- SHUTDOWN ----------
    logger.info("=" * 60)
    logger.info(f"{get_config('app.name', 'ERP Accounting Engine')} — SHUTDOWN graceful ...")
    logger.info("=" * 60)

    try:
        await stop_relay()
        logger.info("🔒 Outbox Relay — ditutup")
    except Exception:
        pass

    try:
        # shutdown_event_gate mungkin async, jadi perlu await jika coroutine
        if asyncio.iscoroutinefunction(shutdown_event_gate):
            await shutdown_event_gate()
        else:
            shutdown_event_gate()
        logger.info("🔒 Event Gateway — ditutup")
    except Exception:
        pass

    try:
        await close_redis()
        logger.info("🔒 Redis Manager — ditutup")
    except Exception:
        pass

    try:
        # dispose mungkin async
        if asyncio.iscoroutinefunction(dispose):
            await dispose()
        else:
            dispose()
        logger.info("🔒 Database Pool — ditutup")
    except Exception:
        pass

    try:
        # flush_metrics mungkin async
        if asyncio.iscoroutinefunction(flush_metrics):
            await flush_metrics()
        else:
            flush_metrics()
        logger.info("🔒 Telemetry — flushed")
    except Exception:
        pass

    logger.info("Shutdown selesai.")


# ============================================================================
# 7. Middleware (CORS, GZip, dan Registrasi Custom Middleware)
# ============================================================================


def _add_middleware(app: FastAPI) -> None:
    """Pasang middleware global."""
    logger = get_logger()

    # GZip compression untuk response > 1KB
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    # CORS
    cors_origins_str = get_config("api.cors_origins", "http://localhost:3000,http://localhost:8000")
    cors_origins = [o.strip() for o in cors_origins_str.split(",") if o.strip()]
    # Tambahkan origin untuk Tauri frontend dan Live Server
    extra_origins = [
        "tauri://localhost",
        "http://127.0.0.1:1420",
        "http://localhost:1420",
        "http://127.0.0.1:5500",  # Live Server default
        "http://localhost:5500",
    ]
    list(set(cors_origins + extra_origins))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Correlation-ID"],
    )

    # Custom middleware (hanya jika tersedia)
    if MIDDLEWARE_REQUEST_ID_AVAILABLE:
        app.add_middleware(RequestIDMiddleware)
        logger.debug("Middleware RequestIDMiddleware berhasil didaftarkan")
    else:
        logger.warning("RequestIDMiddleware tidak tersedia (skip)")

    if MIDDLEWARE_AUDIT_AVAILABLE:
        app.add_middleware(AuditMiddleware)
        logger.debug("Middleware AuditMiddleware berhasil didaftarkan")
    else:
        logger.warning("AuditMiddleware tidak tersedia (skip)")

    if MIDDLEWARE_RATE_LIMIT_AVAILABLE:
        app.add_middleware(RateLimitMiddleware)
        logger.debug("Middleware RateLimitMiddleware berhasil didaftarkan")
    else:
        logger.warning("RateLimitMiddleware tidak tersedia (skip)")


# ============================================================================
# 8. Exception handlers global
# ============================================================================


def _add_exception_handlers(app: FastAPI) -> None:
    """Pasang handler untuk exception umum."""
    logger = get_logger()

    @app.exception_handler(Exception)
    async def handle_unhandled(request: Request, exc: Exception) -> JSONResponse:
        corr = getattr(request.state, "correlation_id", "unknown")
        logger.error(
            f"Unhandled {type(exc).__name__} on {request.url.path} | corr={corr}", exc_info=exc
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "message": "Terjadi kesalahan internal pada server.",
                "correlation_id": corr,
            },
        )

    @app.exception_handler(404)
    async def handle_404(request: Request, exc: Any) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": f"Path tidak ditemukan: {request.url.path}"},
        )

    @app.exception_handler(405)
    async def handle_405(request: Request, exc: Any) -> JSONResponse:
        return JSONResponse(
            status_code=405,
            content={
                "error": "method_not_allowed",
                "message": f"Method {request.method} tidak diizinkan",
            },
        )


# ============================================================================
# 9. Endpoint sistem (root, health, metrics, version) — tanpa dynamic import
# ============================================================================


def _add_system_endpoints(app: FastAPI) -> None:
    """Tambahkan endpoint yang selalu tersedia tanpa dependensi domain."""
    logger = get_logger()

    @app.get("/", tags=["System"])
    async def root() -> dict:
        return {
            "app": get_config("app.name", "ERP Accounting Engine"),
            "version": get_config("app.version", "2.0.0"),
            "env": get_config("app.env", "development"),
            "docs": "/docs",
            "health": "/health",
            "metrics": "/metrics",
        }

    @app.get("/health", tags=["System"])
    async def health_check(request: Request) -> JSONResponse:
        uptime = time.time() - getattr(request.app.state, "started_at", time.time())
        errors = getattr(request.app.state, "startup_errors", 0)
        status = "healthy" if errors == 0 else "degraded"
        code = 200 if errors == 0 else 503
        return JSONResponse(
            status_code=code,
            content={
                "status": status,
                "app": get_config("app.name", "ERP Accounting Engine"),
                "version": get_config("app.version", "2.0.0"),
                "env": get_config("app.env", "development"),
                "uptime_seconds": round(uptime, 1),
                "startup_errors": errors,
            },
        )

    @app.get("/readiness", include_in_schema=False)
    async def readiness(request: Request) -> Response:
        errors = getattr(request.app.state, "startup_errors", 0)
        return Response(
            content="OK" if errors == 0 else "DEGRADED", status_code=200 if errors == 0 else 503
        )

    @app.get("/liveness", include_in_schema=False)
    async def liveness() -> Response:
        return Response(content="OK", status_code=200)

    @app.get("/version", tags=["System"])
    async def version_info() -> dict:
        return {
            "app": get_config("app.name", "ERP Accounting Engine"),
            "version": get_config("app.version", "2.0.0"),
            "env": get_config("app.env", "development"),
            "python": sys.version,
        }

    # Metrics (Prometheus) jika tersedia (import statis)
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        @app.get("/metrics", tags=["System"])
        async def metrics() -> Response:
            return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

        logger.info("Prometheus metrics endpoint aktif di /metrics")
    except ImportError:

        @app.get("/metrics", tags=["System"])
        async def metrics_not_available() -> JSONResponse:
            return JSONResponse(
                status_code=501,
                content={
                    "error": "prometheus_not_installed",
                    "message": "Prometheus client tidak terinstall",
                },
            )

        logger.warning("Prometheus client tidak terinstall, endpoint /metrics tidak aktif")


# ============================================================================
# 10. Daftarkan semua router domain (API v1) — statis
# ============================================================================


def _register_domain_routers(app: FastAPI) -> None:
    """Pasang semua router API versi 1."""
    app.include_router(journal_router, prefix="/api/v1/journals", tags=["Journal"])
    app.include_router(ledger_router, prefix="/api/v1/ledger", tags=["Ledger"])
    app.include_router(coa_router, prefix="/api/v1/coa", tags=["Chart of Accounts"])
    app.include_router(ar_router, prefix="/api/v1/ar", tags=["Accounts Receivable"])
    app.include_router(ap_router, prefix="/api/v1/ap", tags=["Accounts Payable"])
    app.include_router(inventory_router, prefix="/api/v1/inventory", tags=["Inventory"])
    app.include_router(fixed_asset_router, prefix="/api/v1/fixed-assets", tags=["Fixed Assets"])
    app.include_router(bank_cash_router, prefix="/api/v1/bank-cash", tags=["Bank & Cash"])
    app.include_router(tax_router, prefix="/api/v1/tax", tags=["Tax & Coretax"])
    app.include_router(report_router, prefix="/api/v1/reports", tags=["Reports"])
    logger = get_logger()
    logger.info("[routers] 10 router V1 berhasil didaftarkan")


# ============================================================================
# 11. Custom OpenAPI schema dengan security JWT
# ============================================================================


def _custom_openapi(app: FastAPI):
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=get_config("app.name", "ERP Accounting Engine"),
        version=get_config("app.version", "2.0.0"),
        description="ERP Accounting Engine — Bank-Grade Accounting System\nDDD · CQRS · Event Sourcing · Hexagonal Architecture\nStandar: PSAK, IFRS, Coretax DJP, SOX, OJK",
        routes=app.routes,
    )
    schema.setdefault("components", {}).setdefault("securitySchemes", {})
    schema["components"]["securitySchemes"]["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "Masukkan token JWT yang didapat dari endpoint login",
    }
    schema["security"] = [{"BearerAuth": []}]
    app.openapi_schema = schema
    return schema


# ============================================================================
# 12. Application factory
# ============================================================================


def create_application() -> FastAPI:
    """Factory untuk membuat instance FastAPI yang sudah dikonfigurasi."""
    env = get_config("app.env", "development")
    is_production = env == "production"

    app = FastAPI(
        title=get_config("app.name", "ERP Accounting Engine"),
        version=get_config("app.version", "2.0.0"),
        description="Bank-Grade Accounting System",
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
        debug=not is_production,
        lifespan=lifespan,
    )

    # Pasang komponen
    _add_middleware(app)
    _add_exception_handlers(app)
    _add_system_endpoints(app)
    _register_domain_routers(app)
    app.openapi = lambda: _custom_openapi(app)  # type: ignore

    logger = get_logger()
    logger.info(
        f"[asgi] {get_config('app.name', 'ERP Accounting Engine')} v{get_config('app.version', '2.0.0')} "
        f"dikonfigurasi (env={env}, docs={'nonaktif' if is_production else '/docs'})"
    )
    return app


# ============================================================================
# 13. ASGI app instance (export 'app' untuk uvicorn/gunicorn)
# ============================================================================

app = create_application()
