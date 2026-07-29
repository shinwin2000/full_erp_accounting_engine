"""
Unit test untuk app/main.py
Menggunakan pytest, mock, dan FastAPI TestClient.
Semua koneksi eksternal (DB, Redis, Kafka, MinIO, OpenTelemetry) dimock.
"""

import json
import os
import sys
import warnings
from unittest.mock import AsyncMock, MagicMock, patch

# ============================================================
# SET ENVIRONMENT VARIABLES SEBELUM IMPORT APP.MAIN
# ============================================================
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENABLE_MINIO", "false")
os.environ.setdefault("ENABLE_KAFKA", "false")
os.environ.setdefault("ENABLE_JAEGER", "false")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LOG_LEVEL", "INFO")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")

# ============================================================
# SUPPRESS ASYNCMOCK WARNING
# ============================================================
warnings.filterwarnings(
    "ignore",
    category=RuntimeWarning,
    message="coroutine 'AsyncMockMixin._execute_mock_call' was never awaited"
)

# ============================================================
# GUARD: PASTIKAN SQLALCHEMY ASLI SEBELUM IMPORT APP.MAIN
# ============================================================
for mod_name in list(sys.modules.keys()):
    if mod_name.startswith("sqlalchemy"):
        del sys.modules[mod_name]

# ============================================================
# MOCK MODULES LAINNYA (selain sqlalchemy)
# ============================================================

# Mock opentelemetry
opentelemetry_mock = MagicMock()
opentelemetry_mock.sdk = MagicMock()
opentelemetry_mock.sdk.resources = MagicMock()
opentelemetry_mock.sdk.resources.SERVICE_NAME = "test"
opentelemetry_mock.sdk.resources.Resource = MagicMock()
opentelemetry_mock.sdk.trace = MagicMock()
opentelemetry_mock.sdk.trace.TracerProvider = MagicMock()
opentelemetry_mock.sdk.trace.BatchSpanProcessor = MagicMock()
trace_export = MagicMock()
trace_export.BatchSpanProcessor = MagicMock()
opentelemetry_mock.sdk.trace.export = trace_export
opentelemetry_mock.exporter = MagicMock()
opentelemetry_mock.exporter.otlp = MagicMock()
opentelemetry_mock.exporter.otlp.proto = MagicMock()
opentelemetry_mock.exporter.otlp.proto.grpc = MagicMock()
opentelemetry_mock.exporter.otlp.proto.grpc.trace_exporter = MagicMock()
opentelemetry_mock.instrumentation = MagicMock()
opentelemetry_mock.instrumentation.fastapi = MagicMock()
opentelemetry_mock.instrumentation.fastapi.FastAPIInstrumentor = MagicMock()
opentelemetry_mock.instrumentation.redis = MagicMock()
opentelemetry_mock.instrumentation.redis.RedisInstrumentor = MagicMock()
opentelemetry_mock.instrumentation.sqlalchemy = MagicMock()
opentelemetry_mock.instrumentation.sqlalchemy.SQLAlchemyInstrumentor = MagicMock()
opentelemetry_mock.trace = MagicMock()
opentelemetry_mock.trace.get_tracer_provider = MagicMock()
opentelemetry_mock.trace.set_tracer_provider = MagicMock()

sys.modules["opentelemetry"] = opentelemetry_mock
sys.modules["opentelemetry.sdk"] = opentelemetry_mock.sdk
sys.modules["opentelemetry.sdk.resources"] = opentelemetry_mock.sdk.resources
sys.modules["opentelemetry.sdk.trace"] = opentelemetry_mock.sdk.trace
sys.modules["opentelemetry.sdk.trace.export"] = opentelemetry_mock.sdk.trace.export
sys.modules["opentelemetry.exporter"] = opentelemetry_mock.exporter
sys.modules["opentelemetry.exporter.otlp"] = opentelemetry_mock.exporter.otlp
sys.modules["opentelemetry.exporter.otlp.proto"] = opentelemetry_mock.exporter.otlp.proto
sys.modules["opentelemetry.exporter.otlp.proto.grpc"] = opentelemetry_mock.exporter.otlp.proto.grpc
sys.modules["opentelemetry.exporter.otlp.proto.grpc.trace_exporter"] = opentelemetry_mock.exporter.otlp.proto.grpc.trace_exporter
sys.modules["opentelemetry.instrumentation"] = opentelemetry_mock.instrumentation
sys.modules["opentelemetry.instrumentation.fastapi"] = opentelemetry_mock.instrumentation.fastapi
sys.modules["opentelemetry.instrumentation.redis"] = opentelemetry_mock.instrumentation.redis
sys.modules["opentelemetry.instrumentation.sqlalchemy"] = opentelemetry_mock.instrumentation.sqlalchemy
sys.modules["opentelemetry.trace"] = opentelemetry_mock.trace

