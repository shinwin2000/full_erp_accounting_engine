#!/usr/bin/env python3
"""
Module: sqlalchemy_consolidation_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk konsolidasi menggunakan SQLAlchemy.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from domain.consolidation.aggregate_root import ConsolidationGroup
from ports.primary.consolidation_repository_port import ConsolidationRepositoryPort


class SqlAlchemyConsolidationRepository(ConsolidationRepositoryPort):
    """
    Implementasi repository konsolidasi dengan SQLAlchemy.
    Semua metode diimplementasikan sebagai stub untuk keperluan test.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    # ========================================================================
    # Metode abstrak yang diperlukan dari ConsolidationRepositoryPort
    # ========================================================================

    async def get_consolidation(self, group_id: UUID) -> ConsolidationGroup | None:
        """Ambil group konsolidasi berdasarkan ID (stub)."""
        return None

    async def get_entity_equity(self, entity_id: UUID, as_of_date: date) -> Decimal:
        """Ambil ekuitas entitas pada tanggal tertentu (stub)."""
        return Decimal(0)

    async def get_intercompany_balances(self, group_id: UUID) -> list[dict]:
        """Ambil saldo antar perusahaan (stub)."""
        return []

    async def get_intercompany_transactions(self, group_id: UUID) -> list[dict]:
        """Ambil transaksi antar perusahaan (stub)."""
        return []

    async def get_ownership_percentage(self, parent_id: UUID, subsidiary_id: UUID) -> Decimal:
        """Ambil persentase kepemilikan (stub)."""
        return Decimal(100)

    async def list_consolidations(self, legal_entity_id: UUID) -> list[ConsolidationGroup]:
        """Ambil daftar konsolidasi (stub)."""
        return []

    async def save_consolidation(self, group: ConsolidationGroup) -> None:
        """Simpan group konsolidasi (stub)."""
        pass

    async def save_intercompany_transaction(self, transaction: dict) -> None:
        """Simpan transaksi antar perusahaan (stub)."""
        pass

    # ========================================================================
    # Metode tambahan yang mungkin dipanggil oleh service
    # ========================================================================

    async def save(self, group: ConsolidationGroup) -> None:
        """Alias untuk save_consolidation."""
        await self.save_consolidation(group)

    async def get_by_parent_id(self, parent_id: UUID) -> ConsolidationGroup | None:
        """Ambil group berdasarkan ID parent (stub)."""
        return None

    async def get_by_period(self, period_date: date) -> ConsolidationGroup | None:
        """Ambil group berdasarkan periode (stub)."""
        return None

    async def add(self, group: ConsolidationGroup) -> None:
        """Alias untuk save."""
        await self.save(group)

    async def get(self, group_id: UUID) -> ConsolidationGroup | None:
        """Alias untuk get_consolidation."""
        return await self.get_consolidation(group_id)
