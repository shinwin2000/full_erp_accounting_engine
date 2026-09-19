#!/usr/bin/env python3
"""
Module: sqlalchemy_goodwill_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Goodwill menggunakan SQLAlchemy.

FIX (audit 2026-09-15): implementasi sebelumnya punya mapping _to_domain/
_from_domain yang menerjemahkan antara GoodwillTable (ORM) dan Goodwill
(dataclass DDD terpisah di domain/goodwill/aggregate_root.py) - tapi
field-field yang dikirim ke constructor Goodwill() TIDAK COCOK dengan
field yang benar-benar ada di dataclass itu (mis. `acquisition_cost`,
`accumulated_impairment`, `is_active` - none of these exist on Goodwill).
Akibatnya get_by_id()/save()/update() SELALU crash TypeError, bahkan untuk
operasi paling dasar (baca satu goodwill).

Diperbaiki dengan menghapus lapisan terjemahan itu sepenuhnya - repository
ini sekarang bekerja langsung dengan GoodwillTable (ORM), sesuai dengan
GoodwillRepositoryPort yang sudah disederhanakan juga.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.goodwill_impairment_table import GoodwillImpairmentTable
from infrastructure.persistence_orm.goodwill_table import GoodwillTable
from ports.primary.goodwill_repository_port import GoodwillRepositoryPort

logger = logging.getLogger(__name__)


class SQLAlchemyGoodwillRepository(GoodwillRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session_direct
            self._session = await get_async_session_direct()
        return self._session

    # ========================================================================
    # GOODWILL
    # ========================================================================

    async def save_goodwill(self, goodwill: GoodwillTable) -> GoodwillTable:
        session = await self._get_session()
        session.add(goodwill)
        await session.flush()
        await session.commit()
        return goodwill

    async def get_goodwill_by_id(self, goodwill_id: UUID) -> GoodwillTable | None:
        session = await self._get_session()
        stmt = select(GoodwillTable).where(GoodwillTable.id == goodwill_id)
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if table is not None:
            await session.refresh(table, attribute_names=["impairments"])
        return table

    async def get_goodwill_by_legal_entity(self, legal_entity_id: UUID) -> list[GoodwillTable]:
        session = await self._get_session()
        stmt = select(GoodwillTable).where(GoodwillTable.legal_entity_id == legal_entity_id)
        result = await session.execute(stmt)
        tables = list(result.scalars().all())
        for table in tables:
            await session.refresh(table, attribute_names=["impairments"])
        return tables

    async def get_active_goodwill(self, legal_entity_id: UUID) -> list[GoodwillTable]:
        session = await self._get_session()
        stmt = select(GoodwillTable).where(
            GoodwillTable.legal_entity_id == legal_entity_id,
            GoodwillTable.is_active == True,  # noqa: E712
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_last_goodwill_code(self, legal_entity_id: UUID) -> str | None:
        session = await self._get_session()
        stmt = (
            select(GoodwillTable.goodwill_code)
            .where(GoodwillTable.legal_entity_id == legal_entity_id)
            .order_by(desc(GoodwillTable.created_at))
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_goodwill_carrying_amount(self, goodwill_id: UUID, new_amount: Decimal) -> None:
        """Update carrying amount with pessimistic locking to prevent race conditions."""
        session = await self._get_session()
        async with session.begin():
            stmt_lock = select(GoodwillTable).where(GoodwillTable.id == goodwill_id).with_for_update()
            result = await session.execute(stmt_lock)
            existing = result.scalar_one_or_none()
            if not existing:
                raise ValueError(f"Goodwill {goodwill_id} not found")
            existing.carrying_amount = new_amount
            existing.updated_at = datetime.utcnow()
            await session.flush()

    # ========================================================================
    # IMPAIRMENT TEST RECORDS
    # ========================================================================

    async def save_impairment(self, impairment: GoodwillImpairmentTable) -> GoodwillImpairmentTable:
        session = await self._get_session()
        session.add(impairment)
        await session.flush()
        await session.commit()
        return impairment

    async def get_impairments_by_goodwill(self, goodwill_id: UUID) -> list[GoodwillImpairmentTable]:
        session = await self._get_session()
        stmt = (
            select(GoodwillImpairmentTable)
            .where(GoodwillImpairmentTable.goodwill_id == goodwill_id)
            .order_by(desc(GoodwillImpairmentTable.test_date))
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_impairment(self, goodwill_id: UUID) -> GoodwillImpairmentTable | None:
        session = await self._get_session()
        stmt = (
            select(GoodwillImpairmentTable)
            .where(GoodwillImpairmentTable.goodwill_id == goodwill_id)
            .order_by(desc(GoodwillImpairmentTable.test_date))
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS
# ============================================================================

SQLAlchemyGoodwillRepositoryImpl = SQLAlchemyGoodwillRepository

__all__ = ["SQLAlchemyGoodwillRepository", "SQLAlchemyGoodwillRepositoryImpl"]
