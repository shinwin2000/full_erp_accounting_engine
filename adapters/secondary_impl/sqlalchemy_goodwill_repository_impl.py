#!/usr/bin/env python3
"""
Module: sqlalchemy_goodwill_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Goodwill menggunakan SQLAlchemy.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.goodwill_impairment_table import GoodwillImpairmentTable
from infrastructure.persistence_orm.goodwill_table import GoodwillTable
from ports.primary.goodwill_repository_port import GoodwillRepositoryPort


class SQLAlchemyGoodwillRepository(GoodwillRepositoryPort):
    def __init__(self, session: AsyncSession):
        self._session = session

    async def save_goodwill(self, goodwill: GoodwillTable) -> GoodwillTable:
        self._session.add(goodwill)
        await self._session.flush()
        return goodwill

    async def get_goodwill_by_id(self, goodwill_id: uuid.UUID) -> GoodwillTable | None:
        stmt = select(GoodwillTable).where(GoodwillTable.id == goodwill_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_goodwill_by_legal_entity(self, legal_entity_id: uuid.UUID) -> list[GoodwillTable]:
        stmt = select(GoodwillTable).where(GoodwillTable.legal_entity_id == legal_entity_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_goodwill(self, legal_entity_id: uuid.UUID) -> list[GoodwillTable]:
        stmt = select(GoodwillTable).where(
            GoodwillTable.legal_entity_id == legal_entity_id,
            GoodwillTable.is_active == True,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def save_impairment(self, impairment: GoodwillImpairmentTable) -> GoodwillImpairmentTable:
        self._session.add(impairment)
        await self._session.flush()
        return impairment

    async def get_impairments_by_goodwill(
        self, goodwill_id: uuid.UUID
    ) -> list[GoodwillImpairmentTable]:
        stmt = select(GoodwillImpairmentTable).where(
            GoodwillImpairmentTable.goodwill_id == goodwill_id
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_impairment(self, goodwill_id: uuid.UUID) -> GoodwillImpairmentTable | None:
        stmt = (
            select(GoodwillImpairmentTable)
            .where(GoodwillImpairmentTable.goodwill_id == goodwill_id)
            .order_by(GoodwillImpairmentTable.test_date.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_goodwill_carrying_amount(
        self, goodwill_id: uuid.UUID, new_amount: Decimal
    ) -> None:
        stmt = (
            update(GoodwillTable)
            .where(GoodwillTable.id == goodwill_id)
            .values(carrying_amount=new_amount)
        )
        await self._session.execute(stmt)


__all__ = ["SQLAlchemyGoodwillRepository"]