# Mock aiokafka
aiokafka_mock = MagicMock()
aiokafka_mock.AIOKafkaProducer = AsyncMock
sys.modules["aiokafka"] = aiokafka_mock

# Mock minio
minio_mock = MagicMock()
minio_mock.Minio = MagicMock()
sys.modules["minio"] = minio_mock

# Mock redis.asyncio
redis_mock = MagicMock()
redis_asyncio = MagicMock()
redis_asyncio.from_url = MagicMock(return_value=AsyncMock())
sys.modules["redis"] = redis_mock
sys.modules["redis.asyncio"] = redis_asyncio

# Mock dotenv
sys.modules["dotenv"] = MagicMock()

# Mock kernel.error_analysis
kernel_mock = MagicMock()
error_analysis = MagicMock()
error_analysis.analyze_error = MagicMock(return_value={
    "severity": "ERROR",
    "root_cause": "test",
})
error_analysis.log_rca_result = MagicMock()
error_analysis.RCAResult = MagicMock()
kernel_mock.error_analysis = error_analysis
sys.modules["kernel"] = kernel_mock
sys.modules["kernel.error_analysis"] = error_analysis

# Mock bootstrap.dependency_container.ioc_container
bootstrap_mock = MagicMock()
dependency_container = MagicMock()
ioc_container = MagicMock()
ioc_container.get_container = MagicMock()
dependency_container.ioc_container = ioc_container
bootstrap_mock.dependency_container = dependency_container
sys.modules["bootstrap"] = bootstrap_mock
sys.modules["bootstrap.dependency_container"] = dependency_container
sys.modules["bootstrap.dependency_container.ioc_container"] = ioc_container

# Mock bootstrap.iam_setup
iam_setup = MagicMock()
iam_setup.setup_iam_service = MagicMock()
sys.modules["bootstrap.iam_setup"] = iam_setup

# Mock prometheus_client
prometheus_mock = MagicMock()
prometheus_mock.CollectorRegistry = MagicMock()
prometheus_mock.Counter = MagicMock()
prometheus_mock.Gauge = MagicMock()
prometheus_mock.Histogram = MagicMock()
prometheus_mock.generate_latest = MagicMock(return_value=b"")
prometheus_mock.CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
sys.modules["prometheus_client"] = prometheus_mock

# ============================================================
# IMPORT APP.MAIN (dengan try/finally agar cleanup tetap jalan)
# ============================================================
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

# ============================================================
# CLEANUP: lepas semua fake modules yang kita pasang di atas
# (tanpa menyentuh sqlalchemy)
# ============================================================
_cleanup_names = [
    "kernel", "kernel.error_analysis",
    "bootstrap", "bootstrap.dependency_container", "bootstrap.dependency_container.ioc_container",
    "bootstrap.iam_setup",
    "opentelemetry", "opentelemetry.sdk", "opentelemetry.sdk.resources",
    "opentelemetry.sdk.trace", "opentelemetry.sdk.trace.export",
    "opentelemetry.exporter", "opentelemetry.exporter.otlp",
    "opentelemetry.exporter.otlp.proto", "opentelemetry.exporter.otlp.proto.grpc",
    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
    "opentelemetry.instrumentation", "opentelemetry.instrumentation.fastapi",
    "opentelemetry.instrumentation.redis", "opentelemetry.instrumentation.sqlalchemy",
    "opentelemetry.trace",
    "aiokafka", "minio", "redis", "redis.asyncio", "dotenv", "prometheus_client",
]

