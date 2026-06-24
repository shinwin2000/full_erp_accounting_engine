#!/usr/bin/env python3
"""
Module: sqlalchemy_sales_repository_adapter.py
Layer: Adapters (Secondary Implementation)
Responsibility: Real SQLAlchemy implementation of SalesRepositoryPort.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ports.primary.sales_repository_port import SalesRepositoryPort
from adapters.secondary_impl.sqlalchemy_sales_order_repository_impl import (
    SQLAlchemySalesOrderRepository,
    SalesOrderEntity,
)

logger = logging.getLogger(__name__)


class SQLAlchemySalesRepositoryAdapter(SalesRepositoryPort):
    """
    Adapter untuk SalesRepositoryPort yang menggunakan SQLAlchemySalesOrderRepository.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session
        self._repo = SQLAlchemySalesOrderRepository(session)

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
            self._repo._session = self._session
        return self._session

    # ========================================================================
    # METODE DARI SalesRepositoryPort
    # ========================================================================

    async def save_transaction(self, transaction: Any) -> None:
        await self._get_session()
        await self._repo.save(transaction)

    async def get_last_transaction_number(self, legal_entity_id: UUID) -> str | None:
        await self._get_session()
        return await self._repo.get_last_so_number(legal_entity_id)

    async def exists(self, transaction_id: UUID) -> bool:
        await self._get_session()
        existing = await self._repo.get_by_id(transaction_id)
        return existing is not None

    async def delete_transaction(self, transaction_id: UUID) -> None:
        await self._get_session()
        await self._repo.delete(transaction_id)

    async def count_by_period(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> int:
        await self._get_session()
        return await self._repo.count_by_period(legal_entity_id, start_date, end_date)

    async def get_total_by_period(
        self, legal_entity_id: UUID, start_date: date, end_date: date
    ) -> Decimal:
        await self._get_session()
        return await self._repo.get_total_by_period(legal_entity_id, start_date, end_date)

    async def list_by_period(
        self,
        legal_entity_id: UUID,
        start_date: date,
        end_date: date,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Any]:
        await self._get_session()
        return await self._repo.list_by_period(legal_entity_id, start_date, end_date, limit, offset)

    async def search(
        self,
        query: str,
        legal_entity_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Any]:
        await self._get_session()
        return await self._repo.search(query, legal_entity_id, limit, offset)

    # ========================================================================
    # METODE YANG HILANG (dari dashboard)
    # ========================================================================

    async def get_by_id(self, transaction_id: UUID) -> SalesOrderEntity | None:
        await self._get_session()
        return await self._repo.get_by_id(transaction_id)

    async def get_by_number(self, order_number: str, legal_entity_id: UUID) -> SalesOrderEntity | None:
        await self._get_session()
        entity = await self._repo.get_by_number(order_number)
        if entity and entity.legal_entity_id == legal_entity_id:
            return entity
        return None

    async def list_by_customer(
        self,
        customer_id: UUID,
        legal_entity_id: UUID,
        limit: int = 100,
        offset: int = 0,
    ) -> List[SalesOrderEntity]:
        await self._get_session()
        return await self._repo.list_by_customer(customer_id, legal_entity_id, limit, offset)


__all__ = ["SQLAlchemySalesRepositoryAdapter"]