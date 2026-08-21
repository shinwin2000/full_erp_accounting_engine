#!/usr/bin/env python3
"""
Module: variance_analyzer_actual_vs_budget.py
Layer: Projections (Analytics BI)
Responsibility: Menganalisis varian antara actual (realisasi) dan budget (anggaran)
               untuk pendapatan, beban, laba, arus kas, dan metrik keuangan lainnya.
               Mendukung perbandingan per bulan, kuartal, tahun, serta per cost center,
               departemen, atau project. Menyediakan analisis favorable/unfavorable,
               persentase varian, dan rekomendasi tindakan.
Dependencies:
- asyncio, logging, datetime, decimal
- sqlalchemy.ext.asyncio
- infrastructure.database.session_factory_sqlalchemy
- projections.ledger.income_statement_period
- projections.ledger.balance_sheet_snapshot
- domain.budget.aggregate_root (asumsi ada tabel budget)
- infrastructure.telemetry.structured_json_logging
- infrastructure.telemetry.alert_manager_router
Audit: Analisis varian digunakan untuk performance management dan koreksi anggaran.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, DateTime, Index, Integer, delete, insert, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeMeta, declarative_base

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.persistence_orm.fiscal_period_table import FiscalPeriodTable
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger
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

PROJECTION_NAME = "variance_analysis"

# Jenis varian
VARIANCE_FAVORABLE = "favorable"
VARIANCE_UNFAVORABLE = "unfavorable"
VARIANCE_NEUTRAL = "neutral"

# Kategori untuk alert
ALERT_VARIANCE_THRESHOLD_PERCENT = 10.0  # Alert jika varian > 10%

# ============================================================================
# EXCEPTIONS
# ============================================================================


class VarianceAnalyzerError(Exception):
    """Base exception untuk variance analyzer."""

    pass


# ============================================================================
# ORM MODEL
# ============================================================================

Base: DeclarativeMeta = declarative_base()


class VarianceAnalysisTable(Base):
    __tablename__: ClassVar[str] = "variance_analysis"
    __table_args__: ClassVar[tuple] = (
        Index("idx_variance_legal_entity", "legal_entity_id"),
        Index("idx_variance_period", "fiscal_year", "period"),
        {"schema": "projections"},
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    period = Column(Integer, nullable=False)
    analysis_data = Column(JSON, nullable=False)
    generated_at = Column(DateTime(timezone=True), nullable=False)


# ============================================================================
# BUDGET DATA MODEL (sementara, asumsi ada tabel budget)
# ============================================================================

# Untuk sementara kita asumsikan ada tabel budget dengan struktur:
# budget_id, legal_entity_id, fiscal_year, period, account_code, budget_amount, cost_center, department


class BudgetRepository:
    """Repository sederhana untuk budget (placeholder, akan terintegrasi dengan domain budget)."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_budget(
        self,
        legal_entity_id: UUID,
        fiscal_year: int,
        period: int,
        account_code: str | None = None,
        cost_center: str | None = None,
    ) -> Decimal:
        """
        Mendapatkan budget untuk periode tertentu.
        Untuk sementara, return dummy budget (dalam implementasi nyata, query dari tabel budget).
        """
        # Placeholder: budget = actual * 1.1 (untuk testing)
        # Di production, ini akan mengambil dari tabel budget yang sesungguhnya
        # Untuk keperluan demonstrasi, kita akan menggunakan nilai dummy
        return Decimal(0)


# ============================================================================
# VARIANCE ANALYZER
# ============================================================================


