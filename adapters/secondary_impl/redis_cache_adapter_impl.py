#!/usr/bin/env python3
"""
Module: redis_cache_adapter_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Cache adapter menggunakan Redis.
Menyediakan method yang dibutuhkan oleh application layer:
- connect(), disconnect(), ping()
- get(), set(), setex(), exists(), delete()
- method lain seperti incr, decr, dll (opsional)
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RedisCacheAdapter:
    """
    Adapter untuk Redis cache.
    """

    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0):
        self.host = host
        self.port = port
        self.db = db
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        """Establish connection to Redis."""
        if self._client is None:
            self._client = await redis.from_url(
                f"redis://{self.host}:{self.port}/{self.db}",
                decode_responses=True,
            )
            logger.info(f"RedisCacheAdapter connected to {self.host}:{self.port}/{self.db}")

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("RedisCacheAdapter disconnected")

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            await self.connect()
        return self._client

    async def ping(self) -> bool:
        """Check if Redis is responsive."""
        try:
            client = await self._get_client()
            return await client.ping()
        except Exception:
            return False

    async def get(self, key: str) -> Any | None:
        """Get value by key, deserialize JSON."""
        client = await self._get_client()
        value = await client.get(key)
        if value is None:
            return None
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """Set value with TTL (seconds)."""
        client = await self._get_client()
        if not isinstance(value, (str, bytes)):
            value = json.dumps(value, default=str)
        await client.setex(key, ttl, value)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        """Set string value with TTL (seconds)."""
        client = await self._get_client()
        await client.setex(key, ttl, value)

    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        client = await self._get_client()
        return await client.exists(key) > 0

    async def delete(self, *keys: str) -> int:
        """Delete one or more keys."""
        client = await self._get_client()
        return await client.delete(*keys)

    async def expire(self, key: str, ttl: int) -> bool:
        """Set expiration on existing key."""
        client = await self._get_client()
        return await client.expire(key, ttl)

    async def incr(self, key: str, amount: int = 1) -> int:
        """Increment counter."""
        client = await self._get_client()
        return await client.incr(key, amount)

    async def decr(self, key: str, amount: int = 1) -> int:
        """Decrement counter."""
        client = await self._get_client()
        return await client.decr(key, amount)

    async def sadd(self, key: str, *members: str) -> int:
        """Add members to a set."""
        client = await self._get_client()
        return await client.sadd(key, *members)

    async def srem(self, key: str, *members: str) -> int:
        """Remove members from a set."""
        client = await self._get_client()
        return await client.srem(key, *members)

    async def smembers(self, key: str) -> set:
        """Get all members of a set."""
        client = await self._get_client()
        return await client.smembers(key)

    async def hset(self, key: str, field: str, value: Any) -> int:
        """Set field in hash."""
        client = await self._get_client()
        if not isinstance(value, (str, bytes)):
            value = json.dumps(value, default=str)
        return await client.hset(key, field, value)

    async def hget(self, key: str, field: str) -> Any | None:
        """Get field from hash."""
        client = await self._get_client()
        value = await client.hget(key, field)
        if value is None:
            return None
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value

    async def hgetall(self, key: str) -> dict[str, Any]:
        """Get all fields from hash."""
        client = await self._get_client()
        return await client.hgetall(key)

    async def lpush(self, key: str, *values: str) -> int:
        """Push to left of list."""
        client = await self._get_client()
        return await client.lpush(key, *values)

    async def rpush(self, key: str, *values: str) -> int:
        """Push to right of list."""
        client = await self._get_client()
        return await client.rpush(key, *values)

    async def lpop(self, key: str) -> str | None:
        """Pop from left of list."""
        client = await self._get_client()
        return await client.lpop(key)

    async def rpop(self, key: str) -> str | None:
        """Pop from right of list."""
        client = await self._get_client()
        return await client.rpop(key)

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        """Get range of list."""
        client = await self._get_client()
        return await client.lrange(key, start, end)

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        """Add to sorted set."""
        client = await self._get_client()
        return await client.zadd(key, mapping)

    async def zrange(self, key: str, start: int, end: int, withscores: bool = False) -> list:
        """Get range from sorted set."""
        client = await self._get_client()
        return await client.zrange(key, start, end, withscores=withscores)

    async def zrevrange(self, key: str, start: int, end: int, withscores: bool = False) -> list:
        """Get reverse range from sorted set."""
        client = await self._get_client()
        return await client.zrevrange(key, start, end, withscores=withscores)

    async def zrem(self, key: str, *members: str) -> int:
        """Remove from sorted set."""
        client = await self._get_client()
        return await client.zrem(key, *members)

    async def zcard(self, key: str) -> int:
        """Get cardinality of sorted set."""
        client = await self._get_client()
        return await client.zcard(key)

    async def zcount(self, key: str, min_score: float, max_score: float) -> int:
        """Count members in score range."""
        client = await self._get_client()
        return await client.zcount(key, min_score, max_score)

    async def keys(self, pattern: str) -> list[str]:
        """Get keys matching pattern."""
        client = await self._get_client()
        return await client.keys(pattern)

    async def flush_db(self) -> bool:
        """Flush current database."""
        client = await self._get_client()
        await client.flushdb()
        return True

    async def flushdb(self) -> bool:
        return await self.flush_db()


# Alias untuk kompatibilitas dengan kode yang mengharapkan 'RedisManager'
RedisManager = RedisCacheAdapter


__all__ = [
    "RedisCacheAdapter",
    "RedisManager",
]
