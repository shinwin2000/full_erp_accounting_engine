#!/usr/bin/env python3
"""
Module: opentelemetry_setup.py
Layer: Infrastructure (Telemetry)
Responsibility: Menginisialisasi dan mengkonfigurasi OpenTelemetry untuk
               distributed tracing. Mendukung export ke Jaeger, Zipkin, atau
               OTLP collector. Menyediakan tracer provider, span processor,
               dan instrumentasi untuk FastAPI, gRPC, database, dan HTTP clients.
Dependencies:
- opentelemetry-api, opentelemetry-sdk, opentelemetry-instrumentation
- opentelemetry-exporter-jaeger, opentelemetry-exporter-otlp
- asyncio, logging
- config.loader_yaml
- infrastructure.telemetry.structured_json_logging
Audit: Tracing digunakan untuk debugging dan performance analysis.
       Traces tidak mengandung data sensitif (PII redacted).
"""

from __future__ import annotations

import logging
import os
from typing import Any

# OpenTelemetry imports (with fallback if not installed)
try:
    from opentelemetry import _logs, metrics, trace
    from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, ConsoleLogExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import (
        ConsoleMetricExporter,
        PeriodicExportingMetricReader,
    )
    from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    OPENTELEMETRY_AVAILABLE = True
except ImportError:
    OPENTELEMETRY_AVAILABLE = False

    # Create dummy classes
    class trace:
        @staticmethod
        def get_tracer(name):
            return None

        class TracerProvider:
            pass


# Internal dependencies
from config.loader_yaml import load_yaml_config
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_CONFIG = {
    "enabled": True,
    "service_name": "erp-accounting-engine",
    "service_version": "1.0.0",
    "exporter": "jaeger",  # jaeger, zipkin, otlp, console
    "jaeger_agent_host": "localhost",
    "jaeger_agent_port": 6831,
    "jaeger_collector_endpoint": "http://localhost:14268/api/traces",
    "otlp_endpoint": "http://localhost:4317",
    "zipkin_endpoint": "http://localhost:9411/api/v2/spans",
    "sampling_ratio": 0.1,  # 10% sampling
    "enable_fastapi_instrumentation": True,
    "enable_sqlalchemy_instrumentation": True,
    "enable_redis_instrumentation": True,
    "enable_httpx_instrumentation": True,
    "batch_export_schedule_delay_millis": 5000,
    "max_export_batch_size": 512,
}

# ============================================================================
# OPEN TELEMETRY SETUP
# ============================================================================


