#!/usr/bin/env python3
"""
Module: ias_16_ppe.py
Layer: 7 - Policy Engine & Standards / IFRS
Responsibility: IAS 16: Property, Plant and Equipment.
               Mendefinisikan aturan untuk pengakuan, pengukuran,
               depresiasi, dan penghentian pengakuan aset tetap.
               Model biaya dan model revaluasi diperbolehkan.

Dependencies:
- standard library (decimal, datetime, logging, dataclass)
- domain.shared_value_objects.money_vo (Money)

Audit: Setiap perubahan aset tetap dictat.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from domain.shared_value_objects.money_vo import Money

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class IAS16MeasurementModel(Enum):
    COST_MODEL = "cost_model"
    REVALUATION_MODEL = "revaluation_model"


class IAS16DepreciationMethod(Enum):
    STRAIGHT_LINE = "straight_line"
    DECLINING_BALANCE = "declining_balance"
    UNITS_OF_PRODUCTION = "units_of_production"


class IAS16AssetClassification(Enum):
    LAND = "land"
    BUILDING = "building"
    MACHINERY = "machinery"
    VEHICLE = "vehicle"
    FURNITURE = "furniture"
    COMPUTER = "computer"
    OTHER = "other"


# === 2. CUSTOM EXCEPTIONS ===


class IAS16Error(Exception):
    pass


class InvalidRevaluationError(IAS16Error):
    pass


# === 3. VALUE OBJECTS ===


@dataclass(frozen=True)
class IAS16RevaluationSurplus:
    amount: Money
    revaluation_date: datetime
    performed_by: str
    effective_date: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": str(self.amount.amount),
            "currency": self.amount.currency,
            "revaluation_date": self.revaluation_date.isoformat(),
            "effective_date": self.effective_date.isoformat(),
            "performed_by": self.performed_by,
        }


# === 4. ENTITIES ===


@dataclass
class IAS16Asset:
    asset_id: UUID
    asset_code: str
    name: str
    classification: IAS16AssetClassification
    acquisition_date: datetime
    cost: Money
    accumulated_depreciation: Money
    accumulated_impairment: Money
    useful_life_years: int
    residual_value: Money
    depreciation_method: IAS16DepreciationMethod
    measurement_model: IAS16MeasurementModel
    revaluation_surplus: IAS16RevaluationSurplus | None = None
    is_active: bool = True

    def __post_init__(self):
        if self.cost.amount <= 0:
            raise ValueError("Cost must be positive")
        if self.useful_life_years <= 0:
            raise ValueError("Useful life must be positive")
        if self.residual_value.amount < 0:
            raise ValueError("Residual value cannot be negative")
        if self.residual_value.amount > self.cost.amount:
            raise ValueError("Residual value cannot exceed cost")

    @property
    def depreciable_amount(self) -> Money:
        return self.cost - self.residual_value

    @property
    def carrying_amount(self) -> Money:
        return self.cost - self.accumulated_depreciation - self.accumulated_impairment

    def annual_depreciation(self) -> Money:
        if self.depreciation_method == IAS16DepreciationMethod.STRAIGHT_LINE:
            amount = self.depreciable_amount.amount / Decimal(self.useful_life_years)
            return Money(amount, self.cost.currency)
        elif self.depreciation_method == IAS16DepreciationMethod.DECLINING_BALANCE:
            rate = Decimal(2) / Decimal(self.useful_life_years)
            amount = self.carrying_amount.amount * rate
            return Money(amount, self.cost.currency)
        else:
            return Money(Decimal(0), self.cost.currency)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "asset_code": self.asset_code,
            "name": self.name,
            "classification": self.classification.value,
            "acquisition_date": self.acquisition_date.isoformat(),
            "cost": str(self.cost.amount),
            "accumulated_depreciation": str(self.accumulated_depreciation.amount),
            "accumulated_impairment": str(self.accumulated_impairment.amount),
            "carrying_amount": str(self.carrying_amount.amount),
            "useful_life_years": self.useful_life_years,
            "residual_value": str(self.residual_value.amount),
            "depreciation_method": self.depreciation_method.value,
            "measurement_model": self.measurement_model.value,
            "is_active": self.is_active,
        }


@dataclass
class IAS16AssetRegister:
    register_id: UUID
    entity_id: UUID
    assets: list[IAS16Asset] = field(default_factory=list)
    revaluation_frequency_years: int = 3

    def add_asset(self, asset: IAS16Asset) -> IAS16AssetRegister:
        return IAS16AssetRegister(
            register_id=self.register_id,
            entity_id=self.entity_id,
            assets=[*self.assets, asset],
            revaluation_frequency_years=self.revaluation_frequency_years,
        )

    def total_carrying_amount(self) -> Money:
        if not self.assets:
            return Money(Decimal(0), "IDR")
        currency = self.assets[0].cost.currency
        total = sum(a.carrying_amount.amount for a in self.assets)
        return Money(total, currency)

    def total_depreciation_ytd(self) -> Money:
        if not self.assets:
            return Money(Decimal(0), "IDR")
        currency = self.assets[0].cost.currency
        total = sum(a.accumulated_depreciation.amount for a in self.assets)
        return Money(total, currency)

    def to_dict(self) -> dict[str, Any]:
        return {
            "register_id": str(self.register_id),
            "entity_id": str(self.entity_id),
            "assets": [a.to_dict() for a in self.assets],
            "total_carrying": str(self.total_carrying_amount().amount),
            "revaluation_frequency": self.revaluation_frequency_years,
        }


# === 5. DOMAIN SERVICES ===


class IAS16AssetService:
    @staticmethod
    def calculate_depreciation_for_period(
        asset: IAS16Asset, period_start: datetime, period_end: datetime
    ) -> Money:
        annual = asset.annual_depreciation()
        days_in_period = (period_end - period_start).days
        if days_in_period <= 0:
            return Money(Decimal(0), asset.cost.currency)
        pro_rated = annual.amount * Decimal(days_in_period) / Decimal(365)
        return Money(pro_rated, asset.cost.currency)

    @staticmethod
    def revalue_asset(
        asset: IAS16Asset, fair_value: Money, valuation_date: datetime, performed_by: str
    ) -> IAS16Asset:
        if asset.measurement_model != IAS16MeasurementModel.REVALUATION_MODEL:
            raise InvalidRevaluationError("Asset not using revaluation model")
        old_carrying = asset.carrying_amount
        revaluation_surplus = fair_value - old_carrying
        if revaluation_surplus.amount > 0:
            new_surplus = IAS16RevaluationSurplus(
                revaluation_surplus, valuation_date, performed_by, valuation_date
            )
            return IAS16Asset(
                asset_id=asset.asset_id,
                asset_code=asset.asset_code,
                name=asset.name,
                classification=asset.classification,
                acquisition_date=asset.acquisition_date,
                cost=fair_value,
                accumulated_depreciation=Money(Decimal(0), fair_value.currency),
                accumulated_impairment=asset.accumulated_impairment,
                useful_life_years=asset.useful_life_years,
                residual_value=asset.residual_value,
                depreciation_method=asset.depreciation_method,
                measurement_model=asset.measurement_model,
                revaluation_surplus=new_surplus,
                is_active=asset.is_active,
            )
        else:
            new_impairment = asset.accumulated_impairment + revaluation_surplus.abs()
            return IAS16Asset(
                asset_id=asset.asset_id,
                asset_code=asset.asset_code,
                name=asset.name,
                classification=asset.classification,
                acquisition_date=asset.acquisition_date,
                cost=asset.cost,
                accumulated_depreciation=asset.accumulated_depreciation,
                accumulated_impairment=new_impairment,
                useful_life_years=asset.useful_life_years,
                residual_value=asset.residual_value,
                depreciation_method=asset.depreciation_method,
                measurement_model=asset.measurement_model,
                revaluation_surplus=asset.revaluation_surplus,
                is_active=asset.is_active,
            )


# === 6. IAS 16 VALIDATION RESULT ===


@dataclass
class IAS16ValidationResult:
    is_compliant: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_compliant = False

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)

    def merge(self, other: IAS16ValidationResult) -> IAS16ValidationResult:
        return IAS16ValidationResult(
            is_compliant=self.is_compliant and other.is_compliant,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
        )


# === 7. IAS 16 RULES ===


class IAS16Rules:
    @staticmethod
    def validate_useful_life_review(
        current_useful_life: int, remaining_useful_life: int, has_changed: bool
    ) -> IAS16ValidationResult:
        result = IAS16ValidationResult(is_compliant=True)
        if has_changed:
            result.add_warning("Useful life changed; remaining should be re-assessed")
        return result

    @staticmethod
    def validate_revaluation_frequency(
        last_revaluation_date: datetime | None, current_date: datetime, frequency_years: int
    ) -> IAS16ValidationResult:
        result = IAS16ValidationResult(is_compliant=True)
        if last_revaluation_date:
            years_diff = (current_date - last_revaluation_date).days / 365.25
            if years_diff > frequency_years:
                result.add_warning(
                    f"Revaluation overdue by {years_diff - frequency_years:.1f} years"
                )
        return result


# === 8. IAS 16 VALIDATOR ===


class IAS16Validator:
    def __init__(self):
        self._rules = IAS16Rules()

    def validate_asset(self, asset: IAS16Asset) -> IAS16ValidationResult:
        result = IAS16ValidationResult(is_compliant=True)
        if asset.residual_value.amount > asset.cost.amount * Decimal("0.1"):
            result.add_warning(
                f"Residual value {asset.residual_value.amount} is high relative to cost"
            )
        if asset.useful_life_years > 50:
            result.add_warning(
                f"Useful life {asset.useful_life_years} years exceeds typical maximum"
            )
        return result

    def get_requirements_summary(self) -> dict[str, Any]:
        return {
            "initial_measurement": "Cost includes purchase price, import duties, direct attributable costs",
            "subsequent_measurement": "Cost model or revaluation model",
            "depreciation": "Systematic allocation of depreciable amount over useful life",
            "depreciation_methods": "Straight-line, declining balance, units of production",
            "revaluation": "Must be performed regularly; surplus in OCI, deficit in P&L",
            "derecognition": "When disposed or no future economic benefits expected",
        }


# === 9. SINGLETON ACCESSOR ===

_ias16_validator_instance: IAS16Validator | None = None


def get_ias16_validator() -> IAS16Validator:
    global _ias16_validator_instance
    if _ias16_validator_instance is None:
        _ias16_validator_instance = IAS16Validator()
    return _ias16_validator_instance


# === 10. ALIAS UNTUK KOMPATIBILITAS ===
IAS16PPEMeasurement = IAS16MeasurementModel


# === 11. EXPORTS ===

__all__ = [
    "IAS16Asset",
    "IAS16AssetClassification",
    "IAS16AssetRegister",
    "IAS16AssetService",
    "IAS16DepreciationMethod",
    "IAS16MeasurementModel",
    "IAS16PPEMeasurement",
    "IAS16RevaluationSurplus",
    "IAS16Rules",
    "IAS16ValidationResult",
    "IAS16Validator",
    "get_ias16_validator",
]
