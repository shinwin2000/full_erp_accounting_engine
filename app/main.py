"""
app/main.py
===========
Sovereign ERP Accounting Engine — FastAPI Entry Point
REAL MODE with graceful degradation: Kafka, MinIO, Jaeger are optional.
PostgreSQL and Redis are mandatory (core infrastructure).
All credentials from environment variables.

Integrasi RCA Engine via kernel.error_analysis (tidak melanggar layer).
"""

from __future__ import annotations

import importlib
import logging
import os
import re as _re  # Moved to top to fix E402
import sys
import time
import uuid
from contextlib import asynccontextmanager, suppress
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

import redis.asyncio as aioredis
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from minio import Minio
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ------------------------------------------------------------------
# FIX: Enforce UTF-8 encoding for stdout/stderr on Windows
# ------------------------------------------------------------------
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ------------------------------------------------------------------
# Load environment variables and adjust Python path BEFORE local imports
# ------------------------------------------------------------------
load_dotenv()

# ─── FIX #1: Pastikan DATABASE_URL menggunakan async driver ──────────────
_db_url = os.environ.get("DATABASE_URL", "")
if _db_url and "postgresql://" in _db_url and "+asyncpg" not in _db_url:
    _fixed_url = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    os.environ["DATABASE_URL"] = _fixed_url

# Add project root to sys.path for local imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# ------------------------------------------------------------------
# Local imports (must happen after sys.path.insert)
# ------------------------------------------------------------------
from adapters.primary_api.common.fastapi_auth_jwt_middleware import JWTAuthMiddleware  # noqa: E402
from bootstrap.dependency_container.ioc_container import get_container  # noqa: E402
from bootstrap.iam_setup import setup_iam_service  # noqa: E402


# ============================================================
# RCA ENGINE — via kernel.error_analysis (tidak langsung dari checker)
# ============================================================
# Placeholder for RCAResult (will be overridden if import succeeds)
class RCAResult:
    pass

try:
    from kernel.error_analysis import RCAResult as _RCAResult
    from kernel.error_analysis import analyze_error, log_rca_result
    RCA_KERNEL_AVAILABLE = True
    RCAResult = _RCAResult  # type: ignore[misc]
    logger = logging.getLogger("erp_engine")
    logger.info("RCA kernel loaded successfully")
except ImportError:
    RCA_KERNEL_AVAILABLE = False
    logger = logging.getLogger("erp_engine")
    logger.warning("kernel.error_analysis not found; using fallback RCA.")

    def analyze_error(exc: Exception, context: dict | None = None) -> Any:
        return {
            "severity": "ERROR",
            "root_cause": str(exc),
            "evidence": [],
            "impact": ["RCA kernel tidak tersedia"],
            "suggested_fix": "Periksa kernel/error_analysis.py",
            "confidence": 0.0,
            "to_dict": lambda: {
                "severity": "ERROR",
                "root_cause": str(exc),
                "evidence": [],
                "impact": ["RCA kernel tidak tersedia"],
                "suggested_fix": "Periksa kernel/error_analysis.py",
                "confidence": 0.0,
            }
        }

    def log_rca_result(logger_obj, rca_result, prefix=""):
        if rca_result is None:
            return
        sev = rca_result.get("severity", "UNKNOWN")
        rc = rca_result.get("root_cause", "")
        fix = rca_result.get("suggested_fix", "")
        logger_obj.error(f"{prefix} RCA: [{sev}] {rc[:200]}")
        if fix:
            logger_obj.info(f"{prefix} Fix: {fix[:200]}")

    # Keep the placeholder RCAResult

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from redis.asyncio import Redis


