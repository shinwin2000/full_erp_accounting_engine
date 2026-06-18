#!/usr/bin/env python3
"""
Module: fiscal_period_repository_port.py
Layer: Ports (Primary / Inbound Boundary Interface)
Responsibility: Kontrak abstraksi (Interface) mutlak untuk manajemen persistensi
               dan kontrol siklus hidup Periode Fiskal (Fiscal Period).
               Menjamin isolasi total antara Application Layer dengan database/ORM.
Dependencies:
- abc (Abstract Base Classes)
- uuid, datetime
- domain.fiscal_period.aggregate_root
Audit: Modifikasi pada status periode (Open, Soft-Locked, Closed) wajib lewat port ini.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

# Menggunakan TYPE_CHECKING untuk memutus rantai sirkular dependen dengan Domain Layer
if TYPE_CHECKING:
    # Mengacu pada berkas domain\fiscal_period\aggregate_root.py Anda
    from domain.fiscal_period.aggregate_root import FiscalPeriod


class FiscalPeriodRepositoryPort(ABC):
    """
    Port Interface formal untuk operasi agregat Periode Fiskal.
    Menangani validasi penutupan buku bulanan (Monthly Closing) dan tahunan (Year-End).
    """

    @abstractmethod
    async def find_by_id(self, period_id: UUID) -> FiscalPeriod | None:
        """
        Mencari data periode fiskal berdasarkan UUID unik identifikatornya.

        :param period_id: UUID dari periode fiskal.
        :return: Objek Agregat FiscalPeriod atau None jika tidak ditemukan.
        """
        pass

    @abstractmethod
    async def find_by_date(self, target_date: date) -> FiscalPeriod | None:
        """
        Mencari periode fiskal yang aktif menaungi suatu tanggal transaksi tertentu.
        Sangat krusial untuk validasi pencegahan transaksi backdated/future-dated.

        :param target_date: Tanggal dilakukannya penjurnalan/transaksi.
        :return: Objek Agregat FiscalPeriod yang membawahi tanggal tersebut.
        """
        pass

    @abstractmethod
    async def find_active_period(self) -> FiscalPeriod | None:
        """
        Mengambil periode fiskal yang saat ini berstatus berjalan (OPEN)
        untuk pemrosesan transaksi harian utama.
        """
        pass

    @abstractmethod
    async def find_all_ordered(self) -> list[FiscalPeriod]:
        """
        Mengambil seluruh rekam jejak periode fiskal yang terdaftar dalam sistem,
        diurutkan secara kronologis ascending (dari periode terlama ke terbaru).
        """
        pass

    @abstractmethod
    async def save(self, fiscal_period: FiscalPeriod) -> None:
        """
        Menyimpan state terbaru atau mendaftarkan agregat Periode Fiskal baru
        ke dalam media persistensi. Wajib mengeksekusi pengiriman Domain Events
        (seperti PeriodClosedEvent atau YearEndClosingExecutedEvent) setelah unit of work selesai.

        :param fiscal_period: Instance agregat objek domain yang akan di-commit.
        """
        pass

    @abstractmethod
    async def is_period_locked_for_module(self, target_date: date, module_name: str) -> bool:
        """
        Memeriksa kontrol keamanan granular: Apakah sub-ledger tertentu
        (misal: 'AR' (Piutang), 'AP' (Hutang), 'ASSET' (Depresiasi), 'MANUFACTURING')
        telah dikunci secara parsial pada tanggal tersebut, meskipun periode fiskal
        secara umum belum ditutup penuh (*Soft-Locking Feature*).

        :param target_date: Tanggal yang akan diperiksa kelayakannya.
        :param module_name: Nama modul sistem ('GL', 'AR', 'AP', 'ASSET', 'PAYROLL', 'MRP').
        :return: True jika modul terkunci (transaksi ditolak), False jika boleh diakses.
        """
        pass
