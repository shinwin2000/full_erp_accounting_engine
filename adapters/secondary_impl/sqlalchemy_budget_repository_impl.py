#!/usr/bin/env python3
"""
Module: sqlalchemy_budget_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Budget (anggaran) menggunakan SQLAlchemy.
Perbaikan:
  - [FIX] Race condition pada update dan update_budget_amount dengan pessimistic locking.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.budget_table import BudgetLineTable, BudgetTable
from ports.primary.budget_repository_port import (
    BudgetEntity,
    BudgetLineEntity,
    BudgetRepositoryPort,
)


class SQLAlchemyBudgetRepository(BudgetRepositoryPort):
    """Implementasi BudgetRepositoryPort dengan SQLAlchemy."""

    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        self._audit_log: list[dict[str, Any]] = []

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    # ========================================================================
    # MAPPING HELPERS
    # ========================================================================

    def _entity_to_orm_header(self, entity: BudgetEntity) -> BudgetTable:
        return BudgetTable(
            id=entity.id,
            legal_entity_id=entity.legal_entity_id,
            budget_code=entity.budget_code,
            budget_name=entity.budget_name,
            budget_type=entity.budget_type,
            fiscal_year=entity.fiscal_year,
            period=entity.period,
            version=entity.version,
            status=entity.status,
            effective_date=entity.effective_date,
            expiry_date=entity.expiry_date,
            currency=entity.currency,
            is_locked=entity.is_locked,
            notes=entity.notes,
            tags=entity.tags,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            created_by=entity.created_by,
            updated_by=entity.updated_by,
            approved_at=entity.approved_at,
            approved_by=entity.approved_by,
            submitted_at=entity.submitted_at,
            submitted_by=entity.submitted_by,
            rejected_at=entity.rejected_at,
            rejected_by=entity.rejected_by,
            rejection_reason=entity.rejection_reason,
        )

    def _orm_header_to_entity(self, header: BudgetTable, lines: list[BudgetLineTable]) -> BudgetEntity:
        return BudgetEntity(
            id=header.id,
            legal_entity_id=header.legal_entity_id,
            budget_code=header.budget_code,
            budget_name=header.budget_name,
            budget_type=header.budget_type,
            fiscal_year=header.fiscal_year,
            period=header.period,
            version=header.version,
            status=header.status,
            effective_date=header.effective_date,
            expiry_date=header.expiry_date,
            currency=header.currency,
            total_amount=sum(line.amount for line in lines),
            notes=header.notes,
            tags=header.tags,
            is_locked=header.is_locked,
            created_at=header.created_at,
            updated_at=header.updated_at,
            created_by=header.created_by,
            updated_by=header.updated_by,
            approved_at=header.approved_at,
            approved_by=header.approved_by,
            submitted_at=header.submitted_at,
            submitted_by=header.submitted_by,
            rejected_at=header.rejected_at,
            rejected_by=header.rejected_by,
            rejection_reason=header.rejection_reason,
            version_number=header.version,
            lines=[
                BudgetLineEntity(
                    id=line.id,
                    account_id=line.account_id,
                    account_code=line.account_code,
                    amount=line.amount,
                    note=line.note,
                    created_at=line.created_at,
                    updated_at=line.updated_at,
                )
                for line in lines
            ],
        )

    def _line_entity_to_orm(self, entity: BudgetLineEntity, budget_id: UUID) -> BudgetLineTable:
        return BudgetLineTable(
            id=entity.id,
            budget_id=budget_id,
            account_id=entity.account_id,
            account_code=entity.account_code,
            amount=entity.amount,
            note=entity.note,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    async def _log_audit(self, action: str, budget_id: UUID, details: dict[str, Any]) -> None:
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "budget_id": str(budget_id),
            "details": details,
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    # ========================================================================
    # CRUD METHODS (dari port)
    # ========================================================================

    async def save(self, budget: BudgetEntity) -> None:
        """Simpan budget baru."""
        session = await self._get_session()
        header = self._entity_to_orm_header(budget)
        session.add(header)
        for line in budget.lines:
            line_orm = self._line_entity_to_orm(line, budget.id)
            session.add(line_orm)
        await session.flush()
        await self._log_audit("SAVE", budget.id, {"budget_code": budget.budget_code})
        from infrastructure.telemetry import logger
        logger.info(f"Budget saved: {budget.budget_code}")

    async def update(self, budget: BudgetEntity) -> None:
        """Update budget yang sudah ada (dengan pessimistic locking)."""
        session = await self._get_session()
        async with session.begin():
            # Lock header untuk mencegah race condition
            stmt = select(BudgetTable).where(BudgetTable.id == budget.id).with_for_update()
            result = await session.execute(stmt)
            header = result.scalar_one_or_none()
            if not header:
                raise ValueError(f"Budget {budget.id} not found")

            # Update header fields
            header.budget_code = budget.budget_code
            header.budget_name = budget.budget_name
            header.budget_type = budget.budget_type
            header.fiscal_year = budget.fiscal_year
            header.period = budget.period
            header.version = budget.version
            header.status = budget.status
            header.effective_date = budget.effective_date
            header.expiry_date = budget.expiry_date
            header.currency = budget.currency
            header.is_locked = budget.is_locked
            header.notes = budget.notes
            header.tags = budget.tags
            header.updated_at = budget.updated_at
            header.updated_by = budget.updated_by
            header.approved_at = budget.approved_at
            header.approved_by = budget.approved_by
            header.submitted_at = budget.submitted_at
            header.submitted_by = budget.submitted_by
            header.rejected_at = budget.rejected_at
            header.rejected_by = budget.rejected_by
            header.rejection_reason = budget.rejection_reason
            header.version = budget.version_number

            # Update lines: delete old, insert new
            await session.execute(
                BudgetLineTable.__table__.delete().where(BudgetLineTable.budget_id == budget.id)
            )
            for line in budget.lines:
                line_orm = self._line_entity_to_orm(line, budget.id)
                session.add(line_orm)

            await session.flush()
            await self._log_audit("UPDATE", budget.id, {"budget_code": budget.budget_code})
            from infrastructure.telemetry import logger
            logger.info(f"Budget updated: {budget.budget_code}")

    async def get_by_id(self, budget_id: UUID) -> BudgetEntity | None:
        """Ambil budget berdasarkan ID."""
        session = await self._get_session()
        stmt = select(BudgetTable).where(BudgetTable.id == budget_id, BudgetTable.deleted_at.is_(None))
        result = await session.execute(stmt)
        header = result.scalar_one_or_none()
        if not header:
            return None

        lines_stmt = select(BudgetLineTable).where(BudgetLineTable.budget_id == budget_id)
        lines_result = await session.execute(lines_stmt)
        lines = lines_result.scalars().all()

        return self._orm_header_to_entity(header, lines)

    async def get_by_code_and_year(
        self, legal_entity_id: UUID, budget_code: str, fiscal_year: int
    ) -> BudgetEntity | None:
        """Ambil budget berdasarkan kode dan tahun fiskal."""
        session = await self._get_session()
        stmt = select(BudgetTable).where(
            BudgetTable.legal_entity_id == legal_entity_id,
            BudgetTable.budget_code == budget_code,
            BudgetTable.fiscal_year == fiscal_year,
            BudgetTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        header = result.scalar_one_or_none()
        if not header:
            return None

        lines_stmt = select(BudgetLineTable).where(BudgetLineTable.budget_id == header.id)
        lines_result = await session.execute(lines_stmt)
        lines = lines_result.scalars().all()

        return self._orm_header_to_entity(header, lines)

    async def get_by_name_and_year(
        self, legal_entity_id: UUID, budget_name: str, fiscal_year: int
    ) -> BudgetEntity | None:
        """Ambil budget berdasarkan nama dan tahun fiskal."""
        session = await self._get_session()
        stmt = select(BudgetTable).where(
            BudgetTable.legal_entity_id == legal_entity_id,
            BudgetTable.budget_name == budget_name,
            BudgetTable.fiscal_year == fiscal_year,
            BudgetTable.deleted_at.is_(None),
        )
        result = await session.execute(stmt)
        header = result.scalar_one_or_none()
        if not header:
            return None

        lines_stmt = select(BudgetLineTable).where(BudgetLineTable.budget_id == header.id)
        lines_result = await session.execute(lines_stmt)
        lines = lines_result.scalars().all()

        return self._orm_header_to_entity(header, lines)

    async def list_by_legal_entity(
        self, legal_entity_id: UUID, fiscal_year: int | None = None, status: str | None = None
    ) -> list[BudgetEntity]:
        """Daftar budget untuk entitas legal."""
        session = await self._get_session()
        conditions = [
            BudgetTable.legal_entity_id == legal_entity_id,
            BudgetTable.deleted_at.is_(None),
        ]
        if fiscal_year:
            conditions.append(BudgetTable.fiscal_year == fiscal_year)
        if status:
            conditions.append(BudgetTable.status == status)

        stmt = select(BudgetTable).where(and_(*conditions)).order_by(BudgetTable.created_at.desc())
        result = await session.execute(stmt)
        headers = result.scalars().all()

        entities = []
        for header in headers:
            lines_stmt = select(BudgetLineTable).where(BudgetLineTable.budget_id == header.id)
            lines_result = await session.execute(lines_stmt)
            lines = lines_result.scalars().all()
            entities.append(self._orm_header_to_entity(header, lines))

        return entities

    async def get_last_budget_code(self, legal_entity_id: UUID) -> str | None:
        """Dapatkan kode budget terakhir yang digunakan."""
        session = await self._get_session()
        stmt = select(BudgetTable.budget_code).where(
            BudgetTable.legal_entity_id == legal_entity_id,
            BudgetTable.deleted_at.is_(None),
        ).order_by(BudgetTable.created_at.desc()).limit(1)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete(self, budget_id: UUID) -> bool:
        """Hapus budget (soft delete)."""
        session = await self._get_session()
        async with session.begin():
            stmt = select(BudgetTable).where(BudgetTable.id == budget_id).with_for_update()
            result = await session.execute(stmt)
            header = result.scalar_one_or_none()
            if not header:
                return False

            header.deleted_at = datetime.utcnow()
            await session.flush()
            await self._log_audit("DELETE", budget_id, {})
            from infrastructure.telemetry import logger
            logger.info(f"Budget {budget_id} soft deleted")
            return True

    # ========================================================================
    # METODE TAMBAHAN (untuk kompatibilitas dengan kode lama)
    # ========================================================================

    async def save_budget(self, budget: BudgetTable) -> BudgetTable:
        """Simpan budget ORM langsung (untuk kompatibilitas)."""
        session = await self._get_session()
        session.add(budget)
        await session.flush()
        return budget

    async def get_budget_by_id(self, budget_id: UUID) -> BudgetTable | None:
        """Ambil budget ORM langsung (untuk kompatibilitas)."""
        session = await self._get_session()
        stmt = select(BudgetTable).where(BudgetTable.id == budget_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_budgets_by_fiscal_year(self, fiscal_year: int, legal_entity_id: UUID) -> list[BudgetTable]:
        """Ambil budget berdasarkan tahun fiskal (ORM)."""
        session = await self._get_session()
        stmt = select(BudgetTable).where(
            BudgetTable.fiscal_year == fiscal_year,
            BudgetTable.legal_entity_id == legal_entity_id
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_budget_by_account(self, account_code: str, fiscal_year: int, legal_entity_id: UUID) -> BudgetTable | None:
        """Ambil budget berdasarkan akun (ORM)."""
        session = await self._get_session()
        stmt = select(BudgetTable).where(
            BudgetTable.account_code == account_code,
            BudgetTable.fiscal_year == fiscal_year,
            BudgetTable.legal_entity_id == legal_entity_id
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_budget_amount(self, budget_id: UUID, amount: Decimal) -> None:
        """Update amount dengan pessimistic locking."""
        session = await self._get_session()
        async with session.begin():
            stmt = select(BudgetTable).where(BudgetTable.id == budget_id).with_for_update()
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if not existing:
                raise ValueError(f"Budget {budget_id} not found")
            existing.amount = amount
            existing.updated_at = func.now()
            await session.flush()

    # ========================================================================
    # BUDGET ACTUAL (untuk actual tracking)
    # ========================================================================

    async def save_budget_actual(self, actual: Any) -> Any:
        """Simpan actual budget."""
        session = await self._get_session()
        session.add(actual)
        await session.flush()
        return actual

    async def get_actuals_by_budget(self, budget_id: UUID, from_date: date, to_date: date) -> list[Any]:
        """Ambil actuals berdasarkan budget dan range tanggal."""
        from infrastructure.persistence_orm.budget_actual_table import BudgetActualTable
        session = await self._get_session()
        stmt = select(BudgetActualTable).where(
            BudgetActualTable.budget_id == budget_id,
            BudgetActualTable.transaction_date.between(from_date, to_date)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_total_actual_for_budget(self, budget_id: UUID) -> Decimal:
        """Total actual untuk budget."""
        from infrastructure.persistence_orm.budget_actual_table import BudgetActualTable
        session = await self._get_session()
        stmt = select(func.sum(BudgetActualTable.amount)).where(BudgetActualTable.budget_id == budget_id)
        result = await session.execute(stmt)
        return result.scalar() or Decimal(0)

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset:offset + limit]


# ============================================================================
# EKSPOR
# ============================================================================

__all__ = ["SQLAlchemyBudgetRepository"]