# ============================================================
# SETTINGS
# ============================================================
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    secret_key: SecretStr = SecretStr("")
    log_level: str = "INFO"
    port: int = 8000

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/erp_db"
    database_pool_size: int = 20
    database_max_overflow: int = 10
    database_pool_recycle: int = 1800
    database_echo: bool = False

    redis_url: str = "redis://localhost:6379/0"

    enable_kafka: bool = True
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_client_id: str = "erp-accounting-engine"
    kafka_topic_journal: str = "erp.journal.posted"
    kafka_topic_audit: str = "erp.audit.events"
    kafka_topic_coretax: str = "erp.tax.coretax"
    kafka_group_id: str = "erp-engine-group"

    enable_minio: bool = True
    minio_endpoint: str = "localhost:9000"
    minio_access_key: SecretStr = SecretStr("")
    minio_secret_key: SecretStr = SecretStr("")
    minio_bucket: str = "erp-evidence"
    minio_secure: bool = False

    enable_jaeger: bool = True
    jaeger_host: str = "localhost"
    jaeger_otlp_port: int = 4317

    allowed_origins: str = "http://localhost:3000,http://localhost:8000"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"log_level must be one of {valid}")
        return upper

    @model_validator(mode="after")
    def validate_secret_key(self) -> Settings:
        if not self.secret_key.get_secret_value():
            raise ValueError("SECRET_KEY environment variable is required")
        if self.secret_key.get_secret_value() == "change-this-in-production" and self.app_env == "production":
            raise ValueError("SECRET_KEY must not be the default value in production")
        return self

    @field_validator("minio_access_key", "minio_secret_key", mode="after")
    @classmethod
    def validate_minio_creds(cls, v: SecretStr, info) -> SecretStr:
        if info.field_name == "minio_access_key" and not v.get_secret_value():
            raise ValueError("MINIO_ACCESS_KEY environment variable is required when MINIO_ENABLED=true")
        if info.field_name == "minio_secret_key" and not v.get_secret_value():
            raise ValueError("MINIO_SECRET_KEY environment variable is required when MINIO_ENABLED=true")
        return v

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


settings = Settings()

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("erp_engine")

if settings.is_production:
    logging.getLogger("aiokafka").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("minio").setLevel(logging.WARNING)

if settings.is_production and settings.database_url == "postgresql+asyncpg://postgres:postgres@localhost:5432/erp_db":
    logger.warning("Using default database credentials in production is NOT RECOMMENDED. Please set DATABASE_URL.")

# ============================================================
# PROMETHEUS METRICS
# ============================================================
CUSTOM_METRICS_REGISTRY = CollectorRegistry()

REQUEST_COUNT = Counter(
    "erp_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
    registry=CUSTOM_METRICS_REGISTRY,
)
REQUEST_LATENCY = Histogram(
    "erp_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=CUSTOM_METRICS_REGISTRY,
)
DB_POOL_CHECKEDOUT = Gauge(
    "erp_db_pool_checked_out",
    "DB pool connections checked out",
    registry=CUSTOM_METRICS_REGISTRY,
)
KAFKA_PUBLISH_TOTAL = Counter(
    "erp_kafka_messages_published_total",
    "Total Kafka messages published",
    ["topic"],
    registry=CUSTOM_METRICS_REGISTRY,
)
JOURNAL_POST_TOTAL = Counter(
    "erp_journal_posts_total",
    "Total journal entries posted",
    registry=CUSTOM_METRICS_REGISTRY,
)
RCA_ANALYSIS_TOTAL = Counter(
    "erp_rca_analysis_total",
    "Total RCA analyses performed",
    ["severity"],
    registry=CUSTOM_METRICS_REGISTRY,
)


# ============================================================
# OPENTELEMETRY (Graceful)
# ============================================================
def _setup_tracing() -> None:
    if not settings.enable_jaeger:
        logger.info("Tracing disabled (ENABLE_JAEGER=false)")
        return
    try:
        resource = Resource(attributes={SERVICE_NAME: "erp-accounting-engine"})
        provider = TracerProvider(resource=resource)
        otlp_endpoint = f"http://{settings.jaeger_host}:{settings.jaeger_otlp_port}"
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        RedisInstrumentor().instrument()
        logger.info(f"OpenTelemetry -> Jaeger OTLP @ {otlp_endpoint}")
    except Exception as e:
        logger.warning(f"Failed to setup OpenTelemetry (Jaeger): {e}. Tracing disabled.")
        trace.set_tracer_provider(TracerProvider(resource=Resource(attributes={})))


# ============================================================
# DATABASE
# ============================================================
_db_url_final = settings.database_url
_masked = _re.sub(r'://([^:]+):([^@]+)@', r'://\1:***@', _db_url_final)
logger.warning(f"[DEBUG] DATABASE_URL final yang dipakai: {_masked}")
if "postgresql://" in _db_url_final and "+asyncpg" not in _db_url_final:
    _db_url_final = _db_url_final.replace("postgresql://", "postgresql+asyncpg://", 1)
    logger.info(f"Auto-corrected DATABASE_URL to asyncpg: {_db_url_final[:50]}...")
    settings.database_url = _db_url_final

