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
    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, period: FiscalPeriodTable) -> FiscalPeriodTable:
        self._session.add(period)
        await self._session.flush()
        return period

    async def get_by_id(self, period_id: uuid.UUID) -> FiscalPeriodTable | None:
        stmt = select(FiscalPeriodTable).where(FiscalPeriodTable.id == period_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_fiscal_year(
        self, fiscal_year: int, legal_entity_id: uuid.UUID
    ) -> list[FiscalPeriodTable]:
        stmt = (
            select(FiscalPeriodTable)
            .where(
                FiscalPeriodTable.fiscal_year == fiscal_year,
                FiscalPeriodTable.legal_entity_id == legal_entity_id,
            )
            .order_by(FiscalPeriodTable.period_number)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_period_by_date(
        self, date_obj: date, legal_entity_id: uuid.UUID
    ) -> FiscalPeriodTable | None:
        stmt = select(FiscalPeriodTable).where(
            FiscalPeriodTable.start_date <= date_obj,
            FiscalPeriodTable.end_date >= date_obj,
            FiscalPeriodTable.legal_entity_id == legal_entity_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_current_open_period(self, legal_entity_id: uuid.UUID) -> FiscalPeriodTable | None:
        stmt = (
            select(FiscalPeriodTable)
            .where(
                FiscalPeriodTable.legal_entity_id == legal_entity_id,
                FiscalPeriodTable.status == "open",
            )
            .order_by(FiscalPeriodTable.period_number.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def close_period(self, period_id: uuid.UUID, closed_by: uuid.UUID) -> None:
        stmt = (
            update(FiscalPeriodTable)
            .where(FiscalPeriodTable.id == period_id)
            .values(
                status="closed",
                closed_at=date.today(),
                closed_by=closed_by,
            )
        )
        await self._session.execute(stmt)

    async def reopen_period(
        self, period_id: uuid.UUID, reopened_by: uuid.UUID, reason: str
    ) -> None:
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
        await self._session.execute(stmt)


__all__ = ["SQLAlchemyFiscalPeriodRepository"]
