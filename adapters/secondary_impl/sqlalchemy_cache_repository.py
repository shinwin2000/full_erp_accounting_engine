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


class InMemoryCache:
    """Simple in-memory cache store."""
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
    Cache repository using in-memory cache by default.
    Can be extended to use Redis by passing redis_client.
    """
    def __init__(self, use_redis: bool = False, redis_client: Any = None):
        self._use_redis = use_redis
        self._redis_client = redis_client
        if not use_redis:
            self._memory_cache = InMemoryCache()

    async def get(self, key: str) -> Any | None:
        if self._use_redis and self._redis_client:
            try:
                value = await self._redis_client.get(key)
                if value:
                    return json.loads(value)
            except Exception as e:
                logger.error(f"Redis get error: {e}")
                return None
        else:
            return await self._memory_cache.get(key)

    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        if self._use_redis and self._redis_client:
            try:
                await self._redis_client.setex(key, ttl, json.dumps(value, default=str))
            except Exception as e:
                logger.error(f"Redis set error: {e}")
        else:
            await self._memory_cache.set(key, value, ttl)

    async def delete(self, key: str) -> None:
        if self._use_redis and self._redis_client:
            try:
                await self._redis_client.delete(key)
            except Exception as e:
                logger.error(f"Redis delete error: {e}")
        else:
            await self._memory_cache.delete(key)

    async def exists(self, key: str) -> bool:
        if self._use_redis and self._redis_client:
            try:
                return await self._redis_client.exists(key) > 0
            except Exception as e:
                logger.error(f"Redis exists error: {e}")
                return False
        else:
            return await self._memory_cache.exists(key)


# ============================================================================
# ALIAS UNTUK BACKWARD COMPATIBILITY (diperlukan oleh __init__.py)
# ============================================================================
CacheAdapter = SQLAlchemyCacheRepository
SQLAlchemyCacheAdapter = SQLAlchemyCacheRepository


# ============================================================================
# EXPORTS
# ============================================================================
__all__ = [
    "CacheAdapter",
    "InMemoryCache",
    "SQLAlchemyCacheAdapter",
    "SQLAlchemyCacheRepository",
]
