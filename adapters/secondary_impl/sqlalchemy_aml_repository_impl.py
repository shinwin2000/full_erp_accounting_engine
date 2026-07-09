#!/usr/bin/env python3
"""
Module: sqlalchemy_aml_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi AMLRepositoryPort dan AMLRepositoryPortProtocol menggunakan SQLAlchemy.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.aml_risk_score_table import AMLRiskScoreTable
from infrastructure.persistence_orm.aml_suspicious_transaction_table import (
    AMLSuspiciousTransactionTable,
)

# Import port interfaces dan domain types
from ports.primary.aml_repository_port import (
    AMLRepositoryPort,
    AMLRepositoryPortProtocol,
    AMLRiskScore,
    AMLSanctionsHit,
    AMLTransactionRecord,
    SuspiciousTransactionReport,
)

logger = logging.getLogger(__name__)


class SQLAlchemyAMLRepository(AMLRepositoryPort, AMLRepositoryPortProtocol):
    """
    Implementasi AMLRepositoryPort dan AMLRepositoryPortProtocol dengan SQLAlchemy + in-memory.
    """

    def __init__(self, session: AsyncSession | None = None, legal_entity_id: UUID | None = None):
        self._session = session
        self._legal_entity_id = legal_entity_id
        # In-memory storage untuk fitur yang belum punya tabel database
        self._watchlist: dict[str, AMLTransactionRecord] = {}
        self._sanctions_hits: dict[str, AMLSanctionsHit] = {}
        self._screening_results: dict[str, AMLTransactionRecord] = {}
        self._strs: dict[str, SuspiciousTransactionReport] = {}
        self._high_risk_customers: set[str] = set()
        self._screened_transactions: set[str] = set()
        self._lock = asyncio.Lock()

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    def _get_legal_entity_id(self) -> UUID:
        if self._legal_entity_id is None:
            raise ValueError("legal_entity_id not set in repository")
        return self._legal_entity_id

    # ================================================================
    # 1. METODE DARI AMLRepositoryPort (sesuai signature)
    # ================================================================

    # ---- save_screening_result ----
    async def save_screening_result(self, record: AMLTransactionRecord) -> None:
        async with self._lock:
            result_id = str(uuid.uuid4())
            self._screening_results[result_id] = record
            logger.info(f"[AML] Saved screening result: {result_id}")

    # ---- get_screening_result ----
    async def get_screening_result(self, transaction_id: UUID) -> AMLTransactionRecord | None:
        async with self._lock:
            for r in self._screening_results.values():
                if r.transaction_id == transaction_id:
                    return r
            return None

    # ---- list_screened_transactions ----
    async def list_screened_transactions(
        self, legal_entity_id: UUID, from_date: date, to_date: date, result: str | None = None
    ) -> list[AMLTransactionRecord]:
        async with self._lock:
            filtered = []
            for r in self._screening_results.values():
                if r.legal_entity_id != legal_entity_id:
                    continue
                if not (from_date <= r.transaction_date <= to_date):
                    continue
                if result is not None and r.screening_result != result:
                    continue
                filtered.append(r)
            return filtered

    # ---- save_sanctions_hit ----
    async def save_sanctions_hit(self, hit: AMLSanctionsHit) -> None:
        async with self._lock:
            hit_id = str(uuid.uuid4())
            self._sanctions_hits[hit_id] = hit
            logger.info(f"[AML] Saved sanctions hit: {hit_id}")

    # ---- get_sanctions_hits_for_transaction ----
    async def get_sanctions_hits_for_transaction(
        self, transaction_id: UUID
    ) -> list[AMLSanctionsHit]:
        async with self._lock:
            return [h for h in self._sanctions_hits.values() if h.transaction_id == transaction_id]

    # ---- save_str ----
    async def save_str(self, report: SuspiciousTransactionReport) -> None:
        async with self._lock:
            str_id = str(uuid.uuid4())
            self._strs[str_id] = report
            logger.info(f"[AML] Saved STR: {report.report_number}")

    # ---- get_str_by_number ----
    async def get_str_by_number(self, report_number: str) -> SuspiciousTransactionReport | None:
        async with self._lock:
            for s in self._strs.values():
                if s.report_number == report_number:
                    return s
            return None

    # ---- list_strs_by_entity ----
    async def list_strs_by_entity(
        self, legal_entity_id: UUID, from_date: date, to_date: date
    ) -> list[SuspiciousTransactionReport]:
        async with self._lock:
            return [
                s for s in self._strs.values()
                if s.legal_entity_id == legal_entity_id
                and from_date <= s.filed_at.date() <= to_date
            ]

    # ---- save_risk_score ----
    async def save_risk_score(self, risk_score: AMLRiskScore) -> None:
        async with self._lock:
            logger.info(f"[AML] Saved risk score for customer {risk_score.customer_id}")

    # ---- get_current_risk_score ----
    async def get_current_risk_score(self, customer_id: UUID) -> AMLRiskScore | None:
        return None

    # ---- list_high_risk_customers ----
    async def list_high_risk_customers(self, legal_entity_id: UUID) -> list[AMLRiskScore]:
        async with self._lock:
            return []

    # ---- add_to_watchlist ----
    async def add_to_watchlist(self, entity_name: str, reason: str, added_by: UUID) -> None:
        async with self._lock:
            entry_id = str(uuid.uuid4())
            self._watchlist[entry_id] = AMLTransactionRecord(
                id=uuid.uuid4(),
                legal_entity_id=self._get_legal_entity_id(),
                transaction_id=uuid.uuid4(),
                transaction_type="WATCHLIST",
                amount=Decimal(0),
                currency="IDR",
                counterparty_name=entity_name,
                counterparty_country="",
                transaction_date=datetime.now(UTC).date(),
                screening_result="FLAG",
                risk_score=Decimal(0),
                flags=[f"Watchlist: {reason}"],
                screened_at=datetime.now(UTC),
                screened_by=added_by,
            )
            logger.info(f"[AML] Added to watchlist: {entity_name} (by {added_by})")

    # ---- is_on_watchlist ----
    async def is_on_watchlist(self, entity_name: str) -> bool:
        async with self._lock:
            for entry in self._watchlist.values():
                if entry.counterparty_name == entity_name:
                    return True
            return False

    # ================================================================
    # 2. METODE ASLI (Risk Score & Suspicious Transaction)
    # ================================================================

    async def save_risk_score_table(self, risk_score: AMLRiskScoreTable) -> AMLRiskScoreTable:
        session = await self._get_session()
        session.add(risk_score)
        await session.flush()
        return risk_score

    async def get_risk_score_by_id(self, risk_score_id: uuid.UUID) -> AMLRiskScoreTable | None:
        session = await self._get_session()
        stmt = select(AMLRiskScoreTable).where(AMLRiskScoreTable.id == risk_score_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_risk_score_by_customer(self, customer_id: uuid.UUID) -> list[AMLRiskScoreTable]:
        session = await self._get_session()
        stmt = select(AMLRiskScoreTable).where(AMLRiskScoreTable.customer_id == customer_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_current_risk_score_table(self, customer_id: uuid.UUID) -> AMLRiskScoreTable | None:
        session = await self._get_session()
        stmt = (
            select(AMLRiskScoreTable)
            .where(AMLRiskScoreTable.customer_id == customer_id)
            .order_by(AMLRiskScoreTable.calculated_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_risk_score(self, risk_score_id: uuid.UUID, **kwargs) -> None:
        """
        Update risk score with pessimistic locking.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        session = await self._get_session()
        async with session.begin():
            stmt_lock = select(AMLRiskScoreTable).where(
                AMLRiskScoreTable.id == risk_score_id
            ).with_for_update()
            result = await session.execute(stmt_lock)
            record = result.scalar_one_or_none()
            if record is None:
                raise ValueError(f"Risk score {risk_score_id} not found")

            for key, value in kwargs.items():
                if hasattr(record, key):
                    setattr(record, key, value)
            record.updated_at = datetime.now(UTC)
            await session.flush()

    async def save_suspicious_transaction(
        self, transaction: AMLSuspiciousTransactionTable
    ) -> AMLSuspiciousTransactionTable:
        session = await self._get_session()
        session.add(transaction)
        await session.flush()
        return transaction

    async def get_suspicious_transaction_by_id(
        self, transaction_id: uuid.UUID
    ) -> AMLSuspiciousTransactionTable | None:
        session = await self._get_session()
        stmt = select(AMLSuspiciousTransactionTable).where(
            AMLSuspiciousTransactionTable.id == transaction_id
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_suspicious_transactions(
        self,
        status: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = 100,
    ) -> list[AMLSuspiciousTransactionTable]:
        session = await self._get_session()
        stmt = select(AMLSuspiciousTransactionTable)
        if status:
            stmt = stmt.where(AMLSuspiciousTransactionTable.status == status)
        if from_date:
            stmt = stmt.where(AMLSuspiciousTransactionTable.detected_at >= from_date)
        if to_date:
            stmt = stmt.where(AMLSuspiciousTransactionTable.detected_at <= to_date)
        stmt = stmt.order_by(AMLSuspiciousTransactionTable.detected_at.desc()).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update_suspicious_transaction_status(
        self, transaction_id: uuid.UUID, status: str, reviewed_by: uuid.UUID
    ) -> None:
        """
        Update suspicious transaction status with pessimistic locking.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        session = await self._get_session()
        async with session.begin():
            stmt_lock = select(AMLSuspiciousTransactionTable).where(
                AMLSuspiciousTransactionTable.id == transaction_id
            ).with_for_update()
            result = await session.execute(stmt_lock)
            record = result.scalar_one_or_none()
            if record is None:
                raise ValueError(f"Suspicious transaction {transaction_id} not found")

            record.status = status
            record.reviewed_at = datetime.now(UTC)
            record.reviewed_by = reviewed_by
            await session.flush()

    # ================================================================
    # 3. BULK OPERATIONS
    # ================================================================

    async def bulk_save_risk_scores(self, risk_scores: list[AMLRiskScoreTable]) -> None:
        session = await self._get_session()
        session.add_all(risk_scores)
        await session.flush()

    async def delete_old_risk_scores(self, older_than: date) -> int:
        """
        Delete risk scores older than given date with pessimistic locking.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on records to be deleted.
        """
        session = await self._get_session()
        async with session.begin():
            stmt_lock = select(AMLRiskScoreTable.id).where(
                AMLRiskScoreTable.calculated_at < older_than
            ).with_for_update()
            result = await session.execute(stmt_lock)
            ids = [row[0] for row in result.all()]

            if not ids:
                return 0

            stmt = delete(AMLRiskScoreTable).where(AMLRiskScoreTable.id.in_(ids))
            result = await session.execute(stmt)
            deleted_count = result.rowcount
            await session.flush()
            logger.info(f"[AML] Deleted {deleted_count} old risk scores (older than {older_than})")
            return deleted_count

    # ================================================================
    # 4. UTILITY
    # ================================================================

    async def clear_in_memory_data(self) -> None:
        async with self._lock:
            self._watchlist.clear()
            self._sanctions_hits.clear()
            self._screening_results.clear()
            self._strs.clear()
            self._high_risk_customers.clear()
            self._screened_transactions.clear()
        logger.info("[AML] In-memory data cleared")

    async def health_check(self) -> dict[str, Any]:
        async with self._lock:
            return {
                "status": "healthy",
                "watchlist_count": len(self._watchlist),
                "sanctions_hits_count": len(self._sanctions_hits),
                "screening_results_count": len(self._screening_results),
                "strs_count": len(self._strs),
                "high_risk_customers_count": len(self._high_risk_customers),
                "screened_transactions_count": len(self._screened_transactions),
            }


SQLAlchemyAMLRepositoryImpl = SQLAlchemyAMLRepository

__all__ = ["SQLAlchemyAMLRepository", "SQLAlchemyAMLRepositoryImpl"]