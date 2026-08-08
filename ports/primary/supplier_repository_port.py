#!/usr/bin/env python3
"""
Module: supplier_repository_port.py
Layer: 7 - Ports / Primary Ports
Responsibility: Menetapkan kontrak abstract murni (Interface) untuk manajemen data
               Supplier/Vendor di dalam domain Accounts Payable (AP).

Kontrak ini SENGAJA dibuat lengkap (bukan cuma get/save) supaya Service Layer
tidak lagi tergoda menyimpan data di memori (dict) seperti sebelumnya —
setiap operasi CRUD, pencarian, dan laporan Supplier harus lewat sini agar
konsisten tersimpan & terbaca dari database yang sama dipakai Frontend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any
from uuid import UUID


class SupplierRepositoryPort(ABC):
    """
    Interface Port Abstraksi untuk operasi data Supplier.
    Harus diimplementasikan oleh Infrastructure Layer / Repository Pattern.
    """

    # ==================== READ ====================

    @abstractmethod
    async def get_by_id(self, supplier_id: UUID, legal_entity_id: UUID) -> Any | None:
        """Mengambil data agregat supplier berdasarkan ID unik."""

    @abstractmethod
    async def get_by_code(self, legal_entity_id: UUID, supplier_code: str) -> Any | None:
        """Mengambil data supplier berdasarkan kode unik dan entitas hukum."""

    @abstractmethod
    async def get_by_tax_id(self, tax_id: str) -> Any | None:
        """Mengambil data supplier berdasarkan NPWP (harus unik global)."""

    @abstractmethod
    async def is_active(self, supplier_id: UUID) -> bool:
        """Memeriksa apakah status supplier aktif untuk transaksi baru."""

    @abstractmethod
    async def list_by_entity(
        self,
        legal_entity_id: UUID,
        *,
        search: str | None = None,
        city: str | None = None,
        status: str | None = None,
        is_active: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Any], int]:
        """
        Mendapatkan daftar supplier terfilter (search/city/status/is_active)
        berdasarkan entitas perusahaan, dengan pagination.
        Return: (items, total_count) supaya frontend bisa menampilkan
        total baris & pager yang akurat.
        """

    # ==================== WRITE ====================

    @abstractmethod
    async def add(self, supplier: Any) -> Any:
        """Menyimpan supplier baru ke database. Mengembalikan entity tersimpan."""

    @abstractmethod
    async def update(self, supplier: Any) -> Any:
        """Memperbarui data supplier yang sudah ada. Mengembalikan entity terbaru."""

    @abstractmethod
    async def save(self, supplier: Any) -> Any:
        """Upsert (insert jika belum ada, update jika sudah ada)."""

    @abstractmethod
    async def soft_delete(self, supplier_id: UUID, legal_entity_id: UUID, deleted_by: UUID) -> bool:
        """
        Soft-delete (nonaktifkan) supplier. Menolak (return False) jika
        supplier sudah memiliki transaksi (PO/Invoice/Payment) — supplier
        semacam ini tidak boleh dihapus demi menjaga integritas laporan.
        """

    @abstractmethod
    async def has_transactions(self, supplier_id: UUID) -> bool:
        """Cek apakah supplier sudah punya PO/GRN/Invoice/Payment terkait."""

    # ==================== LAPORAN & INTEGRASI ====================

    @abstractmethod
    async def get_outstanding_balance(self, supplier_id: UUID) -> Decimal:
        """Total saldo hutang (AP) yang belum lunas untuk supplier ini."""

    @abstractmethod
    async def get_statistics(self, legal_entity_id: UUID) -> dict[str, Any]:
        """Statistik ringkas (total, aktif, per kategori, per status)."""

    @abstractmethod
    async def export_rows(self, legal_entity_id: UUID) -> list[dict[str, Any]]:
        """Baris-baris supplier siap diekspor (CSV/Excel/PDF)."""

    @abstractmethod
    async def get_next_code(self, legal_entity_id: UUID, prefix: str = "SUP") -> str:
        """
        Menghasilkan kode supplier berikutnya secara otomatis, mis. "SUP-001",
        "SUP-002", dst — berdasarkan kode dengan angka urut TERBESAR yang
        sudah ada untuk `prefix` & `legal_entity_id` ini (bukan cuma jumlah
        baris, supaya tetap benar walau ada supplier yang sudah dihapus).
        """


# === EXPORTS ===
__all__ = ["SupplierRepositoryPort"]
