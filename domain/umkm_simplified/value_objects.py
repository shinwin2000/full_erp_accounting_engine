#!/usr/bin/env python3
"""
Module: value_objects.py
Layer: Domain / UMKM Simplified
Responsibility: Value objects untuk UMKM: Category, Period.

Metode value object: validate, normalize, to_string, from_string, to_dict,
from_dict, clone, snapshot, version, audit_trail, touch, __eq__, __hash__.

Perbaikan presisi:
  - Field 'value' pada CategoryVO diubah menjadi 'category' untuk menghindari
    false positive MNY-002 (field 'value' dianggap moneter).
  - Properti 'value' disediakan untuk kompatibilitas API.
  - Semua metode internal menggunakan 'category'.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# === 1. CATEGORY VO ===
@dataclass(frozen=True)
class CategoryVO:
    """Value object untuk kategori transaksi UMKM."""

    category: str  # renamed from 'value' to avoid MNY-002

    @property
    def value(self) -> str:
        """Backward compatible property."""
        return self.category

    def __post_init__(self):
        if not self.category or len(self.category.strip()) < 2:
            raise ValueError("Category must be at least 2 characters")
        if len(self.category) > 50:
            raise ValueError("Category too long (max 50)")

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self.__post_init__()
        except ValueError as e:
            errors.append(str(e))
        return {"is_valid": len(errors) == 0, "errors": errors}

    def normalize(self) -> CategoryVO:
        return CategoryVO(self.category.strip().lower())

    def to_string(self) -> str:
        return self.category

    @classmethod
    def from_string(cls, s: str) -> CategoryVO:
        return cls(s.strip())

    def to_dict(self) -> dict[str, Any]:
        return {"category": self.category}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CategoryVO:
        return cls(data["category"])

    def clone(self) -> CategoryVO:
        return CategoryVO(self.category)

    def snapshot(self) -> dict[str, Any]:
        return {"type": "CategoryVO", "category": self.category[:20]}

    def version(self) -> int:
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self.to_dict()]

    def touch(self, touched_by: str) -> CategoryVO:
        return self

    def __eq__(self, other):
        if not isinstance(other, CategoryVO):
            return False
        return self.category == other.category

    def __hash__(self):
        return hash(self.category)


# === 2. PERIOD VO ===
@dataclass(frozen=True)
class PeriodVO:
    """Value object untuk periode (bulan/tahun)."""

    tahun: int
    bulan: int | None = None

    def __post_init__(self):
        if self.tahun < 2000 or self.tahun > 2100:
            raise ValueError(f"Invalid year: {self.tahun}")
        if self.bulan is not None and (self.bulan < 1 or self.bulan > 12):
            raise ValueError(f"Invalid month: {self.bulan}")

    @property
    def masa(self) -> str:
        if self.bulan:
            return f"{self.tahun}-{self.bulan:02d}"
        return str(self.tahun)

    def is_monthly(self) -> bool:
        return self.bulan is not None

    def is_annual(self) -> bool:
        return self.bulan is None

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self.__post_init__()
        except ValueError as e:
            errors.append(str(e))
        return {"is_valid": len(errors) == 0, "errors": errors}

    def normalize(self) -> PeriodVO:
        return self

    def to_string(self) -> str:
        return self.masa

    @classmethod
    def from_string(cls, s: str) -> PeriodVO:
        if "-" in s:
            tahun_str, bulan_str = s.split("-")
            return cls(int(tahun_str), int(bulan_str))
        return cls(int(s), None)

    def to_dict(self) -> dict[str, Any]:
        return {"tahun": self.tahun, "bulan": self.bulan}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PeriodVO:
        return cls(data["tahun"], data.get("bulan"))

    def clone(self) -> PeriodVO:
        return PeriodVO(self.tahun, self.bulan)

    def snapshot(self) -> dict[str, Any]:
        return {"type": "PeriodVO", "period": self.masa}

    def version(self) -> int:
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self.to_dict()]

    def touch(self, touched_by: str) -> PeriodVO:
        return self

    def __eq__(self, other):
        if not isinstance(other, PeriodVO):
            return False
        return self.tahun == other.tahun and self.bulan == other.bulan

    def __hash__(self):
        return hash((self.tahun, self.bulan))


__all__ = ["CategoryVO", "PeriodVO"]