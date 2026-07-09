#!/usr/bin/env python3
"""
Module: sqlalchemy_umkm_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository UMKM (simplified accounting) menggunakan SQLAlchemy.
"""

from __future__ import annotations

import logging
import uuid
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.umkm_business_profile_table import UMKMProfileTable
from infrastructure.persistence_orm.umkm_transaction_table import UMKMTransactionTable
from ports.primary.umkm_repository_port import (
    UMKMRepositoryPort,
    UMKMRevenueSummary,
    UMKMTransactionEntity,
)

logger = logging.getLogger(__name__)


class SQLAlchemyUMKMRepository(UMKMRepositoryPort):
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

    async def _get_profile_id(self, legal_entity_id: UUID) -> UUID | None:
        session = await self._get_session()
        stmt = select(UMKMProfileTable.id).where(UMKMProfileTable.legal_entity_id == legal_entity_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    # ========================================================================
    # MAPPING: ORM ↔ Domain
    # ========================================================================

    def _to_domain_transaction(self, table: UMKMTransactionTable) -> UMKMTransactionEntity:
        return UMKMTransactionEntity(
            id=table.id,
            legal_entity_id=table.legal_entity_id,  # assuming table has legal_entity_id or from profile
            transaction_date=table.transaction_date,
            description=table.description,
            amount=table.amount,
            transaction_type=table.transaction_type,
            category=table.category,
            payment_method=table.payment_method,
            reference_number=table.reference_number,
            attachment_ids=[],
            created_by=table.created_by,
            created_at=table.created_at,
        )

    def _from_domain_transaction(self, entity: UMKMTransactionEntity, profile_id: UUID) -> UMKMTransactionTable:
        return UMKMTransactionTable(
            id=entity.id,
            profile_id=profile_id,
            transaction_date=entity.transaction_date,
            description=entity.description,
            amount=entity.amount,
            transaction_type=entity.transaction_type,
            category=entity.category,
            payment_method=entity.payment_method,
            reference_number=entity.reference_number,
            legal_entity_id=entity.legal_entity_id,
            created_by=entity.created_by,
            created_at=entity.created_at or datetime.utcnow(),
        )

    def _to_domain_summary(self, legal_entity_id: UUID, year: int, month: int, revenue: Decimal, expense: Decimal) -> UMKMRevenueSummary:
        net_income = revenue - expense
        pph_final_due = revenue * Decimal("0.005")  # 0.5%
        # Assume we can check if submitted status from some flag; for now set DRAFT
        return UMKMRevenueSummary(
            id=uuid.uuid4(),
            legal_entity_id=legal_entity_id,
            year=year,
            month=month,
            total_revenue=revenue,
            total_expenses=expense,
            net_income=net_income,
            pph_final_due=pph_final_due,
            pph_paid=Decimal(0),
            status="DRAFT",
            submitted_at=None,
        )

    # ========================================================================
    # PORT METHODS
    # ========================================================================

    async def save_transaction(self, transaction: UMKMTransactionEntity) -> None:
        session = await self._get_session()
        profile_id = await self._get_profile_id(transaction.legal_entity_id)
        if not profile_id:
            raise ValueError(f"UMKM profile not found for legal_entity {transaction.legal_entity_id}")
        orm = self._from_domain_transaction(transaction, profile_id)
        existing = await session.get(UMKMTransactionTable, transaction.id)
        if existing:
            # Update
            for key, value in orm.__dict__.items():
                if not key.startswith("_") and key != "id":
                    setattr(existing, key, value)
            existing.updated_at = datetime.utcnow()
        else:
            session.add(orm)
        await session.flush()

    async def get_transaction(self, transaction_id: UUID) -> UMKMTransactionEntity | None:
        session = await self._get_session()
        stmt = select(UMKMTransactionTable).where(UMKMTransactionTable.id == transaction_id)
        result = await session.execute(stmt)
        table = result.scalar_one_or_none()
        if not table:
            return None
        return self._to_domain_transaction(table)

    async def list_transactions_by_period(
        self,
        legal_entity_id: UUID,
        from_date: date,
        to_date: date,
        transaction_type: str | None = None,
    ) -> list[UMKMTransactionEntity]:
        profile_id = await self._get_profile_id(legal_entity_id)
        if not profile_id:
            return []
        session = await self._get_session()
        stmt = select(UMKMTransactionTable).where(
            UMKMTransactionTable.profile_id == profile_id,
            UMKMTransactionTable.transaction_date.between(from_date, to_date),
        )
        if transaction_type:
            stmt = stmt.where(UMKMTransactionTable.transaction_type == transaction_type)
        stmt = stmt.order_by(UMKMTransactionTable.transaction_date)
        result = await session.execute(stmt)
        tables = result.scalars().all()
        return [self._to_domain_transaction(t) for t in tables]

    async def get_monthly_revenue_summary(
        self, legal_entity_id: UUID, year: int, month: int
    ) -> UMKMRevenueSummary | None:
        profile_id = await self._get_profile_id(legal_entity_id)
        if not profile_id:
            return None
        session = await self._get_session()
        # Get total revenue
        rev_stmt = select(func.coalesce(func.sum(UMKMTransactionTable.amount), 0)).where(
            UMKMTransactionTable.profile_id == profile_id,
            UMKMTransactionTable.transaction_type == "revenue",
            UMKMTransactionTable.transaction_date.between(date(year, month, 1), date(year, month, monthrange(year, month)[1])),
        )
        rev_result = await session.execute(rev_stmt)
        revenue = rev_result.scalar() or Decimal(0)
        # Get total expenses
        exp_stmt = select(func.coalesce(func.sum(UMKMTransactionTable.amount), 0)).where(
            UMKMTransactionTable.profile_id == profile_id,
            UMKMTransactionTable.transaction_type == "expense",
            UMKMTransactionTable.transaction_date.between(date(year, month, 1), date(year, month, monthrange(year, month)[1])),
        )
        exp_result = await session.execute(exp_stmt)
        expense = exp_result.scalar() or Decimal(0)
        return self._to_domain_summary(legal_entity_id, year, month, revenue, expense)

    async def save_revenue_summary(self, summary: UMKMRevenueSummary) -> None:
        # In a real implementation, you would have a table for revenue summaries.
        # Since we don't have one, we just log or store in memory.
        logger.info(f"Saving revenue summary for {summary.year}-{summary.month}: net_income={summary.net_income}")
        # Optionally store in a temporary dict or create table later.

    async def submit_tax_report(
        self, legal_entity_id: UUID, year: int, month: int, submitted_by: UUID
    ) -> None:
        # Mark tax report as submitted. We could store this status in a separate table or update profile.
        logger.info(f"Submitting tax report for {year}-{month} by {submitted_by} for legal_entity {legal_entity_id}")
        # For demo, we could update a status flag on profile or store a submission record.
        # If we had a table for monthly tax submissions, we would insert/update here.
        # For now, just log and maybe set a flag on profile (if we add a field).
        # Since we don't have a field, we'll just pass.
        pass

    async def get_total_revenue_ytd(self, legal_entity_id: UUID, year: int) -> Decimal:
        profile_id = await self._get_profile_id(legal_entity_id)
        if not profile_id:
            return Decimal(0)
        session = await self._get_session()
        stmt = select(func.coalesce(func.sum(UMKMTransactionTable.amount), 0)).where(
            UMKMTransactionTable.profile_id == profile_id,
            UMKMTransactionTable.transaction_type == "revenue",
            UMKMTransactionTable.transaction_date.between(date(year, 1, 1), date(year, 12, 31)),
        )
        result = await session.execute(stmt)
        return result.scalar() or Decimal(0)

    # ========================================================================
    # INTERNAL/LEGACY METHODS (untuk kompatibilitas)
    # ========================================================================

    async def save_profile(self, profile: UMKMProfileTable) -> UMKMProfileTable:
        session = await self._get_session()
        session.add(profile)
        await session.flush()
        return profile

    async def get_profile_by_id(self, profile_id: UUID) -> UMKMProfileTable | None:
        session = await self._get_session()
        stmt = select(UMKMProfileTable).where(UMKMProfileTable.id == profile_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_profile_by_legal_entity(self, legal_entity_id: UUID) -> UMKMProfileTable | None:
        session = await self._get_session()
        stmt = select(UMKMProfileTable).where(UMKMProfileTable.legal_entity_id == legal_entity_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_profile_tax_status(self, profile_id: UUID, uses_umkm_tax: bool) -> None:
        """
        Update UMKM tax status with pessimistic locking to prevent race conditions.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        session = await self._get_session()
        async with session.begin():
            # 1. Lock the row with SELECT FOR UPDATE
            stmt_lock = select(UMKMProfileTable).where(
                UMKMProfileTable.id == profile_id
            ).with_for_update()
            result = await session.execute(stmt_lock)
            profile = result.scalar_one_or_none()
            if not profile:
                raise ValueError(f"UMKM profile {profile_id} not found")

            # 2. Update the locked row
            profile.uses_umkm_tax = uses_umkm_tax
            await session.flush()
            logger.info(f"UMKM profile {profile_id} tax status updated to {uses_umkm_tax}")

    async def get_transaction_by_id(self, transaction_id: UUID) -> UMKMTransactionTable | None:
        session = await self._get_session()
        stmt = select(UMKMTransactionTable).where(UMKMTransactionTable.id == transaction_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_transactions_by_period(
        self, profile_id: UUID, from_date: date, to_date: date
    ) -> list[UMKMTransactionTable]:
        session = await self._get_session()
        stmt = (
            select(UMKMTransactionTable)
            .where(
                UMKMTransactionTable.profile_id == profile_id,
                UMKMTransactionTable.transaction_date.between(from_date, to_date),
            )
            .order_by(UMKMTransactionTable.transaction_date)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_total_revenue_by_period(
        self, profile_id: UUID, from_date: date, to_date: date
    ) -> Decimal:
        session = await self._get_session()
        stmt = select(UMKMTransactionTable.amount).where(
            UMKMTransactionTable.profile_id == profile_id,
            UMKMTransactionTable.transaction_type == "revenue",
            UMKMTransactionTable.transaction_date.between(from_date, to_date),
        )
        result = await session.execute(stmt)
        amounts = result.scalars().all()
        return sum(amounts, Decimal(0))

    async def get_monthly_summary(
        self, profile_id: UUID, year: int, month: int
    ) -> dict[str, Decimal]:
        from_date = date(year, month, 1)
        last_day = monthrange(year, month)[1]
        to_date = date(year, month, last_day)

        revenue = await self.get_total_revenue_by_period(profile_id, from_date, to_date)
        session = await self._get_session()
        stmt = select(UMKMTransactionTable.amount).where(
            UMKMTransactionTable.profile_id == profile_id,
            UMKMTransactionTable.transaction_type == "expense",
            UMKMTransactionTable.transaction_date.between(from_date, to_date),
        )
        result = await session.execute(stmt)
        expenses = result.scalars().all()
        total_expense = sum(expenses, Decimal(0))
        return {"revenue": revenue, "expense": total_expense, "net": revenue - total_expense}


# ============================================================================
# ALIAS UNTUK KOMPATIBILITAS
# ============================================================================
SQLAlchemyUmkmRepository = SQLAlchemyUMKMRepository
SQLAlchemyUmkmRepositoryImpl = SQLAlchemyUMKMRepository

__all__ = [
    "SQLAlchemyUMKMRepository",
    "SQLAlchemyUmkmRepository",
    "SQLAlchemyUmkmRepositoryImpl",
]