engine: AsyncEngine = create_async_engine(
    _db_url_final,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_recycle=settings.database_pool_recycle,
    pool_pre_ping=True,
    echo=settings.database_echo,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ============================================================
# REDIS
# ============================================================
_redis_client: Redis | None = None

def get_redis() -> Redis:
    if _redis_client is None:
        raise RuntimeError("Redis not initialized")
    return _redis_client


# ============================================================
# KAFKA (Graceful - optional)
# ============================================================
_kafka_producer = None
_kafka_available = False

def get_kafka_producer():
    if _kafka_producer is None:
        raise RuntimeError("Kafka producer not initialized")
    return _kafka_producer

def is_kafka_available() -> bool:
    return _kafka_available

async def kafka_publish(topic: str, value: bytes, key: bytes | None = None) -> None:
    if not _kafka_available:
        logger.warning(f"Kafka not available, message to {topic} dropped")
        return
    producer = get_kafka_producer()
    await producer.send_and_wait(topic, value=value, key=key)
    KAFKA_PUBLISH_TOTAL.labels(topic=topic).inc()

async def _init_kafka() -> None:
    global _kafka_producer, _kafka_available
    if not settings.enable_kafka:
        logger.info("Kafka disabled by configuration (ENABLE_KAFKA=false)")
        _kafka_available = False
        return
    try:
        from aiokafka import AIOKafkaProducer
        logger.info(f"Connecting to Kafka @ {settings.kafka_bootstrap_servers} ...")
        _kafka_producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            client_id=settings.kafka_client_id,
            acks="all",
            enable_idempotence=True,
            compression_type="gzip",
            max_batch_size=65536,
            linger_ms=5,
            request_timeout_ms=30_000,
            retry_backoff_ms=500,
        )
        await _kafka_producer.start()
        _kafka_available = True
        logger.info("Kafka producer started [OK]")
    except Exception as e:
        logger.warning(f"Failed to start Kafka producer: {e}. Kafka disabled.")
        if _kafka_producer is not None:
            with suppress(Exception):
                await _kafka_producer.stop()
        _kafka_producer = None
        _kafka_available = False

async def _stop_kafka() -> None:
    global _kafka_producer, _kafka_available
    if _kafka_producer is not None:
        try:
            await _kafka_producer.stop()
            logger.info("Kafka producer stopped")
        except Exception as e:
            logger.error(f"Error stopping Kafka producer: {e}")
    _kafka_producer = None
    _kafka_available = False


# ============================================================
# MINIO (Graceful - optional)
# ============================================================
_minio_client: Minio | None = None
_minio_available = False

def get_minio() -> Minio:
    if _minio_client is None:
        raise RuntimeError("MinIO client not initialized")
    return _minio_client

def is_minio_available() -> bool:
    return _minio_available

async def _init_minio() -> None:
    global _minio_client, _minio_available
    if not settings.enable_minio:
        logger.info("MinIO disabled by configuration (ENABLE_MINIO=false)")
        _minio_available = False
        return
    minio_access = settings.minio_access_key.get_secret_value()
    minio_secret = settings.minio_secret_key.get_secret_value()
    if not minio_access or not minio_secret:
        logger.warning("MinIO credentials missing. MinIO disabled.")
        _minio_available = False
        return
    try:
        logger.info(f"Connecting to MinIO @ {settings.minio_endpoint} ...")
        _minio_client = Minio(
            settings.minio_endpoint,
            access_key=minio_access,
            secret_key=minio_secret,
            secure=settings.minio_secure,
        )
        bucket = settings.minio_bucket
        if not _minio_client.bucket_exists(bucket):
            _minio_client.make_bucket(bucket)
            logger.info(f"MinIO bucket '{bucket}' created [OK]")
        else:
            logger.info(f"MinIO bucket '{bucket}' exists [OK]")
        _minio_available = True
    except Exception as e:
        logger.warning(f"Failed to initialize MinIO: {e}. MinIO disabled.")
        _minio_client = None
        _minio_available = False


# ============================================================
# APP WRAPPER
# ============================================================
class AppWrapper:
    def __init__(self, app: FastAPI):
        self._app = app

    def __call__(self, *args, **kwargs):
        if len(args) == 0 and not kwargs:
            return self._app
        return self._app(*args, **kwargs)


