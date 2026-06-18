#!/usr/bin/env python3
"""
Module: telemetry_exceptions.py
Layer: Infrastructure (Telemetry)
Responsibility: Mendefinisikan semua exception yang terkait dengan telemetry.
"""

from __future__ import annotations


class TelemetryError(Exception):
    """Base exception untuk telemetry."""

    pass


class MetricsCollectionError(TelemetryError):
    """Error saat mengumpulkan metrik."""

    def __init__(self, message: str, collector: str | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.collector = collector


class MetricsExportError(TelemetryError):
    """Error saat mengekspor metrik ke Prometheus."""

    def __init__(self, message: str, exporter: str | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.exporter = exporter


class TracingError(TelemetryError):
    """Error saat tracing dengan OpenTelemetry."""

    pass


class SpanCreationError(TracingError):
    """Error saat membuat span."""

    pass


class AlertError(TelemetryError):
    """Error saat mengirim alert."""

    def __init__(self, message: str, channel: str | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.channel = channel


class SLOMonitorError(TelemetryError):
    """Error saat monitoring SLO."""

    def __init__(self, message: str, process_type: str | None = None, **kwargs):
        super().__init__(message, **kwargs)
        self.process_type = process_type


class LoggingError(TelemetryError):
    """Error saat structured logging."""

    pass


__all__ = [
    "AlertError",
    "LoggingError",
    "MetricsCollectionError",
    "MetricsExportError",
    "SLOMonitorError",
    "SpanCreationError",
    "TelemetryError",
    "TracingError",
]
