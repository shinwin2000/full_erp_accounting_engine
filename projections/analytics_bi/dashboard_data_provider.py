#!/usr/bin/env python3
"""
Module: dashboard_data_provider.py
Layer: Projections (Analytics BI)
Responsibility: Menyediakan data terintegrasi untuk dashboard BI (Grafana, Power BI, atau
               frontend internal). Mengagregasi data dari berbagai projection:
               trend analyzer, variance analyzer, profitability, financial ratios,
               dan KPI alerter. Memberikan endpoint data untuk visualisasi real-time
               dan historical. Mendukung filter periode, legal entity, dan segmen.
Dependencies:
- asyncio, logging, datetime
- sqlalchemy.ext.asyncio
- infrastructure.database.session_factory_sqlalchemy
- projections.analytics_bi.trend_analyzer_12month
- projections.analytics_bi.variance_analyzer_actual_vs_budget
- projections.analytics_bi.profitability_by_segment
- projections.analytics_bi.financial_ratios_calculator
- projections.analytics_bi.kpi_threshold_alerter
- infrastructure.telemetry.structured_json_logging
Audit: Data dashboard digunakan untuk monitoring eksekutif dan laporan manajemen.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Column, DateTime, Index, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import DeclarativeMeta

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.persistence_orm.fiscal_period_table import FiscalPeriodTable
from infrastructure.telemetry.structured_json_logging import get_logger
from projections.analytics_bi.financial_ratios_calculator import (
    FinancialRatiosCalculator,
    get_financial_ratios_calculator,
)
from projections.analytics_bi.kpi_threshold_alerter import KPIThresholdAlerter, get_kpi_alerter
from projections.analytics_bi.profitability_by_segment import (
    ProfitabilityBySegment,
    get_profitability_analyzer,
)
from projections.analytics_bi.trend_analyzer_12month import TrendAnalyzer12Month, get_trend_analyzer
from projections.analytics_bi.variance_analyzer_actual_vs_budget import (
    VarianceAnalyzerActualVsBudget,
    get_variance_analyzer,
)
from projections.ledger.balance_sheet_snapshot import (
    BalanceSheetSnapshot,
    get_balance_sheet_snapshot,
)
from projections.ledger.income_statement_period import (
    IncomeStatementPeriod,
    get_income_statement_projection,
)

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

PROJECTION_NAME = "dashboard_data"

# Cache TTL (seconds)
CACHE_TTL = 300  # 5 minutes

# ============================================================================
# EXCEPTIONS
# ============================================================================


class DashboardDataError(Exception):
    """Base exception untuk dashboard data provider."""

    pass


# ============================================================================
# ORM MODEL (untuk menyimpan dashboard snapshots opsional)
# ============================================================================

# Explicitly type Base as DeclarativeMeta to avoid mypy errors
Base: DeclarativeMeta = declarative_base()  # type: ignore


class DashboardSnapshotTable(Base):
    __tablename__ = "dashboard_snapshot"
    __table_args__ = (
        Index("idx_dashboard_snapshot_legal_entity", "legal_entity_id"),
        Index("idx_dashboard_snapshot_period", "period_id"),
        {"schema": "projections"},
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    period_id = Column(PGUUID(as_uuid=True), nullable=False)
    data = Column(JSON, nullable=False)
    generated_at = Column(DateTime(timezone=True), nullable=False)


# ============================================================================
# DASHBOARD DATA PROVIDER
# ============================================================================


class DashboardDataProvider:
    """
    Provider data terintegrasi untuk dashboard BI.

    Fitur:
    - Mendapatkan ringkasan eksekutif (key metrics)
    - Data untuk chart trending (revenue, profit, margin)
    - Data untuk chart variance (actual vs budget)
    - Data untuk profitability by segment
    - Data untuk financial ratios
    - Alert dari KPI monitoring
    - Mendukung filter periode dan legal entity
    - Caching untuk performance
    """

    def __init__(self):
        self._session_factory = None
        self._trend_analyzer: TrendAnalyzer12Month | None = None
        self._variance_analyzer: VarianceAnalyzerActualVsBudget | None = None
        self._profitability_analyzer: ProfitabilityBySegment | None = None
        self._ratios_calc: FinancialRatiosCalculator | None = None
        self._kpi_alerter: KPIThresholdAlerter | None = None
        self._income_stmt: IncomeStatementPeriod | None = None
        self._balance_sheet: BalanceSheetSnapshot | None = None
        self._cache: dict[str, Any] = {}

    async def _get_session(self) -> AsyncSession:
        if self._session_factory is None:
            self._session_factory = await get_session_factory()
        # mypy cannot infer that _session_factory is not None after assignment
        assert self._session_factory is not None
        return self._session_factory.get_session()

    async def _get_trend_analyzer(self) -> TrendAnalyzer12Month:
        if self._trend_analyzer is None:
            self._trend_analyzer = await get_trend_analyzer()
        return self._trend_analyzer

    async def _get_variance_analyzer(self) -> VarianceAnalyzerActualVsBudget:
        if self._variance_analyzer is None:
            self._variance_analyzer = await get_variance_analyzer()
        return self._variance_analyzer

    async def _get_profitability_analyzer(self) -> ProfitabilityBySegment:
        if self._profitability_analyzer is None:
            self._profitability_analyzer = await get_profitability_analyzer()
        return self._profitability_analyzer

    async def _get_ratios_calc(self) -> FinancialRatiosCalculator:
        if self._ratios_calc is None:
            self._ratios_calc = await get_financial_ratios_calculator()
        return self._ratios_calc

    async def _get_kpi_alerter(self) -> KPIThresholdAlerter:
        if self._kpi_alerter is None:
            self._kpi_alerter = await get_kpi_alerter()
        return self._kpi_alerter

    async def _get_income_stmt(self) -> IncomeStatementPeriod:
        if self._income_stmt is None:
            self._income_stmt = await get_income_statement_projection()
        return self._income_stmt

    async def _get_balance_sheet(self) -> BalanceSheetSnapshot:
        if self._balance_sheet is None:
            self._balance_sheet = await get_balance_sheet_snapshot()
        return self._balance_sheet

    def _cache_key(self, legal_entity_id: UUID, period_id: UUID) -> str:
        return f"dashboard:{legal_entity_id}:{period_id}"

    async def get_dashboard_data(
        self, legal_entity_id: UUID, period_id: UUID, force_refresh: bool = False
    ) -> dict[str, Any]:
        """
        Mendapatkan data dashboard lengkap untuk periode tertentu.

        Args:
            legal_entity_id: Legal entity ID
            period_id: Period ID (FiscalPeriod)
            force_refresh: Bypass cache

        Returns:
            Dashboard data dictionary.
        """
        cache_key = self._cache_key(legal_entity_id, period_id)
        if not force_refresh and cache_key in self._cache:
            cached = self._cache[cache_key]
            if (datetime.now(UTC) - cached["cached_at"]).total_seconds() < CACHE_TTL:
                return cached["data"]

        try:
            # 1. Get period information
            async with await self._get_session() as session:
                period_stmt = select(FiscalPeriodTable).where(FiscalPeriodTable.id == period_id)
                period_result = await session.execute(period_stmt)
                period = period_result.scalar_one_or_none()
                if not period:
                    raise DashboardDataError(f"Period {period_id} not found")

            # 2. Key metrics (revenue, net income, etc) from income statement
            # FIX: await _get_income_stmt() first, then call method
            income_stmt = await self._get_income_stmt()
            inc = await income_stmt.get_income_statement(legal_entity_id, period_id)

            balance_sheet = await self._get_balance_sheet()
            bs = await balance_sheet.get_snapshot(legal_entity_id, period_id)

            key_metrics = {
                "revenue": inc.get("total_revenue", 0) if inc else 0,
                "net_income": inc.get("net_income", 0) if inc else 0,
                "total_assets": bs.get("total_assets", 0) if bs else 0,
                "total_liabilities": bs.get("total_liabilities", 0) if bs else 0,
                "total_equity": bs.get("total_equity", 0) if bs else 0,
                "gross_profit": inc.get("gross_profit", 0) if inc else 0,
                "operating_income": inc.get("operating_income", 0) if inc else 0,
            }

            # 3. Trend data (last 12 months)
            trend_analyzer = await self._get_trend_analyzer()
            trend_data = await trend_analyzer.get_trend_analysis(legal_entity_id, 12)

            # 4. Variance analysis (actual vs budget)
            variance_analyzer = await self._get_variance_analyzer()
            variance = await variance_analyzer.analyze_period_variance(
                legal_entity_id, period.fiscal_year, period.period_number
            )

            # 5. Profitability by segment
            profitability_analyzer = await self._get_profitability_analyzer()
            profitability = await profitability_analyzer.get_profitability_summary(
                legal_entity_id, period.start_date, period.end_date
            )

            # 6. Financial ratios
            ratios_calc = await self._get_ratios_calc()
            ratios_data = await ratios_calc.calculate_ratios(legal_entity_id, period_id)

            # 7. KPI alerts
            kpi_alerter = await self._get_kpi_alerter()
            kpi_alerts = await kpi_alerter.get_alert_history(legal_entity_id, limit=20)

            # 8. YTD summary (if period not first)
            ytd_summary = {}
            if period.period_number > 1:
                ytd_inc = await income_stmt.get_ytd_income(
                    legal_entity_id, period.fiscal_year
                )
                ytd_summary = {
                    "revenue_ytd": ytd_inc.get("total_revenue", 0),
                    "net_income_ytd": ytd_inc.get("net_income", 0),
                    "cogs_ytd": ytd_inc.get("total_cogs", 0),
                }

            # 9. Build response
            dashboard_data = {
                "legal_entity_id": str(legal_entity_id),
                "period_id": str(period_id),
                "period_name": period.period_name,
                "period_range": {
                    "start": period.start_date.isoformat(),
                    "end": period.end_date.isoformat(),
                },
                "key_metrics": key_metrics,
                "ytd_summary": ytd_summary,
                "trend_analysis": trend_data,
                "variance_analysis": variance if "error" not in variance else None,
                "profitability": profitability,
                "financial_ratios": ratios_data.get("ratios", {}),
                "industry_comparison": ratios_data.get("industry_comparison", {}),
                "alerts": kpi_alerts,
                "generated_at": datetime.now(UTC).isoformat(),
            }

            # Cache
            self._cache[cache_key] = {"data": dashboard_data, "cached_at": datetime.now(UTC)}

            return dashboard_data

        except Exception as e:
            logger.error(
                f"Failed to get dashboard data for {legal_entity_id} period {period_id}: {e}"
            )
            raise DashboardDataError(f"Dashboard data unavailable: {e}") from e

    async def get_executive_summary(self, legal_entity_id: UUID, period_id: UUID) -> dict:
        """
        Mendapatkan ringkasan eksekutif (ringkasan untuk manajemen).
        """
        dashboard = await self.get_dashboard_data(legal_entity_id, period_id)

        key_metrics = dashboard.get("key_metrics", {})
        variance = dashboard.get("variance_analysis", {})

        # Determine overall health color/status
        health_status = "healthy"
        health_reasons = []

        # Check net income
        if key_metrics.get("net_income", 0) < 0:
            health_status = "critical"
            health_reasons.append("Net income negative")
        elif variance:
            rev_var = variance.get("revenue", {}).get("variance_percent", 0)
            if rev_var < -10:
                health_status = "warning"
                health_reasons.append(f"Revenue variance {rev_var:.1f}% below budget")

        return {
            "legal_entity_id": str(legal_entity_id),
            "period_name": dashboard.get("period_name"),
            "revenue": key_metrics.get("revenue"),
            "net_income": key_metrics.get("net_income"),
            "gross_margin": dashboard.get("financial_ratios", {}).get("gross_margin"),
            "total_assets": key_metrics.get("total_assets"),
            "debt_to_equity": dashboard.get("financial_ratios", {}).get("debt_to_equity"),
            "health_status": health_status,
            "health_reasons": health_reasons,
            "alert_count": len(dashboard.get("alerts", [])),
            "generated_at": dashboard.get("generated_at"),
        }

    async def get_chart_data(self, legal_entity_id: UUID, period_id: UUID, chart_type: str) -> dict:
        """
        Mendapatkan data untuk chart tertentu.

        Args:
            chart_type: "revenue_trend", "profit_trend", "margin_trend",
                        "actual_vs_budget", "profitability_breakdown"
        """
        dashboard = await self.get_dashboard_data(legal_entity_id, period_id)

        if chart_type == "revenue_trend":
            trend = dashboard.get("trend_analysis", {}).get("data_points", [])
            return {
                "labels": [p.get("period_name") for p in trend],
                "datasets": [{"label": "Revenue", "data": [p.get("revenue", 0) for p in trend]}],
            }
        elif chart_type == "profit_trend":
            trend = dashboard.get("trend_analysis", {}).get("data_points", [])
            return {
                "labels": [p.get("period_name") for p in trend],
                "datasets": [
                    {"label": "Gross Profit", "data": [p.get("gross_profit", 0) for p in trend]},
                    {"label": "Net Income", "data": [p.get("net_income", 0) for p in trend]},
                ],
            }
        elif chart_type == "actual_vs_budget":
            variance = dashboard.get("variance_analysis", {})
            if not variance:
                return {"error": "Variance data not available"}
            return {
                "labels": ["Revenue", "Expense", "Net Income"],
                "datasets": [
                    {
                        "label": "Actual",
                        "data": [
                            variance.get("revenue", {}).get("actual", 0),
                            variance.get("expense", {}).get("actual", 0),
                            variance.get("net_income", {}).get("actual", 0),
                        ],
                    },
                    {
                        "label": "Budget",
                        "data": [
                            variance.get("revenue", {}).get("budget", 0),
                            variance.get("expense", {}).get("budget", 0),
                            variance.get("net_income", {}).get("budget", 0),
                        ],
                    },
                ],
            }
        elif chart_type == "profitability_breakdown":
            profitability = dashboard.get("profitability", {})
            products = profitability.get("top_products", [])
            return {
                "labels": [p.get("product_name") for p in products[:10]],
                "datasets": [
                    {"label": "Revenue", "data": [p.get("revenue", 0) for p in products[:10]]}
                ],
            }
        else:
            raise DashboardDataError(f"Unknown chart type: {chart_type}")

    async def clear_cache(self) -> None:
        """Menghapus cache dashboard."""
        self._cache.clear()
        logger.info("Dashboard data cache cleared")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_dashboard_provider: DashboardDataProvider | None = None


async def get_dashboard_provider() -> DashboardDataProvider:
    """Get singleton instance of DashboardDataProvider."""
    global _dashboard_provider
    if _dashboard_provider is None:
        _dashboard_provider = DashboardDataProvider()
    return _dashboard_provider


# ============================================================================
# FASTAPI DEPENDENCY
# ============================================================================


async def get_dashboard_data_dep():
    """FastAPI dependency untuk dashboard data provider."""
    return await get_dashboard_provider()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "DashboardDataError",
    "DashboardDataProvider",
    "get_dashboard_data_dep",
    "get_dashboard_provider",
]
