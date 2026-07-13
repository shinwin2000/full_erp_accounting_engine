#!/usr/bin/env python3
"""
Module: trial_balance_cube.py
Layer: Projections (Ledger)
Responsibility: Membangun read model Trial Balance (neraca saldo) dalam bentuk
               multidimensional cube untuk query cepat. Mendukung agregasi
               berdasarkan akun, periode, cost center, dan level hierarki.
               Digunakan untuk laporan keuangan dan analisis.
Dependencies:
- asyncio, logging, datetime
- sqlalchemy.ext.asyncio
- infrastructure.database.session_factory_sqlalchemy
- infrastructure.persistence_orm.ledger_entry_table
- infrastructure.persistence_orm.account_table
- infrastructure.persistence_orm.fiscal_period_table
- projections.ledger.general_ledger_table (optional)
Audit: Build dan update cube dicatat.

Perbaikan presisi:
    - Mengganti float() dengan str() pada semua nilai moneter (closing_balance,
      debit, credit, dll.) untuk menghindari kehilangan presisi dan memenuhi
      aturan MNY-003.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.persistence_orm.account_table import AccountTable
from infrastructure.persistence_orm.fiscal_period_table import FiscalPeriodTable
from infrastructure.persistence_orm.ledger_entry_table import LedgerEntryTable
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

PROJECTION_NAME = "trial_balance_cube"

# ============================================================================
# EXCEPTIONS
# ============================================================================


class TrialBalanceCubeError(Exception):
    """Base exception untuk trial balance cube."""

    pass


# ============================================================================
# TRIAL BALANCE CUBE
# ============================================================================


class TrialBalanceCube:
    """
    Read model Trial Balance dalam bentuk data cube.

    Fitur:
    - Agregasi balance per account per period
    - Support multiple dimensions (account, period, cost center)
    - Hierarchical roll-up (sub-accounts to parent)
    - Query dengan filter fleksibel
    - Materialized view atau query langsung (pilih salah satu)
    """

    def __init__(self):
        self._session_factory = None
        self._account_cache: dict[str, dict] = {}

    async def _get_session(self) -> AsyncSession:
        if self._session_factory is None:
            self._session_factory = await get_session_factory()
        return self._session_factory.get_session()

    async def _get_account_info(self, account_id: UUID) -> dict | None:
        """Get account information (cached)."""
        key = str(account_id)
        if key in self._account_cache:
            return self._account_cache[key]

        async with await self._get_session() as session:
            stmt = select(
                AccountTable.account_code,
                AccountTable.account_name,
                AccountTable.account_type,
                AccountTable.normal_balance,
                AccountTable.parent_account_id,
                AccountTable.level,
            ).where(AccountTable.id == account_id)
            result = await session.execute(stmt)
            row = result.first()
            if row:
                info = {
                    "account_code": row[0],
                    "account_name": row[1],
                    "account_type": row[2],
                    "normal_balance": row[3],
                    "parent_account_id": row[4],
                    "level": row[5],
                }
                self._account_cache[key] = info
                return info
        return None

    async def get_trial_balance(
        self,
        legal_entity_id: UUID,
        as_of_date: date,
        include_zero_balance: bool = False,
        include_subaccounts: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Mendapatkan neraca saldo per akun pada tanggal tertentu.

        Returns:
            List of dict dengan keys: account_code, account_name, account_type,
            opening_balance, movement, closing_balance (semua sebagai string).
        """
        async with await self._get_session() as session:
            # Get all accounts for legal entity
            account_stmt = (
                select(AccountTable)
                .where(
                    AccountTable.legal_entity_id == legal_entity_id,
                    AccountTable.deleted_at.is_(None),
                )
                .order_by(AccountTable.account_code)
            )
            account_result = await session.execute(account_stmt)
            accounts = account_result.scalars().all()

            # For each account, calculate balance
            result = []
            for account in accounts:
                # Get opening balance (before as_of_date)
                opening_stmt = select(
                    func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("debit"),
                    func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0).label("credit"),
                ).where(
                    LedgerEntryTable.account_id == account.id,
                    LedgerEntryTable.legal_entity_id == legal_entity_id,
                    LedgerEntryTable.posting_date < as_of_date,
                )
                opening_result = await session.execute(opening_stmt)
                opening_row = opening_result.first()
                opening_debit = Decimal(str(opening_row.debit or 0))
                opening_credit = Decimal(str(opening_row.credit or 0))

                # Get movement in period (as_of_date only)
                movement_stmt = select(
                    func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("debit"),
                    func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0).label("credit"),
                ).where(
                    LedgerEntryTable.account_id == account.id,
                    LedgerEntryTable.legal_entity_id == legal_entity_id,
                    LedgerEntryTable.posting_date == as_of_date,
                )
                movement_result = await session.execute(movement_stmt)
                movement_row = movement_result.first()
                movement_debit = Decimal(str(movement_row.debit or 0))
                movement_credit = Decimal(str(movement_row.credit or 0))

                # Calculate closing balance based on normal balance
                if account.normal_balance == "debit":
                    opening_balance = opening_debit - opening_credit
                    closing_balance = opening_balance + movement_debit - movement_credit
                    closing_debit = closing_balance if closing_balance > 0 else 0
                    closing_credit = 0 if closing_balance > 0 else -closing_balance
                else:
                    opening_balance = opening_credit - opening_debit
                    closing_balance = opening_balance + movement_credit - movement_debit
                    closing_debit = 0 if closing_balance > 0 else -closing_balance
                    closing_credit = closing_balance if closing_balance > 0 else 0

                # Skip zero balance if requested
                if not include_zero_balance and closing_balance == 0:
                    continue

                result.append(
                    {
                        "account_id": str(account.id),
                        "account_code": account.account_code,
                        "account_name": account.account_name,
                        "account_type": account.account_type,
                        "normal_balance": account.normal_balance,
                        "opening_balance_debit": str(opening_debit),
                        "opening_balance_credit": str(opening_credit),
                        "movement_debit": str(movement_debit),
                        "movement_credit": str(movement_credit),
                        "closing_balance_debit": str(closing_debit),
                        "closing_balance_credit": str(closing_credit),
                        "closing_balance": str(closing_balance),
                    }
                )

            return result

    async def get_trial_balance_by_period(
        self, legal_entity_id: UUID, period_id: UUID
    ) -> list[dict[str, Any]]:
        """
        Mendapatkan neraca saldo untuk satu periode akuntansi (menggunakan period dates).
        """
        async with await self._get_session() as session:
            # Get period dates
            period_stmt = select(FiscalPeriodTable).where(FiscalPeriodTable.id == period_id)
            period_result = await session.execute(period_stmt)
            period = period_result.scalar_one_or_none()
            if not period:
                raise TrialBalanceCubeError(f"Period {period_id} not found")

            return await self.get_trial_balance(legal_entity_id, period.end_date)

    async def get_aggregated_by_account_type(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> dict[str, str]:
        """
        Mendapatkan total balance per tipe akun (Asset, Liability, Equity, Revenue, Expense).
        Mengembalikan string untuk presisi.
        """
        tb = await self.get_trial_balance(legal_entity_id, as_of_date, include_zero_balance=False)

        result = {}
        for line in tb:
            account_type = line["account_type"]
            balance = Decimal(line["closing_balance"])
            result[account_type] = str(result.get(account_type, Decimal(0)) + balance)

        return result

    async def get_hierarchical_trial_balance(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> list[dict[str, Any]]:
        """
        Mendapatkan neraca saldo dengan hierarki (indentasi berdasarkan level akun).
        """
        tb = await self.get_trial_balance(legal_entity_id, as_of_date, include_zero_balance=True)

        # Build hierarchy
        accounts_by_id = {}
        for line in tb:
            account_id = UUID(line["account_id"])
            accounts_by_id[account_id] = line

        # Get parent-child relationships
        async with await self._get_session() as session:
            stmt = select(AccountTable.id, AccountTable.parent_account_id).where(
                AccountTable.legal_entity_id == legal_entity_id
            )
            result = await session.execute(stmt)
            for row in result:
                acc_id = row[0]
                parent_id = row[1]
                if acc_id in accounts_by_id:
                    accounts_by_id[acc_id]["parent_id"] = str(parent_id) if parent_id else None

        # Build tree (simplified: just add indent level)
        for line in tb:
            level = line.get("level", 0)
            line["indent"] = level * 2

        return tb

    async def get_trial_balance_cube(
        self, legal_entity_id: UUID, start_date: date, end_date: date, group_by: str = "account"
    ) -> list[dict]:
        """
        Mendapatkan data cube untuk analisis multidimensional.

        Args:
            group_by: "account", "period", "account_period", "cost_center"
        """
        async with await self._get_session() as session:
            if group_by == "account":
                stmt = (
                    select(
                        AccountTable.account_code,
                        AccountTable.account_name,
                        func.sum(LedgerEntryTable.debit_amount).label("total_debit"),
                        func.sum(LedgerEntryTable.credit_amount).label("total_credit"),
                    )
                    .join(LedgerEntryTable, AccountTable.id == LedgerEntryTable.account_id)
                    .where(
                        LedgerEntryTable.legal_entity_id == legal_entity_id,
                        LedgerEntryTable.posting_date >= start_date,
                        LedgerEntryTable.posting_date <= end_date,
                    )
                    .group_by(AccountTable.id)
                    .order_by(AccountTable.account_code)
                )

                result = await session.execute(stmt)
                rows = result.all()
                return [
                    {
                        "account_code": row[0],
                        "account_name": row[1],
                        "total_debit": str(row[2] or 0),
                        "total_credit": str(row[3] or 0),
                    }
                    for row in rows
                ]

            elif group_by == "period":
                stmt = (
                    select(
                        LedgerEntryTable.posting_date,
                        func.sum(LedgerEntryTable.debit_amount).label("total_debit"),
                        func.sum(LedgerEntryTable.credit_amount).label("total_credit"),
                    )
                    .where(
                        LedgerEntryTable.legal_entity_id == legal_entity_id,
                        LedgerEntryTable.posting_date >= start_date,
                        LedgerEntryTable.posting_date <= end_date,
                    )
                    .group_by(LedgerEntryTable.posting_date)
                    .order_by(LedgerEntryTable.posting_date)
                )

                result = await session.execute(stmt)
                rows = result.all()
                return [
                    {
                        "posting_date": row[0].isoformat(),
                        "total_debit": str(row[1] or 0),
                        "total_credit": str(row[2] or 0),
                    }
                    for row in rows
                ]

            elif group_by == "account_period":
                stmt = (
                    select(
                        AccountTable.account_code,
                        LedgerEntryTable.posting_date,
                        func.sum(LedgerEntryTable.debit_amount).label("total_debit"),
                        func.sum(LedgerEntryTable.credit_amount).label("total_credit"),
                    )
                    .join(LedgerEntryTable, AccountTable.id == LedgerEntryTable.account_id)
                    .where(
                        LedgerEntryTable.legal_entity_id == legal_entity_id,
                        LedgerEntryTable.posting_date >= start_date,
                        LedgerEntryTable.posting_date <= end_date,
                    )
                    .group_by(AccountTable.id, LedgerEntryTable.posting_date)
                    .order_by(AccountTable.account_code, LedgerEntryTable.posting_date)
                )
                result = await session.execute(stmt)
                rows = result.all()
                return [
                    {
                        "account_code": row[0],
                        "posting_date": row[1].isoformat(),
                        "total_debit": str(row[2] or 0),
                        "total_credit": str(row[3] or 0),
                    }
                    for row in rows
                ]

            elif group_by == "cost_center":
                stmt = (
                    select(
                        LedgerEntryTable.cost_center,
                        AccountTable.account_code,
                        func.sum(LedgerEntryTable.debit_amount).label("total_debit"),
                        func.sum(LedgerEntryTable.credit_amount).label("total_credit"),
                    )
                    .join(LedgerEntryTable, AccountTable.id == LedgerEntryTable.account_id)
                    .where(
                        LedgerEntryTable.legal_entity_id == legal_entity_id,
                        LedgerEntryTable.posting_date >= start_date,
                        LedgerEntryTable.posting_date <= end_date,
                        LedgerEntryTable.cost_center.is_not(None),
                    )
                    .group_by(LedgerEntryTable.cost_center, AccountTable.id)
                    .order_by(LedgerEntryTable.cost_center, AccountTable.account_code)
                )
                result = await session.execute(stmt)
                rows = result.all()
                return [
                    {
                        "cost_center": row[0],
                        "account_code": row[1],
                        "total_debit": str(row[2] or 0),
                        "total_credit": str(row[3] or 0),
                    }
                    for row in rows
                ]

            else:
                raise TrialBalanceCubeError(f"Unsupported group_by: {group_by}")

    async def get_closing_balance_cube(
        self, legal_entity_id: UUID, period_ids: list[UUID]
    ) -> list[dict]:
        """
        Mendapatkan closing balance untuk multiple periods (trend analysis).
        """
        result = []
        for period_id in period_ids:
            async with await self._get_session() as session:
                period_stmt = select(FiscalPeriodTable).where(FiscalPeriodTable.id == period_id)
                period_result = await session.execute(period_stmt)
                period = period_result.scalar_one_or_none()
                if not period:
                    continue

                tb = await self.get_trial_balance(legal_entity_id, period.end_date)
                total_assets = sum(Decimal(l["closing_balance"]) for l in tb if l["account_type"] == "Asset")
                total_liabilities = sum(Decimal(l["closing_balance"]) for l in tb if l["account_type"] == "Liability")
                total_equity = sum(Decimal(l["closing_balance"]) for l in tb if l["account_type"] == "Equity")

                result.append(
                    {
                        "period_id": str(period_id),
                        "period_name": period.period_name,
                        "end_date": period.end_date.isoformat(),
                        "total_assets": str(total_assets),
                        "total_liabilities": str(total_liabilities),
                        "total_equity": str(total_equity),
                        "net_assets": str(total_assets - (total_liabilities + total_equity)),
                    }
                )

        return result

    async def invalidate_cache(self) -> None:
        """Invalidate account cache (call after account changes)."""
        self._account_cache.clear()
        logger.info("Trial balance cube cache invalidated")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_trial_balance_cube: TrialBalanceCube | None = None


async def get_trial_balance_cube() -> TrialBalanceCube:
    """Get singleton instance of TrialBalanceCube."""
    global _trial_balance_cube
    if _trial_balance_cube is None:
        _trial_balance_cube = TrialBalanceCube()
    return _trial_balance_cube


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["TrialBalanceCube", "TrialBalanceCubeError", "get_trial_balance_cube"]
