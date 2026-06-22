#!/usr/bin/env python3
"""
Module: sqlalchemy_hedge_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Hedge (lindung nilai) menggunakan SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update, desc
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.hedge_effectiveness_test_table import (
    HedgeEffectivenessTestTable,
)
from infrastructure.persistence_orm.hedge_instrument_table import HedgeInstrumentTable
from infrastructure.persistence_orm.hedged_item_table import HedgedItemTable
from ports.primary.hedge_repository_port import HedgeRepositoryPort


class SQLAlchemyHedgeRepository(HedgeRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    # ========== Metode yang sudah ada ==========
    async def save_instrument(self, instrument: HedgeInstrumentTable) -> HedgeInstrumentTable:
        session = await self._get_session()
        session.add(instrument)
        await session.flush()
        return instrument

    async def get_instrument_by_id(self, instrument_id: uuid.UUID) -> HedgeInstrumentTable | None:
        session = await self._get_session()
        stmt = select(HedgeInstrumentTable).where(HedgeInstrumentTable.id == instrument_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_instruments(
        self, legal_entity_id: uuid.UUID
    ) -> list[HedgeInstrumentTable]:
        session = await self._get_session()
        stmt = select(HedgeInstrumentTable).where(
            HedgeInstrumentTable.legal_entity_id == legal_entity_id,
            HedgeInstrumentTable.status == "active",
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def save_hedged_item(self, item: HedgedItemTable) -> HedgedItemTable:
        session = await self._get_session()
        session.add(item)
        await session.flush()
        return item

    async def get_hedged_items_by_instrument(
        self, instrument_id: uuid.UUID
    ) -> list[HedgedItemTable]:
        session = await self._get_session()
        stmt = select(HedgedItemTable).where(HedgedItemTable.hedge_instrument_id == instrument_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def save_effectiveness_test(
        self, test: HedgeEffectivenessTestTable
    ) -> HedgeEffectivenessTestTable:
        session = await self._get_session()
        session.add(test)
        await session.flush()
        return test

    async def get_latest_effectiveness_test(
        self, instrument_id: uuid.UUID
    ) -> HedgeEffectivenessTestTable | None:
        session = await self._get_session()
        stmt = (
            select(HedgeEffectivenessTestTable)
            .where(HedgeEffectivenessTestTable.hedge_instrument_id == instrument_id)
            .order_by(HedgeEffectivenessTestTable.test_date.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    # ========== Metode abstrak tambahan (implementasi nyata) ==========

    async def get_hedge_by_id(self, hedge_id: uuid.UUID) -> HedgeInstrumentTable | None:
        """Alias untuk get_instrument_by_id."""
        return await self.get_instrument_by_id(hedge_id)

    async def get_hedge_instrument(self, instrument_id: uuid.UUID) -> HedgeInstrumentTable | None:
        """Alias untuk get_instrument_by_id."""
        return await self.get_instrument_by_id(instrument_id)

    async def get_hedged_item(self, item_id: uuid.UUID) -> HedgedItemTable | None:
        """Mendapatkan hedged item berdasarkan ID."""
        session = await self._get_session()
        stmt = select(HedgedItemTable).where(HedgedItemTable.id == item_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_last_hedge_number(
        self, legal_entity_id: uuid.UUID, prefix: str = "HEDGE"
    ) -> str | None:
        """Mendapatkan nomor hedge terakhir."""
        session = await self._get_session()
        pattern = f"{prefix}-%"
        stmt = (
            select(HedgeInstrumentTable.hedge_number)
            .where(
                HedgeInstrumentTable.legal_entity_id == legal_entity_id,
                HedgeInstrumentTable.hedge_number.like(pattern)
            )
            .order_by(desc(HedgeInstrumentTable.created_at))
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_hedges_by_entity(
        self, legal_entity_id: uuid.UUID, status: str | None = None
    ) -> list[HedgeInstrumentTable]:
        """Mendaftar hedge berdasarkan entitas."""
        session = await self._get_session()
        stmt = select(HedgeInstrumentTable).where(
            HedgeInstrumentTable.legal_entity_id == legal_entity_id
        )
        if status:
            stmt = stmt.where(HedgeInstrumentTable.status == status)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def save_hedge(self, hedge_data: dict[str, Any]) -> HedgeInstrumentTable:
        """
        Menyimpan hedge (insert atau update).
        Data berupa dict yang akan dipetakan ke HedgeInstrumentTable.
        """
        session = await self._get_session()
        # Cek apakah sudah ada
        instrument_id = hedge_data.get("id")
        if instrument_id:
            existing = await self.get_instrument_by_id(instrument_id)
            if existing:
                # Update
                for key, value in hedge_data.items():
                    if hasattr(existing, key):
                        setattr(existing, key, value)
                existing.updated_at = datetime.utcnow()
                await session.flush()
                return existing
        # Insert baru
        new_instrument = HedgeInstrumentTable(
            id=uuid.uuid4(),
            legal_entity_id=hedge_data.get("legal_entity_id"),
            hedge_number=hedge_data.get("hedge_number"),
            instrument_type=hedge_data.get("instrument_type"),
            status=hedge_data.get("status", "draft"),
            # tambahkan field lain sesuai kebutuhan
            created_at=datetime.utcnow(),
        )
        session.add(new_instrument)
        await session.flush()
        return new_instrument

    async def save_hedge_adjustment(
        self, adjustment_data: dict[str, Any]
    ) -> HedgeEffectivenessTestTable:
        """
        Menyimpan penyesuaian hedge (misal sebagai effectiveness test).
        """
        session = await self._get_session()
        adjustment = HedgeEffectivenessTestTable(
            id=uuid.uuid4(),
            hedge_instrument_id=adjustment_data.get("hedge_instrument_id"),
            test_date=adjustment_data.get("test_date", datetime.utcnow().date()),
            result=adjustment_data.get("result", "pending"),
            # field lain
        )
        session.add(adjustment)
        await session.flush()
        return adjustment

    async def find_hedge(self, hedge_id: uuid.UUID) -> HedgeInstrumentTable | None:
        return await self.get_instrument_by_id(hedge_id)
    
# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS DENGAN ADAPTER REGISTRY
# ============================================================================

SQLAlchemyHedgeRepositoryImpl = SQLAlchemyHedgeRepository

__all__ = ["SQLAlchemyHedgeRepository", "SQLAlchemyHedgeRepositoryImpl"]