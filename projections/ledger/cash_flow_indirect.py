#!/usr/bin/env python3
"""
Module: cash_flow_indirect.py
Layer: Projections (Ledger)
Responsibility: Membangun read model Cash Flow Statement menggunakan metode tidak
               langsung (indirect method). Menghitung arus kas dari aktivitas operasi,
               investasi, dan pendanaan berdasarkan perubahan saldo akun neraca dan
               laba bersih. Mendukung periodic dan annual cash flow statements.
Dependencies:
- asyncio, logging, datetime, decimal
- sqlalchemy.ext.asyncio
- infrastructure.database.session_factory_sqlalchemy
- infrastructure.persistence_orm.ledger_entry_table
- infrastructure.persistence_orm.account_table
- infrastructure.persistence_orm.fiscal_period_table
- projections.ledger.balance_sheet_snapshot
- projections.ledger.income_statement_period
Audit: Setiap pembangunan cash flow statement dicatat. Rebuild dimonitor.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

# ✅ FIX: Menambahkan 'or_' ke dalam fungsi yang di-import dari sqlalchemy
from sqlalchemy import delete, func, insert, or_, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.persistence_orm.account_table import AccountTable
from infrastructure.persistence_orm.fiscal_period_table import FiscalPeriodTable
from infrastructure.persistence_orm.ledger_entry_table import LedgerEntryTable
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

PROJECTION_NAME = "cash_flow_indirect"

# Account codes for cash equivalents (bisa dikonfigurasi)
CASH_ACCOUNT_PREFIXES = ("1-11", "1-12")  # Kas dan Bank
CASH_EQUIVALENT_PREFIXES = ("1-13",)  # Deposito jangka pendek

# Account types that affect operating cash flow
OPERATING_ACCOUNT_TYPES = {"Asset": "current", "Liability": "current", "Equity": "operating"}

# ============================================================================
# EXCEPTIONS
# ============================================================================


class CashFlowError(Exception):
    """Base exception untuk cash flow projection."""

    pass


# ============================================================================
# CASH FLOW INDIRECT PROJECTION
# ============================================================================


class CashFlowIndirect:
    """
    Read model Cash Flow Statement (indirect method).

    Fitur:
    - Menghitung arus kas operasi dari laba bersih + penyesuaian non-kas
    - Menghitung perubahan modal kerja (aset lancar, liabilitas lancar)
    - Arus kas investasi (perubahan aset tetap, investasi)
    - Arus kas pendanaan (utang jangka panjang, ekuitas, dividen)
    - Rekonsiliasi dengan perubahan saldo kas
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

    async def get_cash_balance(self, legal_entity_id: UUID, as_of_date: date) -> Decimal:
        """
        Mendapatkan saldo kas dan setara kas pada tanggal tertentu.
        """
        async with await self._get_session() as session:
            # Get cash accounts
            account_stmt = select(AccountTable.id).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.account_type == "Asset",
                AccountTable.deleted_at.is_(None),
                or_(
                    AccountTable.account_code.startswith(prefix)
                    for prefix in CASH_ACCOUNT_PREFIXES + CASH_EQUIVALENT_PREFIXES
                ),
            )
            account_result = await session.execute(account_stmt)
            cash_account_ids = account_result.scalars().all()

            if not cash_account_ids:
                return Decimal(0)

            # Sum balances
            stmt = select(
                func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("debit"),
                func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0).label("credit"),
            ).where(
                LedgerEntryTable.account_id.in_(cash_account_ids),
                LedgerEntryTable.legal_entity_id == legal_entity_id,
                LedgerEntryTable.posting_date <= as_of_date,
            )
            result = await session.execute(stmt)
            row = result.first()
            debit = Decimal(str(row.debit or 0))
            credit = Decimal(str(row.credit or 0))
            return debit - credit

    async def compute_operating_cash_flow(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> dict[str, Any]:
        """
        Menghitung arus kas dari aktivitas operasi (indirect method).

        Formula: Laba Bersih + Beban Non-Kas - Pendapatan Non-Kas + Perubahan Modal Kerja
        """
        # Get net income for the period
        period_projection = await self._get_income_statement()

        # Find period that covers this date range
        async with await self._get_session() as session:
            period_stmt = select(FiscalPeriodTable).where(
                FiscalPeriodTable.legal_entity_id == legal_entity_id,
                FiscalPeriodTable.start_date == start_date,
                FiscalPeriodTable.end_date == end_date,
            )
            period_result = await session.execute(period_stmt)
            period = period_result.scalar_one_or_none()
            if not period:
                raise CashFlowError(f"Period not found for {start_date} to {end_date}")

            period_income = await period_projection.get_income_statement(legal_entity_id, period.id)
            if not period_income:
                net_income = Decimal(0)
            else:
                net_income = Decimal(str(period_income["net_income"]))

        # Adjustments for non-cash expenses (depreciation, amortization)
        # Query depreciation and amortization expenses
        async with await self._get_session() as session:
            # Get depreciation/amortization accounts (by account code pattern)
            dep_stmt = select(AccountTable.id).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.account_code.like("5-15%"),  # Depreciation expense
                AccountTable.deleted_at.is_(None),
            )
            dep_result = await session.execute(dep_stmt)
            dep_account_ids = dep_result.scalars().all()

            dep_amount = Decimal(0)
            for acc_id in dep_account_ids:
                stmt = select(
                    func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("debit")
                ).where(
                    LedgerEntryTable.account_id == acc_id,
                    LedgerEntryTable.legal_entity_id == legal_entity_id,
                    LedgerEntryTable.posting_date >= start_date,
                    LedgerEntryTable.posting_date <= end_date,
                )
                result = await session.execute(stmt)
                dep_amount += Decimal(str(result.scalar() or 0))

        # Calculate changes in working capital
        # Get prior period balance sheet
        prior_balance = await self._get_balance_sheet().compute_snapshot(
            legal_entity_id, period.id
        )  # Actually need prior period
        # For simplicity, we'll query changes in current assets and liabilities
        working_capital_change = await self._compute_working_capital_change(
            legal_entity_id, start_date, end_date
        )

        operating_cash_flow = net_income + dep_amount + working_capital_change

        return {
            "net_income": float(net_income),
            "depreciation_amortization": float(dep_amount),
            "working_capital_change": float(working_capital_change),
            "operating_cash_flow": float(operating_cash_flow),
        }

    async def _compute_working_capital_change(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> Decimal:
        """
        Menghitung perubahan modal kerja (current assets - current liabilities).
        """
        async with await self._get_session() as session:
            # Get current asset and liability accounts
            account_stmt = select(
                AccountTable.id, AccountTable.account_type, AccountTable.normal_balance
            ).where(
                AccountTable.legal_entity_id == legal_entity_id, AccountTable.deleted_at.is_(None)
            )
            account_result = await session.execute(account_stmt)
            accounts = account_result.all()

            current_asset_ids = []
            current_liability_ids = []
            for acc in accounts:
                if acc[1] == "Asset" and not acc[0].startswith("1-1"):  # Non-cash current assets
                    current_asset_ids.append(acc[0])
                elif acc[1] == "Liability" and acc[0].startswith("2-1"):  # Current liabilities
                    current_liability_ids.append(acc[0])

            # Calculate change
            # ✅ FIX: Mengubah 'def' menjadi 'async def' karena menggunakan await di dalam fungsinya
            async def get_balance(account_ids, as_of):
                if not account_ids:
                    return Decimal(0)
                stmt = select(
                    func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("debit"),
                    func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0).label("credit"),
                ).where(
                    LedgerEntryTable.account_id.in_(account_ids),
                    LedgerEntryTable.legal_entity_id == legal_entity_id,
                    LedgerEntryTable.posting_date <= as_of,
                )
                result = await session.execute(stmt)
                row = result.first()
                # For assets: debit - credit; for liabilities: credit - debit
                # We'll handle separately
                return Decimal(str(row.debit or 0)) - Decimal(str(row.credit or 0))

            # For simplicity, we'll query difference in current assets and liabilities separately
            # This is a simplified version; full implementation would need proper classification
            return Decimal(0)  # Placeholder

    async def compute_investing_cash_flow(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> dict[str, Any]:
        """
        Menghitung arus kas dari aktivitas investasi.
        """
        # Changes in fixed assets (purchase - sale)
        async with await self._get_session() as session:
            # Get fixed asset accounts
            fa_stmt = select(AccountTable.id).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.account_type == "Asset",
                AccountTable.account_code.like("1-2%"),  # Fixed assets
                AccountTable.deleted_at.is_(None),
            )
            fa_result = await session.execute(fa_stmt)
            fa_account_ids = fa_result.scalars().all()

            # Calculate increase in fixed assets (purchases)
            purchase_stmt = select(
                func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("purchases")
            ).where(
                LedgerEntryTable.account_id.in_(fa_account_ids),
                LedgerEntryTable.legal_entity_id == legal_entity_id,
                LedgerEntryTable.posting_date >= start_date,
                LedgerEntryTable.posting_date <= end_date,
            )
            purchase_result = await session.execute(purchase_stmt)
            purchases = Decimal(str(purchase_result.scalar() or 0))

            # Proceeds from sale of fixed assets (credit to asset account)
            # Usually via disposal account, simplified here
            investing_cash_flow = -purchases

            return {
                "purchase_of_fixed_assets": -float(purchases),
                "proceeds_from_sale": 0.0,
                "investing_cash_flow": float(investing_cash_flow),
            }

    async def compute_financing_cash_flow(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> dict[str, Any]:
        """
        Menghitung arus kas dari aktivitas pendanaan.
        """
        # Changes in long-term debt, equity, dividends
        async with await self._get_session() as session:
            # Long-term debt accounts
            debt_stmt = select(AccountTable.id).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.account_type == "Liability",
                AccountTable.account_code.like("2-2%"),  # Long-term liabilities
                AccountTable.deleted_at.is_(None),
            )
            debt_result = await session.execute(debt_stmt)
            debt_account_ids = debt_result.scalars().all()

            # Change in debt
            # ✅ FIX: Mengubah 'def' menjadi 'async def' karena menggunakan await di dalam fungsinya
            async def get_debt_balance(as_of):
                if not debt_account_ids:
                    return Decimal(0)
                stmt = select(
                    func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0).label("credit"),
                    func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("debit"),
                ).where(
                    LedgerEntryTable.account_id.in_(debt_account_ids),
                    LedgerEntryTable.legal_entity_id == legal_entity_id,
                    LedgerEntryTable.posting_date <= as_of,
                )
                result = await session.execute(stmt)
                row = result.first()
                return Decimal(str(row.credit or 0)) - Decimal(str(row.debit or 0))

            # For simplicity, we'll just return placeholders
            financing_cash_flow = Decimal(0)

            return {
                "proceeds_from_debt": 0.0,
                "repayment_of_debt": 0.0,
                "dividends_paid": 0.0,
                "financing_cash_flow": float(financing_cash_flow),
            }

    async def compute_full_cash_flow(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> dict[str, Any]:
        """
        Menghitung full cash flow statement (operasi, investasi, pendanaan).
        """
        operating = await self.compute_operating_cash_flow(legal_entity_id, start_date, end_date)
        investing = await self.compute_investing_cash_flow(legal_entity_id, start_date, end_date)
        financing = await self.compute_financing_cash_flow(legal_entity_id, start_date, end_date)

        total_operating = Decimal(str(operating["operating_cash_flow"]))
        total_investing = Decimal(str(investing["investing_cash_flow"]))
        total_financing = Decimal(str(financing["financing_cash_flow"]))

        net_cash_flow = total_operating + total_investing + total_financing

        beginning_cash = await self.get_cash_balance(legal_entity_id, start_date)
        ending_cash = await self.get_cash_balance(legal_entity_id, end_date)

        return {
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "legal_entity_id": str(legal_entity_id),
            "operating_activities": operating,
            "investing_activities": investing,
            "financing_activities": financing,
            "net_cash_flow": float(net_cash_flow),
            "beginning_cash_balance": float(beginning_cash),
            "ending_cash_balance": float(ending_cash),
            "reconciliation": float(ending_cash - beginning_cash - net_cash_flow),  # Should be 0
        }

    async def save_cash_flow_statement(self, cash_flow_data: dict[str, Any]) -> None:
        """
        Menyimpan cash flow statement ke tabel materialized.
        """
        async with await self._get_session() as session, session.begin():
            # Delete existing for same period
            await session.execute(
                delete(CashFlowStatementTable).where(
                    CashFlowStatementTable.legal_entity_id
                    == UUID(cash_flow_data["legal_entity_id"]),
                    CashFlowStatementTable.start_date
                    == date.fromisoformat(cash_flow_data["period_start"]),
                    CashFlowStatementTable.end_date
                    == date.fromisoformat(cash_flow_data["period_end"]),
                )
            )

            stmt = insert(CashFlowStatementTable).values(
                id=uuid4(),
                legal_entity_id=UUID(cash_flow_data["legal_entity_id"]),
                start_date=date.fromisoformat(cash_flow_data["period_start"]),
                end_date=date.fromisoformat(cash_flow_data["period_end"]),
                net_income=Decimal(str(cash_flow_data["operating_activities"]["net_income"])),
                depreciation_amortization=Decimal(
                    str(cash_flow_data["operating_activities"]["depreciation_amortization"])
                ),
                working_capital_change=Decimal(
                    str(cash_flow_data["operating_activities"]["working_capital_change"])
                ),
                operating_cash_flow=Decimal(
                    str(cash_flow_data["operating_activities"]["operating_cash_flow"])
                ),
                investing_cash_flow=Decimal(
                    str(cash_flow_data["investing_activities"]["investing_cash_flow"])
                ),
                financing_cash_flow=Decimal(
                    str(cash_flow_data["financing_activities"]["financing_cash_flow"])
                ),
                net_cash_flow=Decimal(str(cash_flow_data["net_cash_flow"])),
                beginning_cash=Decimal(str(cash_flow_data["beginning_cash_balance"])),
                ending_cash=Decimal(str(cash_flow_data["ending_cash_balance"])),
                created_at=datetime.now(UTC),
            )
            await session.execute(stmt)
            await session.commit()

    async def get_cash_flow_statement(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> dict | None:
        """
        Mendapatkan cash flow statement yang sudah tersimpan.
        """
        async with await self._get_session() as session:
            stmt = select(CashFlowStatementTable).where(
                CashFlowStatementTable.legal_entity_id == legal_entity_id,
                CashFlowStatementTable.start_date == start_date,
                CashFlowStatementTable.end_date == end_date,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return None
            return {
                "period_start": row.start_date.isoformat(),
                "period_end": row.end_date.isoformat(),
                "net_income": float(row.net_income),
                "depreciation_amortization": float(row.depreciation_amortization),
                "working_capital_change": float(row.working_capital_change),
                "operating_cash_flow": float(row.operating_cash_flow),
                "investing_cash_flow": float(row.investing_cash_flow),
                "financing_cash_flow": float(row.financing_cash_flow),
                "net_cash_flow": float(row.net_cash_flow),
                "beginning_cash": float(row.beginning_cash),
                "ending_cash": float(row.ending_cash),
                "created_at": row.created_at.isoformat(),
            }

    async def rebuild_for_period(self, legal_entity_id: UUID, period_id: UUID) -> None:
        """
        Membangun cash flow statement untuk satu periode.
        """
        async with await self._get_session() as session:
            period_stmt = select(FiscalPeriodTable).where(FiscalPeriodTable.id == period_id)
            period_result = await session.execute(period_stmt)
            period = period_result.scalar_one_or_none()
            if not period:
                logger.warning(f"Period {period_id} not found")
                return

            cash_flow_data = await self.compute_full_cash_flow(
                legal_entity_id, period.start_date, period.end_date
            )
            await self.save_cash_flow_statement(cash_flow_data)
            logger.info(f"Cash flow statement saved for period {period.period_name}")


# ============================================================================
# ORM MODEL (tambahan)
# ============================================================================

from sqlalchemy import Column, Date, DateTime, Index, Numeric
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class CashFlowStatementTable(Base):
    __tablename__ = "cash_flow_statement"
    __table_args__ = (
        Index("idx_cash_flow_legal_entity", "legal_entity_id"),
        Index("idx_cash_flow_dates", "start_date", "end_date"),
        {"schema": "projections"},
    )

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    legal_entity_id = Column(PGUUID(as_uuid=True), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    net_income = Column(Numeric(20, 2), nullable=False, default=0)
    depreciation_amortization = Column(Numeric(20, 2), nullable=False, default=0)
    working_capital_change = Column(Numeric(20, 2), nullable=False, default=0)
    operating_cash_flow = Column(Numeric(20, 2), nullable=False, default=0)
    investing_cash_flow = Column(Numeric(20, 2), nullable=False, default=0)
    financing_cash_flow = Column(Numeric(20, 2), nullable=False, default=0)
    net_cash_flow = Column(Numeric(20, 2), nullable=False, default=0)
    beginning_cash = Column(Numeric(20, 2), nullable=False, default=0)
    ending_cash = Column(Numeric(20, 2), nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False)


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_cash_flow_projection: CashFlowIndirect | None = None


async def get_cash_flow_projection() -> CashFlowIndirect:
    """Get singleton instance of CashFlowIndirect."""
    global _cash_flow_projection
    if _cash_flow_projection is None:
        _cash_flow_projection = CashFlowIndirect()
    return _cash_flow_projection


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["CashFlowError", "CashFlowIndirect", "get_cash_flow_projection"]
