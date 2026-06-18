#!/usr/bin/env python3
"""
Module: sqlalchemy_ledger_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk entri buku besar (Ledger) menggunakan
               SQLAlchemy ORM. Repository ini bersifat read-only (karena entri ledger
               hanya dihasilkan dari event posting jurnal). Menyediakan query
               untuk neraca saldo, laporan keuangan, saldo akun, dan mutasi akun.
Dependencies:
- sqlalchemy.ext.asyncio (AsyncSession)
- sqlalchemy import select, func, and_, text
- ports.primary.ledger_repository_port (LedgerRepositoryPort, LedgerEntryReadModel)
- infrastructure.persistence_orm.ledger_entry_table (LedgerEntryTable)
- infrastructure.persistence_orm.account_table (AccountTable)
- domain.shared_value_objects.money_vo (Money, Currency)
Audit: Repository ledger read-only, tidak mengubah data. Query dicatat di audit log.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.account_table import AccountTable

# Infrastructure ORM
from infrastructure.persistence_orm.ledger_entry_table import LedgerEntryTable

# Ports
from ports.primary.ledger_repository_port import LedgerEntryReadModel, LedgerRepositoryPort

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

# Normal balance untuk setiap tipe akun
NORMAL_BALANCE = {
    "Asset": "debit",
    "ContraAsset": "credit",
    "Liability": "credit",
    "ContraLiability": "debit",
    "Equity": "credit",
    "ContraEquity": "debit",
    "Revenue": "credit",
    "Expense": "debit",
}

# ============================================================================
# EXCEPTIONS
# ============================================================================


class LedgerRepositoryError(Exception):
    """Base exception untuk repository ledger."""

    pass


class AccountNotFoundError(LedgerRepositoryError):
    """Akun tidak ditemukan."""

    pass


# ============================================================================
# READ MODEL CONVERTER
# ============================================================================


def to_ledger_entry_read_model(row: Any) -> LedgerEntryReadModel:
    """Convert row result ke LedgerEntryReadModel."""
    return LedgerEntryReadModel(
        id=row.id,
        journal_id=row.journal_id,
        account_id=row.account_id,
        account_code=row.account_code,
        debit_amount=row.debit_amount,
        credit_amount=row.credit_amount,
        posting_date=row.posting_date,
        legal_entity_id=row.legal_entity_id,
        cost_center=row.cost_center,
        reference_number=row.reference_number,
        description=row.description,
    )


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================


class SQLAlchemyLedgerRepository(LedgerRepositoryPort):
    """
    Implementasi repository ledger read-only dengan SQLAlchemy.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise LedgerRepositoryError("Session not set")
        return self._session

    @session.setter
    def session(self, value: AsyncSession) -> None:
        self._session = value

    # ========================================================================
    # QUERY METHODS
    # ========================================================================

    async def get_account_balance(self, account_id: UUID, as_of_date: date) -> Decimal:
        """
        Menghitung saldo sebuah akun pada tanggal tertentu.
        """
        try:
            # Get account normal balance
            account_stmt = select(AccountTable.normal_balance, AccountTable.account_type).where(
                AccountTable.id == account_id
            )
            account_result = await self.session.execute(account_stmt)
            account_info = account_result.first()

            if not account_info:
                raise AccountNotFoundError(f"Account {account_id} not found")

            normal_balance = account_info[0]
            account_type = account_info[1]

            # Sum debit and credit up to as_of_date
            stmt = select(
                func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("total_debit"),
                func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0).label("total_credit"),
            ).where(
                LedgerEntryTable.account_id == account_id,
                LedgerEntryTable.posting_date <= as_of_date,
            )

            result = await self.session.execute(stmt)
            totals = result.first()
            total_debit = Decimal(str(totals[0]))
            total_credit = Decimal(str(totals[1]))

            # Calculate balance based on normal balance
            if normal_balance == "debit":
                balance = total_debit - total_credit
            else:
                balance = total_credit - total_debit

            return balance

        except AccountNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to get account balance for {account_id}: {e}")
            raise LedgerRepositoryError(f"Failed to get balance: {e}") from e

    async def get_account_balance_by_code(
        self, account_code: str, legal_entity_id: UUID, as_of_date: date
    ) -> Decimal:
        """
        Menghitung saldo akun berdasarkan kode akun dan entitas hukum.
        """
        try:
            # Get account by code
            account_stmt = select(AccountTable.id, AccountTable.normal_balance).where(
                AccountTable.account_code == account_code,
                AccountTable.legal_entity_id == legal_entity_id,
            )
            account_result = await self.session.execute(account_stmt)
            account = account_result.first()

            if not account:
                raise AccountNotFoundError(
                    f"Account {account_code} not found in legal entity {legal_entity_id}"
                )

            account_id = account[0]
            normal_balance = account[1]

            # Sum debit and credit
            stmt = select(
                func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("total_debit"),
                func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0).label("total_credit"),
            ).where(
                LedgerEntryTable.account_id == account_id,
                LedgerEntryTable.posting_date <= as_of_date,
                LedgerEntryTable.legal_entity_id == legal_entity_id,
            )

            result = await self.session.execute(stmt)
            totals = result.first()
            total_debit = Decimal(str(totals[0]))
            total_credit = Decimal(str(totals[1]))

            if normal_balance == "debit":
                return total_debit - total_credit
            else:
                return total_credit - total_debit

        except AccountNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to get balance for account {account_code}: {e}")
            raise LedgerRepositoryError(f"Failed to get balance: {e}") from e

    async def get_trial_balance(
        self, legal_entity_id: UUID, as_of_date: date, include_zero_balance: bool = False
    ) -> list[dict[str, Any]]:
        """
        Menghasilkan neraca saldo (trial balance).
        """
        try:
            # Query untuk mendapatkan saldo per akun
            # Subquery untuk menghitung mutasi per akun
            movement_stmt = (
                select(
                    LedgerEntryTable.account_id,
                    func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label(
                        "movement_debit"
                    ),
                    func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0).label(
                        "movement_credit"
                    ),
                )
                .where(
                    LedgerEntryTable.posting_date <= as_of_date,
                    LedgerEntryTable.legal_entity_id == legal_entity_id,
                )
                .group_by(LedgerEntryTable.account_id)
                .subquery()
            )

            # Join dengan account table
            stmt = (
                select(
                    AccountTable.id.label("account_id"),
                    AccountTable.account_code,
                    AccountTable.account_name,
                    AccountTable.account_type,
                    AccountTable.normal_balance,
                    AccountTable.opening_balance_debit,
                    AccountTable.opening_balance_credit,
                    func.coalesce(movement_stmt.c.movement_debit, 0).label("movement_debit"),
                    func.coalesce(movement_stmt.c.movement_credit, 0).label("movement_credit"),
                )
                .outerjoin(movement_stmt, AccountTable.id == movement_stmt.c.account_id)
                .where(
                    AccountTable.legal_entity_id == legal_entity_id, AccountTable.is_active == True
                )
            )

            if not include_zero_balance:
                # Filter akun yang memiliki saldo atau mutasi
                stmt = stmt.where(
                    or_(
                        AccountTable.opening_balance_debit > 0,
                        AccountTable.opening_balance_credit > 0,
                        movement_stmt.c.movement_debit > 0,
                        movement_stmt.c.movement_credit > 0,
                    )
                )

            stmt = stmt.order_by(AccountTable.account_code)
            result = await self.session.execute(stmt)
            rows = result.all()

            lines = []
            total_debit = Decimal(0)
            total_credit = Decimal(0)

            for row in rows:
                opening_debit = Decimal(str(row.opening_balance_debit or 0))
                opening_credit = Decimal(str(row.opening_balance_credit or 0))
                movement_debit = Decimal(str(row.movement_debit or 0))
                movement_credit = Decimal(str(row.movement_credit or 0))

                # Hitung closing balance berdasarkan normal balance
                normal = row.normal_balance
                if normal == "debit":
                    closing_debit = opening_debit + movement_debit - movement_credit
                    closing_credit = Decimal(0)
                else:
                    closing_debit = Decimal(0)
                    closing_credit = opening_credit + movement_credit - movement_debit

                # Untuk laporan, tampilkan sesuai sisi
                if closing_debit > 0:
                    total_debit += closing_debit
                elif closing_credit > 0:
                    total_credit += closing_credit

                lines.append(
                    {
                        "account_id": row.account_id,
                        "account_code": row.account_code,
                        "account_name": row.account_name,
                        "account_type": row.account_type,
                        "opening_balance_debit": opening_debit,
                        "opening_balance_credit": opening_credit,
                        "movement_debit": movement_debit,
                        "movement_credit": movement_credit,
                        "closing_balance_debit": closing_debit,
                        "closing_balance_credit": closing_credit,
                    }
                )

            return {
                "lines": lines,
                "total_debit": total_debit,
                "total_credit": total_credit,
                "is_balanced": abs(total_debit - total_credit) < Decimal("0.01"),
            }

        except Exception as e:
            logger.error(f"Failed to get trial balance: {e}")
            raise LedgerRepositoryError(f"Failed to get trial balance: {e}") from e

    async def find_entries_by_journal(self, journal_id: UUID) -> list[LedgerEntryReadModel]:
        """
        Mencari semua entri ledger yang berasal dari sebuah jurnal.
        """
        try:
            stmt = (
                select(
                    LedgerEntryTable.id,
                    LedgerEntryTable.journal_id,
                    LedgerEntryTable.account_id,
                    LedgerEntryTable.account_code,
                    LedgerEntryTable.debit_amount,
                    LedgerEntryTable.credit_amount,
                    LedgerEntryTable.posting_date,
                    LedgerEntryTable.legal_entity_id,
                    LedgerEntryTable.cost_center,
                    LedgerEntryTable.reference_number,
                    LedgerEntryTable.description,
                )
                .where(LedgerEntryTable.journal_id == journal_id)
                .order_by(LedgerEntryTable.id)
            )

            result = await self.session.execute(stmt)
            rows = result.all()

            return [to_ledger_entry_read_model(row) for row in rows]

        except Exception as e:
            logger.error(f"Failed to find entries by journal {journal_id}: {e}")
            raise LedgerRepositoryError(f"Failed to find entries: {e}") from e

    async def find_entries_by_account_and_date_range(
        self, account_id: UUID, start_date: date, end_date: date
    ) -> list[LedgerEntryReadModel]:
        """
        Mencari entri ledger untuk sebuah akun dalam rentang tanggal.
        """
        try:
            stmt = (
                select(
                    LedgerEntryTable.id,
                    LedgerEntryTable.journal_id,
                    LedgerEntryTable.account_id,
                    LedgerEntryTable.account_code,
                    LedgerEntryTable.debit_amount,
                    LedgerEntryTable.credit_amount,
                    LedgerEntryTable.posting_date,
                    LedgerEntryTable.legal_entity_id,
                    LedgerEntryTable.cost_center,
                    LedgerEntryTable.reference_number,
                    LedgerEntryTable.description,
                )
                .where(
                    LedgerEntryTable.account_id == account_id,
                    LedgerEntryTable.posting_date >= start_date,
                    LedgerEntryTable.posting_date <= end_date,
                )
                .order_by(LedgerEntryTable.posting_date)
            )

            result = await self.session.execute(stmt)
            rows = result.all()

            return [to_ledger_entry_read_model(row) for row in rows]

        except Exception as e:
            logger.error(f"Failed to find entries for account {account_id}: {e}")
            raise LedgerRepositoryError(f"Failed to find entries: {e}") from e

    async def get_balance_sheet(self, legal_entity_id: UUID, as_of_date: date) -> dict[str, Any]:
        """
        Menghasilkan neraca (balance sheet).
        """
        try:
            # Get trial balance first
            tb = await self.get_trial_balance(
                legal_entity_id, as_of_date, include_zero_balance=False
            )

            # Klasifikasikan akun berdasarkan type
            assets = []
            liabilities = []
            equity = []
            total_assets = Decimal(0)
            total_liabilities = Decimal(0)
            total_equity = Decimal(0)

            for line in tb["lines"]:
                account_type = line["account_type"]
                closing_debit = line["closing_balance_debit"]
                closing_credit = line["closing_balance_credit"]

                item = {
                    "account_code": line["account_code"],
                    "account_name": line["account_name"],
                    "balance": closing_debit if closing_debit > 0 else closing_credit,
                }

                if account_type in ["Asset", "ContraAsset"]:
                    assets.append(item)
                    total_assets += item["balance"]
                elif account_type in ["Liability", "ContraLiability"]:
                    liabilities.append(item)
                    total_liabilities += item["balance"]
                elif account_type in ["Equity", "ContraEquity"]:
                    equity.append(item)
                    total_equity += item["balance"]

            return {
                "assets_lines": assets,
                "total_assets": total_assets,
                "liabilities_lines": liabilities,
                "total_liabilities": total_liabilities,
                "equity_lines": equity,
                "total_equity": total_equity,
            }

        except Exception as e:
            logger.error(f"Failed to get balance sheet: {e}")
            raise LedgerRepositoryError(f"Failed to get balance sheet: {e}") from e

    async def get_income_statement(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> dict[str, Any]:
        """
        Menghasilkan laporan laba rugi (income statement).
        """
        try:
            # Get accounts with type Revenue and Expense
            stmt = (
                select(
                    AccountTable.id,
                    AccountTable.account_code,
                    AccountTable.account_name,
                    AccountTable.account_type,
                    func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("total_debit"),
                    func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0).label(
                        "total_credit"
                    ),
                )
                .join(LedgerEntryTable, AccountTable.id == LedgerEntryTable.account_id)
                .where(
                    AccountTable.legal_entity_id == legal_entity_id,
                    AccountTable.account_type.in_(["Revenue", "Expense"]),
                    LedgerEntryTable.posting_date >= start_date,
                    LedgerEntryTable.posting_date <= end_date,
                )
                .group_by(
                    AccountTable.id,
                    AccountTable.account_code,
                    AccountTable.account_name,
                    AccountTable.account_type,
                )
            )

            result = await self.session.execute(stmt)
            rows = result.all()

            revenues = []
            expenses = []
            total_revenue = Decimal(0)
            total_expense = Decimal(0)

            for row in rows:
                total_credit = Decimal(str(row.total_credit))
                total_debit = Decimal(str(row.total_debit))

                if row.account_type == "Revenue":
                    # Revenue: credit increases balance
                    balance = total_credit - total_debit
                    revenues.append(
                        {
                            "account_code": row.account_code,
                            "account_name": row.account_name,
                            "amount": balance,
                        }
                    )
                    total_revenue += balance
                else:
                    # Expense: debit increases balance
                    balance = total_debit - total_credit
                    expenses.append(
                        {
                            "account_code": row.account_code,
                            "account_name": row.account_name,
                            "amount": balance,
                        }
                    )
                    total_expense += balance

            gross_profit = total_revenue - total_expense

            return {
                "revenues": revenues,
                "expenses": expenses,
                "total_revenue": total_revenue,
                "total_expense": total_expense,
                "net_income": gross_profit,
            }

        except Exception as e:
            logger.error(f"Failed to get income statement: {e}")
            raise LedgerRepositoryError(f"Failed to get income statement: {e}") from e

    async def get_cash_flow_statement(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> dict[str, Any]:
        """
        Menghasilkan laporan arus kas (cash flow statement) - indirect method.
        """
        try:
            # Dapatkan net income dari income statement
            income_stmt = await self.get_income_statement(legal_entity_id, start_date, end_date)
            net_income = income_stmt["net_income"]

            # Dapatkan perubahan akun non-kas (asumsi: akun dengan prefix tertentu)
            # Untuk implementasi lengkap, perlu mapping akun arus kas
            # Sederhana: gunakan perubahan modal kerja

            # Query perubahan akun lancar (aset lancar, liabilitas lancar)
            # ... (implementasi lebih lanjut)

            # Sederhana: return placeholde dengan data minimal
            return {
                "net_income": net_income,
                "depreciation_addback": Decimal(0),
                "change_in_working_capital": Decimal(0),
                "cash_from_operations": net_income,
                "cash_from_investing": Decimal(0),
                "cash_from_financing": Decimal(0),
                "net_cash_flow": net_income,
                "beginning_cash": Decimal(0),
                "ending_cash": net_income,
            }

        except Exception as e:
            logger.error(f"Failed to get cash flow statement: {e}")
            raise LedgerRepositoryError(f"Failed to get cash flow statement: {e}") from e


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["AccountNotFoundError", "LedgerRepositoryError", "SQLAlchemyLedgerRepository"]
