#!/usr/bin/env python3
"""
SQLAlchemy implementation of BalanceSheetRepositoryPort.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ports.primary.report_repository_port import (
    BalanceSheetDataDTO,
    BalanceSheetLineDTO,
    BalanceSheetRepositoryPort,
)

logger = logging.getLogger(__name__)


class SQLAlchemyBalanceSheetRepository(BalanceSheetRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def get_balance_sheet(
        self, legal_entity_id: UUID, as_of_date: date, currency_code: str = "IDR"
    ) -> BalanceSheetDataDTO:
        session = await self._get_session()
        # Query from ledger accounts: ASSET, LIABILITY, EQUITY
        sql = text("""
            WITH account_balances AS (
                SELECT
                    la.account_code,
                    la.account_name,
                    la.account_type,
                    SUM(CASE WHEN le.entry_type = 'DEBIT' THEN le.amount ELSE -le.amount END) AS balance
                FROM ledger_accounts la
                LEFT JOIN ledger_entries le ON la.id = le.account_id
                    AND le.legal_entity_id = :legal_entity_id
                    AND le.entry_date <= :as_of_date
                    AND le.currency_code = :currency_code
                WHERE la.legal_entity_id = :legal_entity_id
                    AND la.deleted_at IS NULL
                    AND la.account_type IN ('ASSET', 'LIABILITY', 'EQUITY')
                GROUP BY la.id, la.account_code, la.account_name, la.account_type
            )
            SELECT
                account_code,
                account_name,
                account_type,
                balance
            FROM account_balances
            ORDER BY
                CASE account_type
                    WHEN 'ASSET' THEN 1
                    WHEN 'LIABILITY' THEN 2
                    WHEN 'EQUITY' THEN 3
                END,
                account_code
        """)

        result = await session.execute(
            sql,
            {
                "legal_entity_id": legal_entity_id,
                "as_of_date": as_of_date,
                "currency_code": currency_code,
            }
        )
        rows = result.fetchall()

        total_assets = Decimal(0)
        total_liabilities = Decimal(0)
        total_equity = Decimal(0)
        lines = []

        for row in rows:
            account_code, account_name, account_type, balance = row
            balance = Decimal(str(balance or 0))
            lines.append(
                BalanceSheetLineDTO(
                    account_code=account_code,
                    account_name=account_name,
                    account_type=account_type,
                    amount=balance,
                )
            )
            if account_type == "ASSET":
                total_assets += balance
            elif account_type == "LIABILITY":
                total_liabilities += balance
            elif account_type == "EQUITY":
                total_equity += balance

        return BalanceSheetDataDTO(
            as_of_date=as_of_date,
            currency_code=currency_code,
            total_assets=total_assets,
            total_liabilities=total_liabilities,
            total_equity=total_equity,
            assets_lines=[l for l in lines if l.account_type == "ASSET"],
            liabilities_lines=[l for l in lines if l.account_type == "LIABILITY"],
            equity_lines=[l for l in lines if l.account_type == "EQUITY"],
        )