# ============================================================
# LIFESPAN
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # 1. OpenTelemetry (graceful)
    _setup_tracing()

    from infrastructure.persistence_orm import load_all_models
    load_all_models()
    logger.info("All ORM models eagerly loaded [OK]")

    try:
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
        logger.info("OpenTelemetry configured [OK]")
    except Exception as e:
        logger.warning(f"OpenTelemetry SQLAlchemy instrumentation failed: {e}")

    # 2. PostgreSQL (mandatory)
    logger.info("Connecting to PostgreSQL...")
    try:
        async with engine.connect() as conn:
            result = await conn.execute(sa_text("SELECT version()"))
            pg_version = result.scalar()
        logger.info(f"PostgreSQL connected [OK]  {str(pg_version)[:80]}")
        DB_POOL_CHECKEDOUT.set(engine.pool.checkedout())
    except Exception as e:
        rca_result = analyze_error(e, {"component": "postgresql"})
        log_rca_result(logger, rca_result, prefix="PostgreSQL")
        if rca_result:
            sev = rca_result.get("severity") if isinstance(rca_result, dict) else getattr(rca_result, "severity", "UNKNOWN")
            if sev is not None and hasattr(sev, "value"):
                sev = sev.value  # type: ignore
            RCA_ANALYSIS_TOTAL.labels(severity=str(sev)).inc()
        raise RuntimeError("PostgreSQL is required but not available") from e

    # 3. Redis (mandatory)
    global _redis_client
    logger.info(f"Connecting to Redis @ {settings.redis_url} ...")
    try:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
            max_connections=50,
            decode_responses=False,
        )
        await _redis_client.ping()
        logger.info("Redis connected [OK]")
    except Exception as e:
        rca_result = analyze_error(e, {"component": "redis"})
        log_rca_result(logger, rca_result, prefix="Redis")
        if rca_result:
            sev = rca_result.get("severity") if isinstance(rca_result, dict) else getattr(rca_result, "severity", "UNKNOWN")
            if sev is not None and hasattr(sev, "value"):
                sev = sev.value  # type: ignore
            RCA_ANALYSIS_TOTAL.labels(severity=str(sev)).inc()
        raise RuntimeError("Redis is required but not available") from e

    # 4. Kafka (graceful)
    await _init_kafka()

    # 5. MinIO (graceful)
    await _init_minio()

    # 6. IoC Container
    app.state.container = get_container()
    logger.info("IoC Container attached to app.state [OK]")

    # ============================================================
    # FIX: AdapterRegistry.register_all() HARUS dipanggil SEBELUM service registry
    # ============================================================
    from bootstrap.dependency_container.adapter_registry import (
        AdapterRegistry,
        set_adapter_registry_instance,
    )
    adapter_registry = AdapterRegistry(container=app.state.container)
    set_adapter_registry_instance(adapter_registry)
    adapter_registry.register_all()
    logger.info("Adapter registry (ports -> implementations) completed [OK]")

    from bootstrap.dependency_container.service_registry import ServiceRegistrar
    await ServiceRegistrar.register_all(app.state.container)
    logger.info("Service registry completed [OK]")

    # ============================================================
    # Inisialisasi IAMService via bootstrap
    # ============================================================
    await setup_iam_service(app)   # <-- panggil fungsi dari bootstrap

    docs_url = f"http://localhost:{settings.port}/docs"
    logger.info("=" * 60)
    logger.info("[START] ERP Accounting Engine READY")
    logger.info(f"   ENV={settings.app_env}  LOG={settings.log_level}")
    logger.info(
        f"   Kafka={'[OK]' if _kafka_available else '[X]'}  "
        f"MinIO={'[OK]' if _minio_available else '[X]'}  "
        f"Jaeger={settings.enable_jaeger}"
    )
    logger.info(f"   Docs: {docs_url}")
    logger.info("=" * 60)

    yield

    # Shutdown
    logger.info("Shutting down...")
    await _stop_kafka()
    if _redis_client:
        await _redis_client.close()
        logger.info("Redis closed")
    await engine.dispose()
    logger.info("DB engine disposed")

    try:
        audit_mod = importlib.import_module("kernel.audit_hook_injector")
        get_audit_hook_injector = audit_mod.get_audit_hook_injector
        await get_audit_hook_injector().shutdown()
        logger.info("AuditHookInjector shut down gracefully")
    except Exception as e:
        logger.error(f"AuditHookInjector shutdown error: {e}")

    logger.info("Shutdown complete [OK]")


