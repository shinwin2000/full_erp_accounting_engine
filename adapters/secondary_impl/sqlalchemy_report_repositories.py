#!/usr/bin/env python3
"""
Module: sqlalchemy_report_repositories.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi berbagai report repository dengan SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ports.primary.report_repository_port import (
    BalanceSheetDataDTO,
    BalanceSheetRepositoryPort,
    CashFlowDataDTO,
    CashFlowRepositoryPort,
    IncomeStatementDataDTO,
    IncomeStatementRepositoryPort,
    TrialBalanceRepositoryPort,
    TrialBalanceRowDTO,
)


class SQLAlchemyTrialBalanceRepository(TrialBalanceRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def get_trial_balance(
        self,
        legal_entity_id: uuid.UUID,
        as_of_date: date,
        account_type_filter: list[str] | None = None,
        cost_center_id: uuid.UUID | None = None,
        include_zero_balance: bool = False,
        currency_code: str = "IDR",
    ) -> list[TrialBalanceRowDTO]:
        session = await self._get_session()
        # Asumsikan ada tabel accounts dan journal_entries
        # Query: sum(debit) - sum(credit) per account sampai as_of_date
        # Karena tidak tahu skema pasti, saya berikan query template.
        # Anda perlu sesuaikan dengan skema yang sebenarnya.

        # Contoh query menggunakan raw SQL (aman):
        query = text("""
            SELECT
                a.account_code,
                a.account_name,
                a.account_type,
                COALESCE(SUM(j.debit), 0) AS total_debit,
                COALESCE(SUM(j.credit), 0) AS total_credit,
                COALESCE(SUM(j.debit) - SUM(j.credit), 0) AS balance
            FROM accounts a
            LEFT JOIN journal_entries j ON j.account_id = a.id
                AND j.entry_date <= :as_of_date
                AND j.legal_entity_id = :legal_entity_id
            WHERE a.legal_entity_id = :legal_entity_id
                AND a.is_active = true
            GROUP BY a.id
            HAVING (COALESCE(SUM(j.debit) - SUM(j.credit), 0) != 0 OR :include_zero = true)
            ORDER BY a.account_code
        """)
        result = await session.execute(
            query,
            {
                "legal_entity_id": legal_entity_id,
                "as_of_date": as_of_date,
                "include_zero": include_zero_balance,
            }
        )
        rows = result.fetchall()
        return [
            TrialBalanceRowDTO(
                account_code=row[0],
                account_name=row[1],
                account_type=row[2],
                total_debit=Decimal(str(row[3] or 0)),
                total_credit=Decimal(str(row[4] or 0)),
                balance=Decimal(str(row[5] or 0)),
            )
            for row in rows
        ]


class SQLAlchemyIncomeStatementRepository(IncomeStatementRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def get_income_statement(
        self,
        legal_entity_id: uuid.UUID,
        period_start: date,
        period_end: date,
        show_percent_of_revenue: bool = False,
        currency_code: str = "IDR",
    ) -> IncomeStatementDataDTO:
        session = await self._get_session()
        # Query pendapatan dan beban berdasarkan tipe akun
        query = text("""
            SELECT
                a.account_type,
                SUM(j.debit) AS total_debit,
                SUM(j.credit) AS total_credit
            FROM accounts a
            JOIN journal_entries j ON j.account_id = a.id
            WHERE a.legal_entity_id = :legal_entity_id
                AND j.entry_date BETWEEN :start_date AND :end_date
                AND a.account_type IN ('REVENUE', 'EXPENSE')
            GROUP BY a.account_type
        """)
        result = await session.execute(query, {
            "legal_entity_id": legal_entity_id,
            "start_date": period_start,
            "end_date": period_end,
        })
        rows = result.fetchall()
        revenue = Decimal(0)
        expenses = Decimal(0)
        for row in rows:
            if row[0] == "REVENUE":
                revenue = Decimal(str(row[2] or 0))  # credit
            elif row[0] == "EXPENSE":
                expenses = Decimal(str(row[1] or 0))  # debit

        net_income = revenue - expenses
        return IncomeStatementDataDTO(
            period_start=period_start,
            period_end=period_end,
            revenue=revenue,
            expenses=expenses,
            net_income=net_income,
            details=[],  # bisa tambahkan detail per account jika diperlukan
        )


class SQLAlchemyBalanceSheetRepository(BalanceSheetRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def get_balance_sheet(
        self,
        legal_entity_id: uuid.UUID,
        as_of_date: date,
        currency_code: str = "IDR",
    ) -> BalanceSheetDataDTO:
        session = await self._get_session()
        # Query aset, kewajiban, ekuitas
        query = text("""
            SELECT
                a.account_type,
                SUM(j.debit) - SUM(j.credit) AS balance
            FROM accounts a
            JOIN journal_entries j ON j.account_id = a.id
            WHERE a.legal_entity_id = :legal_entity_id
                AND j.entry_date <= :as_of_date
                AND a.account_type IN ('ASSET', 'LIABILITY', 'EQUITY')
            GROUP BY a.account_type
        """)
        result = await session.execute(query, {
            "legal_entity_id": legal_entity_id,
            "as_of_date": as_of_date,
        })
        rows = result.fetchall()
        assets = Decimal(0)
        liabilities = Decimal(0)
        equity = Decimal(0)
        for row in rows:
            if row[0] == "ASSET":
                assets = Decimal(str(row[1] or 0))
            elif row[0] == "LIABILITY":
                liabilities = Decimal(str(row[1] or 0))
            elif row[0] == "EQUITY":
                equity = Decimal(str(row[1] or 0))

        return BalanceSheetDataDTO(
            as_of_date=as_of_date,
            total_assets=assets,
            total_liabilities=liabilities,
            total_equity=equity,
            assets_detail=[],
            liabilities_detail=[],
            equity_detail=[],
        )


class SQLAlchemyCashFlowRepository(CashFlowRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def get_cash_flow(
        self,
        legal_entity_id: uuid.UUID,
        period_start: date,
        period_end: date,
        method: str = "INDIRECT",
        currency_code: str = "IDR",
    ) -> CashFlowDataDTO:
        session = await self._get_session()
        # Untuk indirect method, kita butuh net income, perubahan aset/liabilitas
        # Saya buat sederhana: ambil perubahan kas dari journal entries
        query = text("""
            SELECT
                COALESCE(SUM(j.debit - j.credit), 0) AS net_cash_flow
            FROM journal_entries j
            JOIN accounts a ON a.id = j.account_id
            WHERE a.legal_entity_id = :legal_entity_id
                AND j.entry_date BETWEEN :start_date AND :end_date
                AND a.account_type = 'ASSET'
                AND a.is_cash_account = true
        """)
        result = await session.execute(query, {
            "legal_entity_id": legal_entity_id,
            "start_date": period_start,
            "end_date": period_end,
        })
        row = result.fetchone()
        net_cash = Decimal(str(row[0] or 0))

        # Dummy breakdown
        return CashFlowDataDTO(
            period_start=period_start,
            period_end=period_end,
            net_cash_from_operating=net_cash,
            net_cash_from_investing=Decimal(0),
            net_cash_from_financing=Decimal(0),
            net_cash_increase=net_cash,
            cash_beginning=Decimal(0),
            cash_ending=net_cash,
            details=[],
        )


__all__ = [
    "SQLAlchemyBalanceSheetRepository",
    "SQLAlchemyCashFlowRepository",
    "SQLAlchemyIncomeStatementRepository",
    "SQLAlchemyTrialBalanceRepository",
]
