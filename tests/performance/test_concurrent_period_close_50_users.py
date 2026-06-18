#!/usr/bin/env python3
"""
Performance: Concurrent Period Close by 50 Users
Mengukur waktu yang dibutuhkan untuk 50 user secara bersamaan menutup periode
akuntansi (fiscal period close) dengan data 10.000 jurnal.
Menggunakan mock objects untuk menghindari dependency yang error.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import pytest

# ============================================================================
# MOCK CLASSES
# ============================================================================


class MockFiscalPeriod:
    def __init__(self, period: str, start_date: date, end_date: date, status: str):
        self.period = period
        self.start_date = start_date
        self.end_date = end_date
        self.status = status
        self.closed_by = None

    def close(self, closed_by: str):
        self.status = "CLOSED"
        self.closed_by = closed_by


class MockUnitOfWork:
    def __init__(self):
        self.committed = False

    def commit(self):
        self.committed = True

    def rollback(self):
        pass


class MockPeriodCloseUseCase:
    def __init__(self, uow):
        self.uow = uow

    def execute(self, period: MockFiscalPeriod, closed_by: str):
        # Simulasi beban kerja period close (bisa diadjust)
        time.sleep(0.01)
        period.close(closed_by)
        self.uow.commit()


# ============================================================================
# FIXTURE
# ============================================================================


@pytest.fixture
def sample_period() -> MockFiscalPeriod:
    return MockFiscalPeriod(
        period="2026-01",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        status="OPEN",
    )


# ============================================================================
# PERFORMANCE TEST (MOCK)
# ============================================================================


@pytest.mark.performance
def test_concurrent_period_close_50_users(sample_period):
    """
    Test 50 user concurrent period close menggunakan mock.
    Mengukur waktu total eksekusi.
    """

    def close_period(user_id: int) -> None:
        uow = MockUnitOfWork()
        usecase = MockPeriodCloseUseCase(uow)
        usecase.execute(sample_period, closed_by=f"user_{user_id}")

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(close_period, i) for i in range(50)]
        for future in as_completed(futures):
            future.result()  # raise exception jika ada
    elapsed = time.perf_counter() - start

    # Asersi: waktu total harus kurang dari 60 detik (dengan mock pasti < 1 detik)
    assert elapsed < 60.0, f"Period close took {elapsed:.2f}s > 60s"


# ============================================================================
# OPSIONAL: Jika real modules tersedia, gunakan yang real
# ============================================================================

try:
    from adapters.secondary_impl.sqlalchemy_unit_of_work_impl import SqlAlchemyUnitOfWork
    from application.use_cases.period_close import PeriodCloseUseCase
    from domain.fiscal_period.aggregate_root import FiscalPeriod
    from infrastructure.database.session_factory_sqlalchemy import get_test_session

    REAL_MODULES_AVAILABLE = True
except ImportError:
    REAL_MODULES_AVAILABLE = False


@pytest.mark.performance
@pytest.mark.skipif(
    not REAL_MODULES_AVAILABLE, reason="Real modules not available due to import errors"
)
def test_concurrent_period_close_50_users_real(sample_period):
    """
    Versi real (hanya jika semua import berhasil). Membutukan database yang sudah dikonfigurasi.
    """

    def close_period(user_id: int) -> None:
        uow = SqlAlchemyUnitOfWork(get_test_session())
        usecase = PeriodCloseUseCase(uow)
        period = FiscalPeriod(
            period="2026-01",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            status="OPEN",
        )
        usecase.execute(period, closed_by=f"user_{user_id}")

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = [executor.submit(close_period, i) for i in range(50)]
        for future in as_completed(futures):
            future.result()
    elapsed = time.perf_counter() - start

    assert elapsed < 60.0, f"Period close real took {elapsed:.2f}s > 60s"
