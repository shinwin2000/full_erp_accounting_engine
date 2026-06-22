#!/usr/bin/env python3
"""
Module: core_tax_port.py
Layer: Ports (Primary)
Responsibility: Port untuk Core Tax Authority (API pajak pemerintah).
"""

from abc import ABC, abstractmethod
from typing import Any


class CoreTaxPort(ABC):
    """
    Port untuk berkomunikasi dengan otoritas pajak (Core Tax).
    """
    @abstractmethod
    async def calculate_tax(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        Menghitung pajak berdasarkan data transaksi.

        Args:
            data: Dict berisi data transaksi (amount, tax_code, dll).

        Returns:
            Dict berisi hasil perhitungan pajak (tax_amount, tax_base, status, dll).
        """
        pass

    @abstractmethod
    async def validate_tax_id(self, tax_id: str) -> bool:
        """
        Memvalidasi NPWP atau tax ID.

        Args:
            tax_id: Nomor pajak (NPWP).

        Returns:
            True jika valid, False jika tidak.
        """
        pass

    @abstractmethod
    async def get_tax_rate(self, tax_code: str, date: str) -> float:
        """
        Mendapatkan tarif pajak untuk kode pajak dan tanggal tertentu.

        Args:
            tax_code: Kode pajak (misal 'PPN', 'PPH21').
            date: Tanggal berlaku (format 'YYYY-MM-DD').

        Returns:
            Tarif pajak sebagai float (misal 0.11 untuk 11%).
        """
        pass