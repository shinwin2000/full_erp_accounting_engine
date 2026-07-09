#!/usr/bin/env python3
"""
Module: file_storage_status_port.py
Layer: Ports (Primary)
Responsibility: Port interface untuk manajemen status file storage.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class FileStorageStatusPort(ABC):
    """
    Port untuk menyimpan dan mengambil status file storage.
    """

    @abstractmethod
    async def get_status(self, file_id: str) -> dict[str, Any] | None:
        """Ambil status file berdasarkan file_id."""
        pass

    @abstractmethod
    async def set_status(self, file_id: str, status: str, file_metadata: str | None = None) -> dict[str, Any]:
        """Set status file (insert atau update)."""
        pass

    @abstractmethod
    async def delete_status(self, file_id: str) -> bool:
        """Hapus status file."""
        pass


__all__ = ["FileStorageStatusPort"]