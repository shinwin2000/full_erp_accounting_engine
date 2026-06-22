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
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    # ====== Metode existing ======
    async def save_goodwill(self, goodwill: GoodwillTable) -> GoodwillTable:
        session = await self._get_session()
        session.add(goodwill)
        await session.flush()
        return goodwill

    async def get_goodwill_by_id(self, goodwill_id: uuid.UUID) -> GoodwillTable | None:
        session = await self._get_session()
        stmt = select(GoodwillTable).where(GoodwillTable.id == goodwill_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_goodwill_by_legal_entity(self, legal_entity_id: uuid.UUID) -> list[GoodwillTable]:
        session = await self._get_session()
        stmt = select(GoodwillTable).where(GoodwillTable.legal_entity_id == legal_entity_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_goodwill(self, legal_entity_id: uuid.UUID) -> list[GoodwillTable]:
        session = await self._get_session()
        stmt = select(GoodwillTable).where(
            GoodwillTable.legal_entity_id == legal_entity_id,
            GoodwillTable.is_active == True
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def save_impairment(self, impairment: GoodwillImpairmentTable) -> GoodwillImpairmentTable:
        session = await self._get_session()
        session.add(impairment)
        await session.flush()
        return impairment

    async def get_impairments_by_goodwill(self, goodwill_id: uuid.UUID) -> list[GoodwillImpairmentTable]:
        session = await self._get_session()
        stmt = select(GoodwillImpairmentTable).where(GoodwillImpairmentTable.goodwill_id == goodwill_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_impairment(self, goodwill_id: uuid.UUID) -> GoodwillImpairmentTable | None:
        session = await self._get_session()
        stmt = select(GoodwillImpairmentTable).where(
            GoodwillImpairmentTable.goodwill_id == goodwill_id
        ).order_by(GoodwillImpairmentTable.test_date.desc()).limit(1)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_goodwill_carrying_amount(self, goodwill_id: uuid.UUID, new_amount: Decimal) -> None:
        session = await self._get_session()
        stmt = update(GoodwillTable).where(GoodwillTable.id == goodwill_id).values(carrying_amount=new_amount)
        await session.execute(stmt)

    # ====== Metode tambahan untuk memenuhi kontrak port (stub/delegasi) ======
    async def save(self, goodwill: GoodwillTable) -> GoodwillTable:
        """Delegates to save_goodwill."""
        return await self.save_goodwill(goodwill)

    async def update(self, goodwill: GoodwillTable) -> None:
        """Update existing goodwill."""
        session = await self._get_session()
        await session.merge(goodwill)
        await session.flush()

    async def get_by_id(self, goodwill_id: uuid.UUID) -> GoodwillTable | None:
        """Delegates to get_goodwill_by_id."""
        return await self.get_goodwill_by_id(goodwill_id)

    async def list_by_legal_entity(self, legal_entity_id: uuid.UUID) -> list[GoodwillTable]:
        """Delegates to get_goodwill_by_legal_entity."""
        return await self.get_goodwill_by_legal_entity(legal_entity_id)

    async def get_last_goodwill_number(self, legal_entity_id: uuid.UUID) -> str | None:
        """Stub: return None."""
        logger = logging.getLogger(__name__)
        logger.warning("get_last_goodwill_number not fully implemented")
        return None

    async def record_impairment_journal(self, impairment: GoodwillImpairmentTable) -> None:
        """Stub: just log."""
        logger = logging.getLogger(__name__)
        logger.warning("record_impairment_journal not fully implemented")
        pass

__all__ = ["SQLAlchemyGoodwillRepository"]