#!/usr/bin/env python3
"""
Module: sqlalchemy_fiscal_period_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Fiscal Period menggunakan SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.fiscal_period_table import FiscalPeriodTable
from ports.primary.fiscal_period_repository_port import FiscalPeriodRepositoryPort


class SQLAlchemyFiscalPeriodRepository(FiscalPeriodRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    # === Metode yang sudah ada ===
    async def save(self, period: FiscalPeriodTable) -> FiscalPeriodTable:
        session = await self._get_session()
        session.add(period)
        await session.flush()
        return period

    async def get_by_id(self, period_id: uuid.UUID) -> FiscalPeriodTable | None:
        session = await self._get_session()
        stmt = select(FiscalPeriodTable).where(FiscalPeriodTable.id == period_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_fiscal_year(
        self, fiscal_year: int, legal_entity_id: uuid.UUID
    ) -> list[FiscalPeriodTable]:
        session = await self._get_session()
        stmt = (
            select(FiscalPeriodTable)
            .where(
                FiscalPeriodTable.fiscal_year == fiscal_year,
                FiscalPeriodTable.legal_entity_id == legal_entity_id,
            )
            .order_by(FiscalPeriodTable.period_number)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_period_by_date(
        self, date_obj: date, legal_entity_id: uuid.UUID
    ) -> FiscalPeriodTable | None:
        session = await self._get_session()
        stmt = select(FiscalPeriodTable).where(
            FiscalPeriodTable.start_date <= date_obj,
            FiscalPeriodTable.end_date >= date_obj,
            FiscalPeriodTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_current_open_period(self, legal_entity_id: uuid.UUID) -> FiscalPeriodTable | None:
        session = await self._get_session()
        stmt = (
            select(FiscalPeriodTable)
            .where(
                FiscalPeriodTable.legal_entity_id == legal_entity_id,
                FiscalPeriodTable.status == "open",
            )
            .order_by(FiscalPeriodTable.period_number.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def close_period(self, period_id: uuid.UUID, closed_by: uuid.UUID) -> None:
        session = await self._get_session()
        stmt = (
            update(FiscalPeriodTable)
            .where(FiscalPeriodTable.id == period_id)
            .values(
                status="closed",
                closed_at=date.today(),
                closed_by=closed_by,
            )
        )
        await session.execute(stmt)

    async def reopen_period(
        self, period_id: uuid.UUID, reopened_by: uuid.UUID, reason: str
    ) -> None:
        session = await self._get_session()
        stmt = (
            update(FiscalPeriodTable)
            .where(FiscalPeriodTable.id == period_id)
            .values(
                status="open",
                reopened_at=date.today(),
                reopened_by=reopened_by,
                reopen_reason=reason,
            )
        )
        await session.execute(stmt)

    # === Metode tambahan untuk memenuhi kontrak port (stub) ===
    async def find_active_period(self, legal_entity_id: uuid.UUID) -> FiscalPeriodTable | None:
        """Mendapatkan periode yang aktif (status open) - delegasi ke get_current_open_period."""
        return await self.get_current_open_period(legal_entity_id)

    async def find_all_ordered(self, legal_entity_id: uuid.UUID) -> list[FiscalPeriodTable]:
        """Mendapatkan semua periode diurutkan berdasarkan period_number."""
        session = await self._get_session()
        stmt = select(FiscalPeriodTable).where(
            FiscalPeriodTable.legal_entity_id == legal_entity_id
        ).order_by(FiscalPeriodTable.period_number)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_date(self, date_obj: date, legal_entity_id: uuid.UUID) -> FiscalPeriodTable | None:
        """Alias untuk get_period_by_date."""
        return await self.get_period_by_date(date_obj, legal_entity_id)

    async def find_by_id(self, period_id: uuid.UUID) -> FiscalPeriodTable | None:
        """Alias untuk get_by_id."""
        return await self.get_by_id(period_id)

    async def is_period_locked_for_module(self, period_id: uuid.UUID, module: str) -> bool:
        """Stub: cek apakah periode terkunci untuk modul tertentu."""
        # Default: periode tidak terkunci
        return False


# === ALIAS untuk kompatibilitas dengan adapter registry ===
SQLAlchemyFiscalPeriodRepositoryImpl = SQLAlchemyFiscalPeriodRepository

__all__ = [
    "SQLAlchemyFiscalPeriodRepository",
    "SQLAlchemyFiscalPeriodRepositoryImpl",
]