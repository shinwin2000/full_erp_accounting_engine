#!/usr/bin/env python3
from __future__ import annotations

"""
Module: customer_repository_port.py
Layer: 7 - Ports / Primary Ports
Responsibility: Menetapkan kontrak abstract murni (Interface) untuk manajemen data
               Customer di dalam domain Accounts Receivable (AR).
"""

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID


class CustomerRepositoryPort(ABC):
    """
    Interface Port Abstraksi untuk operasi data Customer.
    Harus diimplementasikan oleh Infrastructure Layer / Repository Pattern.
    """

    @abstractmethod
    async def get_by_id(self, customer_id: UUID) -> Any | None:
        """Mengambil data agregat customer berdasarkan ID unik."""
        pass

    @abstractmethod
    async def get_by_code(self, legal_entity_id: UUID, customer_code: str) -> Any | None:
        """Mengambil data customer berdasarkan kode unik dan entitas hukum."""
        pass

    @abstractmethod
    async def is_active(self, customer_id: UUID) -> bool:
        """Memeriksa apakah status customer aktif untuk transaksi baru."""
        pass

    @abstractmethod
    async def check_credit_limit(self, customer_id: UUID, invoice_amount: Any) -> bool:
        """Memeriksa apakah penambahan nominal invoice baru melampaui sisa limit kredit."""
        pass

    @abstractmethod
    async def save(self, customer: Any) -> None:
        """Menyimpan atau memperbarui data customer ke dalam database."""
        pass

    @abstractmethod
    async def list_by_entity(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[Any]:
        """Mendapatkan daftar customer terfilter berdasarkan entitas perusahaan."""
        pass


# === EXPORTS ===
__all__ = ["CustomerRepositoryPort"]
