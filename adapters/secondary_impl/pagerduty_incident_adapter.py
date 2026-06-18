#!/usr/bin/env python3
"""
Module: pagerduty_incident_adapter.py
Layer: Adapters (Secondary Implementation)
Responsibility: Membuat incident di PagerDuty untuk alert critical.
Security: API key tidak di-hardcode, diambil dari environment atau konfigurasi.
"""

from __future__ import annotations

import logging
import os
from typing import Any

# Optional HTTP client
try:
    import aiohttp

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    aiohttp = None

logger = logging.getLogger(__name__)


class PagerDutyConfigError(Exception):
    """Konfigurasi PagerDuty tidak valid."""

    pass


class PagerDutyAPIError(Exception):
    """Gagal berkomunikasi dengan PagerDuty API."""

    pass


class PagerDutyIncidentAdapter:
    """
    Adapter untuk PagerDuty Events API v2.
    Kredensial diambil dari environment:
    - PAGERDUTY_API_KEY (wajib) atau PAGERDUTY_ROUTING_KEY
    - PAGERDUTY_SERVICE_ID (opsional, untuk referensi)
    - PAGERDUTY_API_URL (default: https://events.pagerduty.com/v2/enqueue)
    """

    DEFAULT_API_URL = "https://events.pagerduty.com/v2/enqueue"

    def __init__(
        self,
        routing_key: str | None = None,
        api_url: str | None = None,
        service_id: str | None = None,
        timeout_seconds: int = 10,
    ):
        """
        Inisialisasi adapter PagerDuty.
        routing_key (atau PAGERDUTY_API_KEY) wajib diisi.
        """
        # Routing key: bisa dari param, environment, atau fallback (tapi tidak boleh hardcoded)
        self.routing_key = (
            routing_key or os.getenv("PAGERDUTY_API_KEY") or os.getenv("PAGERDUTY_ROUTING_KEY")
        )
        if not self.routing_key:
            raise PagerDutyConfigError(
                "PagerDuty routing key is required. Set PAGERDUTY_API_KEY or PAGERDUTY_ROUTING_KEY environment variable."
            )

        self.api_url = api_url or os.getenv("PAGERDUTY_API_URL", self.DEFAULT_API_URL)
        self.service_id = service_id or os.getenv("PAGERDUTY_SERVICE_ID", "unknown")
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds) if AIOHTTP_AVAILABLE else None

        if not AIOHTTP_AVAILABLE:
            logger.warning(
                "aiohttp not installed, PagerDuty adapter will use mock mode (logs only). Install with: pip install aiohttp"
            )

        logger.info(f"PagerDuty adapter initialized (service: {self.service_id})")

    async def trigger(
        self,
        title: str,
        message: str,
        severity: str = "error",
        source: str = "accounting-engine",
        custom_details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Trigger incident di PagerDuty.
        Returns response dict (success status, dedup_key, dll).
        """
        if not title:
            raise ValueError("Title is required for PagerDuty incident")

        # Severity mapping to PagerDuty event severity
        severity_map = {
            "info": "info",
            "warning": "warning",
            "error": "error",
            "critical": "critical",
        }
        pd_severity = severity_map.get(severity.lower(), "error")

        payload = {
            "routing_key": self.routing_key,
            "event_action": "trigger",
            "payload": {
                "summary": title,
                "severity": pd_severity,
                "source": source,
                "custom_details": custom_details or {"message": message},
            },
            "links": [
                {
                    "href": f"https://your-erp-system.com/alerts?title={title.replace(' ', '_')}",
                    "text": "View in ERP",
                }
            ],
        }

        # Jika aiohttp tidak tersedia, hanya log (mock mode)
        if not AIOHTTP_AVAILABLE:
            logger.critical(
                f"[MOCK] PagerDuty incident: {title} | Severity: {pd_severity} | Message: {message}"
            )
            return {
                "success": False,
                "mock_mode": True,
                "reason": "aiohttp not installed",
                "incident_id": None,
            }

        # Kirim request async ke PagerDuty Events API
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    self.api_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status == 202:
                        data = await resp.json()
                        dedup_key = data.get("dedup_key")
                        logger.info(
                            f"PagerDuty incident triggered: {title} (dedup_key={dedup_key})"
                        )
                        return {
                            "success": True,
                            "status_code": resp.status,
                            "incident_id": dedup_key,
                            "message": "Incident triggered",
                        }
                    else:
                        error_text = await resp.text()
                        logger.error(f"PagerDuty API error {resp.status}: {error_text}")
                        return {
                            "success": False,
                            "status_code": resp.status,
                            "error": error_text,
                        }
        except TimeoutError:
            logger.error(f"PagerDuty API timeout after {self.timeout.total} seconds")
            raise PagerDutyAPIError("Timeout connecting to PagerDuty API")
        except Exception as e:
            logger.exception(f"PagerDuty trigger failed: {e}")
            raise PagerDutyAPIError(f"Failed to trigger incident: {e}") from e

    async def resolve(self, dedup_key: str, resolution_message: str = "Resolved") -> dict[str, Any]:
        """
        Menyelesaikan incident berdasarkan dedup_key.
        """
        if not dedup_key:
            raise ValueError("dedup_key is required to resolve incident")

        payload = {
            "routing_key": self.routing_key,
            "event_action": "resolve",
            "dedup_key": dedup_key,
            "payload": {
                "summary": resolution_message,
                "source": "accounting-engine",
            },
        }

        if not AIOHTTP_AVAILABLE:
            logger.info(f"[MOCK] PagerDuty resolve: dedup_key={dedup_key}")
            return {"success": False, "mock_mode": True}

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(
                    self.api_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status == 202:
                        logger.info(f"Resolved PagerDuty incident: {dedup_key}")
                        return {"success": True, "status_code": resp.status}
                    else:
                        error_text = await resp.text()
                        logger.error(f"Resolve failed: {resp.status} - {error_text}")
                        return {"success": False, "status_code": resp.status, "error": error_text}
        except Exception as e:
            logger.error(f"Resolve error: {e}")
            raise PagerDutyAPIError(f"Failed to resolve incident: {e}") from e

    async def health_check(self) -> dict[str, Any]:
        """Cek apakah routing_key valid (dummy check dengan trigger test)."""
        if not AIOHTTP_AVAILABLE:
            return {"status": "degraded", "reason": "aiohttp missing", "mock_mode": True}
        # Optional: lakukan test trigger dengan event_action=test? PagerDuty tidak mendukung test.
        # Kita hanya cek apakah routing_key tidak kosong.
        if self.routing_key:
            return {
                "status": "configured",
                "routing_key_prefix": self.routing_key[:8] + "...",
                "ready": True,
            }
        return {"status": "misconfigured", "ready": False}


# ============================================================================
# SINGLETON / DEPENDENCY INJECTION
# ============================================================================

_default_adapter: PagerDutyIncidentAdapter | None = None


def get_pagerduty_adapter(
    routing_key: str | None = None,
    service_id: str | None = None,
) -> PagerDutyIncidentAdapter:
    """
    Mendapatkan instance singleton PagerDutyIncidentAdapter.
    Routing key diambil dari environment jika tidak diberikan.
    """
    global _default_adapter
    if _default_adapter is None:
        _default_adapter = PagerDutyIncidentAdapter(
            routing_key=routing_key,
            service_id=service_id,
        )
    return _default_adapter


__all__ = [
    "PagerDutyAPIError",
    "PagerDutyConfigError",
    "PagerDutyIncidentAdapter",
    "get_pagerduty_adapter",
]
