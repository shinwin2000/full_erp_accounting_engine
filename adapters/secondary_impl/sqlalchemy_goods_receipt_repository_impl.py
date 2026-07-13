#!/usr/bin/env python3
"""
Module: sqlalchemy_goods_receipt_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Goods Receipt Note menggunakan SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.goods_receipt_note_table import (
    GoodsReceiptNoteLineTable,
    GoodsReceiptNoteTable,
)
from ports.primary.goods_receipt_repository_port import GoodsReceiptRepositoryPort


class SQLAlchemyGoodsReceiptRepository(GoodsReceiptRepositoryPort):
    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    # ========== GRN Header ==========
    async def save_grn(self, grn: GoodsReceiptNoteTable) -> GoodsReceiptNoteTable:
        session = await self._get_session()
        session.add(grn)
        await session.flush()
        return grn

    async def get_grn_by_id(self, grn_id: uuid.UUID) -> GoodsReceiptNoteTable | None:
        session = await self._get_session()
        stmt = select(GoodsReceiptNoteTable).where(GoodsReceiptNoteTable.id == grn_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_grn_by_number(
        self, grn_number: str, legal_entity_id: uuid.UUID
    ) -> GoodsReceiptNoteTable | None:
        session = await self._get_session()
        stmt = select(GoodsReceiptNoteTable).where(
            GoodsReceiptNoteTable.grn_number == grn_number,
            GoodsReceiptNoteTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_grns_by_po(self, purchase_order_id: uuid.UUID) -> list[GoodsReceiptNoteTable]:
        session = await self._get_session()
        stmt = select(GoodsReceiptNoteTable).where(
            GoodsReceiptNoteTable.purchase_order_id == purchase_order_id
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_grns_by_date_range(
        self, from_date: date, to_date: date, legal_entity_id: uuid.UUID
    ) -> list[GoodsReceiptNoteTable]:
        session = await self._get_session()
        stmt = select(GoodsReceiptNoteTable).where(
            GoodsReceiptNoteTable.receipt_date.between(from_date, to_date),
            GoodsReceiptNoteTable.legal_entity_id == legal_entity_id,
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update_grn_status(self, grn_id: uuid.UUID, status: str) -> None:
        """
        Update GRN status with pessimistic locking to prevent race conditions.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the record.
        """
        session = await self._get_session()
        async with session.begin():
            # 1. Lock the row with SELECT FOR UPDATE
            stmt_lock = select(GoodsReceiptNoteTable).where(
                GoodsReceiptNoteTable.id == grn_id
            ).with_for_update()
            result = await session.execute(stmt_lock)
            grn = result.scalar_one_or_none()
            if not grn:
                raise ValueError(f"GRN {grn_id} not found")

            # 2. Update the locked row
            grn.status = status
            # Assuming there is an updated_at field; if not, you can add it or skip.
            # grn.updated_at = datetime.utcnow()
            await session.flush()

    # ========== GRN Lines ==========
    async def save_line(self, line: GoodsReceiptNoteLineTable) -> GoodsReceiptNoteLineTable:
        session = await self._get_session()
        session.add(line)
        await session.flush()
        return line

    async def get_lines_by_grn(self, grn_id: uuid.UUID) -> list[GoodsReceiptNoteLineTable]:
        session = await self._get_session()
        stmt = (
            select(GoodsReceiptNoteLineTable)
            .where(GoodsReceiptNoteLineTable.grn_id == grn_id)
            .order_by(GoodsReceiptNoteLineTable.line_number)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def delete_lines_by_grn(self, grn_id: uuid.UUID) -> None:
        """
        Delete all lines of a GRN with pessimistic locking to prevent race conditions.
        LOCKING: SELECT FOR UPDATE ensures exclusive lock on the lines to be deleted.
        """
        session = await self._get_session()
        async with session.begin():
            # 1. Lock the lines with SELECT FOR UPDATE
            stmt_lock = select(GoodsReceiptNoteLineTable).where(
                GoodsReceiptNoteLineTable.grn_id == grn_id
            ).with_for_update()
            result = await session.execute(stmt_lock)
            lines = result.scalars().all()

            # 2. Delete the locked lines
            for line in lines:
                await session.delete(line)
            await session.flush()

    # === Metode port dengan tipe yang sesuai (Any) ===
    async def get_by_id(self, grn_id: uuid.UUID) -> Any | None:
        """Alias untuk get_grn_by_id."""
        return await self.get_grn_by_id(grn_id)

    async def get_by_number(self, grn_number: str) -> Any | None:
        """
        Mendapatkan GRN berdasarkan nomor dokumen (tanpa filter legal_entity).
        Karena port hanya menerima satu parameter, kita asumsikan grn_number unik secara global.
        """
        session = await self._get_session()
        stmt = (
            select(GoodsReceiptNoteTable)
            .where(GoodsReceiptNoteTable.grn_number == grn_number)
            .order_by(GoodsReceiptNoteTable.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_purchase_order_id(self, purchase_order_id: uuid.UUID) -> list[Any]:
        """Alias untuk get_grns_by_po."""
        return await self.get_grns_by_po(purchase_order_id)


# === ALIAS untuk kompatibilitas dengan adapter registry ===
SQLAlchemyGoodsReceiptRepositoryImpl = SQLAlchemyGoodsReceiptRepository

__all__ = [
    "SQLAlchemyGoodsReceiptRepository",
    "SQLAlchemyGoodsReceiptRepositoryImpl",
]
