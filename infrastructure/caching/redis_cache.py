#!/usr/bin/env python3
"""
Module: redis_cache.py
Layer: Infrastructure (Caching)
Responsibility:
    - Implementasi CachePort. Adapter tipis di atas RedisManager (singleton)
      yang sudah menangani connection pooling, health check, dan retry.
    - Reuse RedisManager singleton yang sama dengan yang dipakai
      JWTValidator â€” tidak membuka connection pool Redis baru.
Dependencies:
- infrastructure.caching.redis_manager (RedisManager, get_redis_manager)
- ports.primary.cache_port (CachePort)
"""

from __future__ import annotations

from typing import Any

from infrastructure.caching.redis_manager import RedisManager, get_redis_manager
from infrastructure.telemetry.structured_json_logging import get_logger
from ports.primary.cache_port import CachePort

logger = get_logger(__name__)


class RedisCache(CachePort):
    """
    Adapter CachePort di atas RedisManager singleton.

    Selain method dari CachePort (get/set/delete/exists), kelas ini juga
    menyediakan `setex` bergaya redis-py karena beberapa pemanggil (mis.
    IAMService, untuk token blacklist) memanggil `setex` langsung tanpa
    lewat kontrak CachePort.
    """

    def __init__(self) -> None:
        self._manager: RedisManager | None = None

    async def _get_manager(self) -> RedisManager:
        if self._manager is None:
            self._manager = await get_redis_manager()
            logger.info("RedisCache attached to RedisManager singleton")
        return self._manager

    async def get(self, key: str) -> Any | None:
        manager = await self._get_manager()
        return await manager.get(key)

    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        manager = await self._get_manager()
        await manager.set(key, value, ttl_seconds=ttl)

    async def delete(self, key: str) -> None:
        manager = await self._get_manager()
        await manager.delete(None, key)

    async def exists(self, key: str) -> bool:
        manager = await self._get_manager()
        return await manager.exists(key)

    async def setex(self, key: str, ttl_seconds: int, value: Any) -> None:
        """Kompatibilitas gaya redis-py: SET dengan TTL wajib."""
        manager = await self._get_manager()
        await manager.set(key, value, ttl_seconds=ttl_seconds)


__all__ = ["RedisCache"]
