#!/usr/bin/env python3
"""
Module: sqlalchemy_ledger_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository Ledger dengan SQLAlchemy.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.account_table import AccountTable
from infrastructure.persistence_orm.ledger_entry_table import LedgerEntryTable
from ports.primary.ledger_repository_port import (
    AccountBalance,
    AccountType,
    FinancialStatementRow,
    LedgerEntry,
    LedgerRepositoryPort,
    NormalBalance,
    TrialBalanceRow,
)

logger = logging.getLogger(__name__)


class LedgerRepositoryError(Exception):
    pass


class AccountNotFoundError(LedgerRepositoryError):
    pass


class SQLAlchemyLedgerRepository(LedgerRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        self._audit_log: list[dict[str, Any]] = []

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise LedgerRepositoryError("Session not set")
        return self._session

    @session.setter
    def session(self, value: AsyncSession) -> None:
        self._session = value

    async def _log_audit(self, action: str, details: dict[str, Any]) -> None:
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "details": details,
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    # ========================================================================
    # ENTRY MANAGEMENT
    # ========================================================================

    async def add_entry(self, entry: LedgerEntry) -> None:
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
                created_at=datetime.utcnow(),
            )
            self.session.add(new_entry)
            await self.session.flush()
            await self._log_audit("ADD_ENTRY", {"entry_id": str(entry.id)})
            logger.info(f"Ledger entry added: {entry.id}")
        except Exception as e:
            await self.session.rollback()
            raise LedgerRepositoryError(f"Failed to add entry: {e}") from e

    async def add_batch(self, entries: list[LedgerEntry]) -> None:
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
                    created_at=datetime.utcnow(),
                )
                self.session.add(new_entry)
            await self.session.flush()
            await self._log_audit("ADD_BATCH", {"count": len(entries)})
            logger.info(f"Added {len(entries)} ledger entries in batch")
        except Exception as e:
            await self.session.rollback()
            raise LedgerRepositoryError(f"Failed to add batch: {e}") from e

    # ========================================================================
    # BALANCE
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

    async def get_balance(self, account_id: UUID, as_of_date: date) -> Decimal:
        return await self.get_account_balance(account_id, as_of_date)

    async def get_period_balance(
        self, account_id: UUID, fiscal_year: int, period: int, include_opening: bool = True
    ) -> Decimal:
        start_date = date(fiscal_year, period, 1)
        if period == 12:
            end_date = date(fiscal_year + 1, 1, 1)
        else:
            end_date = date(fiscal_year, period + 1, 1)
        as_of_date = end_date - timedelta(days=1)
        return await self.get_account_balance(account_id, as_of_date)

    async def get_account_balance_with_normal(
        self, account_id: UUID, as_of_date: date, normal_balance: NormalBalance
    ) -> Decimal:
        try:
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
            if normal_balance == NormalBalance.DEBIT:
                return total_debit - total_credit
            else:
                return total_credit - total_debit
        except Exception as e:
            logger.error(f"Failed to get account balance with normal for {account_id}: {e}")
            raise LedgerRepositoryError(f"Failed to get balance: {e}") from e

    # ========================================================================
    # TRIAL BALANCE
    # ========================================================================

    async def get_trial_balance(
        self, legal_entity_id: UUID, as_of_date: date, include_zero_balance: bool = False
    ) -> list[TrialBalanceRow]:
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
                    lines.append(
                        TrialBalanceRow(
                            account_code=row.account_code,
                            account_name=row.account_name,
                            debit_balance=closing_debit,
                            credit_balance=Decimal(0),
                        )
                    )
                elif closing_credit > 0:
                    lines.append(
                        TrialBalanceRow(
                            account_code=row.account_code,
                            account_name=row.account_name,
                            debit_balance=Decimal(0),
                            credit_balance=closing_credit,
                        )
                    )
                elif include_zero_balance:
                    lines.append(
                        TrialBalanceRow(
                            account_code=row.account_code,
                            account_name=row.account_name,
                            debit_balance=Decimal(0),
                            credit_balance=Decimal(0),
                        )
                    )
            return lines
        except Exception as e:
            logger.error(f"Failed to get trial balance: {e}")
            raise LedgerRepositoryError(f"Failed to get trial balance: {e}") from e

    async def get_trial_balance_by_period(
        self,
        legal_entity_id: UUID,
        fiscal_year: int,
        period: int,
        include_zero_balance: bool = False,
    ) -> list[TrialBalanceRow]:
        end_date = date(fiscal_year, period, 1)
        if period == 12:
            end_date = date(fiscal_year + 1, 1, 1)
        else:
            end_date = date(fiscal_year, period + 1, 1)
        as_of_date = end_date - timedelta(days=1)
        return await self.get_trial_balance(legal_entity_id, as_of_date, include_zero_balance)

    # ========================================================================
    # FINANCIAL STATEMENTS
    # ========================================================================

    async def get_income_statement(
        self,
        legal_entity_id: UUID,
        fiscal_year: int,
        period: int,
        compare_with_previous: bool = True,
    ) -> dict[str, Any]:
        start_date = date(fiscal_year, period, 1)
        if period == 12:
            end_date = date(fiscal_year + 1, 1, 1)
        else:
            end_date = date(fiscal_year, period + 1, 1)
        try:
            stmt = select(
                AccountTable.account_code,
                AccountTable.account_name,
                AccountTable.account_type,
                func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("total_debit"),
                func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0).label("total_credit"),
            ).join(LedgerEntryTable, AccountTable.id == LedgerEntryTable.account_id).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.account_type.in_(["Revenue", "Expense"]),
                LedgerEntryTable.posting_date >= start_date,
                LedgerEntryTable.posting_date < end_date,
            ).group_by(
                AccountTable.account_code,
                AccountTable.account_name,
                AccountTable.account_type,
            )
            result = await self.session.execute(stmt)
            rows = result.all()
            revenue_rows = []
            expense_rows = []
            total_revenue = Decimal(0)
            total_expense = Decimal(0)
            for row in rows:
                total_credit = Decimal(str(row.total_credit))
                total_debit = Decimal(str(row.total_debit))
                if row.account_type == "Revenue":
                    balance = total_credit - total_debit
                    revenue_rows.append(
                        FinancialStatementRow(
                            account_code=row.account_code,
                            account_name=row.account_name,
                            current_period=balance,
                            previous_period=Decimal(0),
                            variance=balance,
                            variance_percentage=0.0,
                        )
                    )
                    total_revenue += balance
                else:
                    balance = total_debit - total_credit
                    expense_rows.append(
                        FinancialStatementRow(
                            account_code=row.account_code,
                            account_name=row.account_name,
                            current_period=balance,
                            previous_period=Decimal(0),
                            variance=balance,
                            variance_percentage=0.0,
                        )
                    )
                    total_expense += balance
            return {
                "revenue_total": str(total_revenue),
                "expense_total": str(total_expense),
                "net_income": str(total_revenue - total_expense),
                "revenue_details": [
                    {
                        "account_code": r.account_code,
                        "account_name": r.account_name,
                        "current_period": str(r.current_period),
                        "previous_period": str(r.previous_period),
                        "variance": str(r.variance),
                        "variance_percentage": r.variance_percentage,
                    }
                    for r in revenue_rows
                ],
                "expense_details": [
                    {
                        "account_code": e.account_code,
                        "account_name": e.account_name,
                        "current_period": str(e.current_period),
                        "previous_period": str(e.previous_period),
                        "variance": str(e.variance),
                        "variance_percentage": e.variance_percentage,
                    }
                    for e in expense_rows
                ],
            }
        except Exception as e:
            logger.error(f"Failed to get income statement: {e}")
            raise LedgerRepositoryError(f"Failed to get income statement: {e}") from e

    async def get_balance_sheet(
        self,
        legal_entity_id: UUID,
        as_of_date: date,
        compare_with_previous: bool = True,
    ) -> dict[str, Any]:
        tb = await self.get_trial_balance(legal_entity_id, as_of_date, include_zero_balance=False)
        assets = []
        liabilities = []
        equity = []
        total_assets = Decimal(0)
        total_liabilities = Decimal(0)
        total_equity = Decimal(0)
        for row in tb:
            acc_stmt = select(AccountTable.account_type).where(
                AccountTable.account_code == row.account_code,
                AccountTable.legal_entity_id == legal_entity_id,
            )
            acc_result = await self.session.execute(acc_stmt)
            acc_type = acc_result.scalar_one_or_none()
            if not acc_type:
                continue
            balance = row.debit_balance if row.debit_balance > 0 else row.credit_balance
            item = {"account_code": row.account_code, "account_name": row.account_name, "balance": str(balance)}
            if acc_type in ["Asset", "ContraAsset"]:
                assets.append(item)
                total_assets += balance
            elif acc_type in ["Liability", "ContraLiability"]:
                liabilities.append(item)
                total_liabilities += balance
            elif acc_type in ["Equity", "ContraEquity"]:
                equity.append(item)
                total_equity += balance
        return {
            "as_of_date": as_of_date.isoformat(),
            "total_assets": str(total_assets),
            "total_liabilities": str(total_liabilities),
            "total_equity": str(total_equity),
            "liabilities_and_equity": str(total_liabilities + total_equity),
            "asset_details": assets,
            "liability_details": liabilities,
            "equity_details": equity,
        }

    async def get_cash_flow_indirect(
        self, legal_entity_id: UUID, fiscal_year: int, period: int
    ) -> dict[str, Any]:
        income = await self.get_income_statement(legal_entity_id, fiscal_year, period, False)
        net_income = Decimal(str(income["net_income"]))
        start_date = date(fiscal_year, period, 1)
        if period == 12:
            end_date = date(fiscal_year + 1, 1, 1)
        else:
            end_date = date(fiscal_year, period + 1, 1)
        deprec_sql = """
            SELECT COALESCE(SUM(le.credit_amount), 0)
            FROM ledger_entries le
            JOIN accounts a ON le.account_id = a.id
            WHERE a.legal_entity_id = :legal_entity_id
              AND a.account_type = 'Expense'
              AND (a.account_code LIKE '%depreciation%' OR a.account_code LIKE '%amortization%')
              AND le.posting_date BETWEEN :start_date AND :end_date
        """
        deprec = await self.session.scalar(
            text(deprec_sql),
            {
                "legal_entity_id": legal_entity_id,
                "start_date": start_date,
                "end_date": end_date,
            }
        ) or Decimal(0)
        operating_cf = net_income + deprec
        return {
            "period": f"Month {period} {fiscal_year}",
            "net_cash_operating": str(operating_cf),
            "net_cash_investing": "0",
            "net_cash_financing": "0",
            "net_cash_increase": str(operating_cf),
            "operating_activities_details": {
                "net_income": str(net_income),
                "adjustments": [{"description": "Depreciation", "amount": str(deprec)}],
                "changes_in_assets": [],
                "changes_in_liabilities": [],
            },
            "investing_activities_details": [],
            "financing_activities_details": [],
        }

    # ========================================================================
    # ACCOUNT BALANCE SUMMARY
    # ========================================================================

    async def get_account_balance_summary(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> list[AccountBalance]:
        try:
            tb = await self.get_trial_balance(legal_entity_id, as_of_date, include_zero_balance=False)
            result = []
            for row in tb:
                acc_stmt = select(AccountTable.id, AccountTable.account_type, AccountTable.normal_balance).where(
                    AccountTable.account_code == row.account_code,
                    AccountTable.legal_entity_id == legal_entity_id,
                )
                acc = (await self.session.execute(acc_stmt)).first()
                if not acc:
                    continue
                balance = row.debit_balance if row.debit_balance > 0 else row.credit_balance
                result.append(
                    AccountBalance(
                        account_id=acc[0],
                        account_code=row.account_code,
                        account_name=row.account_name,
                        account_type=AccountType(acc[1].lower()),
                        normal_balance=NormalBalance(acc[2]),
                        opening_balance=Decimal(0),
                        debit_movement=Decimal(0),
                        credit_movement=Decimal(0),
                        closing_balance=balance,
                    )
                )
            return result
        except Exception as e:
            logger.error(f"Failed to get account balance summary: {e}")
            raise LedgerRepositoryError(f"Failed to get summary: {e}") from e

    # ========================================================================
    # QUERY ENTRIES
    # ========================================================================

    async def find_entries_by_journal(self, journal_id: UUID) -> list[LedgerEntry]:
        try:
            stmt = select(LedgerEntryTable).where(LedgerEntryTable.journal_id == journal_id).order_by(LedgerEntryTable.id)
            result = await self.session.execute(stmt)
            rows = result.scalars().all()
            return await self._rows_to_domain_entries(rows)
        except Exception as e:
            logger.error(f"Failed to find entries by journal {journal_id}: {e}")
            raise LedgerRepositoryError(f"Failed to find entries: {e}") from e

    async def find_entries_by_account(
        self, account_id: UUID, start_date: date, end_date: date
    ) -> list[LedgerEntry]:
        return await self.find_entries_by_account_and_date_range(account_id, start_date, end_date)

    async def find_entries_by_account_and_date_range(
        self, account_id: UUID, start_date: date, end_date: date
    ) -> list[LedgerEntry]:
        try:
            stmt = select(LedgerEntryTable).where(
                LedgerEntryTable.account_id == account_id,
                LedgerEntryTable.posting_date >= start_date,
                LedgerEntryTable.posting_date <= end_date,
            ).order_by(LedgerEntryTable.posting_date)
            result = await self.session.execute(stmt)
            rows = result.scalars().all()
            return await self._rows_to_domain_entries(rows)
        except Exception as e:
            logger.error(f"Failed to find entries for account {account_id}: {e}")
            raise LedgerRepositoryError(f"Failed to find entries: {e}") from e

    async def find_entries_by_account_code(
        self, account_code: str, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> list[LedgerEntry]:
        try:
            stmt = select(LedgerEntryTable).where(
                LedgerEntryTable.account_code == account_code,
                LedgerEntryTable.legal_entity_id == legal_entity_id,
                LedgerEntryTable.posting_date >= start_date,
                LedgerEntryTable.posting_date <= end_date,
            ).order_by(LedgerEntryTable.posting_date)
            result = await self.session.execute(stmt)
            rows = result.scalars().all()
            return await self._rows_to_domain_entries(rows)
        except Exception as e:
            logger.error(f"Failed to find entries by account code {account_code}: {e}")
            raise LedgerRepositoryError(f"Failed to find entries: {e}") from e

    async def find_entries_by_period(
        self, legal_entity_id: UUID, fiscal_year: int, period: int
    ) -> list[LedgerEntry]:
        start_date = date(fiscal_year, period, 1)
        if period == 12:
            end_date = date(fiscal_year + 1, 1, 1)
        else:
            end_date = date(fiscal_year, period + 1, 1)
        try:
            stmt = select(LedgerEntryTable).where(
                LedgerEntryTable.legal_entity_id == legal_entity_id,
                LedgerEntryTable.posting_date >= start_date,
                LedgerEntryTable.posting_date < end_date,
            ).order_by(LedgerEntryTable.posting_date)
            result = await self.session.execute(stmt)
            rows = result.scalars().all()
            return await self._rows_to_domain_entries(rows)
        except Exception as e:
            logger.error(f"Failed to find entries by period {fiscal_year}-{period}: {e}")
            raise LedgerRepositoryError(f"Failed to find entries: {e}") from e

    async def get_all_entries_for_entity(self, legal_entity_id: UUID) -> list[LedgerEntry]:
        try:
            stmt = select(LedgerEntryTable).where(
                LedgerEntryTable.legal_entity_id == legal_entity_id,
            ).order_by(LedgerEntryTable.posting_date)
            result = await self.session.execute(stmt)
            rows = result.scalars().all()
            return await self._rows_to_domain_entries(rows)
        except Exception as e:
            logger.error(f"Failed to get all entries for entity {legal_entity_id}: {e}")
            raise LedgerRepositoryError(f"Failed to get entries: {e}") from e

    # ========================================================================
    # STATISTICS & AUDIT
    # ========================================================================

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        try:
            total_stmt = select(func.count()).select_from(LedgerEntryTable).where(
                LedgerEntryTable.legal_entity_id == legal_entity_id
            )
            total_entries = (await self.session.execute(total_stmt)).scalar() or 0
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
            # Unique journals
            journals_stmt = select(func.count(func.distinct(LedgerEntryTable.journal_id))).where(
                LedgerEntryTable.legal_entity_id == legal_entity_id
            )
            unique_journals = (await self.session.execute(journals_stmt)).scalar() or 0
            accounts_stmt = select(func.count(func.distinct(LedgerEntryTable.account_id))).where(
                LedgerEntryTable.legal_entity_id == legal_entity_id
            )
            unique_accounts = (await self.session.execute(accounts_stmt)).scalar() or 0
            return {
                "total_entries": total_entries,
                "total_debit": str(total_debit_amount),
                "total_credit": str(total_credit_amount),
                "unique_journals": unique_journals,
                "unique_accounts": unique_accounts,
                "audit_log_size": len(self._audit_log),
            }
        except Exception as e:
            logger.error(f"Failed to get statistics: {e}")
            raise LedgerRepositoryError(f"Failed to get statistics: {e}") from e

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        logs = self._audit_log.copy()
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return logs[offset:offset + limit]

    async def health_check(self) -> dict[str, Any]:
        try:
            await self.session.execute(text("SELECT 1"))
            return {"status": "healthy", "repository": "LedgerRepository"}
        except Exception as e:
            return {"status": "unhealthy", "repository": "LedgerRepository", "error": str(e)}

    # ========================================================================
    # HELPER
    # ========================================================================

    async def _rows_to_domain_entries(self, rows) -> list[LedgerEntry]:
        """Convert ORM rows to domain LedgerEntry."""
        domain_entries = []
        for row in rows:
            acc_stmt = select(AccountTable.account_name, AccountTable.account_type, AccountTable.normal_balance).where(
                AccountTable.id == row.account_id
            )
            acc = (await self.session.execute(acc_stmt)).first()
            account_name = acc[0] if acc else ""
            account_type = acc[1] if acc else "Asset"
            normal_balance = acc[2] if acc else "debit"
            domain_entries.append(
                LedgerEntry(
                    id=row.id,
                    journal_id=row.journal_id,
                    journal_line_id=row.id,
                    account_id=row.account_id,
                    account_code=row.account_code,
                    account_name=account_name,
                    account_type=AccountType(account_type.lower()),
                    normal_balance=NormalBalance(normal_balance),
                    legal_entity_id=row.legal_entity_id,
                    debit_amount=row.debit_amount,
                    credit_amount=row.credit_amount,
                    posting_date=row.posting_date,
                    fiscal_year=row.posting_date.year,
                    period=row.posting_date.month,
                    description=row.description,
                    reference_number=row.reference_number,
                    cost_center=row.cost_center,
                    department_id=None,
                    project_id=None,
                )
            )
        return domain_entries


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "AccountNotFoundError",
    "LedgerRepositoryError",
    "SQLAlchemyLedgerRepository",
]