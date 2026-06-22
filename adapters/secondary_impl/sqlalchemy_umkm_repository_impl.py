#!/usr/bin/env python3
"""
Module: sqlalchemy_umkm_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository UMKM (simplified accounting) menggunakan SQLAlchemy.
"""

from __future__ import annotations

import uuid
from calendar import monthrange
from datetime import date
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.umkm_business_profile_table import UMKMProfileTable
from infrastructure.persistence_orm.umkm_transaction_table import UMKMTransactionTable
from ports.primary.umkm_repository_port import UMKMRepositoryPort


class SQLAlchemyUMKMRepository(UMKMRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    # ========== Business Profile ==========
    async def save_profile(self, profile: UMKMProfileTable) -> UMKMProfileTable:
        session = await self._get_session()
        session.add(profile)
        await session.flush()
        return profile

    async def get_profile_by_id(self, profile_id: uuid.UUID) -> UMKMProfileTable | None:
        session = await self._get_session()
        stmt = select(UMKMProfileTable).where(UMKMProfileTable.id == profile_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_profile_by_legal_entity(
        self, legal_entity_id: uuid.UUID
    ) -> UMKMProfileTable | None:
        session = await self._get_session()
        stmt = select(UMKMProfileTable).where(UMKMProfileTable.legal_entity_id == legal_entity_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_profile_tax_status(self, profile_id: uuid.UUID, uses_umkm_tax: bool) -> None:
        session = await self._get_session()
        stmt = (
            update(UMKMProfileTable)
            .where(UMKMProfileTable.id == profile_id)
            .values(uses_umkm_tax=uses_umkm_tax)
        )
        await session.execute(stmt)

    # ========== Transactions ==========
    async def save_transaction(self, transaction: UMKMTransactionTable) -> UMKMTransactionTable:
        session = await self._get_session()
        session.add(transaction)
        await session.flush()
        return transaction

    async def get_transaction_by_id(self, transaction_id: uuid.UUID) -> UMKMTransactionTable | None:
        session = await self._get_session()
        stmt = select(UMKMTransactionTable).where(UMKMTransactionTable.id == transaction_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_transactions_by_period(
        self, profile_id: uuid.UUID, from_date: date, to_date: date
    ) -> list[UMKMTransactionTable]:
        session = await self._get_session()
        stmt = (
            select(UMKMTransactionTable)
            .where(
                UMKMTransactionTable.profile_id == profile_id,
                UMKMTransactionTable.transaction_date.between(from_date, to_date),
            )
            .order_by(UMKMTransactionTable.transaction_date)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_total_revenue_by_period(
        self, profile_id: uuid.UUID, from_date: date, to_date: date
    ) -> Decimal:
        session = await self._get_session()
        stmt = select(UMKMTransactionTable.amount).where(
            UMKMTransactionTable.profile_id == profile_id,
            UMKMTransactionTable.transaction_type == "revenue",
            UMKMTransactionTable.transaction_date.between(from_date, to_date),
        )
        result = await session.execute(stmt)
        amounts = result.scalars().all()
        return sum(amounts, Decimal(0))

    async def get_monthly_summary(
        self, profile_id: uuid.UUID, year: int, month: int
    ) -> dict[str, Decimal]:
        from_date = date(year, month, 1)
        last_day = monthrange(year, month)[1]
        to_date = date(year, month, last_day)

        revenue = await self.get_total_revenue_by_period(profile_id, from_date, to_date)
        session = await self._get_session()
        stmt = select(UMKMTransactionTable.amount).where(
            UMKMTransactionTable.profile_id == profile_id,
            UMKMTransactionTable.transaction_type == "expense",
            UMKMTransactionTable.transaction_date.between(from_date, to_date),
        )
        result = await session.execute(stmt)
        expenses = result.scalars().all()
        total_expense = sum(expenses, Decimal(0))
        return {"revenue": revenue, "expense": total_expense, "net": revenue - total_expense}

    # === Metode tambahan untuk memenuhi kontrak port (stub/delegasi) ===
    async def get_monthly_revenue_summary(
        self, profile_id: uuid.UUID, year: int, month: int
    ) -> dict[str, Decimal]:
        """Alias untuk get_monthly_summary."""
        return await self.get_monthly_summary(profile_id, year, month)

    async def get_total_revenue_ytd(self, profile_id: uuid.UUID, year: int) -> Decimal:
        """Mendapatkan total revenue year-to-date."""
        from_date = date(year, 1, 1)
        to_date = date(year, 12, 31)
        return await self.get_total_revenue_by_period(profile_id, from_date, to_date)

    async def get_transaction(self, transaction_id: uuid.UUID) -> UMKMTransactionTable | None:
        """Alias untuk get_transaction_by_id."""
        return await self.get_transaction_by_id(transaction_id)

    async def list_transactions_by_period(
        self, profile_id: uuid.UUID, from_date: date, to_date: date
    ) -> list[UMKMTransactionTable]:
        """Alias untuk get_transactions_by_period."""
        return await self.get_transactions_by_period(profile_id, from_date, to_date)

    async def save_revenue_summary(self, summary: dict[str, Any]) -> None:
        """Stub: menyimpan ringkasan revenue (implementasi jika diperlukan)."""
        # Jika ada tabel revenue_summary, bisa diimplementasikan di sini
        pass

    async def submit_tax_report(self, profile_id: uuid.UUID, period_year: int, period_month: int) -> dict[str, Any]:
        """Stub: submit laporan pajak."""
        # Implementasi jika diperlukan
        return {"status": "submitted", "profile_id": str(profile_id), "period": f"{period_year}-{period_month}"}


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS DENGAN ADAPTER REGISTRY
# ============================================================================
SQLAlchemyUmkmRepository = SQLAlchemyUMKMRepository
SQLAlchemyUmkmRepositoryImpl = SQLAlchemyUMKMRepository

# ============================================================================
# EXPORTS
# ============================================================================
__all__ = [
    "SQLAlchemyUMKMRepository",
    "SQLAlchemyUmkmRepository",
    "SQLAlchemyUmkmRepositoryImpl",
]