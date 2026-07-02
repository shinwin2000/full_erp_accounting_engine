#!/usr/bin/env python3
"""
Module: inventory_valuation_repository_port.py
Layer: Ports (Primary)
Responsibility: Antarmuka untuk repository valuasi persediaan.
"""

from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID


class InventoryValuationRepositoryPort(ABC):
    """
    Port untuk mengakses data valuasi persediaan.
    """

    @abstractmethod
    async def get_inventory_valuation(
        self,
        legal_entity_id: UUID,
        as_of_date: date,
        product_ids: list[UUID] | None = None,
        valuation_method: str = "FIFO",
    ) -> dict[str, Any]:
        """
        Mendapatkan nilai persediaan per produk pada tanggal tertentu.
        """
        pass

    @abstractmethod
    async def calculate_valuation_by_product(
        self,
        product_id: UUID,
        as_of_date: date,
        valuation_method: str = "FIFO",
    ) -> Decimal:
        """
        Menghitung nilai persediaan untuk satu produk.
        """
        pass

    @abstractmethod
    async def get_movement_summary(
        self,
        legal_entity_id: UUID,
        start_date: date,
        end_date: date,
        product_ids: list[UUID] | None = None,
    ) -> dict[str, Any]:
        """
        Ringkasan pergerakan persediaan (masuk, keluar, saldo).
        """
        pass

    @abstractmethod
    async def get_reorder_report(
        self,
        legal_entity_id: UUID,
        threshold: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Laporan produk yang perlu di-reorder (stok di bawah threshold).
        """
        pass