#!/usr/bin/env python3
"""
Module: trend_analyzer_12month.py
Layer: Projections (Analytics BI)
Responsibility: Menganalisis tren keuangan 12 bulan terakhir untuk berbagai metrik:
               pendapatan, beban, laba bersih, arus kas, aset, liabilitas, ekuitas.
               Menyediakan data untuk visualisasi grafik tren (line chart) dan
               perhitungan month-over-month (MoM) serta year-over-year (YoY).
               Juga menghitung moving averages dan forecast sederhana.
Dependencies:
- asyncio, logging, datetime, decimal, statistics
- sqlalchemy.ext.asyncio
- infrastructure.database.session_factory_sqlalchemy
- projections.ledger.balance_sheet_snapshot
- projections.ledger.income_statement_period
- projections.ledger.cash_flow_indirect
- infrastructure.telemetry.structured_json_logging
Audit: Data tren digunakan untuk business intelligence dan perencanaan strategis.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, DateTime, Index, delete, insert, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.persistence_orm.fiscal_period_table import FiscalPeriodTable
from infrastructure.telemetry.structured_json_logging import get_logger
from projections.ledger.balance_sheet_snapshot import (
    BalanceSheetSnapshot,
    get_balance_sheet_snapshot,
)
from projections.ledger.cash_flow_indirect import CashFlowIndirect, get_cash_flow_projection
from projections.ledger.income_statement_period import (
    IncomeStatementPeriod,
    get_income_statement_projection,
)

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

PROJECTION_NAME = "trend_analyzer_12month"

TREND_METRICS = [
    "revenue",
    "expense",
    "net_income",
    "operating_cash_flow",
    "total_assets",
    "total_liabilities",
    "total_equity",
    "gross_profit_margin",
    "net_profit_margin",
]

# ============================================================================
# ORM MODEL
# ============================================================================

Base = declarative_base()


class TrendAnalysisTable(Base):
    __tablename__ = "trend_analysis"
    __table_args__ = (
        Index("idx_trend_analysis_legal_entity", "legal_entity_id"),
        Index("idx_trend_analysis_generated", "generated_at"),
        {"schema": "projections"},
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    analysis_data = Column(JSON, nullable=False)
    generated_at = Column(DateTime(timezone=True), nullable=False)


# ============================================================================
# EXCEPTIONS
# ============================================================================


class TrendAnalyzerError(Exception):
    """Base exception untuk trend analyzer."""

    pass


# ============================================================================
# TREND ANALYZER
# ============================================================================


class TrendAnalyzer12Month:
    """
    Analis tren keuangan 12 bulan.

    Fitur:
    - Mengumpulkan data keuangan per bulan untuk 12 bulan terakhir
    - Menghitung MoM (Month-over-Month) perubahan persentase
    - Menghitung YoY (Year-over-Year) perbandingan
    - Menghitung moving average (3 bulan, 6 bulan)
    - Forecast sederhana (linear regression) untuk 3 bulan ke depan
    """

    def __init__(self):
        self._session_factory = None
        self._balance_sheet: BalanceSheetSnapshot | None = None
        self._income_statement: IncomeStatementPeriod | None = None
        self._cash_flow: CashFlowIndirect | None = None

    async def _get_session(self) -> AsyncSession:
        if self._session_factory is None:
            self._session_factory = await get_session_factory()
        return self._session_factory.get_session()

    async def _get_balance_sheet(self) -> BalanceSheetSnapshot:
        if self._balance_sheet is None:
            self._balance_sheet = await get_balance_sheet_snapshot()
        return self._balance_sheet

    async def _get_income_statement(self) -> IncomeStatementPeriod:
        if self._income_statement is None:
            self._income_statement = await get_income_statement_projection()
        return self._income_statement

    async def _get_cash_flow(self) -> CashFlowIndirect:
        if self._cash_flow is None:
            self._cash_flow = await get_cash_flow_projection()
        return self._cash_flow

    async def _get_last_n_periods(self, legal_entity_id: UUID, n: int = 12) -> list[dict]:
        """
        Mendapatkan n periode terakhir yang sudah ditutup.
        """
        async with await self._get_session() as session:
            stmt = (
                select(FiscalPeriodTable)
                .where(
                    FiscalPeriodTable.legal_entity_id == legal_entity_id,
                    FiscalPeriodTable.status == "closed",
                )
                .order_by(FiscalPeriodTable.end_date.desc())
                .limit(n)
            )
            result = await session.execute(stmt)
            periods = result.scalars().all()
            # Urutkan ascending berdasarkan end_date
            return sorted(periods, key=lambda p: p.end_date)

    async def collect_monthly_data(
        self, legal_entity_id: UUID, months: int = 12
    ) -> list[dict[str, Any]]:
        """
        Mengumpulkan data keuangan bulanan untuk n bulan terakhir.

        Returns:
            List of monthly data points with metrics.
        """
        periods = await self._get_last_n_periods(legal_entity_id, months)
        if not periods:
            return []

        balance_sheet = await self._get_balance_sheet()
        income_stmt = await self._get_income_statement()
        cash_flow = await self._get_cash_flow()

        monthly_data = []
        for period in periods:
            # Balance sheet snapshot at period end
            bs = await balance_sheet.get_snapshot(legal_entity_id, period.id)
            total_assets = bs["total_assets"] if bs else 0
            total_liabilities = bs["total_liabilities"] if bs else 0
            total_equity = bs["total_equity"] if bs else 0

            # Income statement for period
            inc = await income_stmt.get_income_statement(legal_entity_id, period.id)
            revenue = inc["total_revenue"] if inc else 0
            expense = inc["total_expense"] if inc else 0
            net_income = inc["net_income"] if inc else 0

            # Cash flow for period
            cf = await cash_flow.get_cash_flow_statement(
                legal_entity_id, period.start_date, period.end_date
            )
            operating_cf = cf["operating_cash_flow"] if cf else 0

            # Calculate margins
            gross_profit_margin = (revenue - expense) / revenue * 100 if revenue > 0 else 0
            net_profit_margin = net_income / revenue * 100 if revenue > 0 else 0

            monthly_data.append(
                {
                    "period_id": str(period.id),
                    "period_name": period.period_name,
                    "year": period.fiscal_year,
                    "month": period.period_number,
                    "end_date": period.end_date.isoformat(),
                    "revenue": revenue,
                    "expense": expense,
                    "net_income": net_income,
                    "operating_cash_flow": operating_cf,
                    "total_assets": total_assets,
                    "total_liabilities": total_liabilities,
                    "total_equity": total_equity,
                    "gross_profit_margin": gross_profit_margin,
                    "net_profit_margin": net_profit_margin,
                }
            )

        return monthly_data

    def calculate_mom_changes(self, data: list[dict]) -> list[dict]:
        """
        Menghitung Month-over-Month changes untuk setiap metrik.
        """
        if len(data) < 2:
            return data

        result = []
        for i, current in enumerate(data):
            item = current.copy()
            if i > 0:
                prev = data[i - 1]
                for metric in TREND_METRICS:
                    if metric in current and metric in prev:
                        current_val = current[metric]
                        prev_val = prev[metric]
                        if prev_val != 0:
                            change_pct = ((current_val - prev_val) / prev_val) * 100
                        else:
                            change_pct = 0 if current_val == 0 else 100
                        item[f"{metric}_mom_pct"] = change_pct
            result.append(item)
        return result

    def calculate_yoy_changes(self, data: list[dict]) -> list[dict]:
        """
        Menghitung Year-over-Year changes (membandingkan dengan bulan yang sama tahun lalu).
        """
        result = []
        # Group by month number
        by_month = {}
        for item in data:
            month = item["month"]
            if month not in by_month:
                by_month[month] = []
            by_month[month].append(item)

        for _month, items in by_month.items():
            # Sort by year ascending
            items_sorted = sorted(items, key=lambda x: x["year"])
            for i, current in enumerate(items_sorted):
                item = current.copy()
                if i > 0:
                    prev = items_sorted[i - 1]
                    for metric in TREND_METRICS:
                        if metric in current and metric in prev:
                            current_val = current[metric]
                            prev_val = prev[metric]
                            if prev_val != 0:
                                change_pct = ((current_val - prev_val) / prev_val) * 100
                            else:
                                change_pct = 0 if current_val == 0 else 100
                            item[f"{metric}_yoy_pct"] = change_pct
                result.append(item)

        # Sort by end_date
        result.sort(key=lambda x: x["end_date"])
        return result

    def calculate_moving_averages(self, data: list[dict], window: int = 3) -> list[dict]:
        """
        Menghitung moving average untuk setiap metrik.
        """
        if len(data) < window:
            return data

        result = []
        for i, current in enumerate(data):
            item = current.copy()
            if i >= window - 1:
                window_data = data[i - window + 1 : i + 1]
                for metric in TREND_METRICS:
                    values = [d[metric] for d in window_data if metric in d]
                    if values:
                        avg = sum(values) / len(values)
                        item[f"{metric}_ma_{window}"] = avg
            result.append(item)
        return result

    def forecast_linear_regression(
        self, data: list[dict], metric: str, months_ahead: int = 3
    ) -> list[dict]:
        """
        Melakukan forecast sederhana menggunakan linear regression.

        Returns:
            List of forecasted values for each future month.
        """
        if len(data) < 3:
            return []

        # Prepare x values (month index from 0)
        x = list(range(len(data)))
        y = [d[metric] for d in data if metric in d]
        if len(y) < 3:
            return []

        # Calculate linear regression coefficients
        n = len(x)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(x[i] * y[i] for i in range(n))
        sum_x2 = sum(x[i] ** 2 for i in range(n))

        denominator = n * sum_x2 - sum_x**2
        if denominator == 0:
            return []

        slope = (n * sum_xy - sum_x * sum_y) / denominator
        intercept = (sum_y - slope * sum_x) / n

        # Forecast future months
        last_date = datetime.fromisoformat(data[-1]["end_date"]).date()
        forecasts = []
        for i in range(1, months_ahead + 1):
            future_x = len(data) + i - 1
            forecast_value = intercept + slope * future_x
            forecast_date = last_date + timedelta(days=30 * i)
            forecasts.append(
                {
                    "period": f"+{i} month",
                    "forecast_date": forecast_date.isoformat(),
                    "forecast_value": max(0, forecast_value),  # No negative values for most metrics
                }
            )
        return forecasts

    async def get_trend_analysis(self, legal_entity_id: UUID, months: int = 12) -> dict[str, Any]:
        """
        Mendapatkan analisis tren lengkap.
        """
        # Collect raw data
        raw_data = await self.collect_monthly_data(legal_entity_id, months)
        if not raw_data:
            return {"error": "No data available", "legal_entity_id": str(legal_entity_id)}

        # Apply MoM and YoY changes
        with_mom = self.calculate_mom_changes(raw_data)
        with_yoy = self.calculate_yoy_changes(with_mom)
        with_ma3 = self.calculate_moving_averages(with_yoy, 3)
        with_ma6 = self.calculate_moving_averages(with_ma3, 6)

        # Generate forecasts for key metrics
        forecasts = {}
        for metric in ["revenue", "net_income", "operating_cash_flow"]:
            forecast = self.forecast_linear_regression(raw_data, metric, 3)
            if forecast:
                forecasts[metric] = forecast

        # Identify trends (increasing/decreasing)
        if len(raw_data) >= 2:
            first = raw_data[0]
            last = raw_data[-1]
            trends = {}
            for metric in TREND_METRICS:
                if metric in first and metric in last:
                    first_val = first[metric]
                    last_val = last[metric]
                    if first_val != 0:
                        overall_change = ((last_val - first_val) / first_val) * 100
                    else:
                        overall_change = 0 if last_val == 0 else 100
                    trends[metric] = {
                        "overall_change_pct": overall_change,
                        "direction": "increasing"
                        if overall_change > 0
                        else "decreasing"
                        if overall_change < 0
                        else "stable",
                    }
        else:
            trends = {}

        return {
            "legal_entity_id": str(legal_entity_id),
            "period_covered": {
                "start": raw_data[0]["end_date"] if raw_data else None,
                "end": raw_data[-1]["end_date"] if raw_data else None,
                "months": len(raw_data),
            },
            "data_points": with_ma6,
            "trends": trends,
            "forecasts": forecasts,
            "generated_at": datetime.now(UTC).isoformat(),
        }

    async def save_trend_analysis(self, legal_entity_id: UUID, analysis: dict[str, Any]) -> None:
        """
        Menyimpan analisis tren ke tabel materialized.
        """
        async with await self._get_session() as session, session.begin():
            await session.execute(
                delete(TrendAnalysisTable).where(
                    TrendAnalysisTable.legal_entity_id == legal_entity_id
                )
            )
            stmt = insert(TrendAnalysisTable).values(
                id=uuid4(),
                legal_entity_id=legal_entity_id,
                analysis_data=analysis,
                generated_at=datetime.now(UTC),
            )
            await session.execute(stmt)
            await session.commit()

    async def get_saved_analysis(self, legal_entity_id: UUID) -> dict | None:
        """
        Mendapatkan analisis tren yang sudah tersimpan.
        """
        async with await self._get_session() as session:
            stmt = (
                select(TrendAnalysisTable)
                .where(TrendAnalysisTable.legal_entity_id == legal_entity_id)
                .order_by(TrendAnalysisTable.generated_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            return row.analysis_data

    async def refresh_analysis(self, legal_entity_id: UUID) -> dict:
        """
        Menghitung dan menyimpan analisis tren terbaru.
        """
        analysis = await self.get_trend_analysis(legal_entity_id)
        await self.save_trend_analysis(legal_entity_id, analysis)
        logger.info(f"Trend analysis refreshed for legal entity {legal_entity_id}")
        return analysis


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_trend_analyzer: TrendAnalyzer12Month | None = None


async def get_trend_analyzer() -> TrendAnalyzer12Month:
    """Get singleton instance of TrendAnalyzer12Month."""
    global _trend_analyzer
    if _trend_analyzer is None:
        _trend_analyzer = TrendAnalyzer12Month()
    return _trend_analyzer


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["TrendAnalyzer12Month", "TrendAnalyzerError", "get_trend_analyzer"]