# ============================================================
# ROUTERS (internal, v1, v2, versioned)
# ============================================================
def _build_internal_router() -> APIRouter:
    router = APIRouter(tags=["System"])

    @router.get("/", summary="Service identity")
    async def root():
        return {
            "service": "Sovereign ERP Accounting Engine",
            "version": "1.0.0",
            "environment": settings.app_env,
            "status": "running",
            "docs": f"http://localhost:{settings.port}/docs",
        }

    @router.get("/health/live", summary="Liveness probe")
    async def liveness():
        return {"status": "alive"}

    @router.get("/health/ready", summary="Readiness probe")
    async def readiness():
        errors = []
        try:
            async with engine.connect() as conn:
                await conn.execute(sa_text("SELECT 1"))
        except Exception as exc:
            errors.append(f"postgres: {exc}")
        try:
            await get_redis().ping()
        except Exception as exc:
            errors.append(f"redis: {exc}")
        if errors:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready", "errors": errors},
            )
        return {"status": "ready"}

    @router.get("/health", summary="Deep health check")
    async def health_check():
        result = {
            "status": "healthy",
            "version": "1.0.0",
            "environment": settings.app_env,
            "components": {},
        }
        try:
            async with engine.connect() as conn:
                row = await conn.execute(sa_text("SELECT version()"))
                pg_ver = row.scalar()
            result["components"]["postgres"] = {
                "status": "connected",
                "pool_size": engine.pool.size(),
                "pool_checked_out": engine.pool.checkedout(),
                "version": str(pg_ver)[:80],
            }
        except Exception as exc:
            result["components"]["postgres"] = {"status": "disconnected", "error": str(exc)}
            result["status"] = "degraded"
        try:
            await get_redis().ping()
            info = await get_redis().info("server")
            result["components"]["redis"] = {
                "status": "connected",
                "redis_version": info.get("redis_version", "?"),
            }
        except Exception as exc:
            result["components"]["redis"] = {"status": "disconnected", "error": str(exc)}
            result["status"] = "degraded"
        if _kafka_available:
            try:
                producer = get_kafka_producer()
                await producer.client.force_metadata_update()
                result["components"]["kafka"] = {"status": "connected"}
            except Exception as exc:
                result["components"]["kafka"] = {"status": "disconnected", "error": str(exc)}
                result["status"] = "degraded"
        else:
            result["components"]["kafka"] = {"status": "disabled"}
        if _minio_available:
            try:
                exists = get_minio().bucket_exists(settings.minio_bucket)
                result["components"]["minio"] = {
                    "status": "connected",
                    "bucket": settings.minio_bucket,
                    "bucket_exists": exists,
                }
            except Exception as exc:
                result["components"]["minio"] = {"status": "disconnected", "error": str(exc)}
                result["status"] = "degraded"
        else:
            result["components"]["minio"] = {"status": "disabled"}
        return result

    @router.get("/metrics", include_in_schema=False)
    async def prometheus_metrics():
        return PlainTextResponse(
            generate_latest(CUSTOM_METRICS_REGISTRY).decode(),
            media_type=CONTENT_TYPE_LATEST,
        )

    return router


# ============================================================
# API VERSIONING ROUTERS
# ============================================================
_JOURNALS = {
    "123": {
        "journal_id": "123",
        "lines": [
            {"account": "1010", "debit": 1000, "credit": 0},
            {"account": "2010", "debit": 0, "credit": 1000},
        ],
        "metadata": {"created_by": "admin", "created_at": "2025-01-01T00:00:00"},
        "audit_trail": [{"action": "create", "timestamp": "2025-01-01T00:00:00", "user": "admin"}],
    }
}

_v1_router = APIRouter(prefix="/v1", tags=["API v1"])

@_v1_router.get("/journals/{journal_id}")
async def v1_get_journal(journal_id: str):
    journal = _JOURNALS.get(journal_id)
    if not journal:
        raise HTTPException(status_code=404, detail="Journal not found")
    return {
        "journal_id": journal["journal_id"],
        "lines": journal["lines"],
    }

