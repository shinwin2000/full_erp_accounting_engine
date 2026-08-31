#!/usr/bin/env python3
"""
Module: cost_entry_vo.py
Layer: Domain / Project Services
Responsibility: Value object untuk entri biaya pada project.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class CostType(str, Enum):
    """Tipe biaya untuk project."""
    MATERIAL = "material"
    LABOR = "labor"
    OVERHEAD = "overhead"
    EQUIPMENT = "equipment"
    SUBCONTRACT = "subcontract"
    OTHER = "other"


@dataclass(frozen=True)
class CostEntryVO:
    """
    Value object untuk entri biaya dalam project.

    Attributes:
        project_id: UUID project terkait (wajib)
        amount: Jumlah biaya (wajib)
        currency: Mata uang (default IDR)
        cost_type: Tipe biaya (CostType)
        description: Deskripsi biaya
        entry_date: Tanggal biaya
        id: UUID unik (auto-generated)
        created_at: Timestamp pembuatan (UTC)
        created_by: UUID pembuat (opsional)
        metadata: Metadata tambahan
    """

    # Non-default fields must come before default fields
    project_id: UUID
    amount: Decimal

    # Default fields
    currency: str = "IDR"
    cost_type: CostType = CostType.OTHER
    description: str = ""
    entry_date: date = field(default_factory=date.today)
    id: UUID = field(default_factory=uuid4)
    # ===== PERBAIKAN: gunakan timezone.utc =====
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validasi setelah inisialisasi."""
        if self.amount < 0:
            raise ValueError("Amount cannot be negative")
        if not self.project_id:
            raise ValueError("project_id is required")
        if not isinstance(self.cost_type, CostType):
            raise ValueError("cost_type must be a CostType enum")
        # Pastikan created_at timezone-aware
        if self.created_at.tzinfo is None:
            # Jika tidak ada timezone, set ke UTC
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "amount": str(self.amount),
            "currency": self.currency,
            "cost_type": self.cost_type.value,
            "description": self.description,
            "entry_date": self.entry_date.isoformat(),
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by) if self.created_by else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CostEntryVO:
        """Reconstruct dari dictionary."""
        cost_type_str = data.get("cost_type", "other")
        try:
            cost_type = CostType(cost_type_str)
        except ValueError:
            cost_type = CostType.OTHER

        # ===== PERBAIKAN: gunakan timezone.utc untuk fallback =====
        created_at = None
        if "created_at" in data:
            try:
                created_at = datetime.fromisoformat(data["created_at"])
            except (ValueError, TypeError):
                created_at = datetime.now(UTC)
        else:
            created_at = datetime.now(UTC)

        return cls(
            project_id=UUID(data["project_id"]),
            amount=Decimal(str(data["amount"])),
            currency=data.get("currency", "IDR"),
            cost_type=cost_type,
            description=data.get("description", ""),
            entry_date=date.fromisoformat(data["entry_date"]) if "entry_date" in data else date.today(),
            id=UUID(data["id"]) if "id" in data else uuid4(),
            created_at=created_at,
            created_by=UUID(data["created_by"]) if data.get("created_by") else None,
            metadata=data.get("metadata", {}),
        )

    def with_amount(self, new_amount: Decimal) -> CostEntryVO:
        """Kembalikan salinan dengan amount baru."""
        return CostEntryVO(
            project_id=self.project_id,
            amount=new_amount,
            currency=self.currency,
            cost_type=self.cost_type,
            description=self.description,
            entry_date=self.entry_date,
            id=self.id,
            created_at=self.created_at,
            created_by=self.created_by,
            metadata=self.metadata,
        )

    def with_description(self, new_description: str) -> CostEntryVO:
        """Kembalikan salinan dengan deskripsi baru."""
        return CostEntryVO(
            project_id=self.project_id,
            amount=self.amount,
            currency=self.currency,
            cost_type=self.cost_type,
            description=new_description,
            entry_date=self.entry_date,
            id=self.id,
            created_at=self.created_at,
            created_by=self.created_by,
            metadata=self.metadata,
        )

    def with_cost_type(self, new_cost_type: CostType) -> CostEntryVO:
        """Kembalikan salinan dengan tipe biaya baru."""
        return CostEntryVO(
            project_id=self.project_id,
            amount=self.amount,
            currency=self.currency,
            cost_type=new_cost_type,
            description=self.description,
            entry_date=self.entry_date,
            id=self.id,
            created_at=self.created_at,
            created_by=self.created_by,
            metadata=self.metadata,
        )

    def with_metadata(self, new_metadata: dict[str, Any]) -> CostEntryVO:
        """Kembalikan salinan dengan metadata baru (merged)."""
        merged = self.metadata.copy()
        merged.update(new_metadata)
        return CostEntryVO(
            project_id=self.project_id,
            amount=self.amount,
            currency=self.currency,
            cost_type=self.cost_type,
            description=self.description,
            entry_date=self.entry_date,
            id=self.id,
            created_at=self.created_at,
            created_by=self.created_by,
            metadata=merged,
        )


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "CostEntryVO",
    "CostType",
]
