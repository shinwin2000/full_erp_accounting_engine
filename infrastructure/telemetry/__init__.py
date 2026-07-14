#!/usr/bin/env python3
"""
Package: infrastructure.telemetry
Telemetry, logging, metrics, tracing, alerting.
"""

from __future__ import annotations

# Logging - pasti ada
from .structured_json_logging import get_logger

# Alerts - coba import
try:
    from .alert_manager_router import trigger_alert
except ImportError:
    trigger_alert = None

try:
    from .alert_manager_trigger import trigger_alert as trigger_alert_direct
except ImportError:
    trigger_alert_direct = None

# Correlation ID
try:
    from .correlation_id_injector import CorrelationIdInjector, get_correlation_id
except ImportError:
    CorrelationIdInjector = None
    get_correlation_id = None

# Exceptions
try:
    from .telemetry_exceptions import TelemetryError
except ImportError:
    TelemetryError = Exception

__all__ = [
    "CorrelationIdInjector",
    "TelemetryError",
    "get_correlation_id",
    "get_logger",
    "trigger_alert",
    "trigger_alert_direct",
]
