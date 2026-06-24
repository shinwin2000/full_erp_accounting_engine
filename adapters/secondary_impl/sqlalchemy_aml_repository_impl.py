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
from datetime import date, datetime, UTC
from typing import Dict, List, Optional, Any
from decimal import Decimal

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.aml_risk_score_table import AMLRiskScoreTable
from infrastructure.persistence_orm.aml_suspicious_transaction_table import (
    AMLSuspiciousTransactionTable,
)

# Import port interface
from ports.primary.aml_repository_port import (
    AMLRepositoryPort,
    AMLRepositoryPortProtocol,
    SanctionsHit,
    ScreeningResult,
    SuspiciousTransactionReport,
    WatchlistEntry,
)

logger = logging.getLogger(__name__)


class SQLAlchemyAMLRepository(AMLRepositoryPort, AMLRepositoryPortProtocol):
    """
    Implementasi AMLRepositoryPort dan AMLRepositoryPortProtocol dengan SQLAlchemy + in-memory.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        # In-memory storage untuk fitur yang belum punya tabel database
        self._watchlist: Dict[str, WatchlistEntry] = {}
        self._sanctions_hits: Dict[str, SanctionsHit] = {}
        self._screening_results: Dict[str, ScreeningResult] = {}
        self._strs: Dict[str, SuspiciousTransactionReport] = {}
        self._high_risk_customers: set[str] = set()
        self._screened_transactions: set[str] = set()
        self._lock = asyncio.Lock()

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    # ================================================================
    # 1. METODE DARI AMLRepositoryPort
    # ================================================================

    async def add_to_watchlist(self, entry: WatchlistEntry) -> str:
        async with self._lock:
            entry_id = str(uuid.uuid4())
            self._watchlist[entry_id] = entry
            logger.info(f"[AML] Added to watchlist: {entry_id}")
            return entry_id

    async def get_sanctions_hits_for_transaction(self, transaction_id: str) -> List[SanctionsHit]:
        async with self._lock:
            return [h for h in self._sanctions_hits.values() if h.transaction_id == transaction_id]

    async def get_screening_result(self, screening_id: str) -> Optional[ScreeningResult]:
        async with self._lock:
            return self._screening_results.get(screening_id)

    async def get_str_by_number(self, str_number: str) -> Optional[SuspiciousTransactionReport]:
        async with self._lock:
            for s in self._strs.values():
                if s.str_number == str_number:
                    return s
            return None

    async def is_on_watchlist(self, entity_id: str) -> bool:
        async with self._lock:
            for entry in self._watchlist.values():
                if entry.entity_id == entity_id:
                    return True
            return False

    async def list_high_risk_customers(self) -> List[str]:
        async with self._lock:
            return list(self._high_risk_customers)

    async def list_screened_transactions(self) -> List[str]:
        async with self._lock:
            return list(self._screened_transactions)

    async def list_strs_by_entity(self, entity_id: str) -> List[SuspiciousTransactionReport]:
        async with self._lock:
            return [s for s in self._strs.values() if s.entity_id == entity_id]

    async def save_sanctions_hit(self, hit: SanctionsHit) -> str:
        async with self._lock:
            hit_id = str(uuid.uuid4())
            self._sanctions_hits[hit_id] = hit
            logger.info(f"[AML] Saved sanctions hit: {hit_id}")
            return hit_id

    async def save_screening_result(self, result: ScreeningResult) -> str:
        async with self._lock:
            result_id = str(uuid.uuid4())
            self._screening_results[result_id] = result
            logger.info(f"[AML] Saved screening result: {result_id}")
            return result_id

    async def save_str(self, str_report: SuspiciousTransactionReport) -> str:
        async with self._lock:
            str_id = str(uuid.uuid4())
            self._strs[str_id] = str_report
            logger.info(f"[AML] Saved STR: {str_id}")
            return str_id

    # ================================================================
    # 2. METODE DARI AMLRepositoryPortProtocol (jika ada tambahan)
    # ================================================================
    # Karena AMLRepositoryPortProtocol mungkin sama dengan AMLRepositoryPort,
    # kita tidak perlu menambahkan method tambahan. Jika ada method khusus,
    # tambahkan di sini.

    # ================================================================
    # 3. METODE ASLI (Risk Score & Suspicious Transaction)
    # ================================================================

    async def save_risk_score(self, risk_score: AMLRiskScoreTable) -> AMLRiskScoreTable:
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

    async def get_current_risk_score(self, customer_id: uuid.UUID) -> AMLRiskScoreTable | None:
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
        session = await self._get_session()
        stmt = (
            update(AMLRiskScoreTable)
            .where(AMLRiskScoreTable.id == risk_score_id)
            .values(**kwargs)
        )
        await session.execute(stmt)

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
        session = await self._get_session()
        stmt = (
            update(AMLSuspiciousTransactionTable)
            .where(AMLSuspiciousTransactionTable.id == transaction_id)
            .values(
                status=status,
                reviewed_at=datetime.now(UTC),
                reviewed_by=reviewed_by,
            )
        )
        await session.execute(stmt)

    # ================================================================
    # 4. BULK OPERATIONS
    # ================================================================

    async def bulk_save_risk_scores(self, risk_scores: list[AMLRiskScoreTable]) -> None:
        session = await self._get_session()
        session.add_all(risk_scores)
        await session.flush()

    async def delete_old_risk_scores(self, older_than: date) -> int:
        session = await self._get_session()
        stmt = delete(AMLRiskScoreTable).where(AMLRiskScoreTable.calculated_at < older_than)
        result = await session.execute(stmt)
        return result.rowcount

    # ================================================================
    # 5. UTILITY
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

    async def health_check(self) -> Dict[str, Any]:
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


__all__ = ["SQLAlchemyAMLRepository"]