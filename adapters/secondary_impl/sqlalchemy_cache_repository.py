#!/usr/bin/env python3
"""
SQLAlchemy implementation of CachePort using in-memory or Redis.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from ports.primary.cache_port import CachePort

logger = logging.getLogger(__name__)


class _InMemoryCache:
    """
    Simple in-memory cache store (private helper, not a repository implementation).
    Digunakan oleh SQLAlchemyCacheRepository sebagai fallback ketika Redis tidak dipakai.
    """
    def __init__(self):
        self._store: dict[str, tuple[Any, datetime]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            if key not in self._store:
                return None
            value, expiry = self._store[key]
            if expiry and datetime.now() > expiry:
                del self._store[key]
                return None
            return value

    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        async with self._lock:
            expiry = datetime.now() + timedelta(seconds=ttl) if ttl > 0 else None
            self._store[key] = (value, expiry)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def exists(self, key: str) -> bool:
        async with self._lock:
            if key not in self._store:
                return False
            value, expiry = self._store[key]
            if expiry and datetime.now() > expiry:
                del self._store[key]
                return False
            return True


class SQLAlchemyCacheRepository(CachePort):
    """
    Implementasi CachePort menggunakan in‑memory (default) atau Redis.
    """
    def __init__(self, use_redis: bool = False, redis_client: Any = None):
        self._use_redis = use_redis
        self._redis_client = redis_client
        if not use_redis:
            self._memory_cache = _InMemoryCache()

    async def get(self, key: str) -> Any | None:
        if self._use_redis and self._redis_client:
            try:
                value = await self._redis_client.get(key)
                if value:
                    return json.loads(value)
            except Exception as e:
                logger.error("Redis get error for key %s: %s", key, e)
                return None
        else:
            return await self._memory_cache.get(key)

    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        if self._use_redis and self._redis_client:
            try:
                await self._redis_client.setex(key, ttl, json.dumps(value, default=str))
            except Exception as e:
                logger.error("Redis set error for key %s: %s", key, e)
        else:
            await self._memory_cache.set(key, value, ttl)

    async def delete(self, key: str) -> None:
        if self._use_redis and self._redis_client:
            try:
                await self._redis_client.delete(key)
            except Exception as e:
                logger.error("Redis delete error for key %s: %s", key, e)
        else:
            await self._memory_cache.delete(key)

    async def exists(self, key: str) -> bool:
        if self._use_redis and self._redis_client:
            try:
                return await self._redis_client.exists(key) > 0
            except Exception as e:
                logger.error("Redis exists error for key %s: %s", key, e)
                return False
        else:
            return await self._memory_cache.exists(key)


# ============================================================================
# Alias untuk kompatibilitas (diperlukan oleh __init__.py)
# ============================================================================
CacheAdapter = SQLAlchemyCacheRepository
SQLAlchemyCacheAdapter = SQLAlchemyCacheRepository


# ============================================================================
# Ekspor
# ============================================================================
__all__ = [
    "CacheAdapter",
    "SQLAlchemyCacheAdapter",
    "SQLAlchemyCacheRepository",
]
