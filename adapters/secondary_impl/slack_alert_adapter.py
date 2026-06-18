#!/usr/bin/env python3
"""
Module: slack_alert_adapter.py
Layer: Adapters (Secondary Implementation)
Responsibility: Mengirim alert ke Slack via webhook.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class SlackAlertAdapter:
    """
    Adapter untuk Slack webhook.
    Stub, hanya log.
    """

    def __init__(self, webhook_url: str = "https://hooks.slack.com/mock"):
        self.webhook_url = webhook_url

    async def send_message(
        self, channel: str, message: str, blocks: list[dict] | None = None
    ) -> bool:
        logger.info(f"Slack message to {channel}: {message}")
        return True
