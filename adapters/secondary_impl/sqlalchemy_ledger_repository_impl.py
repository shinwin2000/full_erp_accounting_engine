#!/usr/bin/env python3
"""
Module: sqlalchemy_ledger_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk entri buku besar (Ledger) menggunakan
               SQLAlchemy ORM. LENGKAP dengan semua method port.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, UTC
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func, or_, select, and_, text
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.account_table import AccountTable
from infrastructure.persistence_orm.ledger_entry_table import LedgerEntryTable
from ports.primary.ledger_repository_port import LedgerEntryReadModel, LedgerRepositoryPort

logger = logging.getLogger(__name__)

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


class LedgerRepositoryError(Exception):
    pass


class AccountNotFoundError(LedgerRepositoryError):
    pass


def to_ledger_entry_read_model(row: Any) -> LedgerEntryReadModel:
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


class SQLAlchemyLedgerRepository(LedgerRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        self._audit_log: List[Dict[str, Any]] = []

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise LedgerRepositoryError("Session not set")
        return self._session

    @session.setter
    def session(self, value: AsyncSession) -> None:
        self._session = value

    async def _log_audit(self, action: str, details: Dict[str, Any]) -> None:
        self._audit_log.append({
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "details": details,
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    # ========================================================================
    # EXISTING METHODS (from original)
    # ========================================================================

    async def get_account_balance(self, account_id: UUID, as_of_date: date) -> Decimal:
        try:
            account_stmt = select(AccountTable.normal_balance, AccountTable.account_type).where(
                AccountTable.id == account_id
            )
            account_result = await self.session.execute(account_stmt)
            account_info = account_result.first()
            if not account_info:
                raise AccountNotFoundError(f"Account {account_id} not found")
            normal_balance = account_info[0]
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
            if normal_balance == "debit":
                return total_debit - total_credit
            else:
                return total_credit - total_debit
        except AccountNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to get account balance for {account_id}: {e}")
            raise LedgerRepositoryError(f"Failed to get balance: {e}") from e

    async def get_account_balance_by_code(
        self, account_code: str, legal_entity_id: UUID, as_of_date: date
    ) -> Decimal:
        try:
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
    ) -> dict[str, Any]:
        try:
            movement_stmt = (
                select(
                    LedgerEntryTable.account_id,
                    func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("movement_debit"),
                    func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0).label("movement_credit"),
                )
                .where(
                    LedgerEntryTable.posting_date <= as_of_date,
                    LedgerEntryTable.legal_entity_id == legal_entity_id,
                )
                .group_by(LedgerEntryTable.account_id)
                .subquery()
            )
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
                    AccountTable.legal_entity_id == legal_entity_id,
                    AccountTable.is_active == True,
                )
            )
            if not include_zero_balance:
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
                normal = row.normal_balance
                if normal == "debit":
                    closing_debit = opening_debit + movement_debit - movement_credit
                    closing_credit = Decimal(0)
                else:
                    closing_debit = Decimal(0)
                    closing_credit = opening_credit + movement_credit - movement_debit
                if closing_debit > 0:
                    total_debit += closing_debit
                elif closing_credit > 0:
                    total_credit += closing_credit
                lines.append({
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
                })
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
        try:
            stmt = select(
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
            ).where(LedgerEntryTable.journal_id == journal_id).order_by(LedgerEntryTable.id)
            result = await self.session.execute(stmt)
            rows = result.all()
            return [to_ledger_entry_read_model(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to find entries by journal {journal_id}: {e}")
            raise LedgerRepositoryError(f"Failed to find entries: {e}") from e

    async def find_entries_by_account_and_date_range(
        self, account_id: UUID, start_date: date, end_date: date
    ) -> list[LedgerEntryReadModel]:
        try:
            stmt = select(
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
            ).where(
                LedgerEntryTable.account_id == account_id,
                LedgerEntryTable.posting_date >= start_date,
                LedgerEntryTable.posting_date <= end_date,
            ).order_by(LedgerEntryTable.posting_date)
            result = await self.session.execute(stmt)
            rows = result.all()
            return [to_ledger_entry_read_model(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to find entries for account {account_id}: {e}")
            raise LedgerRepositoryError(f"Failed to find entries: {e}") from e

    async def get_balance_sheet(self, legal_entity_id: UUID, as_of_date: date) -> dict[str, Any]:
        try:
            tb = await self.get_trial_balance(legal_entity_id, as_of_date, include_zero_balance=False)
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
        try:
            stmt = select(
                AccountTable.id,
                AccountTable.account_code,
                AccountTable.account_name,
                AccountTable.account_type,
                func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("total_debit"),
                func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0).label("total_credit"),
            ).join(LedgerEntryTable, AccountTable.id == LedgerEntryTable.account_id).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.account_type.in_(["Revenue", "Expense"]),
                LedgerEntryTable.posting_date >= start_date,
                LedgerEntryTable.posting_date <= end_date,
            ).group_by(
                AccountTable.id,
                AccountTable.account_code,
                AccountTable.account_name,
                AccountTable.account_type,
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
                    balance = total_credit - total_debit
                    revenues.append({"account_code": row.account_code, "account_name": row.account_name, "amount": balance})
                    total_revenue += balance
                else:
                    balance = total_debit - total_credit
                    expenses.append({"account_code": row.account_code, "account_name": row.account_name, "amount": balance})
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
        try:
            income_stmt = await self.get_income_statement(legal_entity_id, start_date, end_date)
            net_income = income_stmt["net_income"]
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

    # ========================================================================
    # NEW METHODS FOR PORT CONTRACT
    # ========================================================================

    async def add_entry(self, entry: LedgerEntryReadModel) -> None:
        """Add a single ledger entry (for testing/reconciliation)."""
        try:
            new_entry = LedgerEntryTable(
                id=entry.id,
                journal_id=entry.journal_id,
                account_id=entry.account_id,
                account_code=entry.account_code,
                debit_amount=entry.debit_amount,
                credit_amount=entry.credit_amount,
                posting_date=entry.posting_date,
                legal_entity_id=entry.legal_entity_id,
                cost_center=entry.cost_center,
                reference_number=entry.reference_number,
                description=entry.description,
                created_at=datetime.now(UTC),
            )
            self.session.add(new_entry)
            await self.session.flush()
            await self._log_audit("ADD_ENTRY", {"entry_id": str(entry.id)})
            logger.info(f"Ledger entry added: {entry.id}")
        except Exception as e:
            await self.session.rollback()
            raise LedgerRepositoryError(f"Failed to add entry: {e}") from e

    async def add_batch(self, entries: List[LedgerEntryReadModel]) -> None:
        """Add multiple ledger entries in batch."""
        try:
            for entry in entries:
                new_entry = LedgerEntryTable(
                    id=entry.id,
                    journal_id=entry.journal_id,
                    account_id=entry.account_id,
                    account_code=entry.account_code,
                    debit_amount=entry.debit_amount,
                    credit_amount=entry.credit_amount,
                    posting_date=entry.posting_date,
                    legal_entity_id=entry.legal_entity_id,
                    cost_center=entry.cost_center,
                    reference_number=entry.reference_number,
                    description=entry.description,
                    created_at=datetime.now(UTC),
                )
                self.session.add(new_entry)
            await self.session.flush()
            await self._log_audit("ADD_BATCH", {"count": len(entries)})
            logger.info(f"Added {len(entries)} ledger entries in batch")
        except Exception as e:
            await self.session.rollback()
            raise LedgerRepositoryError(f"Failed to add batch: {e}") from e

    async def find_entries_by_account_code(
        self, account_code: str, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> list[LedgerEntryReadModel]:
        """Find ledger entries by account code and date range."""
        try:
            stmt = select(
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
            ).where(
                LedgerEntryTable.account_code == account_code,
                LedgerEntryTable.legal_entity_id == legal_entity_id,
                LedgerEntryTable.posting_date >= start_date,
                LedgerEntryTable.posting_date <= end_date,
            ).order_by(LedgerEntryTable.posting_date)
            result = await self.session.execute(stmt)
            rows = result.all()
            return [to_ledger_entry_read_model(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to find entries by account code {account_code}: {e}")
            raise LedgerRepositoryError(f"Failed to find entries: {e}") from e

    async def find_entries_by_period(
        self, legal_entity_id: UUID, year: int, month: int
    ) -> list[LedgerEntryReadModel]:
        """Find all ledger entries for a specific period (year, month)."""
        try:
            start_date = date(year, month, 1)
            if month == 12:
                end_date = date(year + 1, 1, 1)
            else:
                end_date = date(year, month + 1, 1)
            stmt = select(
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
            ).where(
                LedgerEntryTable.legal_entity_id == legal_entity_id,
                LedgerEntryTable.posting_date >= start_date,
                LedgerEntryTable.posting_date < end_date,
            ).order_by(LedgerEntryTable.posting_date)
            result = await self.session.execute(stmt)
            rows = result.all()
            return [to_ledger_entry_read_model(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to find entries by period {year}-{month}: {e}")
            raise LedgerRepositoryError(f"Failed to find entries: {e}") from e

    async def get_account_balance_summary(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> Dict[str, Decimal]:
        """Get balance summary by account type (Asset, Liability, Equity, Revenue, Expense)."""
        try:
            tb = await self.get_trial_balance(legal_entity_id, as_of_date, include_zero_balance=False)
            summary = {
                "Asset": Decimal(0),
                "Liability": Decimal(0),
                "Equity": Decimal(0),
                "Revenue": Decimal(0),
                "Expense": Decimal(0),
            }
            for line in tb["lines"]:
                account_type = line["account_type"]
                closing_debit = line["closing_balance_debit"]
                closing_credit = line["closing_balance_credit"]
                balance = closing_debit if closing_debit > 0 else closing_credit
                if account_type in summary:
                    summary[account_type] += balance
                else:
                    summary[account_type] = balance
            return summary
        except Exception as e:
            logger.error(f"Failed to get account balance summary: {e}")
            raise LedgerRepositoryError(f"Failed to get summary: {e}") from e

    async def get_account_balance_with_normal(
        self, account_id: UUID, as_of_date: date
    ) -> Tuple[Decimal, str]:
        """Get balance and normal balance direction for an account."""
        try:
            balance = await self.get_account_balance(account_id, as_of_date)
            stmt = select(AccountTable.normal_balance).where(AccountTable.id == account_id)
            result = await self.session.execute(stmt)
            normal = result.scalar_one_or_none()
            if not normal:
                raise AccountNotFoundError(f"Account {account_id} not found")
            return balance, normal
        except AccountNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to get account balance with normal for {account_id}: {e}")
            raise LedgerRepositoryError(f"Failed to get balance: {e}") from e

    async def get_all_entries_for_entity(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> list[LedgerEntryReadModel]:
        """Get all ledger entries for an entity within date range."""
        try:
            stmt = select(
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
            ).where(
                LedgerEntryTable.legal_entity_id == legal_entity_id,
                LedgerEntryTable.posting_date >= start_date,
                LedgerEntryTable.posting_date <= end_date,
            ).order_by(LedgerEntryTable.posting_date)
            result = await self.session.execute(stmt)
            rows = result.all()
            return [to_ledger_entry_read_model(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get all entries for entity {legal_entity_id}: {e}")
            raise LedgerRepositoryError(f"Failed to get entries: {e}") from e

    async def get_cash_flow_indirect(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> dict[str, Any]:
        """Alias for get_cash_flow_statement."""
        return await self.get_cash_flow_statement(legal_entity_id, start_date, end_date)

    async def get_period_balance(
        self, legal_entity_id: UUID, year: int, month: int
    ) -> Dict[str, Decimal]:
        """Get balance for a specific period."""
        try:
            # Get trial balance at end of period
            end_date = date(year, month, 1)
            if month == 12:
                end_date = date(year + 1, 1, 1)
            else:
                end_date = date(year, month + 1, 1)
            # We need balance at end_date - 1 day
            as_of_date = end_date - timedelta(days=1)
            return await self.get_account_balance_summary(legal_entity_id, as_of_date)
        except Exception as e:
            logger.error(f"Failed to get period balance for {year}-{month}: {e}")
            raise LedgerRepositoryError(f"Failed to get period balance: {e}") from e

    async def get_statistics(self, legal_entity_id: UUID) -> Dict[str, Any]:
        """Get statistics about ledger entries."""
        try:
            total_stmt = select(func.count()).select_from(LedgerEntryTable).where(
                LedgerEntryTable.legal_entity_id == legal_entity_id
            )
            total_entries = (await self.session.execute(total_stmt)).scalar() or 0
            min_date_stmt = select(func.min(LedgerEntryTable.posting_date)).where(
                LedgerEntryTable.legal_entity_id == legal_entity_id
            )
            min_date = (await self.session.execute(min_date_stmt)).scalar()
            max_date_stmt = select(func.max(LedgerEntryTable.posting_date)).where(
                LedgerEntryTable.legal_entity_id == legal_entity_id
            )
            max_date = (await self.session.execute(max_date_stmt)).scalar()
            total_debit = await self.session.execute(
                select(func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0)).where(
                    LedgerEntryTable.legal_entity_id == legal_entity_id
                )
            )
            total_debit_amount = total_debit.scalar() or 0
            total_credit = await self.session.execute(
                select(func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0)).where(
                    LedgerEntryTable.legal_entity_id == legal_entity_id
                )
            )
            total_credit_amount = total_credit.scalar() or 0
            return {
                "total_entries": total_entries,
                "first_entry_date": min_date.isoformat() if min_date else None,
                "last_entry_date": max_date.isoformat() if max_date else None,
                "total_debit": float(total_debit_amount),
                "total_credit": float(total_credit_amount),
                "difference": float(total_debit_amount - total_credit_amount),
            }
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            raise LedgerRepositoryError(f"Failed to get statistics: {e}") from e

    async def get_trial_balance_by_period(
        self, legal_entity_id: UUID, year: int, month: int
    ) -> dict[str, Any]:
        """Get trial balance for a specific period."""
        try:
            end_date = date(year, month, 1)
            if month == 12:
                end_date = date(year + 1, 1, 1)
            else:
                end_date = date(year, month + 1, 1)
            as_of_date = end_date - timedelta(days=1)
            return await self.get_trial_balance(legal_entity_id, as_of_date, include_zero_balance=False)
        except Exception as e:
            logger.error(f"Failed to get trial balance by period {year}-{month}: {e}")
            raise LedgerRepositoryError(f"Failed to get trial balance: {e}") from e

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Get audit log of ledger operations."""
        logs = self._audit_log.copy()
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return logs[offset:offset + limit]

    async def health_check(self) -> Dict[str, Any]:
        """Check health of the repository."""
        try:
            await self.session.execute(text("SELECT 1"))
            return {"status": "healthy", "repository": "LedgerRepository"}
        except Exception as e:
            return {"status": "unhealthy", "repository": "LedgerRepository", "error": str(e)}


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "AccountNotFoundError",
    "LedgerRepositoryError",
    "SQLAlchemyLedgerRepository",
]