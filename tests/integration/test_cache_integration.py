#!/usr/bin/env python3
"""
Integration: Redis Cache
Menguji operasi dasar cache (set, get, delete, TTL, invalidation) dan
penggunaan cache di repository/service.
"""

from __future__ import annotations

import time

import pytest

from infrastructure.caching.namespace_isolation import NamespaceIsolation
from infrastructure.caching.redis_manager import RedisCacheManager


@pytest.fixture
def cache_manager():
    # Skip jika Redis tidak tersedia
    try:
        mgr = RedisCacheManager(host="localhost", port=6379, db=1)
        mgr.ping()
        mgr.flushdb()
        return mgr
    except Exception:
        pytest.skip("Redis tidak tersedia")


def test_cache_set_get_delete(cache_manager):
    cache_manager.set("key1", "value1", ttl=60)
    value = cache_manager.get("key1")
    assert value == "value1"

    cache_manager.delete("key1")
    value = cache_manager.get("key1")
    assert value is None


def test_cache_ttl_expiration(cache_manager):
    cache_manager.set("temp_key", "temp_value", ttl=1)
    time.sleep(1.5)
    value = cache_manager.get("temp_key")
    assert value is None


def test_namespace_isolation(cache_manager):
    ns1 = NamespaceIsolation(cache_manager, namespace="app1")
    ns2 = NamespaceIsolation(cache_manager, namespace="app2")
    ns1.set("shared_key", "value from app1")
    ns2.set("shared_key", "value from app2")
    assert ns1.get("shared_key") == "value from app1"
    assert ns2.get("shared_key") == "value from app2"


def test_cache_invalidation_on_event(cache_manager):
    # Simulasi: cache account balance
    cache_manager.set("balance:ACC-001", Decimal("1000000"))
    # Ketika terjadi event JournalPosted, invalidasi cache
    from infrastructure.caching.invalidator_event_listener import CacheInvalidator

    invalidator = CacheInvalidator(cache_manager)
    invalidator.handle_event({"type": "JournalPosted", "account": "ACC-001"})
    value = cache_manager.get("balance:ACC-001")
    assert value is None
