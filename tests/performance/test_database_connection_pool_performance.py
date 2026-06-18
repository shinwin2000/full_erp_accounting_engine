#!/usr/bin/env python3
"""
Performance: Database Connection Pool Performance
Mengukur waktu akuisisi dan pelepasan koneksi di bawah beban 100 thread.
Menggunakan mock connection pool untuk menghindari dependency pada database real.
"""

from __future__ import annotations

import builtins
import contextlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue

import pytest

# ============================================================================
# MOCK CONNECTION POOL (Thread-safe)
# ============================================================================


class MockConnection:
    """Mock database connection."""

    def __init__(self, conn_id: int):
        self.id = conn_id

    def close(self):
        pass


class MockPsycopg2ConnectionPool:
    """
    Thread-safe mock connection pool yang mensimulasikan getconn/putconn.
    """

    def __init__(self, min_size: int = 5, max_size: int = 20, **kwargs):
        self.min_size = min_size
        self.max_size = max_size
        self._pool: Queue = Queue()
        self._in_use: set = set()
        self._counter = 0
        self._lock = threading.Lock()
        self._init_pool()

    def _init_pool(self):
        for i in range(self.min_size):
            self._pool.put(MockConnection(i))

    def getconn(self):
        try:
            # Try to get from pool with timeout
            conn = self._pool.get(timeout=0.1)
        except:
            # Pool empty, try to create new if under max
            with self._lock:
                if self._counter < self.max_size:
                    self._counter += 1
                    conn = MockConnection(self._counter)
                else:
                    raise Exception("Pool exhausted")
        with self._lock:
            self._in_use.add(conn)
        return conn

    def putconn(self, conn):
        with self._lock:
            if conn in self._in_use:
                self._in_use.remove(conn)
                self._pool.put(conn)

    def closeall(self):
        while not self._pool.empty():
            with contextlib.suppress(builtins.BaseException):
                self._pool.get_nowait()
        with self._lock:
            self._in_use.clear()


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def pool():
    """Mock connection pool untuk testing."""
    return MockPsycopg2ConnectionPool(min_size=10, max_size=50)


# ============================================================================
# PERFORMANCE TEST
# ============================================================================


@pytest.mark.performance
def test_connection_pool_concurrent_acquire_release(benchmark, pool):
    """Benchmark concurrent acquire/release dengan mock pool."""

    def worker():
        conn = pool.getconn()
        time.sleep(0.001)  # simulasi query
        pool.putconn(conn)

    def run_50():
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(worker) for _ in range(50)]
            for f in futures:
                f.result()

    benchmark(run_50)

    try:
        mean_seconds = benchmark.stats.mean
    except AttributeError:
        mean_seconds = benchmark.stats["mean"]
    assert mean_seconds < 5.0


# ============================================================================
# OPSIONAL: Test dengan real pool jika tersedia
# ============================================================================

try:
    from infrastructure.database.connection_pool_psycopg2 import Psycopg2ConnectionPool

    REAL_POOL_AVAILABLE = True
except (ImportError, Exception):
    REAL_POOL_AVAILABLE = False


@pytest.mark.performance
@pytest.mark.skipif(not REAL_POOL_AVAILABLE, reason="Real Psycopg2ConnectionPool unavailable")
def test_connection_pool_concurrent_acquire_release_real(benchmark):
    """Versi real dengan database (skip jika tidak ada database)."""
    try:
        real_pool = Psycopg2ConnectionPool(dsn="postgresql://test:test@localhost:5432/test")
    except TypeError:
        try:
            real_pool = Psycopg2ConnectionPool(
                host="localhost", port=5432, database="test", user="test", password="test"
            )
        except Exception as e:
            pytest.skip(f"Cannot create real connection pool: {e}")

    def worker():
        conn = real_pool.getconn()
        time.sleep(0.001)
        real_pool.putconn(conn)

    def run_50():
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(worker) for _ in range(50)]
            for f in futures:
                f.result()

    benchmark(run_50)
    try:
        mean_seconds = benchmark.stats.mean
    except AttributeError:
        mean_seconds = benchmark.stats["mean"]
    assert mean_seconds < 5.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "performance"])
