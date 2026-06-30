#!/usr/bin/env python3
"""
Module: fastapi_request_id_middleware.py
Layer: Adapters (Primary API - Common)
Responsibility: Middleware untuk menambahkan dan mempertahankan Request ID (juga dikenal
               sebagai Correlation ID atau Trace ID) di setiap request-response.
               Request ID digunakan untuk tracing end-to-end, menghubungkan log dari
               berbagai layanan, dan memudahkan debugging. Middleware ini juga menginjeksi
               request ID ke dalam context logger dan OpenTelemetry span.
Dependencies:
- starlette
- uuid, contextvars, logging
- infrastructure.telemetry.correlation_id_injector
- infrastructure.telemetry.opentelemetry_setup (optional)
Audit: Request ID dicatat di audit log, memungkinkan rekonstruksi alur request.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

# Internal imports
try:
    from infrastructure.telemetry.correlation_id_injector import CorrelationIdInjector
    from infrastructure.telemetry.opentelemetry_setup import get_tracer

    TELEMETRY_AVAILABLE = True
except ImportError:
    TELEMETRY_AVAILABLE = False
    CorrelationIdInjector = None

# Context variable untuk menyimpan request ID agar bisa diakses di seluruh stack
_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================

# Header yang umum digunakan untuk request ID
HEADER_REQUEST_ID = "X-Request-ID"
HEADER_CORRELATION_ID = "X-Correlation-ID"
HEADER_TRACE_ID = "X-Trace-ID"

# Fallback jika header tidak ada
DEFAULT_PREFIX = "req"

# Format timestamp untuk request ID (optional)
TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"

# ============================================================================
# CUSTOM EXCEPTIONS
# ============================================================================


class RequestIDError(Exception):
    """Error terkait request ID (jarang terjadi, hanya untuk kesalahan serius)."""

    pass


# ============================================================================
# VALUE OBJECTS / UTILITY CLASSES
# ============================================================================


class RequestIDGenerator:
    """
    Generator untuk membuat request ID yang unik.
    Bisa berupa UUID, atau kombinasi timestamp+random.
    """

    @staticmethod
    def generate_uuid() -> str:
        """Generate UUID4 sebagai request ID."""
        return str(uuid.uuid4())

    @staticmethod
    def generate_short() -> str:
        """Generate request ID pendek (8 karakter hex)."""
        return uuid.uuid4().hex[:8]

    @staticmethod
    def generate_with_timestamp() -> str:
        """Generate request ID dengan timestamp untuk keterbacaan."""
        from datetime import datetime

        ts = datetime.now(UTC).strftime(TIMESTAMP_FORMAT)
        short_id = uuid.uuid4().hex[:6]
        return f"{ts}-{short_id}"

    @staticmethod
    def generate_sequential(prefix: str = DEFAULT_PREFIX) -> str:
        """
        Generate request ID sequential dengan counter.
        Catatan: tidak untuk load balancing, lebih untuk internal.
        """
        import itertools

        # Menggunakan itertools counter yang aman per proses
        counter = getattr(RequestIDGenerator, "_counter", itertools.count(1))
        RequestIDGenerator._counter = counter
        seq = next(counter)
        return f"{prefix}-{seq:06d}"


class RequestIDContext:
    """
    Manajemen context untuk request ID menggunakan contextvars.
    Memungkinkan akses request ID di mana saja dalam request cycle tanpa harus
    melewati parameter secara eksplisit.
    """

    @staticmethod
    def set(request_id: str) -> None:
        """Set request ID di context."""
        _request_id_ctx.set(request_id)

    @staticmethod
    def get() -> str | None:
        """Dapatkan request ID dari context."""
        return _request_id_ctx.get()

    @staticmethod
    def clear() -> None:
        """Clear context (biasanya di akhir request)."""
        _request_id_ctx.set(None)

    @staticmethod
    def ensure_request_id(fallback: str | None = None) -> str:
        """Pastikan ada request ID, jika tidak generate baru."""
        rid = RequestIDContext.get()
        if rid is None:
            rid = fallback or RequestIDGenerator.generate_uuid()
            RequestIDContext.set(rid)
        return rid


class CorrelationIdHandler(logging.Handler):
    """
    Custom logging handler yang menambahkan request ID ke setiap log record.
    Bisa diintegrasikan dengan logging.basicConfig atau dictConfig.
    """

    def __init__(self, target_handler: logging.Handler):
        super().__init__()
        self.target_handler = target_handler

    def emit(self, record: logging.LogRecord) -> None:
        # Tambahkan atribut request_id ke log record
        request_id = RequestIDContext.get()
        if request_id:
            # Gunakan filter atau tambahkan ke extra
            if not hasattr(record, "request_id"):
                record.request_id = request_id
        # Forward ke target handler
        self.target_handler.emit(record)


# ============================================================================
# MAIN MIDDLEWARE CLASS
# ============================================================================


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware untuk menangani Request ID.

    Fitur:
    - Membaca header yang sudah ada (X-Request-ID, X-Correlation-ID, X-Trace-ID)
    - Menghasilkan Request ID baru jika tidak ada
    - Menyimpan Request ID di contextvars untuk diakses oleh logging, tracing, audit
    - Menambahkan Request ID ke response header
    - Menginjeksi ke span OpenTelemetry (jika tersedia)
    - Memastikan Request ID konsisten di seluruh request pipeline
    """

    def __init__(
        self,
        app: ASGIApp,
        header_names: list[str] | None = None,
        generate_if_missing: bool = True,
        add_to_response: bool = True,
        response_header_name: str = HEADER_REQUEST_ID,
        generator: Callable[[], str] | None = None,
        inject_to_logging: bool = True,
        inject_to_telemetry: bool = True,
    ):
        """
        Args:
            app: ASGI application
            header_names: Daftar header yang dicari untuk request ID (prioritas urutan)
            generate_if_missing: Generate ID baru jika tidak ditemukan di header
            add_to_response: Tambahkan request ID ke response header
            response_header_name: Nama header untuk response
            generator: Fungsi generator custom (default: UUID)
            inject_to_logging: Tambahkan request ID ke logging context
            inject_to_telemetry: Tambahkan request ID ke OpenTelemetry span
        """
        super().__init__(app)
        self.header_names = header_names or [
            HEADER_REQUEST_ID,
            HEADER_CORRELATION_ID,
            HEADER_TRACE_ID,
        ]
        self.generate_if_missing = generate_if_missing
        self.add_to_response = add_to_response
        self.response_header_name = response_header_name
        self.generator = generator or RequestIDGenerator.generate_uuid
        self.inject_to_logging = inject_to_logging
        self.inject_to_telemetry = inject_to_telemetry

        # Inisialisasi logging filter jika perlu
        if self.inject_to_logging:
            self._setup_logging_filter()

        # Cache untuk telemetry components
        self._tracer = None
        if self.inject_to_telemetry and TELEMETRY_AVAILABLE:
            try:
                self._tracer = get_tracer("request_id_middleware")
            except Exception as e:
                logger.warning(f"Failed to get OpenTelemetry tracer: {e}")
                self.inject_to_telemetry = False

    def _setup_logging_filter(self) -> None:
        """
        Setup logging filter untuk menambahkan request ID ke semua log record.
        """

        class RequestIDFilter(logging.Filter):
            def filter(self, record):
                request_id = RequestIDContext.get()
                if request_id:
                    record.request_id = request_id
                else:
                    record.request_id = "-"
                return True

        # Tambahkan filter ke root logger dan semua handler
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            handler.addFilter(RequestIDFilter())
        # Juga tambahkan filter ke logger ini sendiri
        logger.addFilter(RequestIDFilter())

    def _extract_request_id(self, request: Request) -> str | None:
        """
        Ekstrak request ID dari header berdasarkan urutan header_names.
        """
        for header in self.header_names:
            rid = request.headers.get(header)
            if rid and rid.strip():
                return rid.strip()
        return None

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """
        Proses request: ekstrak atau generate request ID, set ke context, lalu lanjutkan.
        """
        # Ekstrak dari header
        request_id = self._extract_request_id(request)

        # Generate jika perlu
        if not request_id and self.generate_if_missing:
            request_id = self.generator()
            logger.debug(f"Generated new request ID: {request_id}")

        # Simpan di context
        if request_id:
            RequestIDContext.set(request_id)
            # Juga simpan di request.state untuk akses mudah di endpoint
            request.state.request_id = request_id
        else:
            # Tidak ada request ID (mungkin generate_if_missing=False)
            request.state.request_id = None

        # Mulai span OpenTelemetry jika tersedia
        span = None
        if self.inject_to_telemetry and self._tracer and request_id:
            try:
                span = self._tracer.start_span(
                    "http_request",
                    attributes={
                        "http.request_id": request_id,
                        "http.method": request.method,
                        "http.url": str(request.url),
                    },
                )
                # Set span sebagai current
                span.__enter__()
            except Exception as e:
                logger.warning(f"Failed to start OpenTelemetry span: {e}")

        start_time = time.perf_counter()
        try:
            response = await call_next(request)

            # Tambahkan request ID ke response header
            if self.add_to_response and request_id and self.response_header_name:
                response.headers[self.response_header_name] = request_id

            return response

        except Exception as e:
            # Jika ada error, tetap catat request ID di log
            logger.exception(f"Request {request_id} failed: {e}")
            raise
        finally:
            # End span
            if span:
                try:
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    span.set_attribute("http.duration_ms", duration_ms)
                    span.set_attribute("http.status_code", getattr(response, "status_code", 500))
                    span.__exit__(None, None, None)
                except Exception as e:
                    logger.warning(f"Failed to end OpenTelemetry span: {e}")

            # Bersihkan context (penting untuk mencegah leak antar request)
            RequestIDContext.clear()

    # ============================================================================
    # PUBLIC CLASS METHODS
    # ============================================================================

    @classmethod
    def get_current_request_id(cls) -> str | None:
        """
        Dapatkan request ID dari context saat ini.
        Bisa digunakan di mana saja (service, repository, dll).
        """
        return RequestIDContext.get()

    @classmethod
    def ensure_current_request_id(cls) -> str:
        """
        Pastikan ada request ID, generate jika tidak ada.
        Berguna untuk async tasks yang tidak memiliki request asli.
        """
        rid = cls.get_current_request_id()
        if rid is None:
            rid = RequestIDGenerator.generate_uuid()
            RequestIDContext.set(rid)
        return rid


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================