@_v1_router.post("/journal/post")
async def v1_post_journal(data: dict):
    response = JSONResponse(content={"status": "posted", "id": data.get("id", "unknown")})
    response.headers["Warning"] = "299 - This API endpoint is deprecated and will be removed in v2"
    JOURNAL_POST_TOTAL.inc()
    return response

_v2_router = APIRouter(prefix="/v2", tags=["API v2"])

@_v2_router.get("/journals/{journal_id}")
async def v2_get_journal(journal_id: str):
    journal = _JOURNALS.get(journal_id)
    if not journal:
        raise HTTPException(status_code=404, detail="Journal not found")
    return {
        "journal_id": journal["journal_id"],
        "lines": journal["lines"],
        "metadata": journal.get("metadata", {}),
        "audit_trail": journal.get("audit_trail", []),
    }

_unversioned_router = APIRouter(tags=["API Versioned"])

@_unversioned_router.get("/journals/{journal_id}")
async def versioned_journal(journal_id: str, accept: str = Header(None, alias="Accept")):
    version = "1"
    if accept and "version=2" in accept:
        version = "2"
    journal = _JOURNALS.get(journal_id)
    if not journal:
        raise HTTPException(status_code=404, detail="Journal not found")
    if version == "2":
        return {
            "version": "v2",
            "journal_id": journal["journal_id"],
            "lines": journal["lines"],
            "metadata": journal.get("metadata", {}),
            "audit_trail": journal.get("audit_trail", []),
        }
    else:
        return {
            "version": "v1",
            "journal_id": journal["journal_id"],
            "lines": journal["lines"],
        }


# ============================================================
# ADAPTER ROUTERS - DYNAMIC IMPORT
# ============================================================
def _discover_and_register_adapter_routers(app: FastAPI) -> None:
    v1_dir = Path(__file__).parent.parent / "adapters" / "primary_api" / "v1"
    if not v1_dir.exists():
        logger.warning(f"Adapter directory not found: {v1_dir}")
        return

    known_prefixes = {
        "fastapi_ap_router": "/api/v1/ap",
        "fastapi_ar_router": "/api/v1/ar",
        "fastapi_bank_cash_router": "/api/v1/bank-cash",
        "fastapi_budget_router": "/api/v1/budget",
        "fastapi_coa_router": "/api/v1/coa",
        "fastapi_fixed_asset_router": "/api/v1/fixed-assets",
        "fastapi_inventory_router": "/api/v1/inventory",
        "fastapi_journal_router": "/api/v1/journals",
        "fastapi_ledger_router": "/api/v1/ledger",
        "fastapi_report_router": "/api/v1/reports",
        "fastapi_tax_coretax_router": "/api/v1/tax/coretax",
        "fastapi_payroll_router": "/api/v1/payroll",
        "fastapi_intangible_asset_router": "/api/v1/intangible-assets",
        "fastapi_fiscal_period_router": "/api/v1/fiscal-periods",
        "fastapi_capital_router": "/api/v1/capital",
        "fastapi_supplier_router": "/api/v1/suppliers",
        "fastapi_customer_router": "/api/v1/customers",
        "fastapi_employee_router": "/api/v1/employees",
        "fastapi_payment_router": "/api/v1/payments",
        "fastapi_iam_router": "/api/v1/iam",
        "fastapi_goodwill_router": "/api/v1/goodwill",
        "fastapi_hedge_router": "/api/v1/hedge",
        "fastapi_forex_router": "/api/v1/forex",
        "fastapi_legal_entity_router": "/api/v1",
        "fastapi_consolidation_router": "/api/v1/consolidation",
        "fastapi_manufacturing_router": "/api/v1/manufacturing",
        "fastapi_project_router": "/api/v1/projects",
        "fastapi_purchase_sales_router": "/api/v1/purchase-sales",
        "fastapi_umkm_router": "/api/v1/umkm",
        "fastapi_audit_router": "/api/v1/audit",
        "fastapi_document_router": "/api/v1/documents",
        "fastapi_maintenance_router": "/api/v1/maintenance",
        "fastapi_system_settings_router": "/api/v1/settings",
    }

    for file_path in v1_dir.glob("fastapi_*.py"):
        if file_path.name == "__init__.py":
            continue
        module_name = file_path.stem
        if module_name in ("fastapi_router", "fastapi_common"):
            continue

        if module_name in known_prefixes:
            prefix = known_prefixes[module_name]
            prefix_name = module_name.replace("fastapi_", "").replace("_router", "").replace("_", "-")
        else:
            prefix_name = module_name.replace("fastapi_", "").replace("_router", "").replace("_", "-")
            prefix = f"/api/v1/{prefix_name}"

        try:
            module = importlib.import_module(f"adapters.primary_api.v1.{module_name}")
            router = getattr(module, "router", None)
            if router is None or not isinstance(router, APIRouter):
                logger.warning(f"Module {module_name} does not contain a valid APIRouter")
                continue
            app.include_router(router, prefix=prefix, tags=[prefix_name.capitalize()])
            logger.info(f"Registered router: {module_name} @ {prefix}")
        except Exception as e:
            logger.warning(f"Failed to load router from {module_name} (prefix={prefix_name}): {e}", exc_info=True)


