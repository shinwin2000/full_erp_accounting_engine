#!/usr/bin/env python3
"""
Module: sqlalchemy_file_storage_status_adapter.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi FileStorageStatusPort dengan SQLAlchemy.
Perbaikan:
  - Mengimplementasikan FileStorageStatusPort
  - Menggunakan pessimistic locking (SELECT FOR UPDATE)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, String, Text, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from ports.primary.file_storage_status_port import FileStorageStatusPort

logger = logging.getLogger(__name__)

Base = declarative_base()


class FileStorageStatusTable(Base):
    __tablename__ = "file_storage_status"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(String(200), nullable=False, unique=True)
    status = Column(String(50), nullable=False)
    file_metadata = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=True, onupdate=datetime.utcnow)


class SQLAlchemyFileStorageStatusAdapter(FileStorageStatusPort):
    """
    Implementasi FileStorageStatusPort dengan SQLAlchemy.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    async def get_status(self, file_id: str) -> dict[str, Any] | None:
        session = await self._get_session()
        stmt = select(FileStorageStatusTable).where(FileStorageStatusTable.file_id == file_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None
        return {
            "file_id": row.file_id,
            "status": row.status,
            "file_metadata": row.file_metadata,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    async def set_status(self, file_id: str, status: str, file_metadata: str | None = None) -> dict[str, Any]:
        session = await self._get_session()
        # Lock the row if it exists
        stmt = select(FileStorageStatusTable).where(FileStorageStatusTable.file_id == file_id).with_for_update()
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()

        if row:
            row.status = status
            if file_metadata is not None:
                row.file_metadata = file_metadata
            row.updated_at = datetime.utcnow()
            await session.flush()
        else:
            try:
                row = FileStorageStatusTable(
                    file_id=file_id,
                    status=status,
                    file_metadata=file_metadata,
                )
                session.add(row)
                await session.flush()
            except IntegrityError:
                await session.rollback()
                # Retry with lock
                stmt_retry = select(FileStorageStatusTable).where(
                    FileStorageStatusTable.file_id == file_id
                ).with_for_update()
                result_retry = await session.execute(stmt_retry)
                row = result_retry.scalar_one()
                row.status = status
                if file_metadata is not None:
                    row.file_metadata = file_metadata
                row.updated_at = datetime.utcnow()
                await session.flush()

        return {
            "file_id": row.file_id,
            "status": row.status,
            "file_metadata": row.file_metadata,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    async def delete_status(self, file_id: str) -> bool:
        session = await self._get_session()
        stmt = select(FileStorageStatusTable).where(FileStorageStatusTable.file_id == file_id).with_for_update()
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return False
        await session.delete(row)
        await session.flush()
        return True


__all__ = ["FileStorageStatusTable", "SQLAlchemyFileStorageStatusAdapter"]
