#!/usr/bin/env python3
"""
Module: sqlalchemy_goodwill_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Goodwill menggunakan SQLAlchemy.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from domain.goodwill.aggregate_root import Goodwill
from infrastructure.persistence_orm.goodwill_impairment_table import GoodwillImpairmentTable
from infrastructure.persistence_orm.goodwill_table import GoodwillTable
from ports.primary.goodwill_repository_port import GoodwillRepositoryPort

logger = logging.getLogger(__name__)


class SQLAlchemyGoodwillRepository(GoodwillRepositoryPort):
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

    def _to_domain(self, table: GoodwillTable) -> Goodwill:
        return Goodwill(
            id=table.id,
            legal_entity_id=table.legal_entity_id,
            goodwill_number=table.goodwill_number,
            acquisition_date=table.acquisition_date,
            acquisition_cost=table.acquisition_cost,
            carrying_amount=table.carrying_amount,
            accumulated_impairment=table.accumulated_impairment or Decimal(0),
            is_active=table.is_active,
            status=table.status,
            created_at=table.created_at,
            updated_at=table.updated_at,
            created_by=table.created_by,
            version=table.version,
        )

    def _from_domain(self, domain: Goodwill) -> GoodwillTable:
        return GoodwillTable(
            id=domain.id,
            legal_entity_id=domain.legal_entity_id,
            goodwill_number=domain.goodwill_number,
            acquisition_date=domain.acquisition_date,
            acquisition_cost=domain.acquisition_cost,
            carrying_amount=domain.carrying_amount,
            accumulated_impairment=domain.accumulated_impairment,
            is_active=domain.is_active,
            status=domain.status,
            created_at=domain.created_at,
            updated_at=domain.updated_at,
            created_by=domain.created_by,
            version=domain.version,
        )

    # ========================================================================
    # PORT METHODS
    # ========================================================================

    # ---- save ----
    async def save(self, goodwill: Goodwill) -> None:
        session = await self._get_session()
        table = self._from_domain(goodwill)
        existing = await session.get(GoodwillTable, goodwill.id)
        if existing:
            # Update
            for key, value in table.__dict__.items():
                if not key.startswith("_") and key != "id":
                    setattr(existing, key, value)
            existing.updated_at = datetime.utcnow()
        else:
            session.add(table)
        await session.flush()

    # ---- update ----
    async def update(self, goodwill: Goodwill) -> None:
        """
        Update goodwill with pessimistic locking to prevent race conditions.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        session = await self._get_session()
        async with session.begin():
            # 1. Lock the row with SELECT FOR UPDATE
            stmt_lock = select(GoodwillTable).where(GoodwillTable.id == goodwill.id).with_for_update()
            result = await session.execute(stmt_lock)
            existing = result.scalar_one_or_none()
            if not existing:
                raise ValueError(f"Goodwill {goodwill.id} not found")

            # 2. Update the locked row
            table = self._from_domain(goodwill)
            for key, value in table.__dict__.items():
                if not key.startswith("_") and key != "id":
                    setattr(existing, key, value)
            existing.updated_at = datetime.utcnow()
            await session.flush()

    # ---- get_by_id (1 parameter) ----
    async def get_by_id(self, goodwill_id: UUID) -> Goodwill | None:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        stmt = select(GoodwillTable).where(
            GoodwillTable.id == goodwill_id,
            GoodwillTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if not table:
            return None
        return self._to_domain(table)

    # ---- get_last_goodwill_number ----
    async def get_last_goodwill_number(self, legal_entity_id: UUID) -> str | None:
        session = await self._get_session()
        stmt = (
            select(GoodwillTable.goodwill_number)
            .where(GoodwillTable.legal_entity_id == legal_entity_id)
            .order_by(desc(GoodwillTable.created_at))
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    # ---- list_by_legal_entity ----
    async def list_by_legal_entity(self, legal_entity_id: UUID) -> list[Goodwill]:
        session = await self._get_session()
        stmt = select(GoodwillTable).where(GoodwillTable.legal_entity_id == legal_entity_id)
        result = await session.execute(stmt)
        tables = result.scalars().all()
        return [self._to_domain(t) for t in tables]

    # ---- record_impairment_journal (2 parameter) ----
    async def record_impairment_journal(self, goodwill_id: UUID, journal_id: UUID) -> None:
        """Catat journal impairment untuk goodwill."""
        session = await self._get_session()
        # Cek apakah sudah ada impairment untuk goodwill ini
        stmt = select(GoodwillImpairmentTable).where(
            GoodwillImpairmentTable.goodwill_id == goodwill_id
        ).order_by(desc(GoodwillImpairmentTable.test_date)).limit(1)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Update journal_id pada impairment terakhir
            existing.journal_id = journal_id
            existing.updated_at = datetime.utcnow()
        else:
            # Buat impairment record baru (dengan nilai default)
            impairment = GoodwillImpairmentTable(
                id=uuid.uuid4(),
                goodwill_id=goodwill_id,
                test_date=datetime.utcnow().date(),
                impairment_amount=Decimal(0),
                recoverable_amount=Decimal(0),
                journal_id=journal_id,
                created_at=datetime.utcnow(),
                created_by=None,
            )
            session.add(impairment)
        await session.flush()

    # ========================================================================
    # INTERNAL/LEGACY METHODS (untuk kompatibilitas)
    # ========================================================================

    async def save_goodwill(self, goodwill: GoodwillTable) -> GoodwillTable:
        session = await self._get_session()
        session.add(goodwill)
        await session.flush()
        return goodwill

    async def get_goodwill_by_id(self, goodwill_id: UUID) -> GoodwillTable | None:
        session = await self._get_session()
        stmt = select(GoodwillTable).where(GoodwillTable.id == goodwill_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_goodwill_by_legal_entity(self, legal_entity_id: UUID) -> list[GoodwillTable]:
        session = await self._get_session()
        stmt = select(GoodwillTable).where(GoodwillTable.legal_entity_id == legal_entity_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_goodwill(self, legal_entity_id: UUID) -> list[GoodwillTable]:
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

    async def get_impairments_by_goodwill(self, goodwill_id: UUID) -> list[GoodwillImpairmentTable]:
        session = await self._get_session()
        stmt = select(GoodwillImpairmentTable).where(GoodwillImpairmentTable.goodwill_id == goodwill_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_impairment(self, goodwill_id: UUID) -> GoodwillImpairmentTable | None:
        session = await self._get_session()
        stmt = select(GoodwillImpairmentTable).where(
            GoodwillImpairmentTable.goodwill_id == goodwill_id
        ).order_by(desc(GoodwillImpairmentTable.test_date)).limit(1)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_goodwill_carrying_amount(self, goodwill_id: UUID, new_amount: Decimal) -> None:
        """
        Update carrying amount with pessimistic locking to prevent race conditions.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        session = await self._get_session()
        async with session.begin():
            # 1. Lock the row with SELECT FOR UPDATE
            stmt_lock = select(GoodwillTable).where(GoodwillTable.id == goodwill_id).with_for_update()
            result = await session.execute(stmt_lock)
            existing = result.scalar_one_or_none()
            if not existing:
                raise ValueError(f"Goodwill {goodwill_id} not found")

            # 2. Update the locked row
            existing.carrying_amount = new_amount
            existing.updated_at = datetime.utcnow()
            await session.flush()


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS
# ============================================================================

SQLAlchemyGoodwillRepositoryImpl = SQLAlchemyGoodwillRepository

__all__ = ["SQLAlchemyGoodwillRepository", "SQLAlchemyGoodwillRepositoryImpl"]