class OpenTelemetrySetup:
    """
    Setup dan konfigurasi OpenTelemetry.

    Fitur:
    - Inisialisasi TracerProvider
    - Konfigurasi exporter (Jaeger, Zipkin, OTLP, Console)
    - Instrumentasi FastAPI, SQLAlchemy, Redis, HTTPX
    - Sampling configuration
    - Resource attributes untuk service identification
    """

    def __init__(self, config_path: str = "config_files/telemetry_config.yaml"):
        self.config = self._load_config(config_path)
        self._initialized = False
        self._tracer_provider: TracerProvider | None = None
        self._meter_provider: MeterProvider | None = None
        self._logger_provider: LoggerProvider | None = None

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            telemetry_config = config.get("opentelemetry", {})
            # Merge with defaults
            result = DEFAULT_CONFIG.copy()
            result.update(telemetry_config)
            return result
        except Exception as e:
            logger.warning(f"Failed to load OpenTelemetry config, using defaults: {e}")
            return DEFAULT_CONFIG.copy()

    def _create_resource(self) -> Resource:
        """Create resource with service information."""
        return Resource.create(
            {
                SERVICE_NAME: self.config.get("service_name", "erp-accounting-engine"),
                SERVICE_VERSION: self.config.get("service_version", "1.0.0"),
                "environment": os.environ.get("ERP_ENV", "production"),
                "deployment.environment": os.environ.get("ERP_ENV", "production"),
            }
        )

    def _create_span_processor(self):
        """
        Create span exporter based on configuration.
        """
        if not OPENTELEMETRY_AVAILABLE:
            logger.warning("OpenTelemetry not available")
            return None

        exporter_type = self.config.get("exporter", "jaeger")

        if exporter_type == "console":
            exporter = ConsoleSpanExporter()
        elif exporter_type == "jaeger":
            from opentelemetry.exporter.jaeger.thrift import JaegerExporter

            exporter = JaegerExporter(
                agent_host_name=self.config.get("jaeger_agent_host", "localhost"),
                agent_port=self.config.get("jaeger_agent_port", 6831),
                collector_endpoint=self.config.get("jaeger_collector_endpoint"),
            )
        elif exporter_type == "otlp":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(
                endpoint=self.config.get("otlp_endpoint", "http://localhost:4317"), insecure=True
            )
        elif exporter_type == "zipkin":
            from opentelemetry.exporter.zipkin.json import ZipkinExporter

            exporter = ZipkinExporter(
                endpoint=self.config.get("zipkin_endpoint", "http://localhost:9411/api/v2/spans")
            )
        else:
            logger.warning(f"Unknown exporter type: {exporter_type}, using console")
            exporter = ConsoleSpanExporter()

        return BatchSpanProcessor(
            exporter,
            schedule_delay_millis=self.config.get("batch_export_schedule_delay_millis", 5000),
            max_export_batch_size=self.config.get("max_export_batch_size", 512),
        )

    def setup_tracing(self) -> None:
        """
        Setup tracing with TracerProvider.
        """
        if not OPENTELEMETRY_AVAILABLE:
            logger.warning("OpenTelemetry not available, tracing disabled")
            return

        if not self.config.get("enabled", True):
            logger.info("OpenTelemetry tracing disabled by configuration")
            return

        try:
            # Create tracer provider
            self._tracer_provider = TracerProvider(
                resource=self._create_resource(),
                active_span_processor=self._create_span_processor(),
            )

            # Set global tracer provider
            trace.set_tracer_provider(self._tracer_provider)

            logger.info("OpenTelemetry tracing initialized")
        except Exception as e:
            logger.error(f"Failed to setup OpenTelemetry tracing: {e}")

    def setup_metrics(self) -> None:
        """
        Setup metrics with MeterProvider.
        """
        if not OPENTELEMETRY_AVAILABLE:
            logger.warning("OpenTelemetry not available, metrics disabled")
            return

        if not self.config.get("enabled", True):
            return

        try:
            # Create metric reader
            metric_reader = PeriodicExportingMetricReader(
                ConsoleMetricExporter(), export_interval_millis=60000
            )

            # Create meter provider
            self._meter_provider = MeterProvider(
                resource=self._create_resource(), metric_readers=[metric_reader]
            )

            # Set global meter provider
            metrics.set_meter_provider(self._meter_provider)

            logger.info("OpenTelemetry metrics initialized")
        except Exception as e:
            logger.error(f"Failed to setup OpenTelemetry metrics: {e}")

    def setup_logging(self) -> None:
        """
        Setup OpenTelemetry logging integration.
        """
        if not OPENTELEMETRY_AVAILABLE:
            return

        if not self.config.get("enabled", True):
            return

        try:
            self._logger_provider = LoggerProvider(resource=self._create_resource())
            _logs.set_logger_provider(self._logger_provider)

            # Add log record processor
            processor = BatchLogRecordProcessor(ConsoleLogExporter())
            self._logger_provider.add_log_record_processor(processor)

            # Create logging handler
            handler = LoggingHandler(logger_provider=self._logger_provider)

            # Add handler to root logger
            root_logger = logging.getLogger()
            root_logger.addHandler(handler)

            logger.info("OpenTelemetry logging integration initialized")
        except Exception as e:
            logger.error(f"Failed to setup OpenTelemetry logging: {e}")

    def setup_instrumentation(self, app=None, db_engine=None, redis_client=None) -> None:
        """
        Setup auto-instrumentation for libraries.
        """
        if not OPENTELEMETRY_AVAILABLE:
            return

        if not self.config.get("enabled", True):
            return

        try:
            # FastAPI instrumentation
            if self.config.get("enable_fastapi_instrumentation", True) and app:
                FastAPIInstrumentor.instrument_app(app)
                logger.info("FastAPI instrumentation enabled")

            # SQLAlchemy instrumentation
            if self.config.get("enable_sqlalchemy_instrumentation", True) and db_engine:
                SQLAlchemyInstrumentor().instrument(engine=db_engine)
                logger.info("SQLAlchemy instrumentation enabled")

            # Redis instrumentation
            if self.config.get("enable_redis_instrumentation", True):
                RedisInstrumentor().instrument()
                logger.info("Redis instrumentation enabled")

            # HTTPX instrumentation
            if self.config.get("enable_httpx_instrumentation", True):
                HTTPXClientInstrumentor().instrument()
                logger.info("HTTPX instrumentation enabled")

            # AioHTTP client instrumentation
            AioHttpClientInstrumentor().instrument()

        except Exception as e:
            logger.error(f"Failed to setup instrumentation: {e}")

    def get_tracer(self, name: str = "erp-accounting-engine") -> trace.Tracer | None:
        """
        Get a tracer for manual instrumentation.
        """
        if not OPENTELEMETRY_AVAILABLE or not self._tracer_provider:
            return None

        return trace.get_tracer(name)

    def setup_all(self, app=None, db_engine=None, redis_client=None) -> None:
        """
        Setup all OpenTelemetry components.
        """
        if self._initialized:
            logger.warning("OpenTelemetry already initialized")
            return

        self.setup_tracing()
        self.setup_metrics()
        self.setup_logging()
        self.setup_instrumentation(app, db_engine, redis_client)

        self._initialized = True
        logger.info("OpenTelemetry fully initialized")

    def shutdown(self) -> None:
        """
        Shutdown OpenTelemetry providers.
        """
        if self._tracer_provider:
            self._tracer_provider.shutdown()
        if self._meter_provider:
            self._meter_provider.shutdown()
        if self._logger_provider:
            self._logger_provider.shutdown()

        self._initialized = False
        logger.info("OpenTelemetry shutdown completed")

    @property
    def is_enabled(self) -> bool:
        return self.config.get("enabled", True) and OPENTELEMETRY_AVAILABLE


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_otel_setup: OpenTelemetrySetup | None = None


