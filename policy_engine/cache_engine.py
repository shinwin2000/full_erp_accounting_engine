#!/usr/bin/env python3
"""
Module: cache_engine.py
Layer: 7 - Policy Engine

Responsibility:
    Caching untuk kebijakan dengan fitur:
    - TTL (Time-To-Live) per entry
    - LRU eviction (jika limit ditentukan)
    - Statistik cache (hits, misses, evictions)
    - Warmup (preload) dari data awal
    - Invalidation berdasarkan pattern (wildcard)
    - Persistence (save/load to disk) opsional
    - Distributed cache via Redis (opsional, fallback ke memory)
    - Thread-safe dengan RLock
    - Singleton pattern (DISABLED for testing)

Dependencies:
    - threading, time, pickle (optional), redis (optional)
    - logging, typing, collections

Audit: Setiap cache hit/miss/eviction/invalidation dicatat.
"""

from __future__ import annotations

import hashlib
import json
import logging
import pickle
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Optional Redis support
try:
    import redis

    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False


# ============================================================================
# Constants & Exceptions
# ============================================================================
class CacheError(Exception):
    """Base exception untuk cache engine."""

    pass


class CacheKeyError(CacheError):
    """Error terkait key cache."""

    pass


# ============================================================================
# Cache Entry
# ============================================================================
@dataclass
class CacheEntry:
    """Entri dalam cache."""

    key: str
    value: Any
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_access: datetime = field(default_factory=lambda: datetime.now(UTC))
    ttl_seconds: int = 300  # Default 5 minutes
    access_count: int = 0
    size_bytes: int = 0  # Approximate size

    def __post_init__(self):
        self.size_bytes = len(str(self.value)) if self.value else 0

    def is_expired(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        age = (now - self.created_at).total_seconds()
        return age > self.ttl_seconds

    def touch(self) -> None:
        self.last_access = datetime.now(UTC)
        self.access_count += 1

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "value": self.value,
            "created_at": self.created_at.isoformat(),
            "last_access": self.last_access.isoformat(),
            "ttl_seconds": self.ttl_seconds,
            "access_count": self.access_count,
            "size_bytes": self.size_bytes,
        }


