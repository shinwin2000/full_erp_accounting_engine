#!/usr/bin/env python3
"""
Module: alert_manager_router.py
Layer: Infrastructure (Telemetry)
Responsibility: Mengelola pengiriman alert ke berbagai channel (Slack, PagerDuty,
               Email, WhatsApp, Webhook). Versi ini tidak bergantung pada Redis
               untuk menghindari circular import. Deduplication dan rate limiting
               dapat diimplementasikan menggunakan in-memory cache sederhana.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from datetime import UTC, datetime
from uuid import uuid4

# Optional HTTP client
try:
    import aiohttp

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

# Tidak mengimpor redis_manager di sini

logger = logging.getLogger(__name__)

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"
SEVERITY_CRITICAL = "critical"

CHANNEL_SLACK = "slack"
CHANNEL_PAGERDUTY = "pagerduty"
CHANNEL_EMAIL = "email"
CHANNEL_WHATSAPP = "whatsapp"
CHANNEL_WEBHOOK = "webhook"

DEFAULT_RATE_LIMIT_SECONDS = 60
DEFAULT_DEDUP_WINDOW_SECONDS = 300


class Alert:
    def __init__(
        self, title: str, message: str, severity: str, source: str, metadata: dict | None = None
    ):
        self.id = str(uuid4())
        self.title = title
        self.message = message
        self.severity = severity
        self.source = source
        self.metadata = metadata or {}
        self.created_at = datetime.now(UTC)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "severity": self.severity,
            "source": self.source,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }

    def get_dedup_key(self) -> str:
        content = f"{self.source}:{self.title}:{self.severity}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]


class BaseAlertChannel:
    def __init__(self, config: dict):
        self.config = config
        self.enabled = config.get("enabled", True)

    async def send(self, alert: Alert) -> bool:
        raise NotImplementedError


class SlackAlertChannel(BaseAlertChannel):
    def __init__(self, config: dict):
        super().__init__(config)
        self.webhook_url = config.get("webhook_url")
        self.channel = config.get("channel")

    async def send(self, alert: Alert) -> bool:
        if not self.enabled or not self.webhook_url:
            return False
        payload = {
            "text": f"*[{alert.severity.upper()}] {alert.title}*",
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*{alert.title}*\n{alert.message}"},
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"Source: {alert.source}"},
                        {"type": "mrkdwn", "text": f"Time: {alert.created_at.isoformat()}"},
                    ],
                },
            ],
        }
        if self.channel:
            payload["channel"] = self.channel
        if not AIOHTTP_AVAILABLE:
            logger.warning("aiohttp not available, cannot send Slack alert")
            return False
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.error(f"Failed to send Slack alert: {e}")
            return False


class PagerDutyAlertChannel(BaseAlertChannel):
    def __init__(self, config: dict):
        super().__init__(config)
        self.integration_key = config.get("integration_key") or os.environ.get(
            "PAGERDUTY_INTEGRATION_KEY"
        )
        self.api_url = config.get("api_url", "https://events.pagerduty.com/v2/enqueue")

    async def send(self, alert: Alert) -> bool:
        if not self.enabled or not self.integration_key:
            return False
        severity_map = {
            SEVERITY_INFO: "info",
            SEVERITY_WARNING: "warning",
            SEVERITY_ERROR: "error",
            SEVERITY_CRITICAL: "critical",
        }
        payload = {
            "routing_key": self.integration_key,
            "event_action": "trigger",
            "payload": {
                "summary": alert.title,
                "source": alert.source,
                "severity": severity_map.get(alert.severity, "error"),
                "custom_details": {"message": alert.message, "metadata": alert.metadata},
            },
        }
        if not AIOHTTP_AVAILABLE:
            logger.warning("aiohttp not available, cannot send PagerDuty alert")
            return False
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload) as resp:
                    return resp.status == 202
        except Exception as e:
            logger.error(f"Failed to send PagerDuty alert: {e}")
            return False


class EmailAlertChannel(BaseAlertChannel):
    def __init__(self, config: dict):
        super().__init__(config)
        self.smtp_host = config.get("smtp_host", "localhost")
        self.smtp_port = config.get("smtp_port", 25)
        self.from_email = config.get("from_email", "alerts@erp.internal")
        self.to_emails = config.get("to_emails", [])

    async def send(self, alert: Alert) -> bool:
        if not self.enabled or not self.to_emails:
            return False
        logger.info(f"Email alert would be sent to {self.to_emails}: {alert.title}")
        return True


class WebhookAlertChannel(BaseAlertChannel):
    def __init__(self, config: dict):
        super().__init__(config)
        self.webhook_url = config.get("webhook_url")
        self.method = config.get("method", "POST")
        self.headers = config.get("headers", {})

    async def send(self, alert: Alert) -> bool:
        if not self.enabled or not self.webhook_url:
            return False
        payload = {
            "id": alert.id,
            "title": alert.title,
            "message": alert.message,
            "severity": alert.severity,
            "source": alert.source,
            "metadata": alert.metadata,
            "timestamp": alert.created_at.isoformat(),
        }
        if not AIOHTTP_AVAILABLE:
            logger.warning("aiohttp not available, cannot send webhook alert")
            return False
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.request(
                    method=self.method, url=self.webhook_url, json=payload, headers=self.headers
                ) as resp,
            ):
                return 200 <= resp.status < 300
        except Exception as e:
            logger.error(f"Failed to send webhook alert: {e}")
            return False


class AlertManagerRouter:
    def __init__(self, config_path: str = "config_files/alert_config.yaml"):
        self.config = self._load_config(config_path)
        self._channels: dict[str, BaseAlertChannel] = {}
        self._alert_history: list[Alert] = []
        self._last_alert_time: dict[str, datetime] = {}
        # Deduplication in-memory (simple TTL)
        self._dedup_cache: dict[str, float] = {}
        self._init_channels()

    def _load_config(self, config_path: str) -> dict:
        from config.loader_yaml import load_yaml_config

        try:
            return load_yaml_config(config_path)
        except Exception:
            logger.warning(f"Failed to load config from {config_path}, using defaults")
            return {
                "alert_manager": {
                    "enabled": True,
                    "rate_limit_seconds": 60,
                    "dedup_window_seconds": 300,
                },
                "channels": {
                    "slack": {"enabled": False},
                    "pagerduty": {"enabled": False},
                    "email": {"enabled": False},
                    "webhook": {"enabled": False},
                },
            }

    def _init_channels(self):
        channels_config = self.config.get("channels", {})
        if "slack" in channels_config:
            self._channels["slack"] = SlackAlertChannel(channels_config["slack"])
        if "pagerduty" in channels_config:
            self._channels["pagerduty"] = PagerDutyAlertChannel(channels_config["pagerduty"])
        if "email" in channels_config:
            self._channels["email"] = EmailAlertChannel(channels_config["email"])
        if "webhook" in channels_config:
            self._channels["webhook"] = WebhookAlertChannel(channels_config["webhook"])

    def _is_duplicate(self, dedup_key: str) -> bool:
        """In-memory deduplication with TTL."""
        now = time.time()
        if dedup_key in self._dedup_cache:
            if now < self._dedup_cache[dedup_key]:
                return True
            else:
                del self._dedup_cache[dedup_key]
        ttl = self.config.get("alert_manager", {}).get(
            "dedup_window_seconds", DEFAULT_DEDUP_WINDOW_SECONDS
        )
        self._dedup_cache[dedup_key] = now + ttl
        return False

    def _is_rate_limited(self, source: str, severity: str) -> bool:
        key = f"{source}:{severity}"
        last_time = self._last_alert_time.get(key)
        if last_time:
            rate_limit = self.config.get("alert_manager", {}).get(
                "rate_limit_seconds", DEFAULT_RATE_LIMIT_SECONDS
            )
            if (datetime.now(UTC) - last_time).total_seconds() < rate_limit:
                return True
        self._last_alert_time[key] = datetime.now(UTC)
        return False

    async def send_alert(
        self,
        title: str,
        message: str,
        severity: str,
        source: str,
        metadata: dict | None = None,
        force: bool = False,
    ) -> bool:
        if not self.config.get("alert_manager", {}).get("enabled", True):
            logger.debug("Alert manager disabled")
            return False
        alert = Alert(title, message, severity, source, metadata)
        dedup_key = alert.get_dedup_key()
        if self._is_duplicate(dedup_key):
            logger.debug(f"Duplicate alert suppressed: {title}")
            return False
        if severity != SEVERITY_CRITICAL and not force:
            if self._is_rate_limited(source, severity):
                logger.debug(f"Rate limited alert from {source}: {title}")
                return False
        self._alert_history.append(alert)
        if len(self._alert_history) > 1000:
            self._alert_history = self._alert_history[-1000:]

        channels_to_send = []
        severity_order = [SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_ERROR, SEVERITY_CRITICAL]
        sev_index = severity_order.index(severity)
        for name, channel in self._channels.items():
            if not channel.enabled:
                continue
            channel_config = self.config.get("channels", {}).get(name, {})
            min_severity = channel_config.get("min_severity", SEVERITY_WARNING)
            min_index = severity_order.index(min_severity)
            if sev_index >= min_index:
                channels_to_send.append(channel)

        tasks = [channel.send(alert) for channel in channels_to_send]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        sent_count = sum(1 for r in results if r is True)
        if sent_count > 0:
            logger.info(f"Alert sent: {title} to {sent_count} channels")
        else:
            logger.warning(f"Alert not sent to any channel: {title}")
        return sent_count > 0

    async def add_channel(self, name: str, channel: BaseAlertChannel) -> None:
        self._channels[name] = channel

    def get_history(self, limit: int = 100) -> list[dict]:
        return [a.to_dict() for a in self._alert_history[-limit:]]

    async def clear_history(self) -> None:
        self._alert_history.clear()
        logger.info("Alert history cleared")

    async def test_alerts(self) -> dict[str, bool]:
        results = {}
        test_alert = Alert(
            "Test Alert",
            "This is a test alert from ERP system",
            SEVERITY_INFO,
            "AlertManagerRouter",
        )
        for name, channel in self._channels.items():
            try:
                result = await channel.send(test_alert)
                results[name] = result
            except Exception as e:
                logger.error(f"Test failed for channel {name}: {e}")
                results[name] = False
        return results


_alert_manager: AlertManagerRouter | None = None


async def get_alert_manager() -> AlertManagerRouter:
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManagerRouter()
    return _alert_manager


async def trigger_alert(
    title: str,
    message: str,
    severity: str = "warning",
    source: str = "system",
    metadata: dict | None = None,
) -> bool:
    manager = await get_alert_manager()
    return await manager.send_alert(title, message, severity, source, metadata)


__all__ = [
    "SEVERITY_CRITICAL",
    "SEVERITY_ERROR",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "Alert",
    "AlertManagerRouter",
    "get_alert_manager",
    "trigger_alert",
]
