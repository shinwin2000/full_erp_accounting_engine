#!/usr/bin/env python3
"""
Module: non_controlling_interest.py
Layer: Domain / Consolidation
Responsibility: Perhitungan kepentingan non-pengendali (NCI).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any
from uuid import UUID


@dataclass
class NCICalculationResult:
    """
    Result of a Non-Controlling Interest (NCI) calculation.
    Contains detailed breakdown of NCI values.
    """

    parent_id: UUID
    subsidiary_id: UUID
    ownership_percentage: Decimal
    subsidiary_equity: Decimal
    nci_amount: Decimal
    consolidation_group_id: UUID | None = None
    period_end_date: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "parent_id": str(self.parent_id),
            "subsidiary_id": str(self.subsidiary_id),
            "ownership_percentage": str(self.ownership_percentage),
            "subsidiary_equity": str(self.subsidiary_equity),
            "nci_amount": str(self.nci_amount),
            "consolidation_group_id": str(self.consolidation_group_id)
            if self.consolidation_group_id
            else None,
            "period_end_date": self.period_end_date,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NCICalculationResult:
        return cls(
            parent_id=UUID(data["parent_id"]),
            subsidiary_id=UUID(data["subsidiary_id"]),
            ownership_percentage=Decimal(data["ownership_percentage"]),
            subsidiary_equity=Decimal(data["subsidiary_equity"]),
            nci_amount=Decimal(data["nci_amount"]),
            consolidation_group_id=UUID(data["consolidation_group_id"])
            if data.get("consolidation_group_id")
            else None,
            period_end_date=data.get("period_end_date"),
            notes=data.get("notes", ""),
        )


class NonControllingInterestCalculator:
    """Kalkulator NCI untuk entitas anak."""

    async def calculate_nci(
        self, parent_id: UUID, child_id: UUID, ownership_percentage: Decimal, child_equity: Decimal
    ) -> NCICalculationResult:
        """
        Hitung NCI berdasarkan persentase kepemilikan dan ekuitas anak.
        Returns a detailed NCICalculationResult object.
        """
        if ownership_percentage >= Decimal("1"):
            nci_amount = Decimal("0")
        else:
            nci_amount = child_equity * (Decimal("1") - ownership_percentage)
        nci_amount = nci_amount.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

        return NCICalculationResult(
            parent_id=parent_id,
            subsidiary_id=child_id,
            ownership_percentage=ownership_percentage,
            subsidiary_equity=child_equity,
            nci_amount=nci_amount,
        )

    async def calculate_consolidated_nci(
        self, subsidiaries: list[tuple[UUID, Decimal, Decimal]]
    ) -> Decimal:
        """Total NCI dari multiple anak (legacy method)."""
        total = Decimal("0")
        for _, ownership, equity in subsidiaries:
            total += equity * (Decimal("1") - ownership)
        return total.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

    async def calculate_nci_batch(
        self, parent_id: UUID, subsidiaries: list[tuple[UUID, Decimal, Decimal]]
    ) -> list[NCICalculationResult]:
        """
        Calculate NCI for multiple subsidiaries and return list of results.
        """
        results = []
        for child_id, ownership, equity in subsidiaries:
            result = await self.calculate_nci(parent_id, child_id, ownership, equity)
            results.append(result)
        return results


__all__ = [
    "NCICalculationResult",
    "NonControllingInterestCalculator",
]
