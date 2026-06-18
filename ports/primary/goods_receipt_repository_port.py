#!/usr/bin/env python3
"""
Module: goods_receipt_repository_port.py
Layer: Ports (Primary)
Responsibility: Port interface untuk repository Goods Receipt Note (GRN).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID


class GoodsReceiptRepositoryPort(ABC):
    """
    Port untuk repository Goods Receipt Note.
    Digunakan oleh transformer procurement_to_ap untuk melakukan 3-way match.
    """

    @abstractmethod
    async def get_by_id(self, grn_id: UUID) -> Any | None:
        """
        Mendapatkan Goods Receipt Note berdasarkan ID.
        Returns: Objek GRN (bisa berupa ORM model atau domain aggregate).
        """
        pass

    @abstractmethod
    async def get_by_number(self, grn_number: str) -> Any | None:
        """Mendapatkan GRN berdasarkan nomor dokumen."""
        pass

    @abstractmethod
    async def get_by_purchase_order_id(self, po_id: UUID) -> list[Any]:
        """Mendapatkan semua GRN untuk sebuah Purchase Order."""
        pass