# ============================================================================
# Cache Engine Core (No Singleton)
# ============================================================================
class PolicyCacheEngine:
    """
    Cache engine untuk policy engine dengan multiple backends.
    Every instance is independent (no singleton).
    """

    def __init__(
        self,
        max_size: int | None = None,  # None = unlimited
        default_ttl_seconds: int = 300,
        default_ttl: int | None = None,  # Alias for test compatibility
        enable_redis: bool = False,
        redis_url: str | None = None,
        redis_prefix: str = "policy_cache:",
        persistence_file: str | None = None,
    ):
        self._lock = threading.RLock()
        self._cache: dict[str, CacheEntry] = {}
        self._max_size = max_size
        # Use default_ttl if provided (for test), otherwise default_ttl_seconds
        if default_ttl is not None:
            self._default_ttl = default_ttl
        else:
            self._default_ttl = default_ttl_seconds
        self._persistence_file = persistence_file
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "sets": 0,
            "invalidations": 0,
        }

        # Redis backend
        self._redis_enabled = enable_redis and HAS_REDIS
        self._redis_client: redis.Redis | None = None
        self._redis_prefix = redis_prefix
        if self._redis_enabled and redis_url:
            try:
                self._redis_client = redis.from_url(redis_url, decode_responses=True)
                self._redis_client.ping()
                logger.info("Redis cache backend connected")
            except Exception as e:
                logger.warning(f"Redis connection failed: {e}, falling back to memory")
                self._redis_enabled = False

        # Load from persistence if available
        if self._persistence_file:
            self._load_from_disk()

        # Start cleanup thread
        self._cleanup_thread: threading.Thread | None = None
        self._running = True
        self._start_cleanup_thread()

    # ------------------------------------------------------------------------
    # Key Generation
    # ------------------------------------------------------------------------
    @staticmethod
    def make_key(*args, **kwargs) -> str:
        """Membuat key unik dari argumen (deterministik)."""
        key_parts = []
        for arg in args:
            key_parts.append(str(arg))
        for k, v in sorted(kwargs.items()):
            key_parts.append(f"{k}={v}")
        key_str = "|".join(key_parts)
        # Hash untuk memastikan panjang key tidak berlebihan
        return hashlib.md5(key_str.encode()).hexdigest()

    @staticmethod
    def make_key_from_dict(data: dict, prefix: str = "") -> str:
        """Membuat key dari dictionary (sorted)."""
        sorted_json = json.dumps(data, sort_keys=True, default=str)
        key = hashlib.sha256(sorted_json.encode()).hexdigest()
        return f"{prefix}{key}" if prefix else key

    # ------------------------------------------------------------------------
    # Core Operations
    # ------------------------------------------------------------------------
    def get(self, key: str, update_stats: bool = True) -> Any | None:
        """
        Mendapatkan nilai dari cache. Return None jika tidak ada atau expired.
        """
        # Try Redis first if enabled
        if self._redis_enabled and self._redis_client:
            try:
                redis_key = f"{self._redis_prefix}{key}"
                value_json = self._redis_client.get(redis_key)
                if value_json:
                    data = json.loads(value_json)
                    # Check TTL
                    if "expires_at" in data and datetime.fromisoformat(
                        data["expires_at"]
                    ) > datetime.now(UTC):
                        if update_stats:
                            self._stats["hits"] += 1
                        return data["value"]
                    else:
                        self._redis_client.delete(redis_key)
            except Exception as e:
                logger.warning(f"Redis get failed: {e}")

        # Memory cache
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                if update_stats:
                    self._stats["misses"] += 1
                return None
            if entry.is_expired():
                self._cache.pop(key, None)
                if update_stats:
                    self._stats["evictions"] += 1
                return None
            entry.touch()
            if update_stats:
                self._stats["hits"] += 1
            return entry.value

    def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: int | None = None,
        force: bool = False,
    ) -> None:
        """
        Menyimpan nilai ke cache dengan TTL.
        """
        ttl = ttl_seconds or self._default_ttl

        # Redis backend
        if self._redis_enabled and self._redis_client:
            try:
                expires_at = (datetime.now(UTC) + timedelta(seconds=ttl)).isoformat()
                data = {"value": value, "expires_at": expires_at}
                redis_key = f"{self._redis_prefix}{key}"
                self._redis_client.setex(redis_key, ttl, json.dumps(data, default=str))
            except Exception as e:
                logger.warning(f"Redis set failed: {e}")

        # Memory cache
        with self._lock:
            # Check size limit (evict oldest if needed)
            if (
                self._max_size is not None
                and len(self._cache) >= self._max_size
                and key not in self._cache
            ):
                self._evict_one()

            entry = CacheEntry(key=key, value=value, ttl_seconds=ttl)
            self._cache[key] = entry
            self._stats["sets"] += 1
            logger.debug(f"Cached key {key} with TTL {ttl}s")

    def get_or_compute(
        self,
        compute_func: Callable,
        ttl_seconds: int | None = None,
        *args,
        **kwargs,
    ) -> Any:
        """
        Mendapatkan dari cache atau menghitung jika tidak ada.
        compute_func akan dipanggil dengan *args, **kwargs.
        """
        key = self.make_key(compute_func.__name__, *args, **kwargs)
        value = self.get(key)
        if value is not None:
            return value
        value = compute_func(*args, **kwargs)
        self.set(key, value, ttl_seconds)
        return value

    def get_or_compute_dict(
        self,
        compute_func: Callable,
        dict_data: dict,
        ttl_seconds: int | None = None,
    ) -> Any:
        """Seperti get_or_compute tetapi menggunakan dictionary sebagai input."""
        key = self.make_key_from_dict(dict_data, prefix=compute_func.__name__)
        value = self.get(key)
        if value is not None:
            return value
        value = compute_func(dict_data)
        self.set(key, value, ttl_seconds)
        return value

    # ------------------------------------------------------------------------
    # Invalidation
    # ------------------------------------------------------------------------
    def invalidate(self, key: str) -> bool:
        """Menghapus entry dari cache."""
        # Redis
        if self._redis_enabled and self._redis_client:
            try:
                self._redis_client.delete(f"{self._redis_prefix}{key}")
            except Exception as e:
                logger.warning(f"Redis invalidate failed: {e}")

        # Memory
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                self._stats["invalidations"] += 1
                logger.debug(f"Invalidated key {key}")
                return True
            return False

    def invalidate_pattern(self, pattern: str) -> int:
        """
        Menghapus entry yang key-nya mengandung pattern (substring).
        Untuk memory cache dan Redis (SCAN).
        """
        count = 0
        # Redis
        if self._redis_enabled and self._redis_client:
            try:
                cursor = 0
                while True:
                    cursor, keys = self._redis_client.scan(
                        cursor, match=f"{self._redis_prefix}*{pattern}*", count=100
                    )
                    if keys:
                        self._redis_client.delete(*keys)
                        count += len(keys)
                    if cursor == 0:
                        break
            except Exception as e:
                logger.warning(f"Redis pattern invalidation failed: {e}")

        # Memory
        with self._lock:
            keys_to_remove = [k for k in self._cache if pattern in k]
            for k in keys_to_remove:
                del self._cache[k]
                count += 1
        logger.info(f"Invalidated {count} keys matching pattern '{pattern}'")
        return count

    def invalidate_all(self) -> int:
        """Menghapus semua cache."""
        count = len(self._cache)
        with self._lock:
            self._cache.clear()
        if self._redis_enabled and self._redis_client:
            try:
                cursor = 0
                while True:
                    cursor, keys = self._redis_client.scan(
                        cursor, match=f"{self._redis_prefix}*", count=100
                    )
                    if keys:
                        self._redis_client.delete(*keys)
                    if cursor == 0:
                        break
            except Exception as e:
                logger.warning(f"Redis flush failed: {e}")
        logger.info(f"Invalidated all {count} cache entries")
        return count

    def _evict_one(self) -> None:
        """Evict one entry based on LRU (least recently accessed)."""
        if not self._cache:
            return
        # LRU: find entry with oldest last_access
        oldest_key = min(self._cache.items(), key=lambda x: x[1].last_access)[0]
        del self._cache[oldest_key]
        self._stats["evictions"] += 1
        logger.debug(f"Evicted key {oldest_key} due to size limit")

    # ------------------------------------------------------------------------
    # Statistics & Monitoring
    # ------------------------------------------------------------------------
    def get_stats(self) -> dict[str, Any]:
        """Mendapatkan statistik cache."""
        with self._lock:
            total_requests = self._stats["hits"] + self._stats["misses"]
            hit_rate = (self._stats["hits"] / total_requests * 100) if total_requests > 0 else 0
            return {
                "hits": self._stats["hits"],
                "misses": self._stats["misses"],
                "evictions": self._stats["evictions"],
                "sets": self._stats["sets"],
                "invalidations": self._stats["invalidations"],
                "size": len(self._cache),
                "max_size": self._max_size if self._max_size is not None else "unlimited",
                "hit_rate_percent": round(hit_rate, 2),
            }

    def get_keys(self, pattern: str | None = None) -> list[str]:
        """Mendapatkan daftar key di cache (memory only)."""
        with self._lock:
            if pattern:
                return [k for k in self._cache if pattern in k]
            return list(self._cache.keys())

    def get_ttl_remaining(self, key: str) -> int | None:
        """Mendapatkan sisa TTL dalam detik."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            age = (datetime.now(UTC) - entry.created_at).total_seconds()
            return max(0, entry.ttl_seconds - int(age))

    def contains(self, key: str) -> bool:
        """Cek apakah key ada dan belum expired."""
        return self.get(key, update_stats=False) is not None

    # ------------------------------------------------------------------------
    # Warmup & Persistence
    # ------------------------------------------------------------------------
    def warmup(self, items: dict[str, Any], ttl_seconds: int | None = None) -> int:
        """
        Mengisi cache dengan data awal (warmup).
        items: dict key -> value
        """
        ttl = ttl_seconds or self._default_ttl
        count = 0
        for key, value in items.items():
            self.set(key, value, ttl)
            count += 1
        logger.info(f"Warmed up cache with {count} items")
        return count

    def _save_to_disk(self) -> None:
        """Simpan cache ke disk (pickle)."""
        if not self._persistence_file:
            return
        try:
            with self._lock:
                # Save only non-expired entries
                now = datetime.now(UTC)
                valid_entries = {k: v for k, v in self._cache.items() if not v.is_expired(now)}
            with open(self._persistence_file, "wb") as f:
                pickle.dump(valid_entries, f)
            logger.info(f"Saved {len(valid_entries)} cache entries to {self._persistence_file}")
        except Exception as e:
            logger.error(f"Failed to save cache to disk: {e}")

    def _load_from_disk(self) -> None:
        """Load cache dari disk (pickle, konsisten dengan _save_to_disk)."""
        if not self._persistence_file:
            return
        try:
            import os

            if not os.path.exists(self._persistence_file):
                return

            with open(self._persistence_file, "rb") as f:
                entries = pickle.load(f)

            now = datetime.now(UTC)
            with self._lock:
                for key, entry in entries.items():
                    if not entry.is_expired(now):
                        self._cache[key] = entry
            logger.info(f"Loaded {len(self._cache)} cache entries from disk")
        except Exception as e:
            logger.warning(f"Failed to load cache from disk: {e}")

    def persist(self) -> bool:
        """Simpan cache ke disk secara manual."""
        try:
            self._save_to_disk()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------------
    # Cleanup Thread
    # ------------------------------------------------------------------------
    def _start_cleanup_thread(self, interval_seconds: int = 60) -> None:
        """Start background thread untuk membersihkan expired entries."""

        def cleanup():
            while self._running:
                try:
                    self._cleanup_expired()
                except Exception as e:
                    logger.error(f"Cleanup error: {e}")
                time.sleep(interval_seconds)

        self._cleanup_thread = threading.Thread(target=cleanup, daemon=True)
        self._cleanup_thread.start()

    def _cleanup_expired(self) -> int:
        """Hapus entry yang expired dari memory cache."""
        now = datetime.now(UTC)
        with self._lock:
            expired_keys = [k for k, v in self._cache.items() if v.is_expired(now)]
            for k in expired_keys:
                del self._cache[k]
        count = len(expired_keys)
        if count:
            logger.debug(f"Cleaned up {count} expired cache entries")
        return count

    def stop_cleanup(self) -> None:
        """Stop background cleanup thread."""
        self._running = False
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)

    # ------------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------------
    def generate_report(self) -> dict:
        """Generate laporan cache engine."""
        stats = self.get_stats()
        return {
            "stats": stats,
            "config": {
                "max_size": self._max_size,
                "default_ttl_seconds": self._default_ttl,
                "redis_enabled": self._redis_enabled,
                "persistence_file": self._persistence_file,
            },
            "summary": {
                "hit_rate": f"{stats['hit_rate_percent']}%",
                "total_requests": stats["hits"] + stats["misses"],
            },
        }

    def export_to_json(self, file_path: str) -> None:
        """Export cache report ke JSON."""
        import json

        report = self.generate_report()
        with open(file_path, "w") as f:
            json.dump(report, f, indent=2, default=str)


# ============================================================================
# Singleton Accessor (Kept for backward compatibility, but returns new instance)
# ============================================================================
_policy_cache_engine_instance: PolicyCacheEngine | None = None


def get_policy_cache_engine() -> PolicyCacheEngine:
    """Mendapatkan instance singleton PolicyCacheEngine (kept for compatibility)."""
    global _policy_cache_engine_instance
    if _policy_cache_engine_instance is None:
        _policy_cache_engine_instance = PolicyCacheEngine()
    return _policy_cache_engine_instance


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    cache = PolicyCacheEngine(max_size=100, default_ttl_seconds=10)

    # Set and get
    cache.set("key1", "value1")
    print(f"key1: {cache.get('key1')}")

    # Get or compute
    def expensive_compute(a, b):
        return a + b

    result = cache.get_or_compute(expensive_compute, 5, 3, 2)  # 3+2=5
    print(f"Computed: {result}")

    # Stats
    print("Stats:", cache.get_stats())

    # Wait for expiry
    time.sleep(11)
    print(f"key1 after expiry: {cache.get('key1')}")

    # Invalidate pattern
    cache.set("test_abc", "123")
    cache.set("test_def", "456")
    cache.invalidate_pattern("test_")
    print("Cache keys after pattern invalidation:", cache.get_keys())

    # Report
    cache.export_to_json("cache_report.json")
    print("Report exported")
