"""
Module: sqlalchemy_general_ledger_repository_impl.py
Layer: Adapters (Secondary Impl)
Responsibility: Implementasi SQLAlchemy untuk GeneralLedgerRepositoryPort.
Perbaikan: JOIN dengan JournalHeaderTable, gunakan voucher_number sebagai journal_number.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.persistence_orm.account_table import AccountTable
from infrastructure.persistence_orm.journal_header_table import JournalHeaderTable
from infrastructure.persistence_orm.journal_line_table import JournalLineTable
from ports.primary.report_repository_port import (
    GeneralLedgerDataDTO,
    GeneralLedgerEntryDTO,
    GeneralLedgerRepositoryPort,
)

logger = logging.getLogger(__name__)


class SQLAlchemyGeneralLedgerRepository(GeneralLedgerRepositoryPort):
    """SQLAlchemy implementation of GeneralLedgerRepositoryPort."""

    def __init__(self):
        self._session_factory = None

    async def _get_session(self) -> AsyncSession:
        if self._session_factory is None:
            self._session_factory = await get_session_factory()
        return self._session_factory()

    async def get_ledger(
        self,
        legal_entity_id: UUID,
        account_code: str,
        from_date: date,
        to_date: date,
        include_journal_details: bool = True,
    ) -> GeneralLedgerDataDTO:
        """Get general ledger entries for an account."""
        async with await self._get_session() as session:
            # Get account info from COA
            account_stmt = select(
                AccountTable.account_code,
                AccountTable.account_name,
            ).where(
                and_(
                    AccountTable.account_code == account_code,
                    AccountTable.legal_entity_id == legal_entity_id
                )
            )
            account_result = await session.execute(account_stmt)
            account_row = account_result.first()
            if not account_row:
                raise ValueError(f"Account {account_code} not found")

            # Get journal entries with JOIN to header
            stmt = select(
                JournalHeaderTable.journal_date,
                JournalHeaderTable.voucher_number.label("journal_number"),  # ← perbaikan
                JournalLineTable.description,
                JournalLineTable.debit_amount,
                JournalLineTable.credit_amount,
                JournalHeaderTable.reference_number,
            ).join(
                JournalHeaderTable,
                JournalLineTable.journal_id == JournalHeaderTable.id
            ).where(
                and_(
                    JournalLineTable.account_code == account_code,
                    JournalLineTable.legal_entity_id == legal_entity_id,
                    JournalHeaderTable.journal_date >= from_date,
                    JournalHeaderTable.journal_date <= to_date,
                    JournalHeaderTable.status == "posted"
                )
            ).order_by(JournalHeaderTable.journal_date)

            result = await session.execute(stmt)
            rows = result.all()

            # Calculate opening balance
            opening_stmt = select(
                func.sum(JournalLineTable.debit_amount - JournalLineTable.credit_amount)
            ).join(
                JournalHeaderTable,
                JournalLineTable.journal_id == JournalHeaderTable.id
            ).where(
                and_(
                    JournalLineTable.account_code == account_code,
                    JournalLineTable.legal_entity_id == legal_entity_id,
                    JournalHeaderTable.journal_date < from_date,
                    JournalHeaderTable.status == "posted"
                )
            )
            opening_result = await session.execute(opening_stmt)
            opening_balance = opening_result.scalar() or Decimal(0)

            entries = []
            running_balance = opening_balance
            for row in rows:
                debit = row.debit_amount or Decimal(0)
                credit = row.credit_amount or Decimal(0)
                running_balance += debit - credit
                entries.append(
                    GeneralLedgerEntryDTO(
                        journal_date=row.journal_date,
                        journal_number=row.journal_number,  # dari voucher_number
                        description=row.description or "",
                        debit=debit,
                        credit=credit,
                        running_balance=running_balance,
                        reference=row.reference_number,
                    )
                )

            return GeneralLedgerDataDTO(
                account_code=account_code,
                account_name=account_row.account_name,
                from_date=from_date,
                to_date=to_date,
                opening_balance=opening_balance,
                entries=entries,
                closing_balance=running_balance,
            )