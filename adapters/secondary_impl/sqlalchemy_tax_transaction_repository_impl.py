#!/usr/bin/env python3
"""
Module: sqlalchemy_tax_transaction_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Tax Transaction menggunakan SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.tax_transaction_table import TaxTransactionTable
from ports.primary.tax_transaction_repository_port import TaxTransactionRepositoryPort


class SQLAlchemyTaxTransactionRepository(TaxTransactionRepositoryPort):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, transaction: TaxTransactionTable) -> TaxTransactionTable:
        self._session.add(transaction)
        await self._session.flush()
        return transaction

    async def get_by_id(self, transaction_id: uuid.UUID) -> TaxTransactionTable | None:
        stmt = select(TaxTransactionTable).where(TaxTransactionTable.id == transaction_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_invoice(
        self, invoice_id: uuid.UUID, tax_type: str
    ) -> TaxTransactionTable | None:
        stmt = select(TaxTransactionTable).where(
            TaxTransactionTable.source_document_id == invoice_id,
            TaxTransactionTable.source_document_type == "invoice",
            TaxTransactionTable.tax_type == tax_type,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_period(
        self, tax_type: str, period_year: int, period_month: int, legal_entity_id: uuid.UUID
    ) -> list[TaxTransactionTable]:
        stmt = select(TaxTransactionTable).where(
            TaxTransactionTable.tax_type == tax_type,
            TaxTransactionTable.period_year == period_year,
            TaxTransactionTable.period_month == period_month,
            TaxTransactionTable.legal_entity_id == legal_entity_id,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_pending_submissions(
        self, tax_type: str, legal_entity_id: uuid.UUID
    ) -> list[TaxTransactionTable]:
        stmt = select(TaxTransactionTable).where(
            TaxTransactionTable.tax_type == tax_type,
            TaxTransactionTable.legal_entity_id == legal_entity_id,
            TaxTransactionTable.submission_status == "pending",
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update_submission_status(
        self, transaction_id: uuid.UUID, status: str, submission_id: str | None = None
    ) -> None:
        values = {"submission_status": status, "submitted_at": date.today()}
        if submission_id:
            values["submission_id"] = submission_id
        stmt = (
            update(TaxTransactionTable)
            .where(TaxTransactionTable.id == transaction_id)
            .values(**values)
        )
        await self._session.execute(stmt)

    async def get_summary_by_period(
        self, tax_type: str, period_year: int, period_month: int, legal_entity_id: uuid.UUID
    ) -> Decimal:
        stmt = select(TaxTransactionTable.tax_amount).where(
            TaxTransactionTable.tax_type == tax_type,
            TaxTransactionTable.period_year == period_year,
            TaxTransactionTable.period_month == period_month,
            TaxTransactionTable.legal_entity_id == legal_entity_id,
            TaxTransactionTable.submission_status == "submitted",
        )
        result = await self._session.execute(stmt)
        amounts = result.scalars().all()
        return sum(amounts, Decimal(0))


__all__ = ["SQLAlchemyTaxTransactionRepository"]
