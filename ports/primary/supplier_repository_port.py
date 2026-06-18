#!/usr/bin/env python3
from __future__ import annotations

"""
Module: supplier_repository_port.py
Layer: 7 - Ports / Primary Ports
Responsibility: Menetapkan kontrak abstract murni (Interface) untuk manajemen data
               Supplier/Vendor di dalam domain Accounts Payable (AP).
"""

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID


class SupplierRepositoryPort(ABC):
    """
    Interface Port Abstraksi untuk operasi data Supplier.
    Harus diimplementasikan oleh Infrastructure Layer / Repository Pattern.
    """

    @abstractmethod
    async def get_by_id(self, supplier_id: UUID) -> Any | None:
        """Mengambil data agregat supplier berdasarkan ID unik."""
        pass

    @abstractmethod
    async def get_by_code(self, legal_entity_id: UUID, supplier_code: str) -> Any | None:
        """Mengambil data supplier berdasarkan kode unik dan entitas hukum."""
        pass

    @abstractmethod
    async def is_active(self, supplier_id: UUID) -> bool:
        """Memeriksa apakah status supplier aktif untuk transaksi baru."""
        pass

    @abstractmethod
    async def save(self, supplier: Any) -> None:
        """Menyimpan atau memperbarui data supplier ke dalam database."""
        pass

    @abstractmethod
    async def list_by_entity(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[Any]:
        """Mendapatkan daftar supplier terfilter berdasarkan entitas perusahaan."""
        pass


# === EXPORTS ===
__all__ = ["SupplierRepositoryPort"]