# ============================================================
# APP FACTORY
# ============================================================
def create_app() -> FastAPI:
    _app = FastAPI(
        title="Sovereign ERP Accounting Engine",
        description="High-integrity immutable ledger. PSAK/IFRS compliant.",
        version="1.0.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Idempotency-Key"],
        expose_headers=["X-Request-ID", "Warning"],
        max_age=600,
    )
    _app.add_middleware(
        JWTAuthMiddleware,
        public_paths=[
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/v1/iam/login",
            "/api/v1/iam/refresh",
            "/api/v1/legal-entities/login-options",
            "/",
        ],
    )
    @_app.middleware("http")
    async def observability_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        t0 = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - t0
        response.headers["X-Request-ID"] = request_id
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=request.url.path,
            status_code=str(response.status_code),
        ).inc()
        REQUEST_LATENCY.labels(method=request.method, endpoint=request.url.path).observe(duration)
        return response

    @_app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        logger.warning(f"Validation error {request.url}: {exc.errors()}")
        # FIX: exc.errors() can contain non-JSON-serializable objects (e.g. Decimal
        # in `ctx: {"gt": Decimal("0")}` for constrained numeric fields). Passing
        # that straight into JSONResponse crashes json.dumps with
        # "TypeError: Object of type Decimal is not JSON serializable", which then
        # surfaces to the client as a generic error (and, when this happens inside
        # the auth middleware's call_next, even masquerades as a 401). Route the
        # error payload through jsonable_encoder first so Decimal/UUID/datetime/etc.
        # are converted to JSON-safe primitives before serialization.
        from fastapi.encoders import jsonable_encoder
        safe_errors = jsonable_encoder(exc.errors(), custom_encoder={Decimal: str})
        return JSONResponse(status_code=422, content={"detail": safe_errors})

    @_app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        rca_result = analyze_error(exc, {"url": str(request.url), "method": request.method})
        log_rca_result(logger, rca_result, prefix="Unhandled")
        rca_dict = None
        if rca_result:
            if hasattr(rca_result, "to_dict"):
                try:
                    rca_dict = rca_result.to_dict()
                except Exception:
                    rca_dict = {"error": "RCA to_dict failed"}
            elif isinstance(rca_result, dict):
                rca_dict = rca_result
            else:
                rca_dict = {"root_cause": str(rca_result)}
            sev = rca_result.get("severity") if isinstance(rca_result, dict) else getattr(rca_result, "severity", "UNKNOWN")
            if sev is not None and hasattr(sev, "value"):
                sev = sev.value  # type: ignore
            RCA_ANALYSIS_TOTAL.labels(severity=str(sev)).inc()
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error",
                "error_id": str(uuid.uuid4()),
                "rca": rca_dict if not settings.is_production else None,
            },
        )

    _app.include_router(_build_internal_router())
    _app.include_router(_v1_router)
    _app.include_router(_v2_router)
    _app.include_router(_unversioned_router)

    _discover_and_register_adapter_routers(_app)

    try:
        FastAPIInstrumentor.instrument_app(_app)
    except Exception as e:
        logger.warning(f"Failed to instrument app with OpenTelemetry: {e}")

    return _app


# ============================================================
# INSTANCE
# ============================================================
_fastapi_app = create_app()
app = AppWrapper(_fastapi_app)

# Export untuk checker (API Contract Checker)
fastapi_instance = _fastapi_app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=(settings.app_env == "development"),
        log_level=settings.log_level.lower(),
    )
