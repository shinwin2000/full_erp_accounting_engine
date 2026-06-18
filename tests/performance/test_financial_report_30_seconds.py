#!/usr/bin/env python3
"""
Performance: Financial Report Generation Under 30 Seconds
Mengukur waktu generate balance sheet dan income statement menggunakan mock data.
Mock mensimulasikan beban komputasi dengan 10.000+ akun dan 50.000+ baris.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest

# ============================================================================
# MOCK CLASSES
# ============================================================================


@dataclass(kw_only=True)
class MockBalanceSheetProjection:
    """Mensimulasikan BalanceSheetProjection dengan 10.000+ akun."""

    for_date: date

    def generate(self) -> dict[str, Any]:
        start = time.perf_counter()
        assets = {f"asset_{i}": random.uniform(1000, 1_000_000) for i in range(10000)}
        liabilities = {f"liab_{i}": random.uniform(500, 500_000) for i in range(5000)}
        equity = {f"equity_{i}": random.uniform(1000, 2_000_000) for i in range(3000)}
        elapsed = time.perf_counter() - start
        return {
            "for_date": self.for_date,
            "assets": assets,
            "liabilities": liabilities,
            "equity": equity,
            "total_assets": sum(assets.values()),
            "total_liabilities": sum(liabilities.values()),
            "total_equity": sum(equity.values()),
            "generation_time_sec": elapsed,
        }


@dataclass(kw_only=True)
class MockIncomeStatementProjection:
    """Mensimulasikan IncomeStatementProjection dengan 50.000+ baris."""

    period_start: str
    period_end: str

    def generate(self) -> dict[str, Any]:
        start = time.perf_counter()
        revenue = {f"revenue_{i}": random.uniform(1000, 500_000) for i in range(20000)}
        expenses = {f"expense_{i}": random.uniform(100, 200_000) for i in range(30000)}
        elapsed = time.perf_counter() - start
        total_revenue = sum(revenue.values())
        total_expenses = sum(expenses.values())
        return {
            "period_start": self.period_start,
            "period_end": self.period_end,
            "revenue": revenue,
            "expenses": expenses,
            "total_revenue": total_revenue,
            "total_expenses": total_expenses,
            "net_income": total_revenue - total_expenses,
            "generation_time_sec": elapsed,
        }


# ============================================================================
# PERFORMANCE TESTS
# ============================================================================


@pytest.mark.performance
def test_balance_sheet_generation(benchmark):
    """Benchmark balance sheet generation (mock) – harus < 30 detik."""
    bs = MockBalanceSheetProjection(for_date=date(2026, 12, 31))

    def generate():
        return bs.generate()

    result = benchmark(generate)
    assert "total_assets" in result
    assert result["generation_time_sec"] < 30.0


@pytest.mark.performance
def test_income_statement_generation(benchmark):
    """Benchmark income statement generation (mock) – harus < 30 detik."""
    inc = MockIncomeStatementProjection(period_start="2026-01-01", period_end="2026-12-31")

    def generate():
        return inc.generate()

    result = benchmark(generate)
    assert "net_income" in result
    assert result["generation_time_sec"] < 30.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "performance"])
