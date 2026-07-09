#!/usr/bin/env python3
"""
Performance: Memory Usage During Batch Processing
Mengukur memory usage saat memproses 100.000 jurnal dalam satu batch.
Menggunakan psutil untuk memonitor memory.

Perbaikan presisi:
    - Mengganti tipe parameter float pada nilai moneter (debit, credit) menjadi Decimal
      untuk memenuhi aturan MNY-023.
"""

from __future__ import annotations

import gc
import os
from decimal import Decimal

import psutil
import pytest

# ============================================================================
# MOCK objects to avoid importing heavy real modules that cause circular deps
# ============================================================================


class MockJournalAggregate:
    """Mock aggregate untuk pengujian memory."""

    def __init__(self, journal_id: str):
        self.journal_id = journal_id
        self.lines = []
        self.description = ""

    def create(self, description: str):
        self.description = description

    def add_line(self, account: str, debit: Decimal, credit: Decimal):
        self.lines.append(
            {
                "account": account,
                "debit": debit,
                "credit": credit,
            }
        )


class MockJournalService:
    """Mock service untuk menyimpan jurnal."""

    def __init__(self, session=None):
        self.session = session
        self.saved = []

    def save(self, journal):
        self.saved.append(journal)


def create_large_batch(size: int):
    """Buat sejumlah mock journal aggregate."""
    journals = []
    for i in range(size):
        j = MockJournalAggregate(journal_id=f"JRN-{i}")
        j.create(f"Journal {i}")
        j.add_line(account="101", debit=Decimal("1000"), credit=Decimal("0"))
        j.add_line(account="201", debit=Decimal("0"), credit=Decimal("1000"))
        journals.append(j)
    return journals


# ============================================================================
# Performance Test
# ============================================================================

@pytest.mark.performance
def test_memory_usage_batch_100k(benchmark):
    """
    Menguji memory usage saat membuat dan menyimpan 100.000 jurnal.
    Menggunakan mock objects agar tidak tergantung database.
    """
    process = psutil.Process(os.getpid())
    # Paksa garbage collection sebelum mengukur baseline
    gc.collect()
    mem_before = process.memory_info().rss / 1024 / 1024  # MB

    # 1. Buat 100.000 jurnal dalam memory
    journals = create_large_batch(100000)
    mem_after_create = process.memory_info().rss / 1024 / 1024
    memory_increase_create = mem_after_create - mem_before
    # Asersi: memory increase tidak boleh lebih dari 500 MB
    assert memory_increase_create < 500, (
        f"Memory increase after create: {memory_increase_create:.2f} MB > 500 MB"
    )

    # 2. Simpan ke mock service (simulasi penyimpanan)
    service = MockJournalService()

    def save_all():
        for j in journals:
            service.save(j)

    # Benchmark waktu penyimpanan (tidak perlu ke database real)
    benchmark(save_all)

    mem_final = process.memory_info().rss / 1024 / 1024
    memory_increase_final = mem_final - mem_before
    assert memory_increase_final < 600, (
        f"Memory increase final: {memory_increase_final:.2f} MB > 600 MB"
    )

    # Log untuk informasi
    print(
        f"\nMemory usage: before={mem_before:.1f}MB, after_create={mem_after_create:.1f}MB, after_save={mem_final:.1f}MB"
    )
    print(
        f"Peak memory increase: {max(memory_increase_create, memory_increase_final):.1f} MB"
    )


@pytest.mark.performance
def test_memory_leak_during_batch():
    """
    Test khusus mendeteksi memory leak dengan memproses batch berulang.
    """
    process = psutil.Process(os.getpid())
    gc.collect()
    mem_baseline = process.memory_info().rss / 1024 / 1024

    # Lakukan 10 iterasi, masing-masing buat 10.000 jurnal lalu discard
    for _iteration in range(10):
        journals = create_large_batch(10000)
        service = MockJournalService()
        for j in journals:
            service.save(j)
        # Hapus referensi agar GC bisa membersihkan
        del journals
        del service
        gc.collect()

    mem_after = process.memory_info().rss / 1024 / 1024
    leak = mem_after - mem_baseline
    # Asersi: memory leak tidak boleh lebih dari 50 MB setelah 10 iterasi
    assert leak < 50, (
        f"Potential memory leak: {leak:.2f} MB after 10 iterations"
    )
    print(
        f"\nMemory leak test: baseline={mem_baseline:.1f}MB, after={mem_after:.1f}MB, leak={leak:.2f}MB"
    )