class VarianceAnalyzerActualVsBudget:
    """
    Analis varian antara actual dan budget.

    Fitur:
    - Perbandingan actual vs budget per periode
    - Varian dalam nilai absolut dan persentase
    - Klasifikasi favorable/unfavorable
    - Breakdown per cost center / department
    - Alert untuk varian signifikan
    - Trend varian over time
    """

    def __init__(self):
        self._session_factory = None
        self._income_statement: IncomeStatementPeriod | None = None
        self._balance_sheet: BalanceSheetSnapshot | None = None

    async def _get_session(self) -> AsyncSession:
        if self._session_factory is None:
            self._session_factory = await get_session_factory()
        return self._session_factory.get_session()

    async def _get_income_statement(self) -> IncomeStatementPeriod:
        if self._income_statement is None:
            self._income_statement = await get_income_statement_projection()
        return self._income_statement

    async def _get_balance_sheet(self) -> BalanceSheetSnapshot:
        if self._balance_sheet is None:
            self._balance_sheet = await get_balance_sheet_snapshot()
        return self._balance_sheet

    async def _get_budget_amount(
        self, legal_entity_id: UUID, fiscal_year: int, period: int, metric_type: str
    ) -> Decimal:
        """
        Mendapatkan budget untuk metrik tertentu.
        Metric type: revenue, expense, net_income, operating_cash_flow, total_assets, dll.
        """
        # Di implementasi nyata, akan mengambil dari tabel budget
        # Untuk sementara, kita akan menghitung berdasarkan historical average

        # Placeholder: return nilai dummy yang bervariasi
        # Ini hanya untuk struktur, nanti akan diganti dengan query budget sebenarnya
        base_budget = Decimal(1000000000)  # Rp 1 M
        if metric_type == "revenue":
            return base_budget
        elif metric_type == "expense":
            return base_budget * Decimal("0.8")
        elif metric_type == "net_income":
            return base_budget * Decimal("0.2")
        elif metric_type == "total_assets":
            return base_budget * Decimal("5")
        else:
            return base_budget

    def _determine_favorability(self, metric_type: str, actual: Decimal, budget: Decimal) -> str:
        """
        Menentukan apakah varian favorable atau unfavorable.
        - Revenue: actual > budget = favorable
        - Expense: actual < budget = favorable
        - Net Income: actual > budget = favorable
        - Assets: tergantung konteks (biasanya tidak dinilai)
        """
        if metric_type in ["revenue", "net_income", "operating_cash_flow"]:
            return VARIANCE_FAVORABLE if actual > budget else VARIANCE_UNFAVORABLE
        elif metric_type in ["expense"]:
            return VARIANCE_FAVORABLE if actual < budget else VARIANCE_UNFAVORABLE
        else:
            return VARIANCE_NEUTRAL

    async def analyze_period_variance(
        self, legal_entity_id: UUID, fiscal_year: int, period: int
    ) -> dict[str, Any]:
        """
        Menganalisis varian untuk satu periode.

        Args:
            legal_entity_id: Legal entity ID
            fiscal_year: Tahun fiskal
            period: Nomor periode (1-12)

        Returns:
            Variance analysis for the period
        """
        async with await self._get_session() as session:
            # Get period info
            period_stmt = select(FiscalPeriodTable).where(
                FiscalPeriodTable.legal_entity_id == legal_entity_id,
                FiscalPeriodTable.fiscal_year == fiscal_year,
                FiscalPeriodTable.period_number == period,
                FiscalPeriodTable.status == "closed",
            )
            period_result = await session.execute(period_stmt)
            period_obj = period_result.scalar_one_or_none()
            if not period_obj:
                return {"error": f"Period {period}/{fiscal_year} not found or not closed"}

            # Get actual data from income statement
            income_stmt_projection = await self._get_income_statement()
            income_stmt = await income_stmt_projection.get_income_statement(
                legal_entity_id, period_obj.id
            )
            if not income_stmt:
                return {"error": f"Income statement not available for period {period_obj.id}"}

            # Get budget data
            budget_revenue = await self._get_budget_amount(
                legal_entity_id, fiscal_year, period, "revenue"
            )
            budget_expense = await self._get_budget_amount(
                legal_entity_id, fiscal_year, period, "expense"
            )
            budget_net_income = await self._get_budget_amount(
                legal_entity_id, fiscal_year, period, "net_income"
            )

            actual_revenue = Decimal(str(income_stmt["total_revenue"]))
            actual_expense = Decimal(str(income_stmt["total_expense"]))
            actual_net_income = Decimal(str(income_stmt["net_income"]))

            # Calculate variances
            revenue_variance = actual_revenue - budget_revenue
            revenue_variance_pct = (
                (revenue_variance / budget_revenue * 100) if budget_revenue != 0 else 0
            )
            revenue_favorability = self._determine_favorability(
                "revenue", actual_revenue, budget_revenue
            )

            expense_variance = (
                budget_expense - actual_expense
            )  # positive = favorable (actual lebih kecil)
            expense_variance_pct = (
                (expense_variance / budget_expense * 100) if budget_expense != 0 else 0
            )
            expense_favorability = self._determine_favorability(
                "expense", actual_expense, budget_expense
            )

            net_income_variance = actual_net_income - budget_net_income
            net_income_variance_pct = (
                (net_income_variance / budget_net_income * 100) if budget_net_income != 0 else 0
            )
            net_income_favorability = self._determine_favorability(
                "net_income", actual_net_income, budget_net_income
            )

            result = {
                "legal_entity_id": str(legal_entity_id),
                "period_id": str(period_obj.id),
                "period_name": period_obj.period_name,
                "fiscal_year": fiscal_year,
                "period": period,
                "revenue": {
                    "actual": float(actual_revenue),
                    "budget": float(budget_revenue),
                    "variance": float(revenue_variance),
                    "variance_percent": float(revenue_variance_pct),
                    "favorability": revenue_favorability,
                },
                "expense": {
                    "actual": float(actual_expense),
                    "budget": float(budget_expense),
                    "variance": float(expense_variance),
                    "variance_percent": float(expense_variance_pct),
                    "favorability": expense_favorability,
                },
                "net_income": {
                    "actual": float(actual_net_income),
                    "budget": float(budget_net_income),
                    "variance": float(net_income_variance),
                    "variance_percent": float(net_income_variance_pct),
                    "favorability": net_income_favorability,
                },
                "generated_at": datetime.now(UTC).isoformat(),
            }

            # Trigger alert if significant variance
            if abs(float(revenue_variance_pct)) > ALERT_VARIANCE_THRESHOLD_PERCENT:
                await trigger_alert(
                    title="Significant Revenue Variance",
                    message=f"Revenue variance of {revenue_variance_pct:.1f}% ({revenue_favorability}) for period {period_obj.period_name}",
                    severity="warning",
                    source="VarianceAnalyzerActualVsBudget",
                )

            return result

    async def analyze_ytd_variance(self, legal_entity_id: UUID, fiscal_year: int) -> dict[str, Any]:
        """
        Menganalisis varian Year-to-Date (YTD) untuk tahun fiskal.
        """
        async with await self._get_session() as session:
            # Get all periods in fiscal year that are closed
            period_stmt = (
                select(FiscalPeriodTable)
                .where(
                    FiscalPeriodTable.legal_entity_id == legal_entity_id,
                    FiscalPeriodTable.fiscal_year == fiscal_year,
                    FiscalPeriodTable.status == "closed",
                )
                .order_by(FiscalPeriodTable.end_date)
            )
            period_result = await session.execute(period_stmt)
            periods = period_result.scalars().all()

            if not periods:
                return {"error": f"No closed periods found for fiscal year {fiscal_year}"}

            total_actual_revenue = Decimal(0)
            total_actual_expense = Decimal(0)
            total_actual_net_income = Decimal(0)
            total_budget_revenue = Decimal(0)
            total_budget_expense = Decimal(0)
            total_budget_net_income = Decimal(0)

            period_details = []
            for period_obj in periods:
                period_analysis = await self.analyze_period_variance(
                    legal_entity_id, fiscal_year, period_obj.period_number
                )
                if "error" not in period_analysis:
                    period_details.append(period_analysis)
                    total_actual_revenue += Decimal(str(period_analysis["revenue"]["actual"]))
                    total_actual_expense += Decimal(str(period_analysis["expense"]["actual"]))
                    total_actual_net_income += Decimal(str(period_analysis["net_income"]["actual"]))
                    total_budget_revenue += Decimal(str(period_analysis["revenue"]["budget"]))
                    total_budget_expense += Decimal(str(period_analysis["expense"]["budget"]))
                    total_budget_net_income += Decimal(str(period_analysis["net_income"]["budget"]))

            revenue_variance = total_actual_revenue - total_budget_revenue
            revenue_variance_pct = (
                (revenue_variance / total_budget_revenue * 100) if total_budget_revenue != 0 else 0
            )
            expense_variance = total_budget_expense - total_actual_expense
            expense_variance_pct = (
                (expense_variance / total_budget_expense * 100) if total_budget_expense != 0 else 0
            )
            net_income_variance = total_actual_net_income - total_budget_net_income
            net_income_variance_pct = (
                (net_income_variance / total_budget_net_income * 100)
                if total_budget_net_income != 0
                else 0
            )

            return {
                "legal_entity_id": str(legal_entity_id),
                "fiscal_year": fiscal_year,
                "periods_analyzed": len(period_details),
                "ytd_revenue": {
                    "actual": float(total_actual_revenue),
                    "budget": float(total_budget_revenue),
                    "variance": float(revenue_variance),
                    "variance_percent": float(revenue_variance_pct),
                    "favorability": self._determine_favorability(
                        "revenue", total_actual_revenue, total_budget_revenue
                    ),
                },
                "ytd_expense": {
                    "actual": float(total_actual_expense),
                    "budget": float(total_budget_expense),
                    "variance": float(expense_variance),
                    "variance_percent": float(expense_variance_pct),
                    "favorability": self._determine_favorability(
                        "expense", total_actual_expense, total_budget_expense
                    ),
                },
                "ytd_net_income": {
                    "actual": float(total_actual_net_income),
                    "budget": float(total_budget_net_income),
                    "variance": float(net_income_variance),
                    "variance_percent": float(net_income_variance_pct),
                    "favorability": self._determine_favorability(
                        "net_income", total_actual_net_income, total_budget_net_income
                    ),
                },
                "period_details": period_details,
                "generated_at": datetime.now(UTC).isoformat(),
            }

    async def analyze_by_cost_center(
        self, legal_entity_id: UUID, fiscal_year: int, period: int
    ) -> dict[str, Any]:
        """
        Menganalisis varian per cost center.
        """
        # Placeholder: implementasi akan query actual per cost center dari ledger
        # dan budget per cost center dari tabel budget
        # Untuk sementara, return struktur dasar
        return {
            "legal_entity_id": str(legal_entity_id),
            "fiscal_year": fiscal_year,
            "period": period,
            "cost_centers": [
                {
                    "cost_center": "IT",
                    "revenue_actual": 0,
                    "revenue_budget": 0,
                    "revenue_variance": 0,
                    "expense_actual": 0,
                    "expense_budget": 0,
                    "expense_variance": 0,
                }
            ],
            "message": "Detailed cost center analysis requires budget data configuration",
        }

    async def save_variance_analysis(
        self, legal_entity_id: UUID, fiscal_year: int, period: int, analysis: dict[str, Any]
    ) -> None:
        """
        Menyimpan analisis varian ke tabel materialized.
        """
        async with await self._get_session() as session, session.begin():
            await session.execute(
                delete(VarianceAnalysisTable).where(
                    VarianceAnalysisTable.legal_entity_id == legal_entity_id,
                    VarianceAnalysisTable.fiscal_year == fiscal_year,
                    VarianceAnalysisTable.period == period,
                )
            )
            stmt = insert(VarianceAnalysisTable).values(
                id=uuid4(),
                legal_entity_id=legal_entity_id,
                fiscal_year=fiscal_year,
                period=period,
                analysis_data=analysis,
                generated_at=datetime.now(UTC),
            )
            await session.execute(stmt)
            await session.commit()

    async def get_saved_analysis(
        self, legal_entity_id: UUID, fiscal_year: int, period: int
    ) -> dict | None:
        """
        Mendapatkan analisis varian yang sudah tersimpan.
        """
        async with await self._get_session() as session:
            stmt = select(VarianceAnalysisTable).where(
                VarianceAnalysisTable.legal_entity_id == legal_entity_id,
                VarianceAnalysisTable.fiscal_year == fiscal_year,
                VarianceAnalysisTable.period == period,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            return row.analysis_data

    async def refresh_analysis(self, legal_entity_id: UUID, fiscal_year: int, period: int) -> dict:
        """
        Menghitung dan menyimpan analisis varian terbaru.
        """
        analysis = await self.analyze_period_variance(legal_entity_id, fiscal_year, period)
        if "error" not in analysis:
            await self.save_variance_analysis(legal_entity_id, fiscal_year, period, analysis)
            logger.info(f"Variance analysis saved for {legal_entity_id} FY{fiscal_year}P{period}")
        return analysis


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_variance_analyzer: VarianceAnalyzerActualVsBudget | None = None


async def get_variance_analyzer() -> VarianceAnalyzerActualVsBudget:
    """Get singleton instance of VarianceAnalyzerActualVsBudget."""
    global _variance_analyzer
    if _variance_analyzer is None:
        _variance_analyzer = VarianceAnalyzerActualVsBudget()
    return _variance_analyzer


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["VarianceAnalyzerActualVsBudget", "VarianceAnalyzerError", "get_variance_analyzer"]
