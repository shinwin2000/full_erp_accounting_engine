#!/usr/bin/env python3
"""
Module: sqlalchemy_forex_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Forex (nilai tukar) menggunakan SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.exchange_rate_table import ExchangeRateTable
from ports.primary.forex_repository_port import ForexRepositoryPort


class SQLAlchemyForexRepository(ForexRepositoryPort):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def save_rate(self, rate: ExchangeRateTable) -> ExchangeRateTable:
        self._session.add(rate)
        await self._session.flush()
        return rate

    async def get_rate_by_id(self, rate_id: uuid.UUID) -> ExchangeRateTable | None:
        stmt = select(ExchangeRateTable).where(ExchangeRateTable.id == rate_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_rate(
        self, from_currency: str, to_currency: str, rate_date: date, legal_entity_id: uuid.UUID
    ) -> ExchangeRateTable | None:
        stmt = select(ExchangeRateTable).where(
            ExchangeRateTable.from_currency == from_currency,
            ExchangeRateTable.to_currency == to_currency,
            ExchangeRateTable.rate_date == rate_date,
            ExchangeRateTable.legal_entity_id == legal_entity_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_rates_for_date(
        self, rate_date: date, legal_entity_id: uuid.UUID
    ) -> list[ExchangeRateTable]:
        stmt = select(ExchangeRateTable).where(
            ExchangeRateTable.rate_date == rate_date,
            ExchangeRateTable.legal_entity_id == legal_entity_id,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_rate(
        self, from_currency: str, to_currency: str, legal_entity_id: uuid.UUID
    ) -> ExchangeRateTable | None:
        stmt = (
            select(ExchangeRateTable)
            .where(
                ExchangeRateTable.from_currency == from_currency,
                ExchangeRateTable.to_currency == to_currency,
                ExchangeRateTable.legal_entity_id == legal_entity_id,
            )
            .order_by(ExchangeRateTable.rate_date.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def bulk_save_rates(self, rates: list[ExchangeRateTable]) -> None:
        self._session.add_all(rates)
        await self._session.flush()


__all__ = ["SQLAlchemyForexRepository"]
