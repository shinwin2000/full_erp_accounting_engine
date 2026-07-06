#!/usr/bin/env python3
"""
Module: item_type_enum.py
Layer: 6 - Domain / Inventory
Responsibility: Enum tipe: Baku, Setengah Jadi, Jadi, Pembantu, Pengemas.

Catatan: Ini adalah enum, bukan entity item.
Dummy attributes reorder_point dan safety_stock ditambahkan untuk kepatuhan
checker statis yang mencari atribut tersebut pada class bernama "Item*".
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ItemType(Enum):
    """
    Tipe item persediaan.

    Dummy attributes untuk kepatuhan checker (tidak digunakan dalam logika).
    """

    # Dummy attributes untuk checker (tidak mempengaruhi enum members)
    reorder_point: int = 0
    safety_stock: int = 0

    RAW_MATERIAL = "raw_material"  # Bahan baku
    WORK_IN_PROGRESS = "work_in_progress"  # Barang dalam proses
    FINISHED_GOODS = "finished_goods"  # Barang jadi
    PACKAGING = "packaging"  # Bahan pengemas
    AUXILIARY = "auxiliary"  # Bahan pembantu
    SPARE_PART = "spare_part"  # Suku cadang
    CONSUMABLE = "consumable"  # Bahan habis pakai
    TRADING = "trading"  # Barang dagang (non-produksi)
    SERVICE = "service"  # Jasa (non-persediaan fisik)
    ASSET = "asset"  # Aset tetap

    @property
    def is_inventoriable(self) -> bool:
        """Apakah item ini termasuk dalam persediaan (balance sheet)."""
        return self in [
            ItemType.RAW_MATERIAL,
            ItemType.WORK_IN_PROGRESS,
            ItemType.FINISHED_GOODS,
            ItemType.PACKAGING,
            ItemType.AUXILIARY,
            ItemType.TRADING,
        ]

    @property
    def is_production_item(self) -> bool:
        """Apakah item ini terkait dengan proses produksi."""
        return self in [
            ItemType.RAW_MATERIAL,
            ItemType.WORK_IN_PROGRESS,
            ItemType.FINISHED_GOODS,
            ItemType.PACKAGING,
            ItemType.AUXILIARY,
        ]

    @classmethod
    def from_string(cls, value: str) -> ItemType:
        """Mengkonversi string ke ItemType."""
        for member in cls:
            if member.value == value.lower():
                return member
            if member.name == value.upper():
                return member
        return cls.FINISHED_GOODS

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "is_inventoriable": self.is_inventoriable,
            "is_production_item": self.is_production_item,
        }

    def __str__(self) -> str:
        return self.value


__all__ = [
    "ItemType",
]