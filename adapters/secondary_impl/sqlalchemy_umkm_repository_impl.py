#!/usr/bin/env python3
"""
Module: sqlalchemy_umkm_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository UMKM (simplified accounting) menggunakan SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.umkm_business_profile_table import UMKMProfileTable
from infrastructure.persistence_orm.umkm_transaction_table import UMKMTransactionTable
from ports.primary.umkm_repository_port import UMKMRepositoryPort


class SQLAlchemyUMKMRepository(UMKMRepositoryPort):
    def __init__(self, session: AsyncSession):
        self._session = session

    # ========== Business Profile ==========
    async def save_profile(self, profile: UMKMProfileTable) -> UMKMProfileTable:
        self._session.add(profile)
        await self._session.flush()
        return profile

    async def get_profile_by_id(self, profile_id: uuid.UUID) -> UMKMProfileTable | None:
        stmt = select(UMKMProfileTable).where(UMKMProfileTable.id == profile_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_profile_by_legal_entity(
        self, legal_entity_id: uuid.UUID
    ) -> UMKMProfileTable | None:
        stmt = select(UMKMProfileTable).where(UMKMProfileTable.legal_entity_id == legal_entity_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_profile_tax_status(self, profile_id: uuid.UUID, uses_umkm_tax: bool) -> None:
        stmt = (
            update(UMKMProfileTable)
            .where(UMKMProfileTable.id == profile_id)
            .values(uses_umkm_tax=uses_umkm_tax)
        )
        await self._session.execute(stmt)

    # ========== Transactions ==========
    async def save_transaction(self, transaction: UMKMTransactionTable) -> UMKMTransactionTable:
        self._session.add(transaction)
        await self._session.flush()
        return transaction

    async def get_transaction_by_id(self, transaction_id: uuid.UUID) -> UMKMTransactionTable | None:
        stmt = select(UMKMTransactionTable).where(UMKMTransactionTable.id == transaction_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_transactions_by_period(
        self, profile_id: uuid.UUID, from_date: date, to_date: date
    ) -> list[UMKMTransactionTable]:
        stmt = (
            select(UMKMTransactionTable)
            .where(
                UMKMTransactionTable.profile_id == profile_id,
                UMKMTransactionTable.transaction_date.between(from_date, to_date),
            )
            .order_by(UMKMTransactionTable.transaction_date)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_total_revenue_by_period(
        self, profile_id: uuid.UUID, from_date: date, to_date: date
    ) -> Decimal:
        stmt = select(UMKMTransactionTable.amount).where(
            UMKMTransactionTable.profile_id == profile_id,
            UMKMTransactionTable.transaction_type == "revenue",
            UMKMTransactionTable.transaction_date.between(from_date, to_date),
        )
        result = await self._session.execute(stmt)
        amounts = result.scalars().all()
        return sum(amounts, Decimal(0))

    async def get_monthly_summary(
        self, profile_id: uuid.UUID, year: int, month: int
    ) -> dict[str, Decimal]:
        from_date = date(year, month, 1)
        # sederhana, asumsi semua bulan punya 31 hari? lebih baik pakai date(year, month+1, 1) - 1 hari
        if month == 12:
            to_date = date(year + 1, 1, 1)
        else:
            to_date = date(year, month + 1, 1)
        # atau gunakan date(year, month, 28) sebagai gampang, tapi lebih akurat:
        from calendar import monthrange

        last_day = monthrange(year, month)[1]
        to_date = date(year, month, last_day)

        revenue = await self.get_total_revenue_by_period(profile_id, from_date, to_date)
        stmt = select(UMKMTransactionTable.amount).where(
            UMKMTransactionTable.profile_id == profile_id,
            UMKMTransactionTable.transaction_type == "expense",
            UMKMTransactionTable.transaction_date.between(from_date, to_date),
        )
        result = await self._session.execute(stmt)
        expenses = result.scalars().all()
        total_expense = sum(expenses, Decimal(0))
        return {"revenue": revenue, "expense": total_expense, "net": revenue - total_expense}


__all__ = ["SQLAlchemyUMKMRepository"]
