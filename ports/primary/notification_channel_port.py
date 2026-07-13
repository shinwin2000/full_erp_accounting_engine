#!/usr/bin/env python3
"""
Module: notification_channel_port.py
Layer: Ports (Primary)
Responsibility: Port interface untuk channel notifikasi.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class NotificationChannelPort(ABC):
    """
    Port untuk mengirim notifikasi melalui berbagai channel.
    """

    @abstractmethod
    async def send(self, channel: str, message: dict[str, Any]) -> dict[str, Any]:
        """
        Kirim notifikasi melalui channel tertentu.

        Args:
            channel: Nama channel (email, whatsapp, sms, slack, push, webhook)
            message: Dict berisi 'to', 'subject', 'body', dll.

        Returns:
            Dict berisi id, channel, recipient, sent_at, status.
        """
        pass

    @abstractmethod
    async def get_logs(self, channel: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """
        Ambil log pengiriman notifikasi.

        Args:
            channel: Filter berdasarkan channel (opsional)
            limit: Maksimal jumlah log

        Returns:
            List dict log notifikasi.
        """
        pass


__all__ = ["NotificationChannelPort"]
