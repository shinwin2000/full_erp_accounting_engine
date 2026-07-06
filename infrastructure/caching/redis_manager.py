#!/usr/bin/env python3
"""
Module: redis_manager.py
Layer: Infrastructure (Caching)
Responsibility: Mengelola koneksi ke Redis server untuk caching, session storage,
               rate limiting, distributed locking, dan idempotency.

Dependencies (static imports):
- redis.asyncio (ConnectionPool, Redis)
- config.loader_yaml.load_yaml_config
- standard library (asyncio, json, logging)

Tidak mengimpor alert_manager_router untuk menghindari circular import.
Alert disederhanakan dengan logging.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import ConnectionError, RedisError, TimeoutError

from config.loader_yaml import load_yaml_config

logger = logging.getLogger(__name__)

DEFAULT_REDIS_CONFIG = {
    "host": "localhost",
    "port": 6379,
    "db": 0,
    "password": None,
    "decode_responses": True,
    "socket_timeout": 5,
    "socket_connect_timeout": 5,
    "retry_on_timeout": True,
    "max_connections": 50,
    "health_check_interval": 30,
}

CACHE_TTL_5_MINUTES = 300
CACHE_TTL_15_MINUTES = 900
CACHE_TTL_1_HOUR = 3600
CACHE_TTL_1_DAY = 86400
CACHE_TTL_1_WEEK = 604800


# ============================================================================
# IDEMPOTENCY MANAGER (for delete operation)
# ============================================================================

class IdempotencyManager:
    """
    Simple in-memory idempotency manager untuk operasi Redis delete.
    Menyimpan hasil operasi berdasarkan idempotency_key + method_name.
    TTL 24 jam.
    """

    def __init__(self):
        self._storage: dict[str, tuple[str, datetime]] = {}
        self._ttl_seconds = 86400

    def _get_key(self, idempotency_key: str, method_name: str) -> str:
        raw = f"{method_name}:{idempotency_key}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get_cached_result(self, idempotency_key: str, method_name: str) -> dict[str, Any] | None:
        storage_key = self._get_key(idempotency_key, method_name)
        entry = self._storage.get(storage_key)
        if entry is None:
            return None
        result_json, timestamp = entry
        if (datetime.now() - timestamp).total_seconds() > self._ttl_seconds:
            del self._storage[storage_key]
            return None
        try:
            return json.loads(result_json)
        except json.JSONDecodeError:
            return None

    def cache_result(self, idempotency_key: str, method_name: str, result: dict[str, Any]) -> None:
        storage_key = self._get_key(idempotency_key, method_name)
        try:
            result_json = json.dumps(result, default=str)
        except TypeError:
            result_json = json.dumps({"result": str(result)}, default=str)
        self._storage[storage_key] = (result_json, datetime.now())


_idempotency_manager = IdempotencyManager()


# ============================================================================
# EXCEPTIONS
# ============================================================================

class RedisManagerError(Exception):
    pass


class RedisConnectionError(RedisManagerError):
    pass


class RedisOperationError(RedisManagerError):
    pass


# ============================================================================
# REDIS MANAGER
# ============================================================================

class RedisManager:
    _instance: RedisManager | None = None
    _lock = asyncio.Lock()

    def __new__(cls) -> RedisManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.config = DEFAULT_REDIS_CONFIG.copy()
        self._pool: ConnectionPool | None = None
        self._client: Redis | None = None
        self._healthy = False
        self._health_check_task: asyncio.Task | None = None

    def _load_config(self, config_path: str = "config_files/redis_config.yaml") -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            return config.get("redis", DEFAULT_REDIS_CONFIG)
        except Exception as e:
            logger.warning(f"Failed to load Redis config, using defaults: {e}")
            return DEFAULT_REDIS_CONFIG.copy()

    async def _create_connection_pool(self) -> ConnectionPool:
        return ConnectionPool(
            host=self.config.get("host", "localhost"),
            port=self.config.get("port", 6379),
            db=self.config.get("db", 0),
            password=self.config.get("password"),
            decode_responses=self.config.get("decode_responses", True),
            max_connections=self.config.get("max_connections", 50),
            socket_timeout=self.config.get("socket_timeout", 5),
            socket_connect_timeout=self.config.get("socket_connect_timeout", 5),
            retry_on_timeout=self.config.get("retry_on_timeout", True),
            health_check_interval=self.config.get("health_check_interval", 30),
        )

    async def connect(self) -> Redis:
        async with self._lock:
            if self._client is not None and self._healthy:
                return self._client

            try:
                self._pool = await self._create_connection_pool()
                self._client = Redis(connection_pool=self._pool)

                await self._client.ping()
                self._healthy = True

                if self._health_check_task is None or self._health_check_task.done():
                    self._health_check_task = asyncio.create_task(self._health_check_loop())

                logger.info(
                    f"Redis connected to {self.config.get('host')}:{self.config.get('port')} db={self.config.get('db')}"
                )
                return self._client

            except (ConnectionError, TimeoutError, RedisError) as e:
                self._healthy = False
                logger.error(f"Failed to connect to Redis: {e}")
                raise RedisConnectionError(f"Failed to connect to Redis: {e}") from e

    async def disconnect(self) -> None:
        async with self._lock:
            if self._health_check_task and not self._health_check_task.done():
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass

            if self._client:
                await self._client.close()
                self._client = None

            if self._pool:
                await self._pool.disconnect()
                self._pool = None

            self._healthy = False
            logger.info("Redis disconnected")

    async def get_client(self) -> Redis:
        if self._client is None or not self._healthy:
            return await self.connect()
        return self._client

    async def _health_check_loop(self) -> None:
        interval = self.config.get("health_check_interval", 30)
        while True:
            try:
                await asyncio.sleep(interval)
                if self._client:
                    await self._client.ping()
                    if not self._healthy:
                        self._healthy = True
                        logger.info("Redis recovered")
                else:
                    await self.connect()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Redis health check failed: {e}")
                self._healthy = False

    async def is_healthy(self) -> bool:
        if not self._client:
            return False
        try:
            await self._client.ping()
            self._healthy = True
            return True
        except Exception:
            self._healthy = False
            return False

    # --- Cache operations ---

    async def get(self, key: str) -> Any | None:
        client = await self.get_client()
        try:
            value = await client.get(key)
            if value is None:
                return None
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        except RedisError as e:
            logger.error(f"Redis GET error for key {key}: {e}")
            raise RedisOperationError(f"GET failed: {e}") from e

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> bool:
        client = await self.get_client()
        try:
            if not isinstance(value, (str, bytes)):
                value = json.dumps(value, default=str)
            if ttl_seconds:
                await client.setex(key, ttl_seconds, value)
            else:
                await client.set(key, value)
            return True
        except RedisError as e:
            logger.error(f"Redis SET error for key {key}: {e}")
            raise RedisOperationError(f"SET failed: {e}") from e

    async def delete(self, idempotency_key: str | None = None, *keys: str) -> int:
        """
        Delete one or more keys.

        This method is idempotent: repeated calls with the same keys produce
        the same result (number of deleted keys). If an idempotency_key is
        provided, the result is cached to guarantee idempotent behavior.
        """
        if idempotency_key:
            cached = _idempotency_manager.get_cached_result(idempotency_key, "delete")
            if cached is not None:
                return cached.get("result", 0)

        client = await self.get_client()
        try:
            result = await client.delete(*keys)
            if idempotency_key:
                _idempotency_manager.cache_result(idempotency_key, "delete", {"result": result})
            return result
        except RedisError as e:
            logger.error(f"Redis DELETE error: {e}")
            raise RedisOperationError(f"DELETE failed: {e}") from e

    async def exists(self, key: str) -> bool:
        client = await self.get_client()
        try:
            return await client.exists(key) > 0
        except RedisError as e:
            logger.error(f"Redis EXISTS error for key {key}: {e}")
            raise RedisOperationError(f"EXISTS failed: {e}") from e

    async def expire(self, key: str, ttl_seconds: int) -> bool:
        client = await self.get_client()
        try:
            return await client.expire(key, ttl_seconds)
        except RedisError as e:
            logger.error(f"Redis EXPIRE error for key {key}: {e}")
            raise RedisOperationError(f"EXPIRE failed: {e}") from e

    async def incr(self, key: str, amount: int = 1) -> int:
        client = await self.get_client()
        try:
            return await client.incr(key, amount)
        except RedisError as e:
            logger.error(f"Redis INCR error for key {key}: {e}")
            raise RedisOperationError(f"INCR failed: {e}") from e

    async def decr(self, key: str, amount: int = 1) -> int:
        client = await self.get_client()
        try:
            return await client.decr(key, amount)
        except RedisError as e:
            logger.error(f"Redis DECR error for key {key}: {e}")
            raise RedisOperationError(f"DECR failed: {e}") from e

    async def sadd(self, key: str, *members: str) -> int:
        client = await self.get_client()
        try:
            return await client.sadd(key, *members)
        except RedisError as e:
            logger.error(f"Redis SADD error for key {key}: {e}")
            raise RedisOperationError(f"SADD failed: {e}") from e

    async def srem(self, key: str, *members: str) -> int:
        client = await self.get_client()
        try:
            return await client.srem(key, *members)
        except RedisError as e:
            logger.error(f"Redis SREM error for key {key}: {e}")
            raise RedisOperationError(f"SREM failed: {e}") from e

    async def smembers(self, key: str) -> set:
        client = await self.get_client()
        try:
            return await client.smembers(key)
        except RedisError as e:
            logger.error(f"Redis SMEMBERS error for key {key}: {e}")
            raise RedisOperationError(f"SMEMBERS failed: {e}") from e

    async def hset(self, key: str, field: str, value: Any) -> int:
        client = await self.get_client()
        try:
            if not isinstance(value, (str, bytes)):
                value = json.dumps(value, default=str)
            return await client.hset(key, field, value)
        except RedisError as e:
            logger.error(f"Redis HSET error for key {key}: {e}")
            raise RedisOperationError(f"HSET failed: {e}") from e

    async def hget(self, key: str, field: str) -> Any | None:
        client = await self.get_client()
        try:
            value = await client.hget(key, field)
            if value is None:
                return None
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        except RedisError as e:
            logger.error(f"Redis HGET error for key {key}: {e}")
            raise RedisOperationError(f"HGET failed: {e}") from e

    async def hgetall(self, key: str) -> dict[str, Any]:
        client = await self.get_client()
        try:
            return await client.hgetall(key)
        except RedisError as e:
            logger.error(f"Redis HGETALL error for key {key}: {e}")
            raise RedisOperationError(f"HGETALL failed: {e}") from e

    async def lpush(self, key: str, *values: str) -> int:
        client = await self.get_client()
        try:
            return await client.lpush(key, *values)
        except RedisError as e:
            logger.error(f"Redis LPUSH error for key {key}: {e}")
            raise RedisOperationError(f"LPUSH failed: {e}") from e

    async def rpush(self, key: str, *values: str) -> int:
        client = await self.get_client()
        try:
            return await client.rpush(key, *values)
        except RedisError as e:
            logger.error(f"Redis RPUSH error for key {key}: {e}")
            raise RedisOperationError(f"RPUSH failed: {e}") from e

    async def lpop(self, key: str) -> str | None:
        client = await self.get_client()
        try:
            return await client.lpop(key)
        except RedisError as e:
            logger.error(f"Redis LPOP error for key {key}: {e}")
            raise RedisOperationError(f"LPOP failed: {e}") from e

    async def rpop(self, key: str) -> str | None:
        client = await self.get_client()
        try:
            return await client.rpop(key)
        except RedisError as e:
            logger.error(f"Redis RPOP error for key {key}: {e}")
            raise RedisOperationError(f"RPOP failed: {e}") from e

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        client = await self.get_client()
        try:
            return await client.lrange(key, start, end)
        except RedisError as e:
            logger.error(f"Redis LRANGE error for key {key}: {e}")
            raise RedisOperationError(f"LRANGE failed: {e}") from e

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        client = await self.get_client()
        try:
            return await client.zadd(key, mapping)
        except RedisError as e:
            logger.error(f"Redis ZADD error for key {key}: {e}")
            raise RedisOperationError(f"ZADD failed: {e}") from e

    async def zrange(self, key: str, start: int, end: int, withscores: bool = False) -> list:
        client = await self.get_client()
        try:
            return await client.zrange(key, start, end, withscores=withscores)
        except RedisError as e:
            logger.error(f"Redis ZRANGE error for key {key}: {e}")
            raise RedisOperationError(f"ZRANGE failed: {e}") from e

    async def zrevrange(self, key: str, start: int, end: int, withscores: bool = False) -> list:
        client = await self.get_client()
        try:
            return await client.zrevrange(key, start, end, withscores=withscores)
        except RedisError as e:
            logger.error(f"Redis ZREVRANGE error for key {key}: {e}")
            raise RedisOperationError(f"ZREVRANGE failed: {e}") from e

    async def zrem(self, key: str, *members: str) -> int:
        client = await self.get_client()
        try:
            return await client.zrem(key, *members)
        except RedisError as e:
            logger.error(f"Redis ZREM error for key {key}: {e}")
            raise RedisOperationError(f"ZREM failed: {e}") from e

    async def zcard(self, key: str) -> int:
        client = await self.get_client()
        try:
            return await client.zcard(key)
        except RedisError as e:
            logger.error(f"Redis ZCARD error for key {key}: {e}")
            raise RedisOperationError(f"ZCARD failed: {e}") from e

    async def zcount(self, key: str, min_score: float, max_score: float) -> int:
        client = await self.get_client()
        try:
            return await client.zcount(key, min_score, max_score)
        except RedisError as e:
            logger.error(f"Redis ZCOUNT error for key {key}: {e}")
            raise RedisOperationError(f"ZCOUNT failed: {e}") from e

    async def keys(self, pattern: str) -> list[str]:
        client = await self.get_client()
        try:
            return await client.keys(pattern)
        except RedisError as e:
            logger.error(f"Redis KEYS error for pattern {pattern}: {e}")
            raise RedisOperationError(f"KEYS failed: {e}") from e

    async def flush_db(self) -> bool:
        client = await self.get_client()
        try:
            await client.flushdb()
            return True
        except RedisError as e:
            logger.error(f"Redis FLUSHDB error: {e}")
            raise RedisOperationError(f"FLUSHDB failed: {e}") from e

    async def flushdb(self) -> bool:
        return await self.flush_db()

    async def ping(self) -> bool:
        try:
            client = await self.get_client()
            return await client.ping()
        except Exception:
            return False


_redis_manager: RedisManager | None = None


async def get_redis_manager() -> RedisManager:
    global _redis_manager
    if _redis_manager is None:
        _redis_manager = RedisManager()
    return _redis_manager


async def get_redis_client() -> Redis:
    manager = await get_redis_manager()
    return await manager.get_client()


async def ping_redis() -> bool:
    try:
        manager = await get_redis_manager()
        return await manager.ping()
    except Exception:
        return False


async def close_redis() -> None:
    global _redis_manager
    if _redis_manager:
        await _redis_manager.disconnect()
        _redis_manager = None


async def close() -> None:
    """Alias untuk close_redis untuk kompatibilitas daur hidup ASGI."""
    await close_redis()


RedisCacheManager = RedisManager

__all__ = [
    "CACHE_TTL_1_DAY",
    "CACHE_TTL_1_HOUR",
    "CACHE_TTL_1_WEEK",
    "CACHE_TTL_5_MINUTES",
    "CACHE_TTL_15_MINUTES",
    "RedisCacheManager",
    "RedisConnectionError",
    "RedisManager",
    "RedisManagerError",
    "RedisOperationError",
    "close",
    "close_redis",
    "get_redis_client",
    "get_redis_manager",
    "ping_redis",
]