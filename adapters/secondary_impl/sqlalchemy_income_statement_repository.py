#!/usr/bin/env python3
"""
SQLAlchemy implementation of IncomeStatementRepositoryPort.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ports.primary.report_repository_port import (
    IncomeStatementDataDTO,
    IncomeStatementLineDTO,
    IncomeStatementRepositoryPort,
)

logger = logging.getLogger(__name__)


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
        legal_entity_id: UUID,
        period_start: date,
        period_end: date,
        show_percent_of_revenue: bool = False,
        currency_code: str = "IDR",
    ) -> IncomeStatementDataDTO:
        session = await self._get_session()
        # Query income statement from ledger accounts (Revenue, Cost of Goods Sold, Expenses)
        # Asumsi: account_type in ('REVENUE', 'COGS', 'EXPENSE', 'OTHER_INCOME', 'OTHER_EXPENSE')
        sql = text("""
            WITH account_totals AS (
                SELECT
                    la.account_code,
                    la.account_name,
                    la.account_type,
                    SUM(CASE WHEN le.entry_type = 'CREDIT' THEN le.amount ELSE -le.amount END) AS balance
                FROM ledger_accounts la
                JOIN ledger_entries le ON la.id = le.account_id
                WHERE la.legal_entity_id = :legal_entity_id
                    AND le.legal_entity_id = :legal_entity_id
                    AND le.entry_date BETWEEN :period_start AND :period_end
                    AND le.currency_code = :currency_code
                    AND la.account_type IN ('REVENUE', 'COGS', 'EXPENSE', 'OTHER_INCOME', 'OTHER_EXPENSE')
                    AND la.deleted_at IS NULL
                GROUP BY la.id, la.account_code, la.account_name, la.account_type
            )
            SELECT
                account_code,
                account_name,
                account_type,
                balance
            FROM account_totals
            ORDER BY
                CASE account_type
                    WHEN 'REVENUE' THEN 1
                    WHEN 'OTHER_INCOME' THEN 2
                    WHEN 'COGS' THEN 3
                    WHEN 'EXPENSE' THEN 4
                    WHEN 'OTHER_EXPENSE' THEN 5
                END,
                account_code
        """)

        result = await session.execute(
            sql,
            {
                "legal_entity_id": legal_entity_id,
                "period_start": period_start,
                "period_end": period_end,
                "currency_code": currency_code,
            }
        )
        rows = result.fetchall()

        revenue = Decimal(0)
        cogs = Decimal(0)
        expenses = Decimal(0)
        other_income = Decimal(0)
        other_expense = Decimal(0)

        lines = []
        for row in rows:
            account_code, account_name, account_type, balance = row
            balance = Decimal(str(balance or 0))
            lines.append(
                IncomeStatementLineDTO(
                    account_code=account_code,
                    account_name=account_name,
                    account_type=account_type,
                    amount=balance,
                )
            )
            if account_type == "REVENUE":
                revenue += balance
            elif account_type == "COGS":
                cogs += balance
            elif account_type == "EXPENSE":
                expenses += balance
            elif account_type == "OTHER_INCOME":
                other_income += balance
            elif account_type == "OTHER_EXPENSE":
                other_expense += balance

        gross_profit = revenue - cogs
        operating_income = gross_profit - expenses
        total_other = other_income - other_expense
        net_income = operating_income + total_other

        return IncomeStatementDataDTO(
            period_start=period_start,
            period_end=period_end,
            currency_code=currency_code,
            revenue=revenue,
            cogs=cogs,
            gross_profit=gross_profit,
            operating_expenses=expenses,
            operating_income=operating_income,
            other_income=other_income,
            other_expense=other_expense,
            net_income=net_income,
            lines=lines,
            percent_of_revenue=revenue if show_percent_of_revenue else None,
        )
