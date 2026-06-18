#!/usr/bin/env python3
"""
Module: email_smtp_notification.py
Layer: Adapters (Secondary Implementation)
Responsibility: Mengirim notifikasi email via SMTP.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class EmailSMTPNotification:
    """
    Adapter untuk notifikasi email.
    Stub, tidak benar-benar mengirim email.
    """

    def __init__(
        self,
        smtp_host: str = "localhost",
        smtp_port: int = 25,
        username: str | None = None,
        password: str | None = None,
    ):
        self.host = smtp_host
        self.port = smtp_port
        self.username = username
        self.password = password

    async def send(self, to: list[str], subject: str, body: str, html: str | None = None) -> bool:
        """Kirim email."""
        logger.info(f"Sending email to {to}: {subject}")
        # For stub, just log
        return True
