#!/usr/bin/env python3
"""
Module: unit_of_work.py
Layer: Infrastructure / Persistence ORM
Responsibility: Menyediakan abstraksi Unit of Work (UoW) untuk mengelola transaksi
               database. Implementasi menggunakan SQLAlchemy AsyncSession.
               Digunakan oleh repository dan service layer untuk memastikan atomicity.

Dependencies:
    - sqlalchemy.ext.asyncio.AsyncSession
    - logging
    - typing

Audit: Setiap commit/rollback dicatat ke log.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

T = TypeVar("T")


class UnitOfWork(ABC):
    """
    Abstract base class untuk Unit of Work.
    Mendefinisikan kontrak untuk mengelola transaksi database.
    """

    @abstractmethod
    async def __aenter__(self) -> UnitOfWork:
        """Mulai transaksi dan kembalikan UoW instance."""
        pass

    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Keluar dari konteks; commit jika sukses, rollback jika error."""
        pass

    @abstractmethod
    async def commit(self) -> None:
        """Commit transaksi saat ini."""
        pass

    @abstractmethod
    async def rollback(self) -> None:
        """Rollback transaksi saat ini."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Tutup session dan bebaskan resource."""
        pass

    @abstractmethod
    async def flush(self) -> None:
        """Flush perubahan ke database tanpa commit."""
        pass


class SqlAlchemyUnitOfWork(UnitOfWork):
    """
    Implementasi Unit of Work menggunakan SQLAlchemy AsyncSession.
    Mendukung auto-commit/rollback via context manager.
    """

    def __init__(self, session: AsyncSession, auto_begin: bool = True):
        """
        Args:
            session: SQLAlchemy AsyncSession yang akan digunakan.
            auto_begin: Jika True, akan memulai transaksi secara otomatis
                        saat memasuki context manager.
        """
        self._session = session
        self._auto_begin = auto_begin
        self._is_begun = False

    @property
    def session(self) -> AsyncSession:
        """Mengembalikan session yang digunakan."""
        return self._session

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        """Mulai transaksi jika auto_begin=True."""
        if self._auto_begin and not self._is_begun:
            await self._begin()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Commit jika tidak ada exception, rollback jika ada."""
        if exc_type is not None:
            logger.warning(f"Exception occurred: {exc_type.__name__}. Rolling back.")
            await self.rollback()
        else:
            await self.commit()
        await self.close()

    async def _begin(self) -> None:
        """Memulai transaksi secara eksplisit."""
        if not self._is_begun:
            # SQLAlchemy AsyncSession memulai transaksi secara implisit saat first use,
            # tetapi kita bisa memanggil begin() untuk eksplisit.
            await self._session.begin()
            self._is_begun = True
            logger.debug("Transaction begun.")

    async def commit(self) -> None:
        """Commit transaksi."""
        try:
            await self._session.commit()
            self._is_begun = False
            logger.debug("Transaction committed successfully.")
        except Exception as e:
            logger.error(f"Commit failed: {e}")
            raise

    async def rollback(self) -> None:
        """Rollback transaksi."""
        try:
            await self._session.rollback()
            self._is_begun = False
            logger.debug("Transaction rolled back.")
        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            raise

    async def flush(self) -> None:
        """Flush perubahan ke database tanpa commit."""
        await self._session.flush()

    async def close(self) -> None:
        """Tutup session."""
        await self._session.close()
        self._is_begun = False
        logger.debug("Session closed.")

    async def execute(self, statement: Any, *args, **kwargs) -> Any:
        """Eksekusi statement SQL langsung melalui session."""
        return await self._session.execute(statement, *args, **kwargs)

    async def add(self, instance: Any) -> None:
        """Tambah instance ke session."""
        self._session.add(instance)

    async def add_all(self, instances: list[Any]) -> None:
        """Tambah banyak instance ke session."""
        self._session.add_all(instances)

    async def delete(self, instance: Any) -> None:
        """Hapus instance dari session."""
        await self._session.delete(instance)

    async def refresh(self, instance: Any, attribute_names: list[str] | None = None) -> None:
        """Refresh instance dari database."""
        await self._session.refresh(instance, attribute_names=attribute_names)

    async def merge(self, instance: Any) -> Any:
        """Merge instance ke session."""
        return await self._session.merge(instance)

    def is_active(self) -> bool:
        """Check apakah transaksi sedang aktif."""
        return self._session.is_active and self._is_begun


# ============================================================================
# Convenience Factory
# ============================================================================
async def create_unit_of_work(
    session_factory: Callable[[], AsyncSession], auto_begin: bool = True
) -> SqlAlchemyUnitOfWork:
    """
    Factory untuk membuat Unit of Work dari session factory.
    Args:
        session_factory: Callable yang mengembalikan AsyncSession baru.
        auto_begin: Apakah auto-begin context manager.
    Returns:
        SqlAlchemyUnitOfWork instance.
    """
    session = session_factory()
    return SqlAlchemyUnitOfWork(session, auto_begin=auto_begin)


__all__ = [
    "SqlAlchemyUnitOfWork",
    "UnitOfWork",
    "create_unit_of_work",
]
