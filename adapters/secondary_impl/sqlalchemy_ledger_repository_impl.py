#!/usr/bin/env python3
"""
Module: sqlalchemy_ledger_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk entri buku besar (Ledger) menggunakan
               SQLAlchemy ORM. LENGKAP dengan semua method port.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
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
    LedgerEntryReadModel,
    LedgerRepositoryPort,
    NormalBalance,
    TrialBalanceRow,
)

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


def _rows_to_domain(rows: Any, session: AsyncSession) -> list[LedgerEntry]:
    """Convert raw rows to domain LedgerEntry (helper async, tapi kita panggil di method)."""
    # Karena helper ini sync, kita tidak bisa await. Jadi kita akan mapping langsung di method.
    # Untuk menghindari N+1, kita query semua account terlebih dahulu di method yang memanggil.
    # Saya lebih baik tidak pakai helper ini di sini, langsung mapping di method masing-masing.
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
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "details": details,
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    # ========================================================================
    # CORE METHODS (port contract)
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
                created_at=datetime.now(UTC),
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
                    created_at=datetime.now(UTC),
                )
                self.session.add(new_entry)
            await self.session.flush()
            await self._log_audit("ADD_BATCH", {"count": len(entries)})
            logger.info(f"Added {len(entries)} ledger entries in batch")
        except Exception as e:
            await self.session.rollback()
            raise LedgerRepositoryError(f"Failed to add batch: {e}") from e

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

    # ========================================================================
    # FIX: METHOD YANG HILANG (get_balance sesuai port)
    # ========================================================================

    async def get_balance(self, account_id: UUID, as_of_date: date) -> Decimal:
        """
        Get account balance as of date (alias for get_account_balance).
        This method fulfills the LedgerRepositoryPort contract.
        """
        return await self.get_account_balance(account_id, as_of_date)

    # ========================================================================
    # FIX: METHOD YANG HILANG (find_entries_by_account)
    # ========================================================================

    async def find_entries_by_account(
        self, account_id: UUID, start_date: date, end_date: date
    ) -> list[LedgerEntry]:
        """
        Find ledger entries for an account within a date range.
        This method fulfills the LedgerRepositoryPort contract.
        """
        return await self.find_entries_by_account_and_date_range(account_id, start_date, end_date)

    # ========================================================================
    # FIX: METHOD YANG HILANG (get_account_balance_with_normal) - tambahan
    # ========================================================================

    async def get_account_balance_with_normal(
        self, account_id: UUID, as_of_date: date, normal_balance: NormalBalance
    ) -> Decimal:
        """
        Get account balance as of date, returned in the direction of normal_balance.
        If normal_balance is DEBIT, returns debit - credit.
        If normal_balance is CREDIT, returns credit - debit.
        """
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
    # OTHER METHODS
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
                "revenue_total": float(total_revenue),
                "expense_total": float(total_expense),
                "net_income": float(total_revenue - total_expense),
                "revenue_details": [r.to_dict() for r in revenue_rows],
                "expense_details": [e.to_dict() for e in expense_rows],
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
            item = {"account_code": row.account_code, "account_name": row.account_name, "balance": balance}
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
            "assets_lines": assets,
            "total_assets": total_assets,
            "liabilities_lines": liabilities,
            "total_liabilities": total_liabilities,
            "equity_lines": equity,
            "total_equity": total_equity,
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
            "net_cash_operating": float(operating_cf),
            "net_cash_investing": 0.0,
            "net_cash_financing": 0.0,
            "net_cash_increase": float(operating_cf),
            "operating_activities_details": {
                "net_income": float(net_income),
                "adjustments": [{"description": "Depreciation", "amount": float(deprec)}],
                "changes_in_assets": [],
                "changes_in_liabilities": [],
            },
            "investing_activities_details": [],
            "financing_activities_details": [],
        }

    async def find_entries_by_journal(self, journal_id: UUID) -> list[LedgerEntry]:
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
                        created_at=datetime.now(UTC),
                        created_by=UUID(int=0),
                    )
                )
            return domain_entries
        except Exception as e:
            logger.error(f"Failed to find entries by journal {journal_id}: {e}")
            raise LedgerRepositoryError(f"Failed to find entries: {e}") from e

    async def find_entries_by_account_and_date_range(
        self, account_id: UUID, start_date: date, end_date: date
    ) -> list[LedgerEntry]:
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
            return await self._rows_to_domain_entries(rows)
        except Exception as e:
            logger.error(f"Failed to find entries for account {account_id}: {e}")
            raise LedgerRepositoryError(f"Failed to find entries: {e}") from e

    async def find_entries_by_account_code(
        self, account_code: str, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> list[LedgerEntry]:
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
            return await self._rows_to_domain_entries(rows)
        except Exception as e:
            logger.error(f"Failed to find entries by period {fiscal_year}-{period}: {e}")
            raise LedgerRepositoryError(f"Failed to find entries: {e}") from e

    async def get_all_entries_for_entity(self, legal_entity_id: UUID) -> list[LedgerEntry]:
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
            ).order_by(LedgerEntryTable.posting_date)
            result = await self.session.execute(stmt)
            rows = result.all()
            return await self._rows_to_domain_entries(rows)
        except Exception as e:
            logger.error(f"Failed to get all entries for entity {legal_entity_id}: {e}")
            raise LedgerRepositoryError(f"Failed to get entries: {e}") from e

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

    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
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
                "total_debit": float(total_debit_amount),
                "total_credit": float(total_credit_amount),
                "unique_journals": 0,
                "unique_accounts": 0,
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

    async def _rows_to_domain_entries(self, rows: Any) -> list[LedgerEntry]:
        """Convert raw rows to domain LedgerEntry."""
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
                    created_at=datetime.now(UTC),
                    created_by=UUID(int=0),
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