try:
    from app.main import (
        AppWrapper,
        Settings,
        _build_internal_router,
        _kafka_available,
        _kafka_producer,
        _minio_available,
        _minio_client,
        _redis_client,
        _unversioned_router,
        _v1_router,
        _v2_router,
        create_app,
        get_db_session,
        get_kafka_producer,
        get_minio,
        get_redis,
        is_kafka_available,
        is_minio_available,
        kafka_publish,
    )
finally:
    # Lepas semua fake modules yang kita pasang di atas, agar tidak meracuni test lain
    for name in _cleanup_names:
        sys.modules.pop(name, None)

# ============================================================
# Helper functions untuk membuat mock
# ============================================================
def create_mock_redis():
    """Membuat mock Redis client."""
    redis = AsyncMock()
    redis.ping = AsyncMock(return_value=True)
    redis.info = AsyncMock(return_value={"redis_version": "7.0"})
    redis.aclose = AsyncMock()
    return redis

def create_mock_kafka_producer():
    """Membuat mock Kafka producer."""
    producer = AsyncMock()
    producer.start = AsyncMock()
    producer.stop = AsyncMock()
    producer.send_and_wait = AsyncMock()
    producer.client = MagicMock()
    producer.client.force_metadata_update = AsyncMock()
    return producer

def create_mock_minio_client():
    """Membuat mock MinIO client."""
    minio = MagicMock()
    minio.bucket_exists = MagicMock(return_value=True)
    minio.make_bucket = MagicMock()
    return minio

