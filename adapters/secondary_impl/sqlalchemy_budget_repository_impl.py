#!/usr/bin/env python3
"""
Module: sqlalchemy_budget_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Budget (anggaran) menggunakan SQLAlchemy.
Perbaikan:
  - [FIX] Race condition pada update dan update_budget_amount dengan pessimistic locking.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.budget_actual_table import BudgetActualTable
from infrastructure.persistence_orm.budget_table import BudgetTable
from ports.primary.budget_repository_port import BudgetRepositoryPort


class SQLAlchemyBudgetRepository(BudgetRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    # ---------- Metode dari port (wajib) ----------
    async def save(self, budget: BudgetTable) -> None:                 # ← return None
        session = await self._get_session()
        session.add(budget)
        await session.flush()

    async def get_by_id(self, budget_id: uuid.UUID) -> BudgetTable | None:
        session = await self._get_session()
        stmt = select(BudgetTable).where(BudgetTable.id == budget_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_legal_entity(
        self,
        legal_entity_id: uuid.UUID,
        fiscal_year: int | None = None           # ← parameter tambahan opsional
    ) -> list[BudgetTable]:
        session = await self._get_session()
        stmt = select(BudgetTable).where(
            BudgetTable.legal_entity_id == legal_entity_id
        )
        if fiscal_year is not None:
            stmt = stmt.where(BudgetTable.fiscal_year == fiscal_year)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_name_and_year(
        self,
        legal_entity_id: uuid.UUID,              # ← urutan & nama disesuaikan
        budget_name: str,
        fiscal_year: int
    ) -> BudgetTable | None:
        session = await self._get_session()
        stmt = select(BudgetTable).where(
            BudgetTable.name == budget_name,     # kolom 'name' sesuai ORM
            BudgetTable.fiscal_year == fiscal_year,
            BudgetTable.legal_entity_id == legal_entity_id
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update(self, budget: BudgetTable) -> None:
        session = await self._get_session()
        async with session.begin():
            # Lock the row to prevent race conditions
            stmt = select(BudgetTable).where(BudgetTable.id == budget.id).with_for_update()
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if not existing:
                raise ValueError(f"Budget {budget.id} not found")
            # Merge changes into the locked instance
            # We can update fields manually or use merge, but merge might not use the locked instance.
            # Better to update explicitly:
            for key, value in budget.__dict__.items():
                if key not in ('_sa_instance_state', 'id', 'created_at', 'created_by'):
                    setattr(existing, key, value)
            existing.updated_at = func.now()
            await session.flush()

    async def get_last_budget_number(self, legal_entity_id: uuid.UUID) -> str | None:
        session = await self._get_session()
        stmt = select(BudgetTable.budget_number).where(
            BudgetTable.legal_entity_id == legal_entity_id
        ).order_by(BudgetTable.created_at.desc()).limit(1)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    # ---------- Metode tambahan (dari kode asli) ----------
    async def save_budget(self, budget: BudgetTable) -> BudgetTable:
        await self.save(budget)                  # ← panggil save (return None)
        return budget                            # ← tetap kembalikan objek

    async def get_budget_by_id(self, budget_id: uuid.UUID) -> BudgetTable | None:
        return await self.get_by_id(budget_id)

    async def get_budgets_by_fiscal_year(self, fiscal_year: int, legal_entity_id: uuid.UUID) -> list[BudgetTable]:
        session = await self._get_session()
        stmt = select(BudgetTable).where(
            BudgetTable.fiscal_year == fiscal_year,
            BudgetTable.legal_entity_id == legal_entity_id
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_budget_by_account(self, account_code: str, fiscal_year: int, legal_entity_id: uuid.UUID) -> BudgetTable | None:
        session = await self._get_session()
        stmt = select(BudgetTable).where(
            BudgetTable.account_code == account_code,
            BudgetTable.fiscal_year == fiscal_year,
            BudgetTable.legal_entity_id == legal_entity_id
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_budget_amount(self, budget_id: uuid.UUID, amount: Decimal) -> None:
        session = await self._get_session()
        async with session.begin():
            # Lock the row to prevent race conditions
            stmt = select(BudgetTable).where(BudgetTable.id == budget_id).with_for_update()
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if not existing:
                raise ValueError(f"Budget {budget_id} not found")
            existing.amount = amount
            existing.updated_at = func.now()
            await session.flush()

    # ---------- Budget Actual ----------
    async def save_budget_actual(self, actual: BudgetActualTable) -> BudgetActualTable:
        session = await self._get_session()
        session.add(actual)
        await session.flush()
        return actual

    async def get_actuals_by_budget(self, budget_id: uuid.UUID, from_date: date, to_date: date) -> list[BudgetActualTable]:
        session = await self._get_session()
        stmt = select(BudgetActualTable).where(
            BudgetActualTable.budget_id == budget_id,
            BudgetActualTable.transaction_date.between(from_date, to_date)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_total_actual_for_budget(self, budget_id: uuid.UUID) -> Decimal:
        session = await self._get_session()
        stmt = select(func.sum(BudgetActualTable.amount)).where(BudgetActualTable.budget_id == budget_id)
        result = await session.execute(stmt)
        return result.scalar() or Decimal(0)


__all__ = ["SQLAlchemyBudgetRepository"]