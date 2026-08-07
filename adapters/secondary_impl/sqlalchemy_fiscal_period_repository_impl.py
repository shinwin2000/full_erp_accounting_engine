#!/usr/bin/env python3
"""
Module: sqlalchemy_fiscal_period_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Fiscal Period menggunakan SQLAlchemy.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from domain.fiscal_period.aggregate_root import FiscalPeriod
from infrastructure.persistence_orm.fiscal_period_table import FiscalPeriodTable
from ports.primary.fiscal_period_repository_port import FiscalPeriodRepositoryPort


class SQLAlchemyFiscalPeriodRepository(FiscalPeriodRepositoryPort):
    def __init__(self, session: AsyncSession | None = None, legal_entity_id: UUID | None = None):
        self._session = session
        self._legal_entity_id = legal_entity_id

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session_factory
            factory = await get_async_session_factory()
            self._session = factory()
        return self._session

    def _get_legal_entity_id(self) -> UUID:
        if self._legal_entity_id is None:
            raise ValueError("legal_entity_id not set in repository")
        return self._legal_entity_id

    # ---- Mapping helpers ----
    def _to_domain(self, table: FiscalPeriodTable) -> FiscalPeriod:
        return FiscalPeriod(
            id=table.id,
            legal_entity_id=table.legal_entity_id,
            fiscal_year=table.fiscal_year,
            period_number=table.period_number,
            start_date=table.start_date,
            end_date=table.end_date,
            status=table.status,
            closed_at=table.closed_at,
            closed_by=table.closed_by,
            reopened_at=table.reopened_at,
            reopened_by=table.reopened_by,
            reopen_reason=table.reopen_reason,
        )

    def _from_domain(self, period: FiscalPeriod) -> FiscalPeriodTable:
        return FiscalPeriodTable(
            id=period.id,
            legal_entity_id=period.legal_entity_id,
            fiscal_year=period.fiscal_year,
            period_number=period.period_number,
            start_date=period.start_date,
            end_date=period.end_date,
            status=period.status,
            closed_at=period.closed_at,
            closed_by=period.closed_by,
            reopened_at=period.reopened_at,
            reopened_by=period.reopened_by,
            reopen_reason=period.reopen_reason,
        )

    # ---- Core methods ----
    async def save(self, fiscal_period: FiscalPeriod) -> None:
        session = await self._get_session()
        table = self._from_domain(fiscal_period)
        existing = await session.get(FiscalPeriodTable, fiscal_period.id)
        if existing:
            for key, value in table.__dict__.items():
                if key != '_sa_instance_state':
                    setattr(existing, key, value)
        else:
            session.add(table)
        await session.flush()

    async def find_by_id(self, period_id: UUID) -> FiscalPeriod | None:
        session = await self._get_session()
        stmt = select(FiscalPeriodTable).where(FiscalPeriodTable.id == period_id)
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        return self._to_domain(table) if table else None

    async def find_by_date(self, target_date: date) -> FiscalPeriod | None:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        stmt = select(FiscalPeriodTable).where(
            FiscalPeriodTable.start_date <= target_date,
            FiscalPeriodTable.end_date >= target_date,
            FiscalPeriodTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        return self._to_domain(table) if table else None

    async def find_active_period(self) -> FiscalPeriod | None:
        legal_entity_id = self._get_legal_entity_id()
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
        table = result.scalar_one_or_none()
        return self._to_domain(table) if table else None

    async def find_all_ordered(self) -> list[FiscalPeriod]:
        legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        stmt = select(FiscalPeriodTable).where(
            FiscalPeriodTable.legal_entity_id == legal_entity_id
        ).order_by(FiscalPeriodTable.period_number)
        result = await session.execute(stmt)
        tables = result.scalars().all()
        return [self._to_domain(t) for t in tables]

    async def is_period_locked_for_module(self, target_date: date, module_name: str) -> bool:
        # Stub: selalu False karena belum implementasi lock per modul
        return False

    # ---- Additional methods for service ----
    async def list_by_legal_entity(
        self,
        legal_entity_id: UUID,
        limit: int = 100,
        offset: int = 0,
        from_year: int | None = None,
        to_year: int | None = None,
        status: str | None = None,
    ) -> list[FiscalPeriod]:
        session = await self._get_session()
        stmt = select(FiscalPeriodTable).where(
            FiscalPeriodTable.legal_entity_id == legal_entity_id
        )
        if from_year is not None:
            stmt = stmt.where(FiscalPeriodTable.fiscal_year >= from_year)
        if to_year is not None:
            stmt = stmt.where(FiscalPeriodTable.fiscal_year <= to_year)
        if status is not None:
            # Convert PeriodStatus enum to string value if needed
            status_value = status.value if hasattr(status, 'value') else status
            stmt = stmt.where(FiscalPeriodTable.status == status_value)
        stmt = stmt.order_by(FiscalPeriodTable.period_number).offset(offset).limit(limit)
        result = await session.execute(stmt)
        tables = result.scalars().all()
        return [self._to_domain(t) for t in tables]

    async def list_by_fiscal_year(
        self, legal_entity_id: UUID, fiscal_year: int
    ) -> list[FiscalPeriod]:
        session = await self._get_session()
        stmt = (
            select(FiscalPeriodTable)
            .where(
                FiscalPeriodTable.legal_entity_id == legal_entity_id,
                FiscalPeriodTable.fiscal_year == fiscal_year,
            )
            .order_by(FiscalPeriodTable.period_number)
        )
        result = await session.execute(stmt)
        tables = result.scalars().all()
        return [self._to_domain(t) for t in tables]

    # ---- Legacy internal methods (for backward compatibility) ----
    async def get_by_fiscal_year(
        self, fiscal_year: int, legal_entity_id: UUID | None = None
    ) -> list[FiscalPeriodTable]:
        if legal_entity_id is None:
            legal_entity_id = self._get_legal_entity_id()
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
        self, date_obj: date, legal_entity_id: UUID | None = None
    ) -> FiscalPeriodTable | None:
        if legal_entity_id is None:
            legal_entity_id = self._get_legal_entity_id()
        session = await self._get_session()
        stmt = select(FiscalPeriodTable).where(
            FiscalPeriodTable.start_date <= date_obj,
            FiscalPeriodTable.end_date >= date_obj,
            FiscalPeriodTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_current_open_period(
        self, legal_entity_id: UUID | None = None
    ) -> FiscalPeriodTable | None:
        if legal_entity_id is None:
            legal_entity_id = self._get_legal_entity_id()
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

    async def close_period(self, period_id: UUID, closed_by: UUID) -> None:
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
        self, period_id: UUID, reopened_by: UUID, reason: str
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


# === ALIAS ===
SQLAlchemyFiscalPeriodRepositoryImpl = SQLAlchemyFiscalPeriodRepository

__all__ = [
    "SQLAlchemyFiscalPeriodRepository",
    "SQLAlchemyFiscalPeriodRepositoryImpl",
]
