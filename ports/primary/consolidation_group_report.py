#!/usr/bin/env python3
"""
Module: consolidation_group_report.py
Layer: Ports (Primary)

Responsibility:
    Mendefinisikan port interface untuk menghasilkan laporan konsolidasi grup perusahaan.
    Port ini digunakan oleh adapter sekunder (infrastructure) untuk menyediakan laporan konsolidasi.

Method Standards (ERP):
- generate_report() - Menghasilkan laporan konsolidasi lengkap
- get_intercompany_balances() - Mendapatkan saldo antar perusahaan
- get_consolidated_balance_sheet() - Mendapatkan neraca konsolidasi
- get_consolidated_income_statement() - Mendapatkan laporan laba rugi konsolidasi
- get_consolidated_cash_flow() - Mendapatkan arus kas konsolidasi
- get_elimination_entries() - Mendapatkan jurnal eliminasi
- get_nci_breakdown() - Mendapatkan rincian kepentingan non-pengendali
- get_consolidation_summary() - Mendapatkan ringkasan konsolidasi
- validate_consolidation() - Memvalidasi data konsolidasi
- get_entity_contribution() - Mendapatkan kontribusi per entitas
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any
from uuid import UUID


class ConsolidationGroupReportPort(ABC):
    """
    Port interface untuk laporan konsolidasi grup perusahaan.
    Semua adapter (implementasi) harus mengimplementasikan port ini.
    """

    @abstractmethod
    async def generate_report(
        self,
        group_id: UUID,
        period_start: date,
        period_end: date,
        include_intercompany: bool = True,
        include_nci: bool = True,
    ) -> dict[str, Any]:
        """
        Menghasilkan laporan konsolidasi lengkap untuk grup pada periode tertentu.

        Args:
            group_id: ID grup konsolidasi
            period_start: Tanggal awal periode
            period_end: Tanggal akhir periode
            include_intercompany: Sertakan eliminasi antar perusahaan
            include_nci: Sertakan kepentingan non-pengendali

        Returns:
            Dictionary berisi laporan konsolidasi (neraca, laba rugi, arus kas, dll.)
        """
        pass

    @abstractmethod
    async def get_intercompany_balances(self, group_id: UUID, as_of_date: date) -> list[dict]:
        """
        Mendapatkan saldo antar perusahaan dalam grup pada tanggal tertentu.

        Args:
            group_id: ID grup konsolidasi
            as_of_date: Tanggal penilaian

        Returns:
            List dictionary dengan detail saldo antar perusahaan
        """
        pass

    @abstractmethod
    async def get_consolidated_balance_sheet(
        self,
        group_id: UUID,
        as_of_date: date,
        include_nci: bool = True,
    ) -> dict[str, Any]:
        """
        Mendapatkan neraca konsolidasi pada tanggal tertentu.

        Args:
            group_id: ID grup konsolidasi
            as_of_date: Tanggal neraca
            include_nci: Sertakan kepentingan non-pengendali

        Returns:
            Dictionary berisi neraca konsolidasi (aset, kewajiban, ekuitas)
        """
        pass

    @abstractmethod
    async def get_consolidated_income_statement(
        self,
        group_id: UUID,
        period_start: date,
        period_end: date,
        include_nci: bool = True,
    ) -> dict[str, Any]:
        """
        Mendapatkan laporan laba rugi konsolidasi untuk periode tertentu.

        Args:
            group_id: ID grup konsolidasi
            period_start: Tanggal awal periode
            period_end: Tanggal akhir periode
            include_nci: Sertakan kepentingan non-pengendali

        Returns:
            Dictionary berisi laporan laba rugi konsolidasi
        """
        pass

    @abstractmethod
    async def get_consolidated_cash_flow(
        self,
        group_id: UUID,
        period_start: date,
        period_end: date,
    ) -> dict[str, Any]:
        """
        Mendapatkan laporan arus kas konsolidasi untuk periode tertentu.

        Args:
            group_id: ID grup konsolidasi
            period_start: Tanggal awal periode
            period_end: Tanggal akhir periode

        Returns:
            Dictionary berisi arus kas konsolidasi (operasi, investasi, pendanaan)
        """
        pass

    @abstractmethod
    async def get_elimination_entries(
        self,
        group_id: UUID,
        period_start: date,
        period_end: date,
    ) -> list[dict[str, Any]]:
        """
        Mendapatkan jurnal eliminasi yang digunakan dalam konsolidasi.

        Args:
            group_id: ID grup konsolidasi
            period_start: Tanggal awal periode
            period_end: Tanggal akhir periode

        Returns:
            List dictionary berisi jurnal eliminasi
        """
        pass

    @abstractmethod
    async def get_nci_breakdown(
        self,
        group_id: UUID,
        as_of_date: date,
    ) -> dict[str, Any]:
        """
        Mendapatkan rincian kepentingan non-pengendali (NCI) per entitas anak.

        Args:
            group_id: ID grup konsolidasi
            as_of_date: Tanggal penilaian

        Returns:
            Dictionary dengan rincian NCI per entitas
        """
        pass

    @abstractmethod
    async def get_consolidation_summary(
        self,
        group_id: UUID,
        period_start: date,
        period_end: date,
    ) -> dict[str, Any]:
        """
        Mendapatkan ringkasan konsolidasi untuk periode tertentu.

        Args:
            group_id: ID grup konsolidasi
            period_start: Tanggal awal periode
            period_end: Tanggal akhir periode

        Returns:
            Dictionary berisi ringkasan konsolidasi
        """
        pass

    @abstractmethod
    async def validate_consolidation(
        self,
        group_id: UUID,
        period_start: date,
        period_end: date,
    ) -> dict[str, Any]:
        """
        Memvalidasi data konsolidasi (memastikan keseimbangan, eliminasi lengkap, dll.).

        Args:
            group_id: ID grup konsolidasi
            period_start: Tanggal awal periode
            period_end: Tanggal akhir periode

        Returns:
            Dictionary berisi hasil validasi (valid, errors, warnings)
        """
        pass

    @abstractmethod
    async def get_entity_contribution(
        self,
        group_id: UUID,
        entity_id: UUID,
        period_start: date,
        period_end: date,
    ) -> dict[str, Any]:
        """
        Mendapatkan kontribusi suatu entitas terhadap laporan konsolidasi.

        Args:
            group_id: ID grup konsolidasi
            entity_id: ID entitas anak
            period_start: Tanggal awal periode
            period_end: Tanggal akhir periode

        Returns:
            Dictionary berisi kontribusi entitas (pendapatan, beban, aset, dll.)
        """
        pass


__all__ = ["ConsolidationGroupReportPort"]
