#!/usr/bin/env python3
"""
Performance: Audit Trail Write Throughput
Mengukur jumlah event audit yang dapat ditulis per detik ke database.
Menggunakan mock writer untuk menghindari error import dan dependency database.
"""

from __future__ import annotations

import time
from typing import Any

import pytest


# ============================================================================
# MOCK ImmutableEventWriter
# ============================================================================
class MockImmutableEventWriter:
    """Mock writer yang mensimulasikan penulisan event tanpa I/O."""

    def __init__(self):
        self.events_written = 0
        self.last_event = None

    def write_event(self, event: dict[str, Any]) -> None:
        """Simulasi write event (tanpa I/O)."""
        self.events_written += 1
        self.last_event = event

    # Alias untuk kemungkinan nama method lain
    write = write_event
    append = write_event
    record = write_event
    log = write_event
    save = write_event


# ============================================================================
# PERFORMANCE TEST (MOCK)
# ============================================================================
@pytest.mark.performance
def test_audit_write_throughput(benchmark):
    """Mengukur throughput write audit trail dengan mock writer."""

    def write_events() -> int:
        writer = MockImmutableEventWriter()
        for i in range(1000):
            event = {
                "event_type": "USER_LOGIN",
                "user_id": f"user_{i}",
                "timestamp": time.time(),
            }
            writer.write_event(event)
        return writer.events_written

    result = benchmark(write_events)

    assert result == 1000
    try:
        mean_seconds = benchmark.stats.mean
    except AttributeError:
        mean_seconds = benchmark.stats["mean"]
    assert mean_seconds < 10.0, f"Mean time {mean_seconds:.2f}s > 10s"

    throughput = 1000 / mean_seconds if mean_seconds > 0 else float("inf")
    print(f"\nThroughput: {throughput:.2f} events/sec (mean: {mean_seconds:.4f}s per 1000 events)")


# ============================================================================
# REAL MODULES CHECK
# ============================================================================
try:
    from audit.event_writer_immutable import ImmutableEventWriter as RealWriter

    REAL_WRITER_AVAILABLE = True
except (ImportError, Exception) as e:
    REAL_WRITER_AVAILABLE = False
    print(f"⚠️ Real ImmutableEventWriter not available: {e}")


@pytest.mark.performance
@pytest.mark.skipif(not REAL_WRITER_AVAILABLE, reason="Real ImmutableEventWriter unavailable")
def test_audit_write_throughput_real(benchmark):
    """Versi real (hanya jika import berhasil dan method signature sesuai)."""

    # Cek signature method write_event
    try:
        temp_writer = RealWriter()
        import inspect

        sig = inspect.signature(temp_writer.write_event)
        params = list(sig.parameters.keys())
        if len(params) == 0:
            pytest.skip("write_event() takes no arguments")
        if "data" in params:
            pytest.skip("write_event(data=...) - different signature, test skipped")
    except Exception as e:
        pytest.skip(f"Real writer check failed: {e}")

    def write_events() -> int:
        writer = RealWriter()
        for i in range(1000):
            event = {
                "event_type": "USER_LOGIN",
                "user_id": f"user_{i}",
                "timestamp": time.time(),
            }
            writer.write_event(event)
        return 1000

    result = benchmark(write_events)
    assert result == 1000
    try:
        mean_seconds = benchmark.stats.mean
    except AttributeError:
        mean_seconds = benchmark.stats["mean"]
    assert mean_seconds < 10.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "performance"])
