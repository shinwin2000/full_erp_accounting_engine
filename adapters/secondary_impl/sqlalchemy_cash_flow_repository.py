#!/usr/bin/env python3
"""
SQLAlchemy implementation of CashFlowRepositoryPort.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ports.primary.report_repository_port import (
    CashFlowDataDTO,
    CashFlowLineDTO,
    CashFlowRepositoryPort,
)

logger = logging.getLogger(__name__)


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
        legal_entity_id: UUID,
        period_start: date,
        period_end: date,
        method: str = "INDIRECT",
        currency_code: str = "IDR",
    ) -> CashFlowDataDTO:
        session = await self._get_session()
        # Method INDIRECT: start with net income, adjust for non-cash items, changes in working capital
        # Method DIRECT: sum cash receipts and payments.
        # For simplicity, we implement INDIRECT method using income statement and balance sheet changes.
        if method.upper() == "INDIRECT":
            return await self._get_indirect_cash_flow(
                session, legal_entity_id, period_start, period_end, currency_code
            )
        else:
            return await self._get_direct_cash_flow(
                session, legal_entity_id, period_start, period_end, currency_code
            )

    async def _get_indirect_cash_flow(
        self, session: AsyncSession, legal_entity_id: UUID, start: date, end: date, currency: str
    ) -> CashFlowDataDTO:
        # Query net income
        net_income_sql = text("""
            SELECT COALESCE(SUM(CASE WHEN le.entry_type = 'CREDIT' THEN le.amount ELSE -le.amount END), 0)
            FROM ledger_entries le
            JOIN ledger_accounts la ON le.account_id = la.id
            WHERE le.legal_entity_id = :legal_entity_id
                AND le.entry_date BETWEEN :start AND :end
                AND le.currency_code = :currency
                AND la.account_type IN ('REVENUE', 'OTHER_INCOME', 'EXPENSE', 'COGS', 'OTHER_EXPENSE')
        """)
        net_income = await session.scalar(net_income_sql, {"legal_entity_id": legal_entity_id, "start": start, "end": end, "currency": currency}) or 0

        # Adjust for non-cash items (depreciation, amortization)
        # Asumsi: ada tabel fixed_assets atau depreciation entries
        # Query depreciation expense dari expense accounts
        dep_sql = text("""
            SELECT COALESCE(SUM(le.amount), 0)
            FROM ledger_entries le
            JOIN ledger_accounts la ON le.account_id = la.id
            WHERE le.legal_entity_id = :legal_entity_id
                AND le.entry_date BETWEEN :start AND :end
                AND le.currency_code = :currency
                AND la.account_code LIKE '%DEPRECIATION%'
        """)
        depreciation = await session.scalar(dep_sql, {"legal_entity_id": legal_entity_id, "start": start, "end": end, "currency": currency}) or 0

        # Changes in working capital: AR, AP, Inventory
        # Query changes in AR, AP, Inventory from balance sheet at start and end
        changes_sql = text("""
            WITH balances AS (
                SELECT
                    la.account_type,
                    COALESCE(SUM(CASE WHEN le.entry_type = 'DEBIT' THEN le.amount ELSE -le.amount END), 0) AS balance
                FROM ledger_entries le
                JOIN ledger_accounts la ON le.account_id = la.id
                WHERE le.legal_entity_id = :legal_entity_id
                    AND le.entry_date <= :date
                    AND le.currency_code = :currency
                    AND la.account_type IN ('ASSET', 'LIABILITY')
                    AND la.account_code IN ('AR', 'AP', 'INVENTORY')
                GROUP BY la.account_type
            )
            SELECT account_type, balance FROM balances
        """)
        start_balances = await session.execute(changes_sql, {"legal_entity_id": legal_entity_id, "date": start, "currency": currency})
        end_balances = await session.execute(changes_sql, {"legal_entity_id": legal_entity_id, "date": end, "currency": currency})

        start_map = {row[0]: Decimal(str(row[1] or 0)) for row in start_balances}
        end_map = {row[0]: Decimal(str(row[1] or 0)) for row in end_balances}

        ar_change = end_map.get("AR", Decimal(0)) - start_map.get("AR", Decimal(0))
        ap_change = end_map.get("AP", Decimal(0)) - start_map.get("AP", Decimal(0))
        inv_change = end_map.get("INVENTORY", Decimal(0)) - start_map.get("INVENTORY", Decimal(0))

        # Operating cash flow = net income + depreciation - ar_change - inv_change + ap_change
        operating_cf = Decimal(str(net_income)) + Decimal(str(depreciation)) - ar_change - inv_change + ap_change

        # Investing and financing activities: simplified
        # For demo, we just return operating CF only
        return CashFlowDataDTO(
            period_start=start,
            period_end=end,
            currency_code=currency,
            operating_cash_flow=operating_cf,
            investing_cash_flow=Decimal(0),
            financing_cash_flow=Decimal(0),
            net_cash_flow=operating_cf,
            lines=[
                CashFlowLineDTO(category="Operating", amount=operating_cf),
            ],
        )

    async def _get_direct_cash_flow(
        self, session: AsyncSession, legal_entity_id: UUID, start: date, end: date, currency: str
    ) -> CashFlowDataDTO:
        # Direct method not implemented, fallback to indirect
        return await self._get_indirect_cash_flow(session, legal_entity_id, start, end, currency)
