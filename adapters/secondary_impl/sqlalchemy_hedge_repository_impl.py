#!/usr/bin/env python3
"""
Module: sqlalchemy_hedge_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Hedge (lindung nilai) menggunakan SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from domain.hedge.aggregate_root import HedgeRelationship, HedgeStatus
from domain.hedge.hedge_instrument import HedgeInstrument
from domain.hedge.hedged_item import HedgedItem
from infrastructure.persistence_orm.hedge_effectiveness_test_table import (
    HedgeEffectivenessTestTable,
)
from infrastructure.persistence_orm.hedge_instrument_table import HedgeInstrumentTable
from infrastructure.persistence_orm.hedged_item_table import HedgedItemTable
from ports.primary.hedge_repository_port import HedgeRepositoryPort


class SQLAlchemyHedgeRepository(HedgeRepositoryPort):
    def __init__(self, session: AsyncSession | None = None, legal_entity_id: UUID | None = None):
        self._session = session
        self._legal_entity_id = legal_entity_id

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    def _get_legal_entity_id(self) -> UUID:
        if self._legal_entity_id is None:
            raise ValueError("legal_entity_id not set in repository")
        return self._legal_entity_id

    # ========================================================================
    # MAPPING: ORM ↔ Domain
    # ========================================================================

    def _instrument_to_domain(self, table: HedgeInstrumentTable) -> HedgeInstrument:
        return HedgeInstrument(
            id=table.id,
            legal_entity_id=table.legal_entity_id,
            hedge_number=table.hedge_number,
            instrument_type=table.instrument_type,
            status=HedgeStatus(table.status) if table.status else HedgeStatus.DRAFT,
            created_at=table.created_at,
            updated_at=table.updated_at,
        )

    def _instrument_from_domain(self, domain: HedgeInstrument) -> HedgeInstrumentTable:
        return HedgeInstrumentTable(
            id=domain.id,
            legal_entity_id=domain.legal_entity_id,
            hedge_number=domain.hedge_number,
            instrument_type=domain.instrument_type,
            status=domain.status.value if hasattr(domain.status, "value") else str(domain.status),
            created_at=domain.created_at,
            updated_at=domain.updated_at,
        )

    def _hedged_item_to_domain(self, table: HedgedItemTable) -> HedgedItem:
        return HedgedItem(
            id=table.id,
            hedge_instrument_id=table.hedge_instrument_id,
            item_type=table.item_type,
            item_id=table.item_id,
            amount=table.amount,
            currency=table.currency,
            created_at=table.created_at,
        )

    # ========================================================================
    # PORT METHODS
    # ========================================================================

    async def save_hedge(self, hedge: HedgeRelationship) -> None:
        # Simpan sebagai HedgeInstrument (asumsi hedge memiliki instrument)
        session = await self._get_session()
        instrument = getattr(hedge, 'instrument', None)
        if instrument:
            table = self._instrument_from_domain(instrument)
            existing = await session.get(HedgeInstrumentTable, instrument.id)
            if existing:
                for key, value in table.__dict__.items():
                    if not key.startswith("_") and key != "id":
                        setattr(existing, key, value)
                existing.updated_at = datetime.utcnow()
            else:
                session.add(table)
        await session.flush()

    async def get_hedge_by_id(self, hedge_id: UUID) -> HedgeRelationship | None:
        instrument = await self.get_hedge_instrument(hedge_id)
        if not instrument:
            return None
        return HedgeRelationship(
            id=instrument.id,
            legal_entity_id=instrument.legal_entity_id,
            instrument=instrument,
            status=instrument.status,
        )

    async def get_last_hedge_number(self, legal_entity_id: UUID) -> str | None:
        session = await self._get_session()
        stmt = (
            select(HedgeInstrumentTable.hedge_number)
            .where(
                HedgeInstrumentTable.legal_entity_id == legal_entity_id,
            )
            .order_by(desc(HedgeInstrumentTable.created_at))
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_hedges_by_entity(
        self, legal_entity_id: UUID, status: HedgeStatus | None = None
    ) -> list[HedgeRelationship]:
        session = await self._get_session()
        conditions = [HedgeInstrumentTable.legal_entity_id == legal_entity_id]
        if status:
            status_str = status.value if hasattr(status, "value") else str(status)
            conditions.append(HedgeInstrumentTable.status == status_str)
        stmt = select(HedgeInstrumentTable).where(and_(*conditions))
        result = await session.execute(stmt)
        tables = result.scalars().all()
        hedge_relationships = []
        for t in tables:
            instrument = self._instrument_to_domain(t)
            hedge_relationships.append(
                HedgeRelationship(
                    id=t.id,
                    legal_entity_id=t.legal_entity_id,
                    instrument=instrument,
                    status=instrument.status,
                )
            )
        return hedge_relationships

    async def get_hedge_instrument(self, instrument_id: UUID) -> HedgeInstrument | None:
        session = await self._get_session()
        stmt = select(HedgeInstrumentTable).where(HedgeInstrumentTable.id == instrument_id)
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if not table:
            return None
        return self._instrument_to_domain(table)

    async def get_hedged_item(self, item_id: UUID) -> HedgedItem | None:
        session = await self._get_session()
        stmt = select(HedgedItemTable).where(HedgedItemTable.id == item_id)
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if not table:
            return None
        return self._hedged_item_to_domain(table)

    # ===== FIX: save_effectiveness_test dengan user_id (2 required) =====
    async def save_effectiveness_test(self, test_result: dict[str, Any], user_id: UUID) -> None:
        session = await self._get_session()
        test = HedgeEffectivenessTestTable(
            id=uuid.uuid4(),
            hedge_instrument_id=test_result.get("hedge_instrument_id"),
            test_date=test_result.get("test_date", datetime.utcnow().date()),
            result=test_result.get("result", "pending"),
            created_at=datetime.utcnow(),
            created_by=user_id,
        )
        session.add(test)
        await session.flush()

    # ===== FIX: save_hedge_adjustment dengan user_id (2 required) =====
    async def save_hedge_adjustment(self, adjustment: dict[str, Any], user_id: UUID) -> None:
        session = await self._get_session()
        adj = HedgeEffectivenessTestTable(
            id=uuid.uuid4(),
            hedge_instrument_id=adjustment.get("hedge_instrument_id"),
            test_date=adjustment.get("adjustment_date", datetime.utcnow().date()),
            result=adjustment.get("result", "adjusted"),
            notes=adjustment.get("notes"),
            created_at=datetime.utcnow(),
            created_by=user_id,
        )
        session.add(adj)
        await session.flush()

    # ========================================================================
    # INTERNAL/LEGACY METHODS (untuk kompatibilitas)
    # ========================================================================

    async def save_instrument(self, instrument: HedgeInstrumentTable) -> HedgeInstrumentTable:
        session = await self._get_session()
        session.add(instrument)
        await session.flush()
        return instrument

    async def get_instrument_by_id(self, instrument_id: UUID) -> HedgeInstrumentTable | None:
        session = await self._get_session()
        stmt = select(HedgeInstrumentTable).where(HedgeInstrumentTable.id == instrument_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_instruments(self, legal_entity_id: UUID) -> list[HedgeInstrumentTable]:
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
        self, instrument_id: UUID
    ) -> list[HedgedItemTable]:
        session = await self._get_session()
        stmt = select(HedgedItemTable).where(
            HedgedItemTable.hedge_instrument_id == instrument_id
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def save_effectiveness_test_orm(
        self, test: HedgeEffectivenessTestTable
    ) -> HedgeEffectivenessTestTable:
        session = await self._get_session()
        session.add(test)
        await session.flush()
        return test

    async def get_latest_effectiveness_test(
        self, instrument_id: UUID
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

    async def find_hedge(self, hedge_id: UUID) -> HedgeInstrumentTable | None:
        return await self.get_instrument_by_id(hedge_id)


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS DENGAN ADAPTER REGISTRY
# ============================================================================

SQLAlchemyHedgeRepositoryImpl = SQLAlchemyHedgeRepository

__all__ = ["SQLAlchemyHedgeRepository", "SQLAlchemyHedgeRepositoryImpl"]
