#!/usr/bin/env python3
"""
Module: sqlalchemy_budget_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Budget (anggaran) menggunakan SQLAlchemy.
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
    def __init__(self, session: AsyncSession):
        self._session = session

    # ========== Budget Header ==========
    async def save_budget(self, budget: BudgetTable) -> BudgetTable:
        self._session.add(budget)
        await self._session.flush()
        return budget

    async def get_budget_by_id(self, budget_id: uuid.UUID) -> BudgetTable | None:
        stmt = select(BudgetTable).where(BudgetTable.id == budget_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_budgets_by_fiscal_year(
        self, fiscal_year: int, legal_entity_id: uuid.UUID
    ) -> list[BudgetTable]:
        stmt = select(BudgetTable).where(
            BudgetTable.fiscal_year == fiscal_year,
            BudgetTable.legal_entity_id == legal_entity_id,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_budget_by_account(
        self, account_code: str, fiscal_year: int, legal_entity_id: uuid.UUID
    ) -> BudgetTable | None:
        stmt = select(BudgetTable).where(
            BudgetTable.account_code == account_code,
            BudgetTable.fiscal_year == fiscal_year,
            BudgetTable.legal_entity_id == legal_entity_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_budget_amount(self, budget_id: uuid.UUID, amount: Decimal) -> None:
        stmt = (
            update(BudgetTable)
            .where(BudgetTable.id == budget_id)
            .values(amount=amount, updated_at=func.now())
        )
        await self._session.execute(stmt)

    # ========== Budget Actual ==========
    async def save_budget_actual(self, actual: BudgetActualTable) -> BudgetActualTable:
        self._session.add(actual)
        await self._session.flush()
        return actual

    async def get_actuals_by_budget(
        self, budget_id: uuid.UUID, from_date: date, to_date: date
    ) -> list[BudgetActualTable]:
        stmt = select(BudgetActualTable).where(
            BudgetActualTable.budget_id == budget_id,
            BudgetActualTable.transaction_date.between(from_date, to_date),
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_total_actual_for_budget(self, budget_id: uuid.UUID) -> Decimal:
        stmt = select(func.sum(BudgetActualTable.amount)).where(
            BudgetActualTable.budget_id == budget_id
        )
        result = await self._session.execute(stmt)
        return result.scalar() or Decimal(0)


__all__ = ["SQLAlchemyBudgetRepository"]