def create_mock_db_session():
    """Membuat mock DB session."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    return mock_session

# ============================================================
# Fixtures
# ============================================================
@pytest.fixture
def mock_env(monkeypatch):
    """Fixture untuk set environment variables test."""
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/1")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("ENABLE_KAFKA", "false")
    monkeypatch.setenv("ENABLE_MINIO", "false")
    monkeypatch.setenv("ENABLE_JAEGER", "false")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "minioadmin")
    monkeypatch.setenv("MINIO_SECRET_KEY", "minioadmin")
    yield

@pytest.fixture
def settings(mock_env):
    """Fixture untuk Settings object."""
    return Settings()

@pytest.fixture
def test_app(mock_env):
    """
    Test client dengan mock untuk semua dependency eksternal.
    Engine di-patch per test karena global state.
    """
    global _redis_client, _kafka_producer, _kafka_available
    global _minio_client, _minio_available

    # Simpan asli
    original_redis = _redis_client
    original_kafka_prod = _kafka_producer
    original_kafka_avail = _kafka_available
    original_minio = _minio_client
    original_minio_avail = _minio_available

    # Set mock
    _redis_client = create_mock_redis()
    _kafka_producer = create_mock_kafka_producer()
    _kafka_available = True
    _minio_client = create_mock_minio_client()
    _minio_available = True

    # Buat app
    fastapi_app = create_app()
    fastapi_app.router.lifespan_context = lambda app: AsyncMock()
    fastapi_app.state.container = MagicMock()

    client = TestClient(fastapi_app)

    yield client

    # Restore
    _redis_client = original_redis
    _kafka_producer = original_kafka_prod
    _kafka_available = original_kafka_avail
    _minio_client = original_minio
    _minio_available = original_minio_avail

# ============================================================
# Test Settings
# ============================================================
class TestSettings:
    """Test class untuk Settings validation."""

    def test_validate_log_level_valid(self, settings):
        """Test valid log level."""
        assert settings.log_level == "INFO"
        with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
            s = Settings()
            assert s.log_level == "DEBUG"

    def test_validate_log_level_invalid(self):
        """Test invalid log level raises ValueError."""
        with patch.dict(os.environ, {"LOG_LEVEL": "INVALID"}):
            with pytest.raises(ValueError, match="log_level must be one of"):
                Settings()

    def test_validate_secret_key_missing(self, monkeypatch):
        """Test missing SECRET_KEY raises ValueError."""
        monkeypatch.delenv("SECRET_KEY", raising=False)
        with pytest.raises(ValueError, match="SECRET_KEY environment variable is required"):
            Settings()

    def test_validate_secret_key_default_in_production(self, monkeypatch):
        """Test default SECRET_KEY in production raises ValueError."""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("SECRET_KEY", "change-this-in-production")
        with pytest.raises(ValueError, match="SECRET_KEY must not be the default value in production"):
            Settings()

    def test_cors_origins(self, settings):
        """Test CORS origins parsing."""
        assert settings.cors_origins == ["http://localhost:3000", "http://localhost:8000"]
        with patch.dict(os.environ, {"ALLOWED_ORIGINS": "https://example.com ,https://test.com "}):
            s = Settings()
            assert s.cors_origins == ["https://example.com", "https://test.com"]

    def test_is_production(self, settings):
        """Test is_production property."""
        assert settings.is_production is False
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            s = Settings()
            assert s.is_production is True

# ============================================================
# Test Helper Functions
# ============================================================
@pytest.mark.asyncio
async def test_get_db_session_success():
    """Test get_db_session berhasil commit."""
    mock_session = create_mock_db_session()
    with patch("app.main.AsyncSessionLocal", return_value=mock_session):
        async for session in get_db_session():
            assert session is mock_session
        mock_session.commit.assert_awaited_once()

@pytest.mark.asyncio
async def test_get_db_session_rollback_on_exception():
    """Simulasikan kegagalan commit dengan memicu exception pada session.commit()."""
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock()
    mock_session.commit = AsyncMock(side_effect=ZeroDivisionError("test error"))
    mock_session.rollback = AsyncMock()

    with patch('app.main.AsyncSessionLocal', return_value=mock_session):
        gen = get_db_session()
        async for _ in gen:
            pass
        mock_session.rollback.assert_awaited_once()

        gen2 = get_db_session()
        async for _ in gen2:
            pass
        try:
            await gen2.aclose()
        except ZeroDivisionError:
            pass

def test_get_redis_success():
    """Test get_redis berhasil."""
    with patch("app.main._redis_client", AsyncMock()):
        client = get_redis()
        assert client is not None

def test_get_redis_not_initialized():
    """Test get_redis raises RuntimeError ketika tidak diinisialisasi."""
    with patch("app.main._redis_client", None):
        with pytest.raises(RuntimeError, match="Redis not initialized"):
            get_redis()

def test_get_kafka_producer_success():
    """Test get_kafka_producer berhasil."""
    with patch("app.main._kafka_producer", MagicMock()):
        producer = get_kafka_producer()
        assert producer is not None

def test_get_kafka_producer_not_initialized():
    """Test get_kafka_producer raises RuntimeError ketika tidak diinisialisasi."""
    with patch("app.main._kafka_producer", None):
        with pytest.raises(RuntimeError, match="Kafka producer not initialized"):
            get_kafka_producer()

def test_is_kafka_available():
    """Test is_kafka_available."""
    with patch("app.main._kafka_available", True):
        assert is_kafka_available() is True
    with patch("app.main._kafka_available", False):
        assert is_kafka_available() is False

@pytest.mark.asyncio
async def test_kafka_publish_when_available():
    """Test kafka_publish ketika Kafka tersedia."""
    mock_producer = create_mock_kafka_producer()
    with patch("app.main._kafka_available", True):
        with patch("app.main._kafka_producer", mock_producer):
            await kafka_publish("test-topic", b"test-value", key=b"test-key")
            mock_producer.send_and_wait.assert_awaited_once_with(
                "test-topic", value=b"test-value", key=b"test-key"
            )

@pytest.mark.asyncio
async def test_kafka_publish_when_not_available(caplog):
    """Test kafka_publish ketika Kafka tidak tersedia."""
    with patch("app.main._kafka_available", False), caplog.at_level("WARNING"):
        await kafka_publish("test-topic", b"test-value")
        assert "Kafka not available" in caplog.text

def test_get_minio_success():
    """Test get_minio berhasil."""
    with patch("app.main._minio_client", MagicMock()):
        client = get_minio()
        assert client is not None

def test_get_minio_not_initialized():
    """Test get_minio raises RuntimeError ketika tidak diinisialisasi."""
    with patch("app.main._minio_client", None):
        with pytest.raises(RuntimeError, match="MinIO client not initialized"):
            get_minio()

def test_is_minio_available():
    """Test is_minio_available."""
    with patch("app.main._minio_available", True):
        assert is_minio_available() is True
    with patch("app.main._minio_available", False):
        assert is_minio_available() is False

# ============================================================
# Test AppWrapper
# ============================================================
class TestAppWrapper:
    """Test class untuk AppWrapper."""

    def test_appwrapper_call_without_args(self):
        """Test AppWrapper tanpa argumen."""
        mock_app = MagicMock()
        wrapper = AppWrapper(mock_app)
        result = wrapper()
        assert result is mock_app
        mock_app.assert_not_called()

    def test_appwrapper_call_with_args(self):
        """Test AppWrapper dengan argumen."""
        mock_app = MagicMock()
        wrapper = AppWrapper(mock_app)
        wrapper("arg1", "arg2", key="value")
        mock_app.assert_called_once_with("arg1", "arg2", key="value")

# ============================================================
# Test Routes via TestClient
# ============================================================
class TestRoutes:
    """Test class untuk routes API."""

    def test_root(self, test_app):
        """Test root endpoint."""
        response = test_app.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "Sovereign ERP Accounting Engine"
        assert data["status"] == "running"

    def test_liveness(self, test_app):
        """Test liveness endpoint."""
        response = test_app.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "alive"}

    def test_readiness_ok(self, test_app):
        """Test readiness endpoint ketika DB OK."""
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value=1)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock()

        mock_engine = MagicMock()
        mock_engine.connect = MagicMock(return_value=mock_conn)

        with patch('app.main.engine', mock_engine):
            with patch('app.main.get_redis') as mock_get_redis:
                mock_redis = AsyncMock()
                mock_redis.ping = AsyncMock(return_value=True)
                mock_get_redis.return_value = mock_redis

                response = test_app.get("/health/ready")
                assert response.status_code == 200
                assert response.json() == {"status": "ready"}

    def test_readiness_db_fail(self, test_app):
        """Test readiness endpoint ketika DB gagal."""
        mock_engine = MagicMock()
        mock_engine.connect = MagicMock(side_effect=Exception("DB down"))

        with patch('app.main.engine', mock_engine):
            response = test_app.get("/health/ready")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "not_ready"
            assert any("postgres" in err for err in data["errors"])

    def test_health_check(self, test_app):
        """Test health check endpoint."""
        mock_result = MagicMock()
        mock_result.scalar = MagicMock(return_value="PostgreSQL 15.0")

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock()

        mock_engine = MagicMock()
        mock_engine.connect = MagicMock(return_value=mock_conn)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.info = AsyncMock(return_value={"redis_version": "7.0"})

        with patch('app.main.engine', mock_engine):
            with patch('app.main.get_redis', return_value=mock_redis):
                response = test_app.get("/health")
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "healthy"
                assert "components" in data

    def test_prometheus_metrics(self, test_app):
        """Test Prometheus metrics endpoint."""
        response = test_app.get("/metrics")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"

    def test_v1_get_journal_found(self, test_app):
        """Test v1 get journal ditemukan."""
        response = test_app.get("/v1/journals/123")
        assert response.status_code == 200
        data = response.json()
        assert data["journal_id"] == "123"
        assert "metadata" not in data

    def test_v1_get_journal_not_found(self, test_app):
        """Test v1 get journal tidak ditemukan."""
        response = test_app.get("/v1/journals/999")
        assert response.status_code == 404
        assert response.json()["detail"] == "Journal not found"

    def test_v1_post_journal(self, test_app):
        """Test v1 post journal."""
        payload = {"id": "456", "lines": []}
        response = test_app.post("/v1/journal/post", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "posted"
        assert data["id"] == "456"
        assert "Warning" in response.headers

    def test_v2_get_journal_found(self, test_app):
        """Test v2 get journal ditemukan dengan metadata."""
        response = test_app.get("/v2/journals/123")
        assert response.status_code == 200
        data = response.json()
        assert data["journal_id"] == "123"
        assert "metadata" in data

    def test_v2_get_journal_not_found(self, test_app):
        """Test v2 get journal tidak ditemukan."""
        response = test_app.get("/v2/journals/999")
        assert response.status_code == 404

    def test_versioned_journal_v1_default(self, test_app):
        """Test versioned journal default ke v1."""
        response = test_app.get("/journals/123")
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == "v1"

    def test_versioned_journal_v2_via_header(self, test_app):
        """Test versioned journal v2 via Accept header."""
        headers = {"Accept": "application/json; version=2"}
        response = test_app.get("/journals/123", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == "v2"

    def test_versioned_journal_not_found(self, test_app):
        """Test versioned journal tidak ditemukan."""
        response = test_app.get("/journals/999")
        assert response.status_code == 404

# ============================================================
# Test Middleware & Exception Handlers
# ============================================================
class TestMiddlewareAndExceptions:
    """Test class untuk middleware dan exception handlers."""

    def test_middleware_adds_request_id(self, test_app):
        """Test middleware menambahkan X-Request-ID."""
        response = test_app.get("/")
        assert "X-Request-ID" in response.headers
        import uuid
        try:
            uuid.UUID(response.headers["X-Request-ID"])
        except ValueError:
            pytest.fail("X-Request-ID is not a valid UUID")

    def test_validation_error_handler_triggered(self, test_app):
        """Test validation error handler triggered."""
        response = test_app.post("/v1/journal/post", data="not json", headers={"Content-Type": "application/json"})
        assert response.status_code == 422
        assert "detail" in response.json()

    @pytest.mark.asyncio
    async def test_unhandled_exception_handler(self, test_app):
        """Test unhandled exception handler dengan RCA."""
        handler = test_app.app.exception_handlers[Exception]
        request = MagicMock(spec=Request)
        request.url = MagicMock()
        request.url.path = "/test"
        request.method = "GET"
        exc = Exception("Test exception")
        with patch("app.main.analyze_error") as mock_analyze:
            mock_analyze.return_value = {
                "severity": "ERROR",
                "root_cause": "test",
            }
            response = await handler(request, exc)
            assert response.status_code == 500
            data = json.loads(response.body)
            assert "error_id" in data
            assert "rca" in data

# ============================================================
# Test create_app dan routers
# ============================================================
class TestAppCreation:
    """Test class untuk create_app dan routers."""

    def test_create_app_returns_fastapi_app(self):
        """Test create_app mengembalikan FastAPI app."""
        app_obj = create_app()
        assert app_obj.title == "Sovereign ERP Accounting Engine"
        assert app_obj.version == "1.0.0"

    def test_internal_router(self):
        """Test internal router memiliki path yang benar."""
        router = _build_internal_router()
        paths = [r.path for r in router.routes]
        assert "/" in paths
        assert "/health/live" in paths
        assert "/health/ready" in paths
        assert "/health" in paths
        assert "/metrics" in paths

    def test_v1_router_prefix(self):
        """Test v1 router prefix."""
        assert _v1_router.prefix == "/v1"
        route_paths = [r.path for r in _v1_router.routes if hasattr(r, "path")]
        assert any("journal" in path for path in route_paths)

    def test_v2_router_prefix(self):
        """Test v2 router prefix."""
        assert _v2_router.prefix == "/v2"
        route_paths = [r.path for r in _v2_router.routes if hasattr(r, "path")]
        assert any("journal" in path for path in route_paths)

    def test_unversioned_router_has_journal(self):
        """Test unversioned router memiliki journal endpoint."""
        paths = [r.path for r in _unversioned_router.routes if hasattr(r, "path")]
        assert "/journals/{journal_id}" in paths
