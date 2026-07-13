# intangible_asset_request.py - Complete implementation with all required DTOs

#!/usr/bin/env python3

"""
Module: intangible_asset_request.py
Layer: Application / DTO Objects
Responsibility: DTO untuk operasi aset tidak berwujud (intangible asset).

Fitur:
- Create intangible asset
- Update intangible asset
- Amortization run
- Revaluation
- Impairment testing
- Asset disposal
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

# ============================================================================
# 1. CREATE REQUEST
# ============================================================================

@dataclass(kw_only=True)
class IntangibleAssetCreateRequest:
    """
    Request DTO untuk membuat intangible asset baru.
    Nama ini digunakan oleh router (fastapi_intangible_asset_router.py).
    """
    legal_entity_id: UUID
    asset_code: str
    asset_name: str
    acquisition_date: date
    acquisition_cost: Decimal
    residual_value: Decimal
    useful_life_years: int
    asset_type: str  # PATENT, LICENSE, SOFTWARE, GOODWILL, TRADEMARK, COPYRIGHT, FRANCHISE
    amortization_method: str  # STRAIGHT_LINE, DECLINING_BALANCE, DOUBLE_DECLINING, SUM_OF_YEARS
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
            "PATENT", "LICENSE", "SOFTWARE", "GOODWILL",
            "TRADEMARK", "COPYRIGHT", "FRANCHISE"
        ]
        if self.asset_type.upper() not in valid_types:
            raise ValueError(f"Invalid asset_type: {self.asset_type}. Must be one of {valid_types}")
        valid_methods = ["STRAIGHT_LINE", "DECLINING_BALANCE", "DOUBLE_DECLINING", "SUM_OF_YEARS"]
        if self.amortization_method.upper() not in valid_methods:
            raise ValueError(f"Invalid amortization_method: {self.amortization_method}")

    @property
    def amortizable_amount(self) -> Decimal:
        return self.acquisition_cost - self.residual_value

    @property
    def annual_amortization(self) -> Decimal:
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


# ============================================================================
# 2. UPDATE REQUEST
# ============================================================================

@dataclass(kw_only=True)
class IntangibleAssetUpdateRequest:
    """
    Request DTO untuk memperbarui intangible asset yang sudah ada.
    Semua field opsional kecuali id.
    """
    asset_id: UUID
    legal_entity_id: UUID | None = None
    asset_code: str | None = None
    asset_name: str | None = None
    acquisition_date: date | None = None
    acquisition_cost: Decimal | None = None
    residual_value: Decimal | None = None
    useful_life_years: int | None = None
    asset_type: str | None = None
    amortization_method: str | None = None
    description: str | None = None
    supplier_id: UUID | None = None
    is_active: bool | None = None

    def __post_init__(self) -> None:
        if self.asset_code is not None and len(self.asset_code.strip()) < 3:
            raise ValueError("Asset code must be at least 3 characters")
        if self.asset_name is not None and not self.asset_name:
            raise ValueError("Asset name cannot be empty")
        if self.acquisition_cost is not None and self.acquisition_cost <= 0:
            raise ValueError(f"Acquisition cost must be positive: {self.acquisition_cost}")
        if self.residual_value is not None and self.residual_value < 0:
            raise ValueError(f"Residual value cannot be negative: {self.residual_value}")
        if self.useful_life_years is not None and self.useful_life_years < 1:
            raise ValueError(f"Useful life must be at least 1 year: {self.useful_life_years}")
        if self.asset_type is not None:
            valid_types = [
                "PATENT", "LICENSE", "SOFTWARE", "GOODWILL",
                "TRADEMARK", "COPYRIGHT", "FRANCHISE"
            ]
            if self.asset_type.upper() not in valid_types:
                raise ValueError(f"Invalid asset_type: {self.asset_type}. Must be one of {valid_types}")
        if self.amortization_method is not None:
            valid_methods = ["STRAIGHT_LINE", "DECLINING_BALANCE", "DOUBLE_DECLINING", "SUM_OF_YEARS"]
            if self.amortization_method.upper() not in valid_methods:
                raise ValueError(f"Invalid amortization_method: {self.amortization_method}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "acquisition_date": self.acquisition_date.isoformat() if self.acquisition_date else None,
            "acquisition_cost": str(self.acquisition_cost) if self.acquisition_cost is not None else None,
            "residual_value": str(self.residual_value) if self.residual_value is not None else None,
            "useful_life_years": self.useful_life_years,
            "asset_type": self.asset_type,
            "amortization_method": self.amortization_method,
            "description": self.description,
            "supplier_id": str(self.supplier_id) if self.supplier_id else None,
            "is_active": self.is_active,
        }


# ============================================================================
# 3. AMORTIZATION RUN REQUEST
# ============================================================================

@dataclass(kw_only=True)
class AmortizationRunRequest:
    """
    Request DTO untuk menjalankan amortisasi untuk periode tertentu.
    """
    legal_entity_id: UUID
    period_id: UUID
    period_date: date
    asset_ids: list[UUID] | None = None  # Jika None, semua aset aktif

    def __post_init__(self) -> None:
        if not self.legal_entity_id:
            raise ValueError("legal_entity_id is required")
        if not self.period_id:
            raise ValueError("period_id is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "period_id": str(self.period_id),
            "period_date": self.period_date.isoformat(),
            "asset_ids": [str(aid) for aid in self.asset_ids] if self.asset_ids else None,
        }


# ============================================================================
# 4. REVALUATION REQUEST
# ============================================================================

@dataclass(kw_only=True)
class RevaluationRequest:
    """
    Request DTO untuk revaluasi intangible asset.
    """
    asset_id: UUID
    revaluation_date: date
    new_fair_value: Decimal
    reason: str | None = None
    legal_entity_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.new_fair_value < 0:
            raise ValueError(f"Fair value cannot be negative: {self.new_fair_value}")
        if not self.reason:
            self.reason = "Revaluation based on market assessment"

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "revaluation_date": self.revaluation_date.isoformat(),
            "new_fair_value": str(self.new_fair_value),
            "reason": self.reason,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
        }


# ============================================================================
# 5. DISPOSAL REQUEST
# ============================================================================

@dataclass(kw_only=True)
class DisposalRequest:
    """
    Request DTO untuk disposal intangible asset.
    """
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
        # Placeholder - actual gain/loss depends on book value
        return Decimal(0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "disposal_date": self.disposal_date.isoformat(),
            "disposal_amount": str(self.disposal_amount),
            "reason": self.reason,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
        }


# ============================================================================
# 6. ALIASES FOR BACKWARD COMPATIBILITY
# ============================================================================

# Alias to match old names if needed
CreateIntangibleAssetRequest = IntangibleAssetCreateRequest
AmortizeRequest = AmortizationRunRequest
DisposeAssetRequest = DisposalRequest

# Juga export kelas lama untuk kompatibilitas
# (sudah ada di file asli, kita pertahankan)


# ============================================================================
# 7. IMPAIRMENT TEST REQUEST (tetap dipertahankan)
# ============================================================================

@dataclass(kw_only=True)
class ImpairmentTestRequest:
    """
    Request DTO untuk impairment testing aset tidak berwujud.
    """
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


# ============================================================================
# 8. EXPORT ALL
# ============================================================================

__all__ = [
    # New names used by router
    "IntangibleAssetCreateRequest",
    "IntangibleAssetUpdateRequest",
    "AmortizationRunRequest",
    "RevaluationRequest",
    "DisposalRequest",
    # Legacy/backward compatibility
    "CreateIntangibleAssetRequest",
    "AmortizeRequest",
    "DisposeAssetRequest",
    "ImpairmentTestRequest",
]
