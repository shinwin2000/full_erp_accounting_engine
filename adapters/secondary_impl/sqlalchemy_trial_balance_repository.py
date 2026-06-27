#!/usr/bin/env python3
"""
SQLAlchemy implementation of TrialBalanceRepositoryPort.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ports.primary.report_repository_port import TrialBalanceRepositoryPort, TrialBalanceRowDTO

logger = logging.getLogger(__name__)


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
        legal_entity_id: UUID,
        as_of_date: date,
        account_type_filter: list[str] | None = None,
        cost_center_id: UUID | None = None,
        include_zero_balance: bool = False,
        currency_code: str = "IDR",
    ) -> list[TrialBalanceRowDTO]:
        session = await self._get_session()
        # Query from ledger_accounts and ledger_entries
        # Asumsi: ada tabel ledger_accounts (account_code, account_name, account_type, normal_balance)
        # dan ledger_entries (account_id, amount, entry_date, legal_entity_id, currency_code, cost_center_id)
        # Untuk trial balance, kita sum debit - credit per account.
        # Karena tidak ada model pasti, kita gunakan raw SQL atau query dengan model yang sudah ada.
        # Saya asumsikan ada tabel 'ledger_accounts' dan 'ledger_entries' dengan kolom-kolom tersebut.
        # Jika tidak, sesuaikan dengan skema yang sebenarnya.

        # Query menggunakan SQLAlchemy Core (text) agar fleksibel
        sql = text("""
            WITH account_balances AS (
                SELECT
                    la.id AS account_id,
                    la.account_code,
                    la.account_name,
                    la.account_type,
                    la.normal_balance,
                    COALESCE(SUM(
                        CASE
                            WHEN le.entry_type = 'DEBIT' THEN le.amount
                            ELSE 0
                        END
                    ), 0) AS total_debit,
                    COALESCE(SUM(
                        CASE
                            WHEN le.entry_type = 'CREDIT' THEN le.amount
                            ELSE 0
                        END
                    ), 0) AS total_credit
                FROM ledger_accounts la
                LEFT JOIN ledger_entries le ON la.id = le.account_id
                    AND le.legal_entity_id = :legal_entity_id
                    AND le.entry_date <= :as_of_date
                    AND le.currency_code = :currency_code
                    AND (:cost_center_id IS NULL OR le.cost_center_id = :cost_center_id)
                WHERE la.legal_entity_id = :legal_entity_id
                    AND la.deleted_at IS NULL
                    AND (:account_type_filter IS NULL OR la.account_type = ANY(:account_type_filter))
                GROUP BY la.id, la.account_code, la.account_name, la.account_type, la.normal_balance
            )
            SELECT
                account_code,
                account_name,
                account_type,
                normal_balance,
                total_debit - total_credit AS balance,
                total_debit,
                total_credit
            FROM account_balances
            WHERE include_zero_balance = TRUE OR (total_debit - total_credit) != 0
            ORDER BY account_code
        """)

        result = await session.execute(
            sql,
            {
                "legal_entity_id": legal_entity_id,
                "as_of_date": as_of_date,
                "currency_code": currency_code,
                "cost_center_id": cost_center_id,
                "account_type_filter": account_type_filter,
                "include_zero_balance": include_zero_balance,
            }
        )
        rows = result.fetchall()
        return [
            TrialBalanceRowDTO(
                account_code=row[0],
                account_name=row[1],
                account_type=row[2],
                normal_balance=row[3],
                balance=Decimal(str(row[4] or 0)),
                debit=Decimal(str(row[5] or 0)),
                credit=Decimal(str(row[6] or 0)),
            )
            for row in rows
        ]
