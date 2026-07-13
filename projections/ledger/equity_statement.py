#!/usr/bin/env python3
"""
Module: equity_statement.py
Layer: Projections (Ledger)
Responsibility: Membangun read model Statement of Changes in Equity (Laporan Perubahan
               Ekuitas). Menyajikan perubahan modal saham, tambahan modal disetor,
               laba ditahan, dan komponen ekuitas lainnya selama periode tertentu.
               Mendukung periodic dan annual statements.
Dependencies:
- asyncio, logging, datetime, decimal
- sqlalchemy.ext.asyncio
- infrastructure.database.session_factory_sqlalchemy
- infrastructure.persistence_orm.ledger_entry_table
- infrastructure.persistence_orm.account_table
- infrastructure.persistence_orm.fiscal_period_table
- projections.ledger.balance_sheet_snapshot
- projections.ledger.income_statement_period
Audit: Setiap pembangunan equity statement dicatat. Rebuild dimonitor.

Perbaikan presisi:
    - Semua nilai moneter dikonversi ke string (bukan float) untuk menghindari
      kehilangan presisi dan memenuhi aturan MNY-003.
    - Menggunakan Decimal secara konsisten dalam perhitungan internal.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.persistence_orm.account_table import AccountTable
from infrastructure.persistence_orm.fiscal_period_table import FiscalPeriodTable
from infrastructure.persistence_orm.ledger_entry_table import LedgerEntryTable
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

PROJECTION_NAME = "equity_statement"

# Account code prefixes for equity components
EQUITY_COMPONENTS = {
    "share_capital": ("3-1",),  # Modal saham
    "additional_paid_in": ("3-2",),  # Tambahan modal disetor
    "retained_earnings": ("3-3",),  # Laba ditahan
    "treasury_stock": ("3-4",),  # Saham treasuri (contra equity)
    "revaluation_surplus": ("3-5",),  # Surplus revaluasi
    "other_comprehensive": ("3-6",),  # Pendapatan komprehensif lain
    "dividend": ("3-7",),  # Dividen (pengurang ekuitas)
}

# ============================================================================
# EXCEPTIONS
# ============================================================================


class EquityStatementError(Exception):
    """Base exception untuk equity statement projection."""

    pass


# ============================================================================
# EQUITY STATEMENT PROJECTION
# ============================================================================


class EquityStatement:
    """
    Read model Statement of Changes in Equity.

    Fitur:
    - Menghitung perubahan ekuitas per komponen
    - Mendukung period-to-period comparison
    - Menyajikan laba ditahan setelah dividen
    - Menghitung total ekuitas
    - Rebuild dari event store
    """

    def __init__(self):
        self._session_factory = None
        self._balance_sheet: BalanceSheetSnapshot | None = None
        self._income_statement: IncomeStatementPeriod | None = None

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

    async def get_equity_component_balance(
        self, legal_entity_id: UUID, component_type: str, as_of_date: date
    ) -> Decimal:
        """
        Mendapatkan saldo komponen ekuitas pada tanggal tertentu.
        """
        prefixes = EQUITY_COMPONENTS.get(component_type, ())
        if not prefixes:
            return Decimal(0)

        async with await self._get_session() as session:
            # Get accounts matching prefixes
            conditions = []
            for prefix in prefixes:
                conditions.append(AccountTable.account_code.startswith(prefix))

            # Build OR condition manually
            from sqlalchemy import or_

            account_stmt = select(AccountTable.id).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.account_type.in_(["Equity", "ContraEquity"]),
                AccountTable.deleted_at.is_(None),
                or_(*conditions),
            )
            account_result = await session.execute(account_stmt)
            account_ids = account_result.scalars().all()

            if not account_ids:
                return Decimal(0)

            # Sum balance
            stmt = select(
                func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("debit"),
                func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0).label("credit"),
            ).where(
                LedgerEntryTable.account_id.in_(account_ids),
                LedgerEntryTable.legal_entity_id == legal_entity_id,
                LedgerEntryTable.posting_date <= as_of_date,
            )
            result = await session.execute(stmt)
            row = result.first()
            debit = Decimal(str(row.debit or 0))
            credit = Decimal(str(row.credit or 0))

            # For equity, normal balance is credit
            # Contra equity (treasury stock) is debit
            if component_type == "treasury_stock":
                return debit - credit
            else:
                return credit - debit

    async def compute_equity_statement(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> dict[str, Any]:
        """
        Menghitung statement of changes in equity untuk periode tertentu.
        """
        # Get opening balances (as of start_date)
        opening = {}
        for component in EQUITY_COMPONENTS:
            opening[component] = await self.get_equity_component_balance(
                legal_entity_id, component, start_date
            )

        # Get net income for the period
        period_projection = await self._get_income_statement()
        async with await self._get_session() as session:
            period_stmt = select(FiscalPeriodTable).where(
                FiscalPeriodTable.legal_entity_id == legal_entity_id,
                FiscalPeriodTable.start_date == start_date,
                FiscalPeriodTable.end_date == end_date,
            )
            period_result = await session.execute(period_stmt)
            period = period_result.scalar_one_or_none()
            if not period:
                raise EquityStatementError(f"Period not found for {start_date} to {end_date}")

            period_income = await period_projection.get_income_statement(legal_entity_id, period.id)
            if period_income:
                net_income = Decimal(str(period_income["net_income"]))
            else:
                net_income = Decimal(0)

        # Other comprehensive income (if any)
        oci_balance = await self.get_equity_component_balance(
            legal_entity_id, "other_comprehensive", end_date
        )
        oci_change = oci_balance - opening.get("other_comprehensive", Decimal(0))

        # Dividends declared during period (decrease retained earnings)
        dividend_balance = await self.get_equity_component_balance(
            legal_entity_id, "dividend", end_date
        )
        dividends = dividend_balance - opening.get("dividend", Decimal(0))

        # Calculate retained earnings after net income and dividends
        opening_retained = opening.get("retained_earnings", Decimal(0))
        ending_retained = opening_retained + net_income - dividends

        # Calculate total equity
        total_opening = sum(opening.values())
        total_ending = (
            ending_retained
            + opening.get("share_capital", Decimal(0))
            + opening.get("additional_paid_in", Decimal(0))
            + opening.get("treasury_stock", Decimal(0))
            + opening.get("revaluation_surplus", Decimal(0))
            + opening.get("other_comprehensive", Decimal(0))
            + oci_change
        )

        # Build changes (menggunakan string untuk serialisasi)
        changes = []
        for component, opening_balance in opening.items():
            if component == "retained_earnings":
                closing_balance = ending_retained
                change = net_income - dividends
                changes.append(
                    {
                        "component": component,
                        "opening_balance": str(opening_balance),
                        "additions": str(net_income) if component == "retained_earnings" else "0",
                        "deductions": str(dividends) if component == "retained_earnings" else "0",
                        "closing_balance": str(closing_balance),
                        "change": str(change),
                    }
                )
            elif component == "dividend":
                # Dividen sudah diakui di retained earnings, tidak ditampilkan sebagai komponen terpisah
                continue
            else:
                closing_balance = await self.get_equity_component_balance(
                    legal_entity_id, component, end_date
                )
                change = closing_balance - opening_balance
                changes.append(
                    {
                        "component": component,
                        "opening_balance": str(opening_balance),
                        "additions": str(change) if change > 0 else "0",
                        "deductions": str(-change) if change < 0 else "0",
                        "closing_balance": str(closing_balance),
                        "change": str(change),
                    }
                )

        return {
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "legal_entity_id": str(legal_entity_id),
            "opening_total_equity": str(total_opening),
            "net_income": str(net_income),
            "other_comprehensive_income": str(oci_change),
            "dividends_declared": str(dividends),
            "closing_total_equity": str(total_ending),
            "changes": changes,
            "created_at": datetime.now(UTC).isoformat(),
        }

    async def save_equity_statement(self, equity_data: dict[str, Any]) -> None:
        """
        Menyimpan equity statement ke tabel materialized.
        """
        async with await self._get_session() as session, session.begin():
            # Delete existing for same period
            await session.execute(
                delete(EquityStatementTable).where(
                    EquityStatementTable.legal_entity_id == UUID(equity_data["legal_entity_id"]),
                    EquityStatementTable.start_date
                    == date.fromisoformat(equity_data["period_start"]),
                    EquityStatementTable.end_date == date.fromisoformat(equity_data["period_end"]),
                )
            )

            stmt = insert(EquityStatementTable).values(
                id=uuid4(),
                legal_entity_id=UUID(equity_data["legal_entity_id"]),
                start_date=date.fromisoformat(equity_data["period_start"]),
                end_date=date.fromisoformat(equity_data["period_end"]),
                opening_total_equity=Decimal(equity_data["opening_total_equity"]),
                net_income=Decimal(equity_data["net_income"]),
                other_comprehensive_income=Decimal(equity_data["other_comprehensive_income"]),
                dividends_declared=Decimal(equity_data["dividends_declared"]),
                closing_total_equity=Decimal(equity_data["closing_total_equity"]),
                changes_data=equity_data["changes"],
                created_at=datetime.now(UTC),
            )
            await session.execute(stmt)
            await session.commit()

    async def get_equity_statement(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> dict | None:
        """
        Mendapatkan equity statement yang sudah tersimpan.
        """
        async with await self._get_session() as session:
            stmt = select(EquityStatementTable).where(
                EquityStatementTable.legal_entity_id == legal_entity_id,
                EquityStatementTable.start_date == start_date,
                EquityStatementTable.end_date == end_date,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            return {
                "period_start": row.start_date.isoformat(),
                "period_end": row.end_date.isoformat(),
                "opening_total_equity": str(row.opening_total_equity),
                "net_income": str(row.net_income),
                "other_comprehensive_income": str(row.other_comprehensive_income),
                "dividends_declared": str(row.dividends_declared),
                "closing_total_equity": str(row.closing_total_equity),
                "changes": row.changes_data,
                "created_at": row.created_at.isoformat(),
            }

    async def rebuild_for_period(self, legal_entity_id: UUID, period_id: UUID) -> None:
        """
        Membangun equity statement untuk satu periode.
        """
        async with await self._get_session() as session:
            period_stmt = select(FiscalPeriodTable).where(FiscalPeriodTable.id == period_id)
            period_result = await session.execute(period_stmt)
            period = period_result.scalar_one_or_none()
            if not period:
                logger.warning(f"Period {period_id} not found")
                return

            equity_data = await self.compute_equity_statement(
                legal_entity_id, period.start_date, period.end_date
            )
            await self.save_equity_statement(equity_data)
            logger.info(f"Equity statement saved for period {period.period_name}")

    async def rebuild_for_legal_entity(self, legal_entity_id: UUID) -> dict[str, Any]:
        """
        Membangun ulang equity statement untuk semua periode legal entity.
        """
        logger.info(f"Rebuilding equity statements for legal entity {legal_entity_id}")
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
                await self.rebuild_for_period(legal_entity_id, period.id)
                success_count += 1
            except Exception as e:
                logger.error(f"Failed to rebuild equity statement for period {period.id}: {e}")
                error_count += 1

        duration = (datetime.now(UTC) - start_time).total_seconds()

        result = {
            "legal_entity_id": str(legal_entity_id),
            "periods_processed": len(periods),
            "success": success_count,
            "errors": error_count,
            "duration_seconds": duration,
        }

        logger.info(
            f"Equity statements rebuild completed: {success_count} periods, {error_count} errors"
        )

        if error_count > 0:
            await trigger_alert(
                title="Equity Statement Rebuild Partial Failure",
                message=f"{error_count} periods failed to generate equity statement",
                severity="warning",
                source="EquityStatement",
            )

        return result

    async def rebuild_all(self) -> dict[str, Any]:
        """
        Membangun ulang equity statement untuk semua legal entity.
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

    async def incremental_update(self, period_id: UUID) -> None:
        """
        Incremental update ketika periode ditutup.
        """
        async with await self._get_session() as session:
            period_stmt = select(FiscalPeriodTable).where(FiscalPeriodTable.id == period_id)
            period_result = await session.execute(period_stmt)
            period = period_result.scalar_one_or_none()
            if not period:
                logger.warning(f"Period {period_id} not found for equity statement update")
                return

            await self.rebuild_for_period(period.legal_entity_id, period_id)
            logger.info(f"Equity statement updated for period {period.period_name}")


# ============================================================================
# ORM MODEL (tambahan)
# ============================================================================

from sqlalchemy import JSON, Column, Date, DateTime, Index, Numeric
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class EquityStatementTable(Base):
    __tablename__ = "equity_statement"
    __table_args__ = (
        Index("idx_equity_stmt_legal_entity", "legal_entity_id"),
        Index("idx_equity_stmt_dates", "start_date", "end_date"),
        {"schema": "projections"},
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    opening_total_equity = Column(Numeric(20, 2), nullable=False, default=0)
    net_income = Column(Numeric(20, 2), nullable=False, default=0)
    other_comprehensive_income = Column(Numeric(20, 2), nullable=False, default=0)
    dividends_declared = Column(Numeric(20, 2), nullable=False, default=0)
    closing_total_equity = Column(Numeric(20, 2), nullable=False, default=0)
    changes_data = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_equity_statement: EquityStatement | None = None


async def get_equity_statement() -> EquityStatement:
    """Get singleton instance of EquityStatement."""
    global _equity_statement
    if _equity_statement is None:
        _equity_statement = EquityStatement()
    return _equity_statement


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["EquityStatement", "EquityStatementError", "get_equity_statement"]
