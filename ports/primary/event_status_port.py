#!/usr/bin/env python3
"""
Module: event_status_port.py
Layer: Ports (Primary)
Responsibility: Port interface untuk manajemen status event.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class EventStatusPort(ABC):
    """
    Port untuk menyimpan dan mengambil status event.
    """

    @abstractmethod
    async def get_status(self, event_id: str) -> dict[str, Any] | None:
        """Ambil status event berdasarkan event_id."""
        pass

    @abstractmethod
    async def set_status(self, event_id: str, status: str, message: str | None = None) -> dict[str, Any]:
        """Set status event (insert atau update)."""
        pass

    @abstractmethod
    async def delete_status(self, event_id: str) -> bool:
        """Hapus status event."""
        pass


__all__ = ["EventStatusPort"]