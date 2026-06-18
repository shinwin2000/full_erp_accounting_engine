# intangible_asset_request.py - Hardened version with complete implementation

#!/usr/bin/env python3

"""
Module: intangible_asset_request.py
Layer: Application / DTO Objects
Responsibility: DTO for intangible asset operations.

Fitur:
- Create intangible asset
- Amortization run
- Impairment testing
- Asset disposal
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID


@dataclass(kw_only=True)
class CreateIntangibleAssetRequest:
    """Request DTO untuk membuat intangible asset baru."""

    legal_entity_id: UUID
    asset_code: str
    asset_name: str
    acquisition_date: date
    acquisition_cost: Decimal
    residual_value: Decimal
    useful_life_years: int
    asset_type: str  # e.g., "PATENT", "LICENSE", "SOFTWARE", "GOODWILL", "TRADEMARK", "COPYRIGHT"
    amortization_method: str  # "STRAIGHT_LINE", "DECLINING_BALANCE", "DOUBLE_DECLINING"
    description: str | None = None
    supplier_id: UUID | None = None
    is_active: bool = True

    def __post_init__(self) -> None:
        if not self.asset_code or len(self.asset_code.strip()) < 3:
            raise ValueError("Asset code must be at least 3 characters")
        if not self.asset_name:
            raise ValueError("Asset name is required")
        if self.acquisition_cost <= 0:
            raise ValueError(f"Acquisition cost must be positive: {self.acquisition_cost}")
        if self.residual_value < 0:
            raise ValueError(f"Residual value cannot be negative: {self.residual_value}")
        if self.residual_value > self.acquisition_cost:
            raise ValueError("Residual value cannot exceed acquisition cost")
        if self.useful_life_years < 1:
            raise ValueError(f"Useful life must be at least 1 year: {self.useful_life_years}")
        valid_types = [
            "PATENT",
            "LICENSE",
            "SOFTWARE",
            "GOODWILL",
            "TRADEMARK",
            "COPYRIGHT",
            "FRANCHISE",
        ]
        if self.asset_type.upper() not in valid_types:
            raise ValueError(f"Invalid asset_type: {self.asset_type}. Must be one of {valid_types}")
        valid_methods = ["STRAIGHT_LINE", "DECLINING_BALANCE", "DOUBLE_DECLINING", "SUM_OF_YEARS"]
        if self.amortization_method.upper() not in valid_methods:
            raise ValueError(f"Invalid amortization_method: {self.amortization_method}")

    @property
    def amortizable_amount(self) -> Decimal:
        """Calculate amortizable amount."""
        return self.acquisition_cost - self.residual_value

    @property
    def annual_amortization(self) -> Decimal:
        """Calculate annual amortization for straight-line method."""
        if self.amortization_method.upper() == "STRAIGHT_LINE" and self.useful_life_years > 0:
            return self.amortizable_amount / Decimal(self.useful_life_years)
        return Decimal(0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "acquisition_date": self.acquisition_date.isoformat(),
            "acquisition_cost": str(self.acquisition_cost),
            "residual_value": str(self.residual_value),
            "useful_life_years": self.useful_life_years,
            "asset_type": self.asset_type,
            "amortization_method": self.amortization_method,
            "description": self.description,
            "supplier_id": str(self.supplier_id) if self.supplier_id else None,
            "is_active": self.is_active,
            "amortizable_amount": str(self.amortizable_amount),
            "annual_amortization": str(self.annual_amortization),
        }


@dataclass(kw_only=True)
class AmortizeRequest:
    """Request DTO untuk menjalankan amortisasi."""

    legal_entity_id: UUID
    period_date: date
    period_id: UUID
    asset_ids: list[UUID] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "period_date": self.period_date.isoformat(),
            "period_id": str(self.period_id),
            "asset_ids": [str(aid) for aid in self.asset_ids] if self.asset_ids else None,
        }


@dataclass(kw_only=True)
class ImpairmentTestRequest:
    """Request DTO untuk impairment testing aset tidak berwujud."""

    asset_id: UUID
    test_date: date
    recoverable_amount: Decimal
    reason: str | None = None
    legal_entity_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.recoverable_amount < 0:
            raise ValueError(f"Recoverable amount cannot be negative: {self.recoverable_amount}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "test_date": self.test_date.isoformat(),
            "recoverable_amount": str(self.recoverable_amount),
            "reason": self.reason,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
        }


@dataclass(kw_only=True)
class DisposeAssetRequest:
    """Request DTO untuk disposal aset tidak berwujud."""

    asset_id: UUID
    disposal_date: date
    disposal_amount: Decimal
    reason: str
    legal_entity_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.disposal_amount < 0:
            raise ValueError(f"Disposal amount cannot be negative: {self.disposal_amount}")
        if not self.reason or len(self.reason.strip()) < 5:
            raise ValueError("Reason must be at least 5 characters")

    @property
    def gain_loss(self) -> Decimal:
        """Placeholder - actual gain/loss depends on book value."""
        return Decimal(0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "disposal_date": self.disposal_date.isoformat(),
            "disposal_amount": str(self.disposal_amount),
            "reason": self.reason,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
        }


__all__ = [
    "AmortizeRequest",
    "CreateIntangibleAssetRequest",
    "DisposeAssetRequest",
    "ImpairmentTestRequest",
]
