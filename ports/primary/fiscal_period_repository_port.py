#!/usr/bin/env python3
"""
Module: fiscal_period_repository_port.py
Layer: Ports (Primary / Inbound Boundary Interface)
Responsibility: Kontrak abstraksi (Interface) mutlak untuk manajemen persistensi
               dan kontrol siklus hidup Periode Fiskal (Fiscal Period).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from domain.fiscal_period.aggregate_root import FiscalPeriod


class FiscalPeriodRepositoryPort(ABC):
    """
    Port Interface formal untuk operasi agregat Periode Fiskal.
    """

    @abstractmethod
    async def find_by_id(self, period_id: UUID) -> FiscalPeriod | None:
        """Mencari periode fiskal berdasarkan ID."""
        pass

    @abstractmethod
    async def find_by_date(self, target_date: date) -> FiscalPeriod | None:
        """Mencari periode yang mencakup tanggal tertentu."""
        pass

    @abstractmethod
    async def find_active_period(self) -> FiscalPeriod | None:
        """Mengambil periode yang sedang aktif (OPEN)."""
        pass

    @abstractmethod
    async def find_all_ordered(self) -> list[FiscalPeriod]:
        """Mengambil semua periode, diurutkan secara kronologis."""
        pass

    @abstractmethod
    async def save(self, fiscal_period: FiscalPeriod) -> None:
        """Menyimpan atau memperbarui periode fiskal."""
        pass

    @abstractmethod
    async def is_period_locked_for_module(self, target_date: date, module_name: str) -> bool:
        """Cek apakah periode terkunci untuk modul tertentu."""
        pass

    @abstractmethod
    async def list_by_legal_entity(
        self,
        legal_entity_id: UUID,
        limit: int = 100,
        offset: int = 0,
        from_year: int | None = None,
        to_year: int | None = None,
        status: str | None = None,
    ) -> list[FiscalPeriod]:
        """
        Mendaftar periode fiskal untuk suatu legal entity dengan pagination dan filter tahun.

        Args:
            legal_entity_id: ID entitas legal
            limit: Jumlah maksimum hasil
            offset: Offset untuk pagination
            from_year: Filter tahun awal (opsional)
            to_year: Filter tahun akhir (opsional)
            status: Filter status (opsional), bisa string atau PeriodStatus enum
        """
        pass

    @abstractmethod
    async def list_by_fiscal_year(
        self, legal_entity_id: UUID, fiscal_year: int
    ) -> list[FiscalPeriod]:
        """Mendaftar periode untuk tahun fiskal tertentu."""
        pass