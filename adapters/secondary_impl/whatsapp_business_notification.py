#!/usr/bin/env python3
"""
Module: whatsapp_business_notification.py
Layer: Adapters (Secondary Implementation)
Responsibility: Mengirim notifikasi WhatsApp Business via API.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class WhatsAppBusinessNotification:
    """
    Adapter untuk WhatsApp Business API.
    Stub, hanya log.
    """

    def __init__(self, phone_number_id: str, access_token: str):
        self.phone_number_id = phone_number_id
        self.access_token = access_token

    async def send_text(self, to_number: str, text: str) -> dict[str, Any]:
        logger.info(f"WhatsApp text to {to_number}: {text}")
        return {"message_id": "mock-wa-id", "success": True}

    async def send_template(
        self, to_number: str, template_name: str, language: str = "id"
    ) -> dict[str, Any]:
        logger.info(f"WhatsApp template {template_name} to {to_number}")
        return {"message_id": "mock-template-id", "success": True}
