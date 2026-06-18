# ports/primary/cache_port.py

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CachePort(ABC):
    """Port abstrak untuk operasi caching."""

    @abstractmethod
    async def get(self, key: str) -> Any | None:
        """Ambil nilai dari cache berdasarkan key."""
        ...

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        """Simpan nilai ke cache dengan TTL (detik)."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Hapus key dari cache."""
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Cek apakah key ada di cache."""
        ...