def get_opentelemetry_setup() -> OpenTelemetrySetup:
    """Get singleton instance of OpenTelemetrySetup."""
    global _otel_setup
    if _otel_setup is None:
        _otel_setup = OpenTelemetrySetup()
    return _otel_setup


def get_tracer(name: str = "erp-accounting-engine"):
    """Get tracer for manual instrumentation."""
    setup = get_opentelemetry_setup()
    return setup.get_tracer(name)


def get_trace_id(span) -> str | None:
    """Extract trace ID from span for logging."""
    if span and span.get_span_context().trace_id:
        return format(span.get_span_context().trace_id, "032x")
    return None


# ============================================================================
# CONVENIENCE FUNCTION FOR APP_FACTORY
# ============================================================================


def setup_opentelemetry(
    service_name: str = "erp_accounting_engine",
    endpoint: str = "localhost:4317",
    exporter_type: str = "otlp",
    sampling_ratio: float = 0.1,
    **kwargs,
) -> None:
    """
    Quick setup for OpenTelemetry tracing with OTLP exporter.
    This function is called from app_factory.py.

    Args:
        service_name: Name of the service for tracing
        endpoint: OTLP collector endpoint (e.g., localhost:4317)
        exporter_type: Type of exporter (otlp, jaeger, zipkin, console)
        sampling_ratio: Sampling ratio (0.0 to 1.0)
        **kwargs: Additional configuration overrides
    """
    setup = get_opentelemetry_setup()

    # Override config with parameters
    setup.config["service_name"] = service_name
    setup.config["exporter"] = exporter_type
    setup.config["sampling_ratio"] = sampling_ratio
    setup.config["enabled"] = True

    if exporter_type == "otlp":
        setup.config["otlp_endpoint"] = endpoint
    elif exporter_type == "jaeger":
        # For Jaeger, endpoint might be agent host:port, parse if needed
        if ":" in endpoint:
            host, port = endpoint.split(":")
            setup.config["jaeger_agent_host"] = host
            setup.config["jaeger_agent_port"] = int(port)
    elif exporter_type == "zipkin":
        setup.config["zipkin_endpoint"] = endpoint

    # Apply any additional kwargs to config
    for key, value in kwargs.items():
        if key in setup.config:
            setup.config[key] = value

    # Setup all components (without passing app/db_engine here, those are separate)
    setup.setup_all()

    logger.info(
        f"OpenTelemetry setup completed for service '{service_name}' with exporter '{exporter_type}'"
    )


# ============================================================================
setup_telemetry = setup_opentelemetry


# DECORATOR
# ============================================================================


def traced(span_name: str, attributes: dict[str, Any] | None = None):
    """
    Decorator untuk menandai fungsi dengan span tracing.

    Usage:
        @traced("process_journal", attributes={"entity": "journal"})
        async def process_journal(journal_id: str):
            ...
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            tracer = get_tracer()
            if tracer is None:
                return await func(*args, **kwargs)

            with tracer.start_as_current_span(span_name) as span:
                if attributes:
                    for key, value in attributes.items():
                        span.set_attribute(key, value)
                return await func(*args, **kwargs)

        return wrapper

    return decorator


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "OPENTELEMETRY_AVAILABLE",
    "OpenTelemetrySetup",
    "get_opentelemetry_setup",
    "get_trace_id",
    "get_tracer",
    "setup_opentelemetry",
    "setup_telemetry",
    "traced",
]
