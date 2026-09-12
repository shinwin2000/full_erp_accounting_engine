from typing import Any

from .structured_json_logging import get_logger

# Fallback types
trigger_alert: Any
trigger_alert_direct: Any
CorrelationIdInjector: Any
get_correlation_id: Any
TelemetryError: Any

try:
    from .alert_manager_router import trigger_alert
except ImportError:
    trigger_alert = None

try:
    from .alert_manager_trigger import trigger_alert as trigger_alert_direct
except ImportError:
    trigger_alert_direct = None

try:
    from .correlation_id_injector import (
        CorrelationIdInjector,
        get_current_correlation_id as get_correlation_id,
    )
except ImportError:
    CorrelationIdInjector = None
    get_correlation_id = None

try:
    from .telemetry_exceptions import TelemetryError
except ImportError:
    TelemetryError = Exception
    