def get_current_request_id() -> str | None:
    """
    Fungsi convenience untuk mendapatkan request ID dari context.
    Dapat diimport dan digunakan di lapisan manapun (application, domain, infrastructure).
    """
    return RequestIDMiddleware.get_current_request_id()


def set_request_id_for_task(request_id: str) -> None:
    """
    Set request ID untuk async task yang tidak memiliki context.
    Berguna ketika menjalankan background task (outbox, saga, dll) yang terkait
    dengan request asli.
    """
    RequestIDContext.set(request_id)


def generate_request_id() -> str:
    """Generate request ID baru (UUID)."""
    return RequestIDGenerator.generate_uuid()


# ============================================================================
# MIDDLEWARE FACTORY
# ============================================================================


def create_request_id_middleware(app, config: dict[str, Any]) -> RequestIDMiddleware:
    """
    Factory untuk membuat RequestIDMiddleware dari konfigurasi dictionary.
    """
    return RequestIDMiddleware(
        app,
        header_names=config.get("request_id_headers", [HEADER_REQUEST_ID, HEADER_CORRELATION_ID]),
        generate_if_missing=config.get("generate_if_missing", True),
        add_to_response=config.get("add_to_response", True),
        response_header_name=config.get("response_header_name", HEADER_REQUEST_ID),
        inject_to_logging=config.get("inject_to_logging", True),
        inject_to_telemetry=config.get("inject_to_telemetry", True),
    )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "HEADER_CORRELATION_ID",
    "HEADER_REQUEST_ID",
    "HEADER_TRACE_ID",
    "RequestIDContext",
    "RequestIDGenerator",
    "RequestIDMiddleware",
    "create_request_id_middleware",
    "generate_request_id",
    "get_current_request_id",
    "set_request_id_for_task",
]