#!/usr/bin/env python3
"""
Module: sqlalchemy_report_repositories.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi berbagai report repository dengan SQLAlchemy.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ports.primary.report_repository_port import (
    AgingReportRepositoryPort,
    BalanceSheetDataDTO,
    BalanceSheetRepositoryPort,
    CashFlowDataDTO,
    CashFlowRepositoryPort,
    IncomeStatementDataDTO,
    IncomeStatementRepositoryPort,
    ReportRepositoryPort,
    TrialBalanceRepositoryPort,
    TrialBalanceRowDTO,
)

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
        legal_entity_id: uuid.UUID,
        as_of_date: date,
        account_type_filter: list[str] | None = None,
        cost_center_id: uuid.UUID | None = None,
        include_zero_balance: bool = False,
        currency_code: str = "IDR",
    ) -> list[TrialBalanceRowDTO]:
        session = await self._get_session()
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
            details=[],
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


# ============================================================================
# ReportRepositoryPort + AgingReportRepositoryPort implementation
# ============================================================================

class SQLAlchemyReportRepository(ReportRepositoryPort, AgingReportRepositoryPort):
    """
    Implementasi gabungan untuk ReportRepositoryPort dan AgingReportRepositoryPort.
    Mendelegasikan ke repository spesifik atau menyediakan metode langsung.
    """
    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        self._trial_balance_repo = SQLAlchemyTrialBalanceRepository(session)
        self._income_statement_repo = SQLAlchemyIncomeStatementRepository(session)
        self._balance_sheet_repo = SQLAlchemyBalanceSheetRepository(session)
        self._cash_flow_repo = SQLAlchemyCashFlowRepository(session)

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
            # Update session di child repos
            self._trial_balance_repo._session = self._session
            self._income_statement_repo._session = self._session
            self._balance_sheet_repo._session = self._session
            self._cash_flow_repo._session = self._session
        return self._session

    # ---- ReportRepositoryPort methods ----

    async def get_trial_balance(
        self,
        legal_entity_id: uuid.UUID,
        as_of_date: date,
        account_type_filter: list[str] | None = None,
        cost_center_id: uuid.UUID | None = None,
        include_zero_balance: bool = False,
        currency_code: str = "IDR",
    ) -> list[TrialBalanceRowDTO]:
        await self._get_session()
        return await self._trial_balance_repo.get_trial_balance(
            legal_entity_id,
            as_of_date,
            account_type_filter,
            cost_center_id,
            include_zero_balance,
            currency_code,
        )

    async def get_income_statement(
        self,
        legal_entity_id: uuid.UUID,
        period_start: date,
        period_end: date,
        show_percent_of_revenue: bool = False,
        currency_code: str = "IDR",
    ) -> IncomeStatementDataDTO:
        await self._get_session()
        return await self._income_statement_repo.get_income_statement(
            legal_entity_id,
            period_start,
            period_end,
            show_percent_of_revenue,
            currency_code,
        )

    async def get_balance_sheet(
        self,
        legal_entity_id: uuid.UUID,
        as_of_date: date,
        currency_code: str = "IDR",
    ) -> BalanceSheetDataDTO:
        await self._get_session()
        return await self._balance_sheet_repo.get_balance_sheet(
            legal_entity_id,
            as_of_date,
            currency_code,
        )

    async def get_cash_flow(
        self,
        legal_entity_id: uuid.UUID,
        period_start: date,
        period_end: date,
        method: str = "INDIRECT",
        currency_code: str = "IDR",
    ) -> CashFlowDataDTO:
        await self._get_session()
        return await self._cash_flow_repo.get_cash_flow(
            legal_entity_id,
            period_start,
            period_end,
            method,
            currency_code,
        )

    # ---- AgingReportRepositoryPort methods ----

    async def get_ar_aging(
        self,
        legal_entity_id: uuid.UUID,
        as_of_date: date,
        bucket_days: list[int] | None = None,
        currency_code: str = "IDR",
    ) -> list[dict[str, Any]]:
        """
        Mendapatkan aging report untuk piutang (AR).
        Stub: implementasi nyata perlu query ke tabel AR invoices.
        """
        await self._get_session()
        logger.warning("get_ar_aging() menggunakan data dummy - implementasi nyata belum dibuat")
        return []

    async def get_ap_aging(
        self,
        legal_entity_id: uuid.UUID,
        as_of_date: date,
        bucket_days: list[int] | None = None,
        currency_code: str = "IDR",
    ) -> list[dict[str, Any]]:
        """
        Mendapatkan aging report untuk utang (AP).
        Stub: implementasi nyata perlu query ke tabel AP invoices.
        """
        await self._get_session()
        logger.warning("get_ap_aging() menggunakan data dummy - implementasi nyata belum dibuat")
        return []

    # ---- Additional methods from ReportRepositoryPort (if any) ----

    async def generate_report(
        self,
        report_type: str,
        legal_entity_id: uuid.UUID,
        parameters: dict[str, Any] | None = None,
        format: str = "PDF",
    ) -> dict[str, Any]:
        """
        Generate laporan berdasarkan tipe dan parameter.
        Stub: implementasi nyata akan memanggil report engine.
        """
        await self._get_session()
        logger.warning(
            "generate_report() menggunakan data dummy - implementasi nyata belum dibuat "
            f"(report_type={report_type}, format={format})"
        )
        return {
            "report_type": report_type,
            "format": format,
            "generated_at": date.today().isoformat(),
            "data": [],
            "message": "Stub implementation - replace with actual report generation",
        }

    async def get_report_data(
        self,
        report_id: str,
        legal_entity_id: uuid.UUID,
    ) -> dict[str, Any]:
        """
        Ambil data laporan yang sudah pernah digenerate berdasarkan ID.
        Stub: implementasi nyata perlu query ke tabel report cache.
        """
        await self._get_session()
        logger.warning(
            "get_report_data() menggunakan data dummy - implementasi nyata belum dibuat "
            f"(report_id={report_id})"
        )
        return {
            "report_id": report_id,
            "status": "not_found",
            "message": "Stub implementation - replace with actual report retrieval",
        }


__all__ = [
    "SQLAlchemyBalanceSheetRepository",
    "SQLAlchemyCashFlowRepository",
    "SQLAlchemyIncomeStatementRepository",
    "SQLAlchemyReportRepository",
    "SQLAlchemyTrialBalanceRepository",
]
