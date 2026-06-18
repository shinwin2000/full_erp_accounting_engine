#!/usr/bin/env python3
"""
Module: sqlalchemy_aml_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository AML (Anti-Money Laundering) menggunakan SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.aml_risk_score_table import AMLRiskScoreTable
from infrastructure.persistence_orm.aml_suspicious_transaction_table import (
    AMLSuspiciousTransactionTable,
)
from ports.primary.aml_repository_port import AMLRepositoryPort


class SQLAlchemyAMLRepository(AMLRepositoryPort):
    """Implementasi AML repository dengan SQLAlchemy."""

    def __init__(self, session: AsyncSession):
        self._session = session

    # ========== Risk Score ==========
    async def save_risk_score(self, risk_score: AMLRiskScoreTable) -> AMLRiskScoreTable:
        self._session.add(risk_score)
        await self._session.flush()
        return risk_score

    async def get_risk_score_by_id(self, risk_score_id: uuid.UUID) -> AMLRiskScoreTable | None:
        stmt = select(AMLRiskScoreTable).where(AMLRiskScoreTable.id == risk_score_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_risk_score_by_customer(self, customer_id: uuid.UUID) -> list[AMLRiskScoreTable]:
        stmt = select(AMLRiskScoreTable).where(AMLRiskScoreTable.customer_id == customer_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_current_risk_score(self, customer_id: uuid.UUID) -> AMLRiskScoreTable | None:
        stmt = (
            select(AMLRiskScoreTable)
            .where(AMLRiskScoreTable.customer_id == customer_id)
            .order_by(AMLRiskScoreTable.calculated_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_risk_score(self, risk_score_id: uuid.UUID, **kwargs) -> None:
        stmt = (
            update(AMLRiskScoreTable).where(AMLRiskScoreTable.id == risk_score_id).values(**kwargs)
        )
        await self._session.execute(stmt)

    # ========== Suspicious Transaction ==========
    async def save_suspicious_transaction(
        self, transaction: AMLSuspiciousTransactionTable
    ) -> AMLSuspiciousTransactionTable:
        self._session.add(transaction)
        await self._session.flush()
        return transaction

    async def get_suspicious_transaction_by_id(
        self, transaction_id: uuid.UUID
    ) -> AMLSuspiciousTransactionTable | None:
        stmt = select(AMLSuspiciousTransactionTable).where(
            AMLSuspiciousTransactionTable.id == transaction_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_suspicious_transactions(
        self,
        status: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = 100,
    ) -> list[AMLSuspiciousTransactionTable]:
        stmt = select(AMLSuspiciousTransactionTable)
        if status:
            stmt = stmt.where(AMLSuspiciousTransactionTable.status == status)
        if from_date:
            stmt = stmt.where(AMLSuspiciousTransactionTable.detected_at >= from_date)
        if to_date:
            stmt = stmt.where(AMLSuspiciousTransactionTable.detected_at <= to_date)
        stmt = stmt.order_by(AMLSuspiciousTransactionTable.detected_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update_suspicious_transaction_status(
        self, transaction_id: uuid.UUID, status: str, reviewed_by: uuid.UUID
    ) -> None:
        stmt = (
            update(AMLSuspiciousTransactionTable)
            .where(AMLSuspiciousTransactionTable.id == transaction_id)
            .values(status=status, reviewed_at=datetime.utcnow(), reviewed_by=reviewed_by)
        )
        await self._session.execute(stmt)

    # ========== Bulk Operations ==========
    async def bulk_save_risk_scores(self, risk_scores: list[AMLRiskScoreTable]) -> None:
        self._session.add_all(risk_scores)
        await self._session.flush()

    async def delete_old_risk_scores(self, older_than: date) -> int:
        stmt = delete(AMLRiskScoreTable).where(AMLRiskScoreTable.calculated_at < older_than)
        result = await self._session.execute(stmt)
        return result.rowcount


__all__ = ["SQLAlchemyAMLRepository"]
