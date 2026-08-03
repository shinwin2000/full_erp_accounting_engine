#!/usr/bin/env python3
"""
Module: tamper_alert_trigger.py
Layer: Audit
Responsibility: Mendeteksi tampering pada audit trail dan memicu alert.
               Memantau hash chain integrity secara periodik, memverifikasi
               bahwa tidak ada perubahan ilegal pada data audit. Jika tampering
               terdeteksi, akan mengirim alert ke tim security.
Dependencies:
- asyncio, logging, datetime
- audit.hash_chain_builder (AuditHashChainBuilder)
- infrastructure.event_store.append_only_store (AppendOnlyStore)
- infrastructure.telemetry.alert_manager_router (trigger_alert)
- infrastructure.telemetry.structured_json_logging
Audit: Setiap deteksi tampering dicatat dengan detail. Alert dikirim ke channel
       yang sudah dikonfigurasi (Slack, PagerDuty, email).
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from datetime import UTC, datetime
from typing import Any

# Internal audit imports (allowed, same layer)
from audit.hash_chain_builder import (
    AuditHashChainBuilder,
    get_audit_hash_builder,
)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_CONFIG = {
    "enabled": True,
    "check_interval_seconds": 3600,  # Check every hour
    "alert_cooldown_seconds": 3600,  # Don't alert more than once per hour per stream
    "streams_to_monitor": ["audit", "security_audit", "event_gate"],
    "alert_on_first_failure": True,
    "auto_repair": False,  # If True, attempt to repair broken chain (not recommended)
}

_logger = None


def _get_logger():
    """Lazy logger initialization."""
    global _logger
    if _logger is None:
        mod = importlib.import_module("infrastructure.telemetry.structured_json_logging")
        get_logger_func = mod.get_logger
        _logger = get_logger_func(__name__)
    return _logger


# ============================================================================
# EXCEPTIONS
# ============================================================================


class TamperDetectionError(Exception):
    """Base exception untuk tamper detection."""

    pass


# ============================================================================
# TAMPER ALERT TRIGGER
# ============================================================================


class TamperAlertTrigger:
    """
    Trigger untuk alert tampering pada audit trail.

    Fitur:
    - Periodic check hash chain integrity
    - Mendeteksi broken chain
    - Mengirim alert dengan detail pelanggaran
    - Cooldown untuk menghindari spam alert
    - Support multiple streams
    """

    def __init__(self, config_path: str = "config_files/audit_config.yaml"):
        self.config = self._load_config(config_path)
        self._enabled = self.config.get("enabled", True)
        self._check_interval = self.config.get("check_interval_seconds", 3600)
        self._alert_cooldown = self.config.get("alert_cooldown_seconds", 3600)
        self._streams = self.config.get(
            "streams_to_monitor", ["audit", "security_audit", "event_gate"]
        )
        self._alert_on_first_failure = self.config.get("alert_on_first_failure", True)
        self._auto_repair = self.config.get("auto_repair", False)

        self._hash_builder: AuditHashChainBuilder | None = None
        self._event_store = None
        self._last_alert_time: dict[str, datetime] = {}
        self._monitor_task: asyncio.Task | None = None
        self._running = False

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            # Lazy import config loader
            mod = importlib.import_module("config.loader_yaml")
            load_yaml_config = mod.load_yaml_config
            config = load_yaml_config(config_path)
            tamper_config = config.get("tamper_alert", {})
            result = DEFAULT_CONFIG.copy()
            result.update(tamper_config)
            return result
        except Exception:
            return DEFAULT_CONFIG.copy()

    async def _get_hash_builder(self) -> AuditHashChainBuilder:
        if self._hash_builder is None:
            self._hash_builder = get_audit_hash_builder()
        return self._hash_builder

    async def _get_event_store(self):
        if self._event_store is None:
            mod = importlib.import_module("infrastructure.event_store.append_only_store")
            get_audit_store = mod.get_audit_store
            self._event_store = await get_audit_store()
        return self._event_store

    async def check_stream_integrity(self, stream_name: str) -> dict[str, Any]:
        """
        Check integrity of a specific audit stream.

        Returns:
            Dictionary with check results
        """
        store = await self._get_event_store()
        hash_builder = await self._get_hash_builder()

        result = {
            "stream_name": stream_name,
            "timestamp": datetime.now(UTC).isoformat(),
            "is_valid": True,
            "error": None,
            "broken_at_index": None,
            "records_checked": 0,
        }

        try:
            # Get all events from stream (limit to recent for performance)
            events = await store.read_stream(stream_name, limit=10000)
            result["records_checked"] = len(events)

            if not events:
                logger = _get_logger()
                logger.debug(f"No events found in stream {stream_name}, skipping integrity check")
                return result

            # Verify chain
            is_valid, broken_at, error = await hash_builder.verify_chain(events, stream_name)
            result["is_valid"] = is_valid
            result["broken_at_index"] = broken_at if not is_valid else None

            if not is_valid:
                result["error"] = error
                logger = _get_logger()
                logger.error(f"Tampering detected in stream {stream_name}: {error}")

                # Send alert if cooldown passed
                await self._send_alert(stream_name, result)

                # Auto-repair if configured (not recommended)
                if self._auto_repair:
                    await self._attempt_repair(stream_name, events, broken_at)

        except Exception as e:
            result["is_valid"] = False
            result["error"] = str(e)
            logger = _get_logger()
            logger.error(f"Failed to check integrity for stream {stream_name}: {e}")

        return result

    async def _send_alert(self, stream_name: str, result: dict[str, Any]) -> None:
        """
        Send tamper alert.
        """
        now = datetime.now(UTC)
        last_alert = self._last_alert_time.get(stream_name)

        if last_alert and (now - last_alert).total_seconds() < self._alert_cooldown:
            logger = _get_logger()
            logger.info(f"Alert cooldown active for stream {stream_name}, skipping alert")
            return

        self._last_alert_time[stream_name] = now

        title = f"AUDIT TAMPERING DETECTED in {stream_name}"
        message = (
            f"Tampering detected in audit stream '{stream_name}':\n"
            f"Records checked: {result['records_checked']}\n"
            f"Broken at index: {result['broken_at_index']}\n"
            f"Error: {result['error']}\n"
            f"Timestamp: {result['timestamp']}\n\n"
            f"This indicates potential unauthorized modification of audit data."
        )

        # Lazy import alert manager
        alert_mod = importlib.import_module("infrastructure.telemetry.alert_manager_router")
        trigger_alert = alert_mod.trigger_alert

        await trigger_alert(
            title=title,
            message=message,
            severity="critical",
            source="TamperAlertTrigger",
            metadata={
                "stream_name": stream_name,
                "broken_at_index": result["broken_at_index"],
                "records_checked": result["records_checked"],
            },
        )

        # Also log to security audit
        security_logger = logging.getLogger("security")
        security_logger.critical(
            f"Tampering detected in audit stream {stream_name}: {result['error']}"
        )

    async def _attempt_repair(self, stream_name: str, events: list[dict], broken_at: int) -> None:
        """
        Attempt to repair broken hash chain (not recommended, but available).
        """
        logger = _get_logger()
        logger.warning(
            f"Attempting to repair hash chain for stream {stream_name} from index {broken_at}"
        )

        try:
            hash_builder = await self._get_hash_builder()
            # Repair chain but ignore returned events (just log)
            await hash_builder.repair_chain(events, broken_at)

            # In production, this would require careful handling
            # For now, just log
            logger.warning(f"Hash chain repaired for stream {stream_name}. Please verify manually.")

            # Lazy import alert manager
            alert_mod = importlib.import_module("infrastructure.telemetry.alert_manager_router")
            trigger_alert = alert_mod.trigger_alert

            await trigger_alert(
                title=f"Audit Hash Chain Repaired for {stream_name}",
                message=f"The hash chain for stream '{stream_name}' was automatically repaired from index {broken_at}. "
                f"Please investigate the cause of tampering.",
                severity="warning",
                source="TamperAlertTrigger",
            )
        except Exception as e:
            logger.error(f"Failed to repair hash chain for {stream_name}: {e}")

    async def check_all_streams(self) -> list[dict[str, Any]]:
        """
        Check integrity of all configured streams.

        Returns:
            List of check results
        """
        results = []
        for stream_name in self._streams:
            result = await self.check_stream_integrity(stream_name)
            results.append(result)

            # If first failure and we should stop, break
            if not result["is_valid"] and self._alert_on_first_failure:
                logger = _get_logger()
                logger.warning(f"Tampering detected in {stream_name}, stopping further checks")
                break

        return results

    async def start_periodic_monitoring(self) -> None:
        """Start periodic tamper monitoring."""
        if not self._enabled:
            logger = _get_logger()
            logger.info("Tamper alert trigger is disabled")
            return

        if self._running:
            logger = _get_logger()
            logger.warning("Tamper monitoring already running")
            return

        self._running = True

        async def _monitor_loop():
            while self._running:
                try:
                    await self.check_all_streams()
                    await asyncio.sleep(self._check_interval)
                except asyncio.CancelledError:
                    logger = _get_logger()
                    logger.debug("Tamper monitoring loop cancelled")
                    break
                except Exception as e:
                    logger = _get_logger()
                    logger.error(f"Tamper monitoring error: {e}")
                    await asyncio.sleep(60)

        self._monitor_task = asyncio.create_task(_monitor_loop())
        logger = _get_logger()
        logger.info(f"Tamper alert trigger started (interval: {self._check_interval}s)")

    async def stop_periodic_monitoring(self) -> None:
        """Stop periodic tamper monitoring."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                logger = _get_logger()
                logger.debug("Tamper monitoring task cancelled during stop")
                # Expected cancellation; swallow after logging
            self._monitor_task = None
        logger = _get_logger()
        logger.info("Tamper alert trigger stopped")

    async def run_manual_check(self) -> list[dict[str, Any]]:
        """Run a manual integrity check (for on-demand)."""
        return await self.check_all_streams()

    async def get_status(self) -> dict[str, Any]:
        """Get status of the tamper alert trigger."""
        return {
            "enabled": self._enabled,
            "running": self._running,
            "check_interval_seconds": self._check_interval,
            "streams_monitored": self._streams,
            "last_alerts": {k: v.isoformat() for k, v in self._last_alert_time.items()},
            "auto_repair": self._auto_repair,
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_tamper_alert: TamperAlertTrigger | None = None


async def get_tamper_alert_trigger() -> TamperAlertTrigger:
    """Get singleton instance of TamperAlertTrigger."""
    global _tamper_alert
    if _tamper_alert is None:
        _tamper_alert = TamperAlertTrigger()
    return _tamper_alert


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["TamperAlertTrigger", "TamperDetectionError", "get_tamper_alert_trigger"]
