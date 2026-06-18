# infrastructure/telemetry/alert_manager_trigger.py
#!/usr/bin/env python3
"""
Module: alert_manager_trigger.py
Layer: Infrastructure / Telemetry
Responsibility: Fungsi untuk memicu alert ke sistem monitoring (alert manager).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def trigger_alert(
    title: str,
    message: str,
    severity: str = "warning",
    source: str = "unknown",
    tags: dict[str, Any] | None = None,
) -> None:
    """
    Trigger an alert to the alert manager (Prometheus Alertmanager, etc.).
    Implementasi stub untuk keperluan development.
    """
    logger.warning(f"ALERT: [{severity.upper()}] {title} - {message} (source={source})")
    # Di production, bisa kirim ke Alertmanager API, Slack, PagerDuty, dll.
    # Untuk sekarang hanya log.
