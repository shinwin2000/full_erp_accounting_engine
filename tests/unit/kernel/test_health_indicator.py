#!/usr/bin/env python3
"""
Module: test_health_indicator.py
Layer: Tests / Unit / Kernel

Responsibility:
    Unit tests untuk health indicator (liveness/readiness probes).
"""

from __future__ import annotations

import asyncio
import threading  # <-- Kita gunakan threading murni untuk kendali penuh atas loop

import pytest

from kernel.health_indicator import HealthCheckRegistry, HealthIndicator, HealthStatus


def test_health_indicator_checks():
    indicator = HealthIndicator()
    indicator.register_check("database", lambda: True)
    indicator.register_check("cache", lambda: False)

    status = indicator.check_health()
    assert status.status == HealthStatus.DEGRADED
    assert status.details["database"] is True
    assert status.details["cache"] is False


def test_health_indicator_with_async_check():
    indicator = HealthIndicator()

    async def async_check():
        await asyncio.sleep(0.01)
        return True

    indicator.register_async_check("async_db", async_check)

    # Pindahkan eksekusi ke thread terisolasi DAN buat loop yang bersih
    res = {}

    def worker():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)  # Daftarkan loop khusus untuk thread ini
            res["status"] = indicator.check_health()
            loop.close()
        except Exception as e:
            res["error"] = e

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    if "error" in res:
        raise res["error"]

    assert res["status"].status == HealthStatus.HEALTHY


def test_health_check_registry():
    registry = HealthCheckRegistry()
    registry.register("db", lambda: True)
    registry.register("cache", lambda: False)
    results = registry.run_all()
    assert results["db"] is True
    assert results["cache"] is False


def test_health_check_timeout():
    registry = HealthCheckRegistry(timeout=0.1)

    async def slow_check():
        await asyncio.sleep(0.5)
        return True

    registry.register_async("slow", slow_check)

    # Terapkan isolasi yang sama di sini agar pengetesan timeout benar-benar valid,
    # bukan lolos karena loop-nya yang crash di latar belakang.
    res = {}

    def worker():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            res["results"] = registry.run_all()
            loop.close()
        except Exception as e:
            res["error"] = e

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    if "error" in res:
        raise res["error"]

    assert res["results"]["slow"] is False  # timeout


if __name__ == "__main__":
    pytest.main([__file__])
