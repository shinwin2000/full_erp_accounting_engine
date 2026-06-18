#!/usr/bin/env python3
"""
Module: sqlalchemy_goods_receipt_repository_impl.py
Layer: Infrastructure (Secondary Adapter)
Responsibility: Implementasi repository Goods Receipt Note menggunakan SQLAlchemy.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence_orm.goods_receipt_note_table import (
    GoodsReceiptNoteLineTable,
    GoodsReceiptNoteTable,
)
from ports.primary.goods_receipt_repository_port import GoodsReceiptRepositoryPort


class SQLAlchemyGoodsReceiptRepository(GoodsReceiptRepositoryPort):
    def __init__(self, session: AsyncSession):
        self._session = session

    # ========== GRN Header ==========
    async def save_grn(self, grn: GoodsReceiptNoteTable) -> GoodsReceiptNoteTable:
        self._session.add(grn)
        await self._session.flush()
        return grn

    async def get_grn_by_id(self, grn_id: uuid.UUID) -> GoodsReceiptNoteTable | None:
        stmt = select(GoodsReceiptNoteTable).where(GoodsReceiptNoteTable.id == grn_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_grn_by_number(
        self, grn_number: str, legal_entity_id: uuid.UUID
    ) -> GoodsReceiptNoteTable | None:
        stmt = select(GoodsReceiptNoteTable).where(
            GoodsReceiptNoteTable.grn_number == grn_number,
            GoodsReceiptNoteTable.legal_entity_id == legal_entity_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_grns_by_po(self, purchase_order_id: uuid.UUID) -> list[GoodsReceiptNoteTable]:
        stmt = select(GoodsReceiptNoteTable).where(
            GoodsReceiptNoteTable.purchase_order_id == purchase_order_id
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_grns_by_date_range(
        self, from_date: date, to_date: date, legal_entity_id: uuid.UUID
    ) -> list[GoodsReceiptNoteTable]:
        stmt = select(GoodsReceiptNoteTable).where(
            GoodsReceiptNoteTable.receipt_date.between(from_date, to_date),
            GoodsReceiptNoteTable.legal_entity_id == legal_entity_id,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update_grn_status(self, grn_id: uuid.UUID, status: str) -> None:
        stmt = (
            update(GoodsReceiptNoteTable)
            .where(GoodsReceiptNoteTable.id == grn_id)
            .values(status=status)
        )
        await self._session.execute(stmt)

    # ========== GRN Lines ==========
    async def save_line(self, line: GoodsReceiptNoteLineTable) -> GoodsReceiptNoteLineTable:
        self._session.add(line)
        await self._session.flush()
        return line

    async def get_lines_by_grn(self, grn_id: uuid.UUID) -> list[GoodsReceiptNoteLineTable]:
        stmt = (
            select(GoodsReceiptNoteLineTable)
            .where(GoodsReceiptNoteLineTable.grn_id == grn_id)
            .order_by(GoodsReceiptNoteLineTable.line_number)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def delete_lines_by_grn(self, grn_id: uuid.UUID) -> None:
        stmt = select(GoodsReceiptNoteLineTable).where(GoodsReceiptNoteLineTable.grn_id == grn_id)
        result = await self._session.execute(stmt)
        for line in result.scalars():
            await self._session.delete(line)


__all__ = ["SQLAlchemyGoodsReceiptRepository"]
