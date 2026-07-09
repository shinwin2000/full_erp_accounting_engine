#!/usr/bin/env python3
"""
Module: financial_ratios_calculator.py
Layer: Projections (Analytics BI)
Responsibility: Menghitung berbagai rasio keuangan untuk analisis fundamental:
               likuiditas (current ratio, quick ratio), solvabilitas (debt to equity,
               debt to assets), profitabilitas (ROA, ROE, gross margin, net margin,
               operating margin), aktivitas (inventory turnover, receivables turnover,
               payables turnover), dan market ratios. Mendukung perbandingan
               dengan industry average dan analisis tren multi-periode.
Dependencies:
- asyncio, logging, datetime, decimal, math
- sqlalchemy.ext.asyncio
- infrastructure.database.session_factory_sqlalchemy
- projections.ledger.balance_sheet_snapshot
- projections.ledger.income_statement_period
- projections.ledger.cash_flow_indirect
- infrastructure.telemetry.structured_json_logging
- infrastructure.telemetry.alert_manager_router
Audit: Rasio keuangan digunakan untuk analisis kesehatan perusahaan.

Perbaikan presisi:
    - Mengganti float() dengan str() pada nilai moneter (working_capital, alerts)
      untuk menjaga presisi dan memenuhi aturan MNY-003.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.persistence_orm.fiscal_period_table import FiscalPeriodTable
from infrastructure.telemetry.alert_manager_router import trigger_alert
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

PROJECTION_NAME = "financial_ratios"

# Industry average benchmarks (contoh, bisa dikonfigurasi)
INDUSTRY_AVERAGES = {
    "current_ratio": 2.0,
    "quick_ratio": 1.0,
    "debt_to_equity": 0.8,
    "debt_to_assets": 0.4,
    "roe": 0.15,
    "roa": 0.08,
    "gross_margin": 0.35,
    "net_margin": 0.10,
    "operating_margin": 0.12,
    "inventory_turnover": 6.0,
    "receivables_turnover": 12.0,
    "payables_turnover": 8.0,
}

# Alert thresholds
ALERT_THRESHOLD_DEVIATION = 0.5  # 50% deviation from benchmark

# ============================================================================
# EXCEPTIONS
# ============================================================================


class FinancialRatiosError(Exception):
    """Base exception untuk financial ratios calculator."""

    pass


# ============================================================================
# FINANCIAL RATIOS CALCULATOR
# ============================================================================


class FinancialRatiosCalculator:
    """
    Kalkulator rasio keuangan.

    Fitur:
    - Liquidity ratios: current ratio, quick ratio, cash ratio
    - Solvency ratios: debt to equity, debt to assets, interest coverage
    - Profitability ratios: ROA, ROE, gross margin, net margin, operating margin, EBITDA margin
    - Activity ratios: inventory turnover, receivables turnover, payables turnover, asset turnover
    - Working capital ratios
    - Comparison with industry averages
    - Trend analysis over multiple periods
    - Alert for significant deviations
    """

    def __init__(self):
        self._session_factory = None
        self._balance_sheet: BalanceSheetSnapshot | None = None
        self._income_statement: IncomeStatementPeriod | None = None
        self._cash_flow: CashFlowIndirect | None = None
        self._industry_averages = INDUSTRY_AVERAGES.copy()

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

    async def _get_balance_sheet_data(self, legal_entity_id: UUID, period_id: UUID) -> dict:
        """Mendapatkan data balance sheet untuk periode tertentu."""
        bs = await self._balance_sheet.get_snapshot(legal_entity_id, period_id)
        if not bs:
            return {}
        return {
            "total_assets": Decimal(str(bs.get("total_assets", 0))),
            "current_assets": Decimal(str(bs.get("current_assets", 0))),
            "total_liabilities": Decimal(str(bs.get("total_liabilities", 0))),
            "current_liabilities": Decimal(str(bs.get("current_liabilities", 0))),
            "total_equity": Decimal(str(bs.get("total_equity", 0))),
            "inventory": Decimal(str(bs.get("inventory", 0))),
            "accounts_receivable": Decimal(str(bs.get("accounts_receivable", 0))),
            "accounts_payable": Decimal(str(bs.get("accounts_payable", 0))),
            "cash": Decimal(str(bs.get("cash", 0))),
        }

    async def _get_income_statement_data(self, legal_entity_id: UUID, period_id: UUID) -> dict:
        """Mendapatkan data income statement untuk periode tertentu."""
        inc = await self._income_statement.get_income_statement(legal_entity_id, period_id)
        if not inc:
            return {}
        return {
            "revenue": Decimal(str(inc.get("total_revenue", 0))),
            "cogs": Decimal(str(inc.get("total_cogs", 0))),
            "operating_expense": Decimal(str(inc.get("total_expense", 0)))
            - Decimal(str(inc.get("total_cogs", 0))),
            "net_income": Decimal(str(inc.get("net_income", 0))),
            "ebitda": Decimal(str(inc.get("ebitda", 0))) if inc.get("ebitda") else Decimal(0),
            "interest_expense": Decimal(str(inc.get("interest_expense", 0)))
            if inc.get("interest_expense")
            else Decimal(0),
        }

    async def calculate_ratios(self, legal_entity_id: UUID, period_id: UUID) -> dict[str, Any]:
        """
        Menghitung semua rasio keuangan untuk periode tertentu.
        """
        period_stmt = select(FiscalPeriodTable).where(FiscalPeriodTable.id == period_id)
        async with await self._get_session() as session:
            period_result = await session.execute(period_stmt)
            period = period_result.scalar_one_or_none()
            if not period:
                raise FinancialRatiosError(f"Period {period_id} not found")

        bs_data = await self._get_balance_sheet_data(legal_entity_id, period_id)
        inc_data = await self._get_income_statement_data(legal_entity_id, period_id)

        # Extract values
        total_assets = bs_data.get("total_assets", Decimal(0))
        current_assets = bs_data.get("current_assets", Decimal(0))
        current_liabilities = bs_data.get("current_liabilities", Decimal(0))
        total_liabilities = bs_data.get("total_liabilities", Decimal(0))
        total_equity = bs_data.get("total_equity", Decimal(0))
        inventory = bs_data.get("inventory", Decimal(0))
        accounts_receivable = bs_data.get("accounts_receivable", Decimal(0))
        accounts_payable = bs_data.get("accounts_payable", Decimal(0))
        cash = bs_data.get("cash", Decimal(0))

        revenue = inc_data.get("revenue", Decimal(0))
        cogs = inc_data.get("cogs", Decimal(0))
        operating_expense = inc_data.get("operating_expense", Decimal(0))
        net_income = inc_data.get("net_income", Decimal(0))
        ebitda = inc_data.get("ebitda", Decimal(0))
        interest_expense = inc_data.get("interest_expense", Decimal(0))

        # Liquidity Ratios
        current_ratio = current_assets / current_liabilities if current_liabilities != 0 else None
        quick_ratio = (
            (current_assets - inventory) / current_liabilities if current_liabilities != 0 else None
        )
        cash_ratio = cash / current_liabilities if current_liabilities != 0 else None

        # Solvency Ratios
        debt_to_equity = total_liabilities / total_equity if total_equity != 0 else None
        debt_to_assets = total_liabilities / total_assets if total_assets != 0 else None
        interest_coverage = ebitda / interest_expense if interest_expense != 0 else None

        # Profitability Ratios
        roa = net_income / total_assets if total_assets != 0 else None
        roe = net_income / total_equity if total_equity != 0 else None
        gross_margin = (revenue - cogs) / revenue if revenue != 0 else None
        operating_margin = (revenue - cogs - operating_expense) / revenue if revenue != 0 else None
        net_margin = net_income / revenue if revenue != 0 else None
        ebitda_margin = ebitda / revenue if revenue != 0 else None

        # Activity Ratios (assuming period length = 1 year for turnover calculations)
        # For monthly/quarterly, we would annualize. Here we assume period represents a year.
        inventory_turnover = cogs / inventory if inventory != 0 else None
        receivables_turnover = revenue / accounts_receivable if accounts_receivable != 0 else None
        payables_turnover = cogs / accounts_payable if accounts_payable != 0 else None
        asset_turnover = revenue / total_assets if total_assets != 0 else None

        # Working capital
        working_capital = current_assets - current_liabilities
        working_capital_turnover = revenue / working_capital if working_capital != 0 else None

        # Days metrics
        days_inventory = 365 / inventory_turnover if inventory_turnover else None
        days_receivables = 365 / receivables_turnover if receivables_turnover else None
        days_payables = 365 / payables_turnover if payables_turnover else None
        cash_conversion_cycle = (
            (days_inventory or 0) + (days_receivables or 0) - (days_payables or 0)
            if days_inventory and days_receivables and days_payables
            else None
        )

        # Compare with industry averages
        ratios = {
            "current_ratio": current_ratio,
            "quick_ratio": quick_ratio,
            "cash_ratio": cash_ratio,
            "debt_to_equity": debt_to_equity,
            "debt_to_assets": debt_to_assets,
            "interest_coverage": interest_coverage,
            "roa": roa,
            "roe": roe,
            "gross_margin": gross_margin,
            "operating_margin": operating_margin,
            "net_margin": net_margin,
            "ebitda_margin": ebitda_margin,
            "inventory_turnover": inventory_turnover,
            "receivables_turnover": receivables_turnover,
            "payables_turnover": payables_turnover,
            "asset_turnover": asset_turnover,
            "working_capital": str(working_capital),  # ganti float -> str
            "working_capital_turnover": working_capital_turnover,
            "days_inventory": days_inventory,
            "days_receivables": days_receivables,
            "days_payables": days_payables,
            "cash_conversion_cycle": cash_conversion_cycle,
        }

        # Compare with industry benchmarks and send alerts if significantly different
        alerts = []
        for ratio_name, value in ratios.items():
            if value is not None and ratio_name in self._industry_averages:
                benchmark = self._industry_averages[ratio_name]
                if benchmark != 0:
                    deviation = abs((value - benchmark) / benchmark)
                    if deviation > ALERT_THRESHOLD_DEVIATION:
                        alerts.append(
                            {
                                "ratio": ratio_name,
                                "value": str(value),  # ganti float -> str
                                "benchmark": benchmark,
                                "deviation_percent": deviation * 100,
                                "message": f"{ratio_name} deviates {deviation * 100:.1f}% from industry average",
                            }
                        )

        if alerts:
            await trigger_alert(
                title="Significant Ratio Deviation",
                message=f"Financial ratios deviate significantly from industry benchmarks: {len(alerts)} ratios",
                severity="warning",
                source="FinancialRatiosCalculator",
                metadata={"alerts": alerts[:3]},
            )

        return {
            "legal_entity_id": str(legal_entity_id),
            "period_id": str(period_id),
            "period_name": period.period_name,
            "ratios": ratios,
            "industry_comparison": {
                "benchmarks": {k: v for k, v in self._industry_averages.items() if k in ratios},
                "alerts": alerts,
            },
            "generated_at": datetime.now(UTC).isoformat(),
        }

    async def get_trend_ratios(self, legal_entity_id: UUID, periods: int = 4) -> list[dict]:
        """
        Mendapatkan tren rasio untuk beberapa periode terakhir.
        """
        async with await self._get_session() as session:
            period_stmt = (
                select(FiscalPeriodTable)
                .where(
                    FiscalPeriodTable.legal_entity_id == legal_entity_id,
                    FiscalPeriodTable.status == "closed",
                )
                .order_by(FiscalPeriodTable.end_date.desc())
                .limit(periods)
            )
            period_result = await session.execute(period_stmt)
            periods_list = period_result.scalars().all()
            periods_list.sort(key=lambda p: p.end_date)  # Ascending

        trend = []
        for period in periods_list:
            ratios_data = await self.calculate_ratios(legal_entity_id, period.id)
            # Extract key ratios for trend
            r = ratios_data["ratios"]
            trend.append(
                {
                    "period_name": period.period_name,
                    "end_date": period.end_date.isoformat(),
                    "current_ratio": r.get("current_ratio"),
                    "debt_to_equity": r.get("debt_to_equity"),
                    "roa": r.get("roa"),
                    "roe": r.get("roe"),
                    "gross_margin": r.get("gross_margin"),
                    "net_margin": r.get("net_margin"),
                    "inventory_turnover": r.get("inventory_turnover"),
                }
            )
        return trend

    async def save_ratios(
        self, legal_entity_id: UUID, period_id: UUID, ratios_data: dict[str, Any]
    ) -> None:
        """
        Menyimpan rasio keuangan ke tabel materialized.
        """
        async with await self._get_session() as session, session.begin():
            await session.execute(
                delete(FinancialRatiosTable).where(
                    FinancialRatiosTable.legal_entity_id == legal_entity_id,
                    FinancialRatiosTable.period_id == period_id,
                )
            )
            stmt = insert(FinancialRatiosTable).values(
                id=uuid4(),
                legal_entity_id=legal_entity_id,
                period_id=period_id,
                ratios_data=ratios_data,
                generated_at=datetime.now(UTC),
            )
            await session.execute(stmt)
            await session.commit()

    async def get_saved_ratios(self, legal_entity_id: UUID, period_id: UUID) -> dict | None:
        """
        Mendapatkan rasio yang sudah tersimpan.
        """
        async with await self._get_session() as session:
            stmt = select(FinancialRatiosTable).where(
                FinancialRatiosTable.legal_entity_id == legal_entity_id,
                FinancialRatiosTable.period_id == period_id,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            return row.ratios_data

    async def refresh_all_periods(self, legal_entity_id: UUID) -> list[dict]:
        """
        Menghitung dan menyimpan rasio untuk semua periode tertutup.
        """
        async with await self._get_session() as session:
            period_stmt = select(FiscalPeriodTable.id).where(
                FiscalPeriodTable.legal_entity_id == legal_entity_id,
                FiscalPeriodTable.status == "closed",
            )
            period_result = await session.execute(period_stmt)
            period_ids = period_result.scalars().all()

        results = []
        for period_id in period_ids:
            ratios = await self.calculate_ratios(legal_entity_id, period_id)
            await self.save_ratios(legal_entity_id, period_id, ratios)
            results.append(ratios)
            logger.info(f"Financial ratios calculated for period {period_id}")

        return results

    async def update_industry_benchmarks(self, benchmarks: dict[str, float]) -> None:
        """
        Memperbarui industry benchmarks.
        """
        self._industry_averages.update(benchmarks)
        logger.info(f"Industry benchmarks updated: {benchmarks}")


# ============================================================================
# ORM MODEL (tambahan)
# ============================================================================

from sqlalchemy import JSON, Column, DateTime, Index

Base = declarative_base()


class FinancialRatiosTable(Base):
    __tablename__ = "financial_ratios"
    __table_args__ = (
        Index("idx_financial_ratios_legal_entity", "legal_entity_id"),
        Index("idx_financial_ratios_period", "period_id"),
        {"schema": "projections"},
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    period_id = Column(PGUUID(as_uuid=True), nullable=False)
    ratios_data = Column(JSON, nullable=False)
    generated_at = Column(DateTime(timezone=True), nullable=False)


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_financial_ratios_calculator: FinancialRatiosCalculator | None = None


async def get_financial_ratios_calculator() -> FinancialRatiosCalculator:
    """Get singleton instance of FinancialRatiosCalculator."""
    global _financial_ratios_calculator
    if _financial_ratios_calculator is None:
        _financial_ratios_calculator = FinancialRatiosCalculator()
    return _financial_ratios_calculator


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["FinancialRatiosCalculator", "FinancialRatiosError", "get_financial_ratios_calculator"]