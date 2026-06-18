#!/usr/bin/env python3
"""
Module: sqlalchemy_hedge_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Hedge (lindung nilai) menggunakan SQLAlchemy.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.hedge_effectiveness_test_table import (
    HedgeEffectivenessTestTable,
)
from infrastructure.persistence_orm.hedge_instrument_table import HedgeInstrumentTable
from infrastructure.persistence_orm.hedged_item_table import HedgedItemTable
from ports.primary.hedge_repository_port import HedgeRepositoryPort


class SQLAlchemyHedgeRepository(HedgeRepositoryPort):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def save_instrument(self, instrument: HedgeInstrumentTable) -> HedgeInstrumentTable:
        self._session.add(instrument)
        await self._session.flush()
        return instrument

    async def get_instrument_by_id(self, instrument_id: uuid.UUID) -> HedgeInstrumentTable | None:
        stmt = select(HedgeInstrumentTable).where(HedgeInstrumentTable.id == instrument_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_instruments(
        self, legal_entity_id: uuid.UUID
    ) -> list[HedgeInstrumentTable]:
        stmt = select(HedgeInstrumentTable).where(
            HedgeInstrumentTable.legal_entity_id == legal_entity_id,
            HedgeInstrumentTable.status == "active",
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def save_hedged_item(self, item: HedgedItemTable) -> HedgedItemTable:
        self._session.add(item)
        await self._session.flush()
        return item

    async def get_hedged_items_by_instrument(
        self, instrument_id: uuid.UUID
    ) -> list[HedgedItemTable]:
        stmt = select(HedgedItemTable).where(HedgedItemTable.hedge_instrument_id == instrument_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def save_effectiveness_test(
        self, test: HedgeEffectivenessTestTable
    ) -> HedgeEffectivenessTestTable:
        self._session.add(test)
        await self._session.flush()
        return test

    async def get_latest_effectiveness_test(
        self, instrument_id: uuid.UUID
    ) -> HedgeEffectivenessTestTable | None:
        stmt = (
            select(HedgeEffectivenessTestTable)
            .where(HedgeEffectivenessTestTable.hedge_instrument_id == instrument_id)
            .order_by(HedgeEffectivenessTestTable.test_date.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


__all__ = ["SQLAlchemyHedgeRepository"]
