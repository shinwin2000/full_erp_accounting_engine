#!/usr/bin/env python3
"""
Module: sqlalchemy_ledger_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository Ledger dengan SQLAlchemy.

Catatan revisi:
- get_balance_sheet() sekarang mengisi ``balance_previous`` per baris bila
  compare_with_previous=True (default: saldo per 31 Des tahun sebelumnya).
- Ditambahkan method opsional untuk arus kas 3 sektor:
  get_working_capital_changes, get_investing_activities, get_financing_activities.
  Klasifikasi memakai kolom AccountTable.cashflow_type bila ada; kalau kolom
  belum tersedia di skema, method akan mengembalikan list kosong (aman).
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
        """Neraca dengan opsi pembanding periode lalu.

        Bila compare_with_previous=True, setiap line diberi field
        ``balance_previous`` (saldo per 31 Desember tahun sebelumnya, yaitu hari
        terakhir sebelum awal tahun berjalan tempat as_of_date berada).
        """
        tb = await self.get_trial_balance(legal_entity_id, as_of_date, include_zero_balance=False)

        acc_stmt = select(
            AccountTable.account_code,
            AccountTable.account_type,
        ).where(
            AccountTable.legal_entity_id == legal_entity_id,
            AccountTable.is_active == True,
        )
        acc_result = await self.session.execute(acc_stmt)
        account_type_map = {row.account_code: row.account_type for row in acc_result.all()}

        # Ambil saldo pembanding (akhir tahun sebelumnya) bila diminta.
        prev_balance_map: dict[str, Decimal] = {}
        if compare_with_previous:
            prev_as_of = date(as_of_date.year - 1, 12, 31)
            tb_prev = await self.get_trial_balance(
                legal_entity_id, prev_as_of, include_zero_balance=False
            )
            for row in tb_prev:
                bal = row.debit_balance if row.debit_balance > 0 else row.credit_balance
                prev_balance_map[row.account_code] = bal

        assets: list[dict[str, Any]] = []
        liabilities: list[dict[str, Any]] = []
        equity: list[dict[str, Any]] = []
        total_assets = Decimal(0)
        total_liabilities = Decimal(0)
        total_equity = Decimal(0)
        total_assets_prev = Decimal(0)
        total_liabilities_prev = Decimal(0)
        total_equity_prev = Decimal(0)

        for row in tb:
            acc_type = account_type_map.get(row.account_code)
            if not acc_type:
                continue
            balance = row.debit_balance if row.debit_balance > 0 else row.credit_balance
            prev_balance = prev_balance_map.get(row.account_code, Decimal(0))
            item = {
                "account_code": row.account_code,
                "account_name": row.account_name,
                "balance": str(balance),
                "balance_previous": str(prev_balance),
            }
            if acc_type in ["Asset", "ContraAsset"]:
                assets.append(item)
                total_assets += balance
                total_assets_prev += prev_balance
            elif acc_type in ["Liability", "ContraLiability"]:
                liabilities.append(item)
                total_liabilities += balance
                total_liabilities_prev += prev_balance
            elif acc_type in ["Equity", "ContraEquity"]:
                equity.append(item)
                total_equity += balance
                total_equity_prev += prev_balance

        return {
            "as_of_date": as_of_date.isoformat(),
            "total_assets": str(total_assets),
            "total_liabilities": str(total_liabilities),
            "total_equity": str(total_equity),
            "liabilities_and_equity": str(total_liabilities + total_equity),
            "asset_details": assets,
            "liability_details": liabilities,
            "equity_details": equity,
            "total_assets_previous": str(total_assets_prev),
            "total_liabilities_previous": str(total_liabilities_prev),
            "total_equity_previous": str(total_equity_prev),
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
    # CASH FLOW 3-SECTOR HELPERS (opsional, best-effort)
    # ========================================================================
    #
    # Klasifikasi memakai AccountTable.cashflow_type bila kolom tsb tersedia.
    # Nilai yang diharapkan: 'operating' | 'investing' | 'financing' | ''.
    # Bila kolom tidak ada, method akan mengembalikan list kosong (aman).

    async def get_working_capital_changes(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        """Perubahan modal kerja untuk arus kas metode tidak langsung:
        piutang, persediaan, utang usaha, dll. Dihitung dari selisih saldo
        awal vs akhir periode. Best-effort, kembalikan [] bila kolom tidak ada.
        """
        try:
            # Ambil saldo awal (hari sebelum start_date) & akhir.
            opening_tb = await self.get_trial_balance(
                legal_entity_id, start_date - timedelta(days=1), include_zero_balance=True
            )
            closing_tb = await self.get_trial_balance(
                legal_entity_id, end_date, include_zero_balance=True
            )
            opening_map = {r.account_code: (r.debit_balance - r.credit_balance) for r in opening_tb}

            changes: list[dict[str, Any]] = []
            for row in closing_tb:
                code = row.account_code
                if not (code.startswith("11") or code.startswith("12") or code.startswith("21")):
                    continue  # hanya aset lancar & kewajiban jangka pendek
                closing = row.debit_balance - row.credit_balance
                opening = opening_map.get(code, Decimal(0))
                delta = closing - opening
                if delta == 0:
                    continue
                # Aset naik = pemakaian kas (negatif); Kewajiban naik = sumber kas.
                sign = Decimal(-1) if code.startswith("11") or code.startswith("12") else Decimal(1)
                changes.append({
                    "description": f"Perubahan {row.account_name}",
                    "amount": sign * delta,
                })
            return changes
        except Exception as e:
            logger.warning(f"get_working_capital_changes failed: {e}")
            return []

    async def get_investing_activities(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        """Arus kas dari aktivitas investasi. Bila COA punya kolom
        ``cashflow_type='investing'``, pakai itu; kalau tidak, kembalikan []."""
        return await self._cashflow_by_type(legal_entity_id, start_date, end_date, "investing")

    async def get_financing_activities(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        """Arus kas dari aktivitas pendanaan."""
        return await self._cashflow_by_type(legal_entity_id, start_date, end_date, "financing")

    async def _cashflow_by_type(
        self, legal_entity_id: UUID, start_date: date, end_date: date, flow_type: str
    ) -> list[dict[str, Any]]:
        """Helper: agregat per akun untuk cashflow_type tertentu."""
        try:
            has_col = hasattr(AccountTable, "cashflow_type")
            if not has_col:
                return []
            stmt = (
                select(
                    AccountTable.account_code,
                    AccountTable.account_name,
                    func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("d"),
                    func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0).label("c"),
                )
                .join(LedgerEntryTable, AccountTable.id == LedgerEntryTable.account_id)
                .where(
                    AccountTable.legal_entity_id == legal_entity_id,
                    AccountTable.cashflow_type == flow_type,
                    LedgerEntryTable.posting_date >= start_date,
                    LedgerEntryTable.posting_date <= end_date,
                )
                .group_by(AccountTable.account_code, AccountTable.account_name)
            )
            result = await self.session.execute(stmt)
            out: list[dict[str, Any]] = []
            for row in result.all():
                net = Decimal(str(row.c)) - Decimal(str(row.d))
                if net == 0:
                    continue
                out.append({
                    "description": row.account_name,
                    "amount": net,
                })
            return out
        except Exception as e:
            logger.warning(f"_cashflow_by_type({flow_type}) failed: {e}")
            return []

    # ========================================================================
    # ACCOUNT BALANCE SUMMARY
    # ========================================================================

    async def get_account_balance_summary(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> list[AccountBalance]:
        try:
            tb = await self.get_trial_balance(legal_entity_id, as_of_date, include_zero_balance=False)

            acc_stmt = select(
                AccountTable.account_code,
                AccountTable.id,
                AccountTable.account_type,
                AccountTable.normal_balance,
            ).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.is_active == True,
            )
            acc_result = await self.session.execute(acc_stmt)
            account_info_map = {}
            for row in acc_result.all():
                account_info_map[row.account_code] = (row.id, row.account_type, row.normal_balance)

            result = []
            for row in tb:
                acc_info = account_info_map.get(row.account_code)
                if not acc_info:
                    continue
                acc_id, acc_type, normal_balance = acc_info
                balance = row.debit_balance if row.debit_balance > 0 else row.credit_balance
                result.append(
                    AccountBalance(
                        account_id=acc_id,
                        account_code=row.account_code,
                        account_name=row.account_name,
                        account_type=AccountType(acc_type.lower()),
                        normal_balance=NormalBalance(normal_balance),
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
    # DETAILED TRIAL BALANCE
    # ========================================================================

    async def get_trial_balance_detailed(
        self, legal_entity_id: UUID, as_of_date: date, include_zero_balance: bool = False
    ) -> list[dict[str, Any]]:
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

            lines: list[dict[str, Any]] = []
            for row in rows:
                opening_debit = Decimal(str(row.opening_balance_debit or 0))
                opening_credit = Decimal(str(row.opening_balance_credit or 0))
                movement_debit = Decimal(str(row.movement_debit or 0))
                movement_credit = Decimal(str(row.movement_credit or 0))
                normal = row.normal_balance
                if normal == "debit":
                    closing_debit = opening_debit + movement_debit - movement_credit
                    closing_credit = Decimal(0)
                    if closing_debit < 0:
                        closing_credit, closing_debit = -closing_debit, Decimal(0)
                else:
                    closing_credit = opening_credit + movement_credit - movement_debit
                    closing_debit = Decimal(0)
                    if closing_credit < 0:
                        closing_debit, closing_credit = -closing_credit, Decimal(0)

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
            return lines
        except Exception as e:
            logger.error(f"Failed to get detailed trial balance: {e}")
            raise LedgerRepositoryError(f"Failed to get trial balance: {e}") from e

    # ========================================================================
    # NET INCOME / CASH BALANCE HELPERS
    # ========================================================================

    async def get_income_expense_breakdown(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        try:
            stmt = (
                select(
                    AccountTable.id.label("account_id"),
                    AccountTable.account_code,
                    AccountTable.account_name,
                    AccountTable.account_type,
                    func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("total_debit"),
                    func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0).label("total_credit"),
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
                .order_by(AccountTable.account_code)
            )
            result = await self.session.execute(stmt)
            rows = []
            for row in result.all():
                total_debit = Decimal(str(row.total_debit))
                total_credit = Decimal(str(row.total_credit))
                amount = (
                    total_credit - total_debit
                    if row.account_type == "Revenue"
                    else total_debit - total_credit
                )
                if amount == 0:
                    continue
                rows.append(
                    {
                        "account_id": row.account_id,
                        "account_code": row.account_code,
                        "account_name": row.account_name,
                        "account_type": row.account_type,
                        "amount": amount,
                    }
                )
            return rows
        except Exception as e:
            logger.error(f"Failed to get income/expense breakdown: {e}")
            raise LedgerRepositoryError(f"Failed to get income/expense breakdown: {e}") from e

    async def get_net_income_for_range(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> tuple[Decimal, Decimal, Decimal]:
        try:
            stmt = (
                select(
                    AccountTable.account_type,
                    func.coalesce(func.sum(LedgerEntryTable.debit_amount), 0).label("total_debit"),
                    func.coalesce(func.sum(LedgerEntryTable.credit_amount), 0).label("total_credit"),
                )
                .join(LedgerEntryTable, AccountTable.id == LedgerEntryTable.account_id)
                .where(
                    AccountTable.legal_entity_id == legal_entity_id,
                    AccountTable.account_type.in_(["Revenue", "Expense"]),
                    LedgerEntryTable.posting_date >= start_date,
                    LedgerEntryTable.posting_date <= end_date,
                )
                .group_by(AccountTable.account_type)
            )
            result = await self.session.execute(stmt)
            total_revenue = Decimal(0)
            total_expense = Decimal(0)
            for row in result.all():
                total_debit = Decimal(str(row.total_debit))
                total_credit = Decimal(str(row.total_credit))
                if row.account_type == "Revenue":
                    total_revenue += total_credit - total_debit
                else:
                    total_expense += total_debit - total_credit
            return total_revenue, total_expense, total_revenue - total_expense
        except Exception as e:
            logger.error(f"Failed to compute net income for range: {e}")
            raise LedgerRepositoryError(f"Failed to compute net income: {e}") from e

    async def get_cash_balance(self, legal_entity_id: UUID, as_of_date: date) -> Decimal:
        try:
            stmt = select(AccountTable.id).where(
                AccountTable.legal_entity_id == legal_entity_id,
                AccountTable.is_cash_account == True,
                AccountTable.is_active == True,
            )
            result = await self.session.execute(stmt)
            account_ids = [row.id for row in result.all()]
            total = Decimal(0)
            for account_id in account_ids:
                total += await self.get_account_balance(account_id, as_of_date)
            return total
        except Exception as e:
            logger.error(f"Failed to get cash balance: {e}")
            raise LedgerRepositoryError(f"Failed to get cash balance: {e}") from e

    # ========================================================================
    # LEDGER ENTRIES - DETAILED
    # ========================================================================

    async def get_ledger_entries_detailed(
        self,
        legal_entity_id: UUID,
        start_date: date,
        end_date: date,
        account_id: UUID | None = None,
        journal_id: UUID | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> tuple[list[dict[str, Any]], int]:
        from infrastructure.persistence_orm.journal_header_table import JournalHeaderTable

        try:
            base_filters = [
                LedgerEntryTable.legal_entity_id == legal_entity_id,
                LedgerEntryTable.posting_date >= start_date,
                LedgerEntryTable.posting_date <= end_date,
            ]
            if account_id is not None:
                base_filters.append(LedgerEntryTable.account_id == account_id)
            if journal_id is not None:
                base_filters.append(LedgerEntryTable.journal_id == journal_id)

            count_stmt = select(func.count()).select_from(LedgerEntryTable).where(*base_filters)
            total_count = (await self.session.execute(count_stmt)).scalar() or 0

            stmt = (
                select(
                    LedgerEntryTable.id,
                    LedgerEntryTable.journal_id,
                    LedgerEntryTable.account_id,
                    LedgerEntryTable.account_code,
                    LedgerEntryTable.debit_amount,
                    LedgerEntryTable.credit_amount,
                    LedgerEntryTable.posting_date,
                    LedgerEntryTable.description,
                    LedgerEntryTable.reference_number,
                    LedgerEntryTable.cost_center,
                    LedgerEntryTable.department,
                    LedgerEntryTable.created_at,
                    AccountTable.account_name,
                    JournalHeaderTable.voucher_number,
                    JournalHeaderTable.journal_date,
                    JournalHeaderTable.journal_type,
                    JournalHeaderTable.posted_by,
                    JournalHeaderTable.created_by,
                )
                .join(AccountTable, AccountTable.id == LedgerEntryTable.account_id)
                .join(JournalHeaderTable, JournalHeaderTable.id == LedgerEntryTable.journal_id)
                .where(*base_filters)
                .order_by(LedgerEntryTable.posting_date, LedgerEntryTable.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            result = await self.session.execute(stmt)
            rows = result.all()

            valid_entry_types = {"journal", "adjustment", "closing", "reversal"}
            entries = [
                {
                    "id": row.id,
                    "journal_id": row.journal_id,
                    "journal_number": row.voucher_number,
                    "journal_date": row.journal_date,
                    "account_id": row.account_id,
                    "account_code": row.account_code,
                    "account_name": row.account_name,
                    "debit_amount": row.debit_amount,
                    "credit_amount": row.credit_amount,
                    "posting_date": row.posting_date,
                    "description": row.description or "",
                    "reference_number": row.reference_number,
                    "cost_center": row.cost_center,
                    "department": row.department,
                    "project_id": None,
                    "entry_type": row.journal_type if row.journal_type in valid_entry_types else "journal",
                    "created_at": row.created_at,
                    "posted_by": row.posted_by or row.created_by or UUID(int=0),
                }
                for row in rows
            ]
            return entries, total_count
        except Exception as e:
            logger.error(f"Failed to get detailed ledger entries: {e}")
            raise LedgerRepositoryError(f"Failed to get ledger entries: {e}") from e

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
        if not rows:
            return []

        account_ids = list({row.account_id for row in rows})
        stmt = select(
            AccountTable.id,
            AccountTable.account_name,
            AccountTable.account_type,
            AccountTable.normal_balance,
        ).where(AccountTable.id.in_(account_ids))
        result = await self.session.execute(stmt)
        acc_rows = result.all()
        account_map = {}
        for acc in acc_rows:
            account_map[acc.id] = (acc.account_name, acc.account_type, acc.normal_balance)

        domain_entries = []
        for row in rows:
            acc_info = account_map.get(row.account_id)
            account_name = acc_info[0] if acc_info else ""
            account_type_str = acc_info[1] if acc_info else "Asset"
            normal_balance_str = acc_info[2] if acc_info else "debit"
            domain_entries.append(
                LedgerEntry(
                    id=row.id,
                    journal_id=row.journal_id,
                    journal_line_id=row.id,
                    account_id=row.account_id,
                    account_code=row.account_code,
                    account_name=account_name,
                    account_type=AccountType(account_type_str.lower()),
                    normal_balance=NormalBalance(normal_balance_str),
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
