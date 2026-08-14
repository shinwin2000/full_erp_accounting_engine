#!/usr/bin/env python3
"""
Module: fiscal_income_statement.py
Layer: Projections (Ledger)
Responsibility: Membangun read model Income Statement untuk fiscal year (tahunan).
               Mengagregasi data dari income statement periodik untuk menghasilkan
               laporan laba rugi tahunan. Mendukung perbandingan antar tahun,
               rolling forecast, dan analisis tren.
Dependencies:
- asyncio, logging, datetime
- sqlalchemy.ext.asyncio
- infrastructure.database.session_factory_sqlalchemy
- infrastructure.persistence_orm.ledger_entry_table
- infrastructure.persistence_orm.account_table
- infrastructure.persistence_orm.fiscal_period_table
- projections.ledger.income_statement_period (IncomeStatementPeriod)
Audit: Setiap pembangunan fiscal income statement dicatat. Rebuild dimonitor.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, DateTime, Index, Integer, Numeric, delete, insert, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.persistence_orm.account_table import AccountTable
from infrastructure.persistence_orm.fiscal_period_table import FiscalPeriodTable
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger
from projections.ledger.income_statement_period import (
    IncomeStatementPeriod,
    get_income_statement_projection,
)

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

PROJECTION_NAME = "fiscal_income_statement"

# ============================================================================
# EXCEPTIONS
# ============================================================================


class FiscalIncomeStatementError(Exception):
    """Base exception untuk fiscal income statement projection."""

    pass


# ============================================================================
# ORM MODEL
# ============================================================================

Base = declarative_base()


class FiscalIncomeStatementTable(Base):
    __tablename__ = "fiscal_income_statement"
    __table_args__ = (
        Index("idx_fiscal_income_legal_entity", "legal_entity_id"),
        Index("idx_fiscal_income_year", "fiscal_year"),
        {"schema": "projections"},
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    total_revenue = Column(Numeric(20, 2), nullable=False, default=0)
    total_expense = Column(Numeric(20, 2), nullable=False, default=0)
    total_cogs = Column(Numeric(20, 2), nullable=False, default=0)
    gross_profit = Column(Numeric(20, 2), nullable=False, default=0)
    operating_income = Column(Numeric(20, 2), nullable=False, default=0)
    net_income = Column(Numeric(20, 2), nullable=False, default=0)
    periods_data = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


# ============================================================================
# FISCAL INCOME STATEMENT PROJECTION
# ============================================================================


class FiscalIncomeStatement:
    """
    Read model Income Statement untuk fiscal year.

    Fitur:
    - Mengagregasi income statement per periode menjadi tahunan
    - Menyimpan hasil dalam tabel materialized
    - Mendukung perbandingan antar tahun (year-over-year)
    - Rolling forecast (YTD + forecast)
    - Rebuild dari event store atau dari period aggregation
    """

    def __init__(self):
        self._session_factory = None
        self._period_projection: IncomeStatementPeriod | None = None

    async def _get_session(self) -> AsyncSession:
        if self._session_factory is None:
            self._session_factory = await get_session_factory()
        return self._session_factory.get_session()

    async def _get_period_projection(self) -> IncomeStatementPeriod:
        if self._period_projection is None:
            self._period_projection = await get_income_statement_projection()
        return self._period_projection

    async def compute_fiscal_year_income(
        self, legal_entity_id: UUID, fiscal_year: int
    ) -> dict[str, Any]:
        """
        Menghitung income statement untuk satu fiscal year dengan mengagregasi periode.
        """
        async with await self._get_session() as session:
            # Get all periods in this fiscal year
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
            logger.warning(f"No closed periods found for fiscal year {fiscal_year}")
            return {
                "fiscal_year": fiscal_year,
                "legal_entity_id": str(legal_entity_id),
                "total_revenue": 0.0,
                "total_expense": 0.0,
                "total_cogs": 0.0,
                "gross_profit": 0.0,
                "operating_income": 0.0,
                "net_income": 0.0,
                "periods": [],
            }

        period_projection = await self._get_period_projection()

        total_revenue = Decimal(0)
        total_expense = Decimal(0)
        total_cogs = Decimal(0)
        monthly_data = []

        for period in periods:
            period_data = await period_projection.get_income_statement(legal_entity_id, period.id)
            if period_data:
                revenue = Decimal(str(period_data["total_revenue"]))
                expense = Decimal(str(period_data["total_expense"]))
                cogs = Decimal(str(period_data["total_cogs"]))

                total_revenue += revenue
                total_expense += expense
                total_cogs += cogs

                monthly_data.append(
                    {
                        "period_id": str(period.id),
                        "period_name": period.period_name,
                        "period_number": period.period_number,
                        "revenue": float(revenue),
                        "expense": float(expense),
                        "net_income": float(revenue - expense),
                    }
                )

        gross_profit = total_revenue - total_cogs
        operating_income = gross_profit - (total_expense - total_cogs)
        net_income = total_revenue - total_expense

        return {
            "fiscal_year": fiscal_year,
            "legal_entity_id": str(legal_entity_id),
            "total_revenue": float(total_revenue),
            "total_expense": float(total_expense),
            "total_cogs": float(total_cogs),
            "gross_profit": float(gross_profit),
            "operating_income": float(operating_income),
            "net_income": float(net_income),
            "periods": monthly_data,
            "created_at": datetime.now(UTC).isoformat(),
        }

    async def save_fiscal_income(self, income_data: dict[str, Any]) -> None:
        """
        Menyimpan fiscal income statement ke tabel materialized.
        """
        async with await self._get_session() as session, session.begin():
            # Delete existing
            await session.execute(
                delete(FiscalIncomeStatementTable).where(
                    FiscalIncomeStatementTable.legal_entity_id
                    == UUID(income_data["legal_entity_id"]),
                    FiscalIncomeStatementTable.fiscal_year == income_data["fiscal_year"],
                )
            )

            stmt = insert(FiscalIncomeStatementTable).values(
                id=uuid4(),
                legal_entity_id=UUID(income_data["legal_entity_id"]),
                fiscal_year=income_data["fiscal_year"],
                total_revenue=Decimal(str(income_data["total_revenue"])),
                total_expense=Decimal(str(income_data["total_expense"])),
                total_cogs=Decimal(str(income_data["total_cogs"])),
                gross_profit=Decimal(str(income_data["gross_profit"])),
                operating_income=Decimal(str(income_data["operating_income"])),
                net_income=Decimal(str(income_data["net_income"])),
                periods_data=income_data["periods"],
                created_at=datetime.now(UTC),
            )
            await session.execute(stmt)
            await session.commit()

    async def rebuild_for_legal_entity(self, legal_entity_id: UUID) -> dict[str, Any]:
        """
        Membangun ulang fiscal income statement untuk semua tahun.
        """
        logger.info(f"Rebuilding fiscal income statements for legal entity {legal_entity_id}")
        start_time = datetime.now(UTC)

        async with await self._get_session() as session:
            # Get distinct fiscal years
            stmt = (
                select(FiscalPeriodTable.fiscal_year)
                .where(
                    FiscalPeriodTable.legal_entity_id == legal_entity_id,
                    FiscalPeriodTable.status == "closed",
                )
                .distinct()
                .order_by(FiscalPeriodTable.fiscal_year)
            )
            result = await session.execute(stmt)
            fiscal_years = result.scalars().all()

        success_count = 0
        error_count = 0

        for year in fiscal_years:
            try:
                income_data = await self.compute_fiscal_year_income(legal_entity_id, year)
                await self.save_fiscal_income(income_data)
                success_count += 1
            except Exception as e:
                logger.error(f"Failed to compute fiscal income for year {year}: {e}")
                error_count += 1

        duration = (datetime.now(UTC) - start_time).total_seconds()

        result = {
            "legal_entity_id": str(legal_entity_id),
            "years_processed": len(fiscal_years),
            "success": success_count,
            "errors": error_count,
            "duration_seconds": duration,
        }

        logger.info(
            f"Fiscal income statements rebuild completed: {success_count} years, {error_count} errors"
        )

        if error_count > 0:
            await trigger_alert(
                title="Fiscal Income Statement Rebuild Partial Failure",
                message=f"{error_count} years failed to generate fiscal income statement",
                severity="warning",
                source="FiscalIncomeStatement",
            )

        return result

    async def rebuild_all(self) -> dict[str, Any]:
        """
        Membangun ulang fiscal income statement untuk semua legal entity.
        """
        async with await self._get_session() as session:
            stmt = select(AccountTable.legal_entity_id).distinct()
            result = await session.execute(stmt)
            legal_entity_ids = result.scalars().all()

        total_success = 0
        total_errors = 0

        for le_id in legal_entity_ids:
            res = await self.rebuild_for_legal_entity(le_id)
            total_success += res["success"]
            total_errors += res["errors"]

        return {
            "legal_entities_processed": len(legal_entity_ids),
            "total_success": total_success,
            "total_errors": total_errors,
            "completed_at": datetime.now(UTC).isoformat(),
        }

    async def get_fiscal_income(self, legal_entity_id: UUID, fiscal_year: int) -> dict | None:
        """
        Mendapatkan fiscal income statement untuk tahun tertentu.
        """
        async with await self._get_session() as session:
            stmt = select(FiscalIncomeStatementTable).where(
                FiscalIncomeStatementTable.legal_entity_id == legal_entity_id,
                FiscalIncomeStatementTable.fiscal_year == fiscal_year,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            return {
                "fiscal_year": row.fiscal_year,
                "legal_entity_id": str(row.legal_entity_id),
                "total_revenue": float(row.total_revenue),
                "total_expense": float(row.total_expense),
                "total_cogs": float(row.total_cogs),
                "gross_profit": float(row.gross_profit),
                "operating_income": float(row.operating_income),
                "net_income": float(row.net_income),
                "periods": row.periods_data,
                "created_at": row.created_at.isoformat(),
            }

    async def get_yearly_comparison(self, legal_entity_id: UUID, years: list[int]) -> list[dict]:
        """
        Mendapatkan perbandingan antar tahun (year-over-year analysis).
        """
        result = []
        for year in years:
            data = await self.get_fiscal_income(legal_entity_id, year)
            if data:
                result.append(data)

        # Calculate year-over-year changes
        for i in range(1, len(result)):
            prev = result[i - 1]
            curr = result[i]
            curr["yoy_revenue_change"] = curr["total_revenue"] - prev["total_revenue"]
            curr["yoy_revenue_percent"] = (
                (curr["yoy_revenue_change"] / prev["total_revenue"] * 100)
                if prev["total_revenue"] != 0
                else 0
            )
            curr["yoy_net_income_change"] = curr["net_income"] - prev["net_income"]
            curr["yoy_net_income_percent"] = (
                (curr["yoy_net_income_change"] / prev["net_income"] * 100)
                if prev["net_income"] != 0
                else 0
            )

        return result

    async def get_rolling_forecast(
        self, legal_entity_id: UUID, current_fiscal_year: int, current_period: int
    ) -> dict[str, Any]:
        """
        Menghitung rolling forecast untuk sisa tahun berjalan.

        Args:
            current_fiscal_year: Tahun fiskal saat ini
            current_period: Periode terakhir yang sudah ditutup

        Returns:
            Forecast untuk sisa tahun
        """
        # Get actual YTD data
        actual = await self.get_fiscal_income(legal_entity_id, current_fiscal_year)
        if not actual:
            return {"error": "No actual data found for current year"}

        # Get historical average growth rates for remaining periods
        prev_year_data = await self.get_fiscal_income(legal_entity_id, current_fiscal_year - 1)

        # Calculate average revenue per remaining period
        total_periods = 12  # Assuming monthly periods
        periods_remaining = total_periods - current_period
        if periods_remaining <= 0:
            return {"forecast": 0, "message": "Year already complete"}

        # Simple forecast: extrapolate YTD average
        avg_revenue_per_period = (
            actual["total_revenue"] / current_period if current_period > 0 else 0
        )
        forecast_revenue = avg_revenue_per_period * periods_remaining

        # Historical growth adjustment
        if prev_year_data:
            historical_growth = (
                (actual["total_revenue"] / prev_year_data["total_revenue"] - 1)
                if prev_year_data["total_revenue"] > 0
                else 0
            )
            adjusted_forecast = forecast_revenue * (1 + historical_growth)
        else:
            adjusted_forecast = forecast_revenue
            historical_growth = 0

        return {
            "legal_entity_id": str(legal_entity_id),
            "current_fiscal_year": current_fiscal_year,
            "current_period": current_period,
            "actual_ytd_revenue": actual["total_revenue"],
            "actual_ytd_net_income": actual["net_income"],
            "forecast_revenue": adjusted_forecast,
            "forecast_net_income": adjusted_forecast
            * (actual["net_income"] / actual["total_revenue"])
            if actual["total_revenue"] != 0
            else 0,
            "periods_remaining": periods_remaining,
            "assumptions": {
                "historical_growth_rate": historical_growth,
                "avg_revenue_per_period": avg_revenue_per_period,
            },
        }

    async def incremental_update(self, period_id: UUID) -> None:
        """
        Incremental update ketika periode ditutup.
        """
        async with await self._get_session() as session:
            period_stmt = select(FiscalPeriodTable).where(FiscalPeriodTable.id == period_id)
            period_result = await session.execute(period_stmt)
            period = period_result.scalar_one_or_none()
            if not period:
                logger.warning(f"Period {period_id} not found")
                return

            # Recompute for the fiscal year of this period
            await self.rebuild_for_legal_entity(period.legal_entity_id)
            logger.info(f"Fiscal income statement updated for year {period.fiscal_year}")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_fiscal_income_projection: FiscalIncomeStatement | None = None


async def get_fiscal_income_projection() -> FiscalIncomeStatement:
    """Get singleton instance of FiscalIncomeStatement."""
    global _fiscal_income_projection
    if _fiscal_income_projection is None:
        _fiscal_income_projection = FiscalIncomeStatement()
    return _fiscal_income_projection


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["FiscalIncomeStatement", "FiscalIncomeStatementError", "get_fiscal_income_projection"]
