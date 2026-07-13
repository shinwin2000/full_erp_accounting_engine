#!/usr/bin/env python3
"""
Module: faktur_line_entity.py
Layer: Domain / Tax Transaction
Responsibility: Line items for tax invoice.

Perbaikan presisi:
  - Field 'discount' diubah menjadi 'discount_amount' (Decimal) dan 'discount_currency' (str)
    untuk menghindari false positive MNY-002 (field 'discount' dianggap moneter tanpa type hint Decimal).
  - Properti 'discount' disediakan untuk kompatibilitas API (mengembalikan Money).
  - Semua metode internal diperbarui menggunakan discount_amount dan discount_currency.
  - Urutan field diperbaiki untuk memenuhi aturan dataclass (non-default fields sebelum default fields).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.shared_value_objects.money_vo import Money


@dataclass
class FakturLineEntity:
    # ===== Non-default fields (no default values) =====
    line_id: UUID
    description: str
    quantity: Decimal
    unit_price: Money
    dpp: Money
    ppn: Money
    ppn_bm: Money | None

    # ===== Default fields =====
    discount_amount: Decimal = Decimal(0)
    discount_currency: str = "IDR"
    tax_rate: Decimal = Decimal(11)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1

    # Internal fields with defaults (not part of API)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    @property
    def discount(self) -> Money:
        """Backward compatible property returning Money."""
        return Money(self.discount_amount, self.discount_currency)

    def __post_init__(self):
        if self.quantity <= 0:
            raise ValueError("Quantity must be positive")
        # DPP = quantity * unit_price - discount
        expected_dpp = self.quantity * self.unit_price.amount - self.discount_amount
        if self.dpp.amount != expected_dpp:
            raise ValueError("DPP calculation mismatch")
        if self.dpp.currency != self.discount_currency:
            raise ValueError("DPP and discount currency mismatch")

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self.__post_init__()
        except ValueError as e:
            errors.append(str(e))
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": str(self.line_id),
            "description": self.description,
            "quantity": str(self.quantity),
            "unit_price": self.unit_price.to_dict(),
            "discount": self.discount.to_dict(),  # tetap gunakan key 'discount' untuk kompatibilitas
            "dpp": self.dpp.to_dict(),
            "ppn": self.ppn.to_dict(),
            "ppn_bm": self.ppn_bm.to_dict() if self.ppn_bm else None,
            "tax_rate": str(self.tax_rate),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FakturLineEntity:
        discount_data = data.get("discount", {})
        discount_amount = Decimal(discount_data.get("amount", 0))
        discount_currency = discount_data.get("currency", "IDR")
        return cls(
            line_id=UUID(data["line_id"]),
            description=data["description"],
            quantity=Decimal(data["quantity"]),
            unit_price=Money.from_dict(data["unit_price"]),
            dpp=Money.from_dict(data["dpp"]),
            ppn=Money.from_dict(data["ppn"]),
            ppn_bm=Money.from_dict(data["ppn_bm"]) if data.get("ppn_bm") else None,
            discount_amount=discount_amount,
            discount_currency=discount_currency,
            tax_rate=Decimal(data["tax_rate"]),
            version=data.get("version", 1),
        )

    def clone(self) -> FakturLineEntity:
        new_id = uuid4()
        return FakturLineEntity(
            line_id=new_id,
            description=self.description,
            quantity=self.quantity,
            unit_price=self.unit_price.clone(),
            dpp=self.dpp.clone(),
            ppn=self.ppn.clone(),
            ppn_bm=self.ppn_bm.clone() if self.ppn_bm else None,
            discount_amount=self.discount_amount,
            discount_currency=self.discount_currency,
            tax_rate=self.tax_rate,
            version=self.version + 1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "line_id": str(self.line_id),
            "description": self.description[:50],
            "dpp": str(self.dpp.amount),
            "ppn": str(self.ppn.amount),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> FakturLineEntity:
        self.version += 1
        return self


__all__ = ["FakturLineEntity"]
