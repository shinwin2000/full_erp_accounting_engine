#!/usr/bin/env python3
"""
Module: income_statement_period.py
Layer: Projections (Ledger)
Responsibility: Membangun read model Income Statement (Laporan Laba Rugi) per periode.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.persistence_orm.account_table import AccountTable
from infrastructure.persistence_orm.fiscal_period_table import FiscalPeriodTable
from infrastructure.persistence_orm.ledger_entry_table import LedgerEntryTable
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

PROJECTION_NAME = "income_statement_period"
BATCH_SIZE = 100
REVENUE_ACCOUNT_TYPES = ("Revenue",)
EXPENSE_ACCOUNT_TYPES = ("Expense",)
COGS_ACCOUNT_TYPES = ("Expense",)

# ============================================================================
# EXCEPTIONS
# ============================================================================


class IncomeStatementError(Exception):
    pass


# ============================================================================
# INCOME STATEMENT PERIOD PROJECTION
# ============================================================================


class IncomeStatementPeriod:
    def __init__(self):
        self._event_store = None
        self._session_factory = None
        self._account_type_cache: dict[str, str] = {}
        self._is_cogs_cache: dict[str, bool] = {}

    async def _get_event_store(self):
        if self._event_store is None:
            from infrastructure.event_store.append_only_store import get_event_store
            self._event_store = await get_event_store()
        return self._event_store

    async def _get_session(self) -> AsyncSession:
        if self._session_factory is None:
            self._session_factory = await get_session_factory()
        return self._session_factory.get_session()

    async def _get_account_type(self, account_id: UUID) -> str | None:
        key = str(account_id)
        if key in self._account_type_cache:
            return self._account_type_cache[key]
        async with await self._get_session() as session:
            stmt = select(AccountTable.account_type).where(AccountTable.id == account_id)
            result = await session.execute(stmt)
            acc_type = result.scalar_one_or_none()
            if acc_type:
                self._account_type_cache[key] = acc_type
            return acc_type

    async def _is_cogs_account(self, account_id: UUID) -> bool:
        key = str(account_id)
        if key in self._is_cogs_cache:
            return self._is_cogs_cache[key]
        async with await self._get_session() as session:
            stmt = select(AccountTable.account_code, AccountTable.is_cogs).where(
                AccountTable.id == account_id
            )
            result = await session.execute(stmt)
            row = result.first()
            if row:
                is_cogs = row[1] or (row[0] and row[0].startswith("5-11"))
                self._is_cogs_cache[key] = is_cogs
                return is_cogs
            return False

    async def compute_period_income(self, legal_entity_id: UUID, period_id: UUID) -> dict[str, Any]:
        async with await self._get_session() as session:
            period_stmt = select(FiscalPeriodTable).where(FiscalPeriodTable.id == period_id)
            period_result = await session.execute(period_stmt)
            period = period_result.scalar_one_or_none()
            if not period:
                raise IncomeStatementError(f"Period {period_id} not found")

            start_date = period.start_date
            end_date = period.end_date

            revenue_stmt = select(
                AccountTable.id, AccountTable.account_code, AccountTable.account_name
            ).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.account_type.in_(REVENUE_ACCOUNT_TYPES),
                AccountTable.deleted_at.is_(None),
            )
            revenue_result = await session.execute(revenue_stmt)
            revenue_accounts = revenue_result.all()

            expense_stmt = select(
                AccountTable.id, AccountTable.account_code, AccountTable.account_name
            ).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.account_type.in_(EXPENSE_ACCOUNT_TYPES),
                AccountTable.deleted_at.is_(None),
            )
            expense_result = await session.execute(expense_stmt)
            expense_accounts = expense_result.all()

            total_revenue = Decimal(0)
            revenue_breakdown = []
            for acc in revenue_accounts:
                balance_stmt = select(
                    func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0).label("credit"),
                    func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("debit"),
                ).where(
                    LedgerEntryTable.account_id == acc[0],
                    LedgerEntryTable.legal_entity_id == legal_entity_id,
                    LedgerEntryTable.posting_date >= start_date,
                    LedgerEntryTable.posting_date <= end_date,
                )
                balance_result = await session.execute(balance_stmt)
                row = balance_result.first()
                credit = Decimal(str(row.credit or 0))
                debit = Decimal(str(row.debit or 0))
                amount = credit - debit
                total_revenue += amount
                revenue_breakdown.append(
                    {
                        "account_id": str(acc[0]),
                        "account_code": acc[1],
                        "account_name": acc[2],
                        "amount": str(amount),
                    }
                )

            total_expense = Decimal(0)
            total_cogs = Decimal(0)
            expense_breakdown = []
            for acc in expense_accounts:
                balance_stmt = select(
                    func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("debit"),
                    func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0).label("credit"),
                ).where(
                    LedgerEntryTable.account_id == acc[0],
                    LedgerEntryTable.legal_entity_id == legal_entity_id,
                    LedgerEntryTable.posting_date >= start_date,
                    LedgerEntryTable.posting_date <= end_date,
                )
                balance_result = await session.execute(balance_stmt)
                row = balance_result.first()
                debit = Decimal(str(row.debit or 0))
                credit = Decimal(str(row.credit or 0))
                amount = debit - credit
                total_expense += amount

                is_cogs = await self._is_cogs_account(acc[0])
                if is_cogs:
                    total_cogs += amount

                expense_breakdown.append(
                    {
                        "account_id": str(acc[0]),
                        "account_code": acc[1],
                        "account_name": acc[2],
                        "amount": str(amount),
                        "is_cogs": is_cogs,
                    }
                )

            gross_profit = total_revenue - total_cogs
            operating_income = gross_profit - (total_expense - total_cogs)
            net_income = total_revenue - total_expense

            return {
                "period_id": str(period_id),
                "period_name": period.period_name,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "legal_entity_id": str(legal_entity_id),
                "total_revenue": str(total_revenue),
                "total_expense": str(total_expense),
                "total_cogs": str(total_cogs),
                "gross_profit": str(gross_profit),
                "operating_income": str(operating_income),
                "net_income": str(net_income),
                "revenue_breakdown": revenue_breakdown,
                "expense_breakdown": expense_breakdown,
                "created_at": datetime.now(UTC).isoformat(),
            }

    async def save_income_statement(self, income_data: dict[str, Any]) -> None:
        async with await self._get_session() as session, session.begin():
            await session.execute(
                delete(IncomeStatementPeriodTable).where(
                    IncomeStatementPeriodTable.legal_entity_id
                    == UUID(income_data["legal_entity_id"]),
                    IncomeStatementPeriodTable.period_id == UUID(income_data["period_id"]),
                )
            )
            stmt = insert(IncomeStatementPeriodTable).values(
                id=uuid4(),
                legal_entity_id=UUID(income_data["legal_entity_id"]),
                period_id=UUID(income_data["period_id"]),
                period_name=income_data["period_name"],
                start_date=date.fromisoformat(income_data["start_date"]),
                end_date=date.fromisoformat(income_data["end_date"]),
                total_revenue=Decimal(income_data["total_revenue"]),
                total_expense=Decimal(income_data["total_expense"]),
                total_cogs=Decimal(income_data["total_cogs"]),
                gross_profit=Decimal(income_data["gross_profit"]),
                operating_income=Decimal(income_data["operating_income"]),
                net_income=Decimal(income_data["net_income"]),
                revenue_breakdown=income_data["revenue_breakdown"],
                expense_breakdown=income_data["expense_breakdown"],
                created_at=datetime.now(UTC),
            )
            await session.execute(stmt)
            await session.commit()

    async def rebuild_for_legal_entity(self, legal_entity_id: UUID) -> dict[str, Any]:
        logger.info(f"Rebuilding income statements for legal entity {legal_entity_id}")
        start_time = datetime.now(UTC)
        async with await self._get_session() as session:
            period_stmt = (
                select(FiscalPeriodTable)
                .where(
                    FiscalPeriodTable.legal_entity_id == legal_entity_id,
                    FiscalPeriodTable.status == "closed",
                )
                .order_by(FiscalPeriodTable.end_date)
            )
            period_result = await session.execute(period_stmt)
            periods = period_result.scalars().all()

        success_count = 0
        error_count = 0
        for period in periods:
            try:
                income_data = await self.compute_period_income(legal_entity_id, period.id)
                await self.save_income_statement(income_data)
                success_count += 1
            except (IncomeStatementError, SQLAlchemyError, ValueError, TypeError) as e:
                logger.error(f"Failed to compute income statement for period {period.id}: {e}")
                error_count += 1
            except Exception as e:
                logger.error(f"Unexpected error for period {period.id}: {e}")
                error_count += 1

        duration = (datetime.now(UTC) - start_time).total_seconds()
        result = {
            "legal_entity_id": str(legal_entity_id),
            "periods_processed": len(periods),
            "success": success_count,
            "errors": error_count,
            "duration_seconds": duration,
        }
        logger.info(f"Income statements rebuild completed: {success_count} periods, {error_count} errors")
        if error_count > 0:
            await trigger_alert(
                title="Income Statement Rebuild Partial Failure",
                message=f"{error_count} periods failed to generate income statement",
                severity="warning",
                source="IncomeStatementPeriod",
            )
        return result

    async def rebuild_all(self) -> dict[str, Any]:
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

    async def get_income_statement(self, legal_entity_id: UUID, period_id: UUID) -> dict | None:
        async with await self._get_session() as session:
            stmt = select(IncomeStatementPeriodTable).where(
                IncomeStatementPeriodTable.legal_entity_id == legal_entity_id,
                IncomeStatementPeriodTable.period_id == period_id,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            return {
                "period_id": str(row.period_id),
                "period_name": row.period_name,
                "start_date": row.start_date.isoformat(),
                "end_date": row.end_date.isoformat(),
                "total_revenue": str(row.total_revenue),
                "total_expense": str(row.total_expense),
                "total_cogs": str(row.total_cogs),
                "gross_profit": str(row.gross_profit),
                "operating_income": str(row.operating_income),
                "net_income": str(row.net_income),
                "revenue_breakdown": row.revenue_breakdown,
                "expense_breakdown": row.expense_breakdown,
                "created_at": row.created_at.isoformat(),
            }

    async def get_ytd_income(self, legal_entity_id: UUID, fiscal_year: int) -> dict[str, Any]:
        async with await self._get_session() as session:
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

        total_revenue = Decimal(0)
        total_expense = Decimal(0)
        total_cogs = Decimal(0)
        for period in periods:
            stmt = select(IncomeStatementPeriodTable).where(
                IncomeStatementPeriodTable.legal_entity_id == legal_entity_id,
                IncomeStatementPeriodTable.period_id == period.id,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row:
                total_revenue += Decimal(str(row.total_revenue))
                total_expense += Decimal(str(row.total_expense))
                total_cogs += Decimal(str(row.total_cogs))

        return {
            "fiscal_year": fiscal_year,
            "legal_entity_id": str(legal_entity_id),
            "total_revenue": str(total_revenue),
            "total_expense": str(total_expense),
            "total_cogs": str(total_cogs),
            "gross_profit": str(total_revenue - total_cogs),
            "net_income": str(total_revenue - total_expense),
        }

    async def get_period_comparison(
        self, legal_entity_id: UUID, period1_id: UUID, period2_id: UUID
    ) -> dict:
        income1 = await self.get_income_statement(legal_entity_id, period1_id)
        income2 = await self.get_income_statement(legal_entity_id, period2_id)
        if not income1 or not income2:
            return {"error": "One or both periods not found"}

        rev1 = Decimal(income1["total_revenue"])
        rev2 = Decimal(income2["total_revenue"])
        net1 = Decimal(income1["net_income"])
        net2 = Decimal(income2["net_income"])
        gp1 = Decimal(income1["gross_profit"])
        gp2 = Decimal(income2["gross_profit"])

        revenue_change = rev2 - rev1
        revenue_change_pct = (revenue_change / rev1 * 100) if rev1 != 0 else Decimal(0)
        net_income_change = net2 - net1
        net_income_change_pct = (net_income_change / net1 * 100) if net1 != 0 else Decimal(0)

        return {
            "period1": income1,
            "period2": income2,
            "comparison": {
                "revenue_change": str(revenue_change),
                "revenue_change_percent": str(revenue_change_pct),
                "net_income_change": str(net_income_change),
                "net_income_change_percent": str(net_income_change_pct),
                "gross_profit_change": str(gp2 - gp1),
            },
        }

    async def incremental_update(self, period_id: UUID) -> None:
        async with await self._get_session() as session:
            period_stmt = select(FiscalPeriodTable).where(FiscalPeriodTable.id == period_id)
            period_result = await session.execute(period_stmt)
            period = period_result.scalar_one_or_none()
            if not period:
                logger.warning(f"Period {period_id} not found for income statement update")
                return
            try:
                income_data = await self.compute_period_income(period.legal_entity_id, period_id)
                await self.save_income_statement(income_data)
                logger.info(f"Income statement updated for period {period.period_name}")
            except (IncomeStatementError, SQLAlchemyError, ValueError, TypeError) as e:
                logger.error(f"Failed to update income statement for period {period_id}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error updating income statement for period {period_id}: {e}")


# ============================================================================
# ORM MODEL
# ============================================================================

from sqlalchemy import JSON, Column, Date, DateTime, Index, Numeric, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class IncomeStatementPeriodTable(Base):
    __tablename__ = "income_statement_period"
    __table_args__ = (
        Index("idx_income_stmt_legal_entity", "legal_entity_id"),
        Index("idx_income_stmt_period", "period_id"),
        Index("idx_income_stmt_dates", "start_date", "end_date"),
        {"schema": "projections"},
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    period_id = Column(PGUUID(as_uuid=True), nullable=False)
    period_name = Column(String(100), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    total_revenue = Column(Numeric(20, 2), nullable=False, default=0)
    total_expense = Column(Numeric(20, 2), nullable=False, default=0)
    total_cogs = Column(Numeric(20, 2), nullable=False, default=0)
    gross_profit = Column(Numeric(20, 2), nullable=False, default=0)
    operating_income = Column(Numeric(20, 2), nullable=False, default=0)
    net_income = Column(Numeric(20, 2), nullable=False, default=0)
    revenue_breakdown = Column(JSON, nullable=True)
    expense_breakdown = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_income_statement_projection: IncomeStatementPeriod | None = None

async def get_income_statement_projection() -> IncomeStatementPeriod:
    global _income_statement_projection
    if _income_statement_projection is None:
        _income_statement_projection = IncomeStatementPeriod()
    return _income_statement_projection


class IncomeStatementProjection:
    def __init__(self, period: str, period_end: str):
        self.period = period
        self.period_end = period_end

    def generate(self) -> dict:
        return {
            "period": self.period,
            "period_end": self.period_end,
            "total_revenue": "0.00",
            "total_expense": "0.00",
            "net_income": "0.00",
        }


__all__ = [
    "IncomeStatementError",
    "IncomeStatementPeriod",
    "IncomeStatementProjection",
    "get_income_statement_projection",
]