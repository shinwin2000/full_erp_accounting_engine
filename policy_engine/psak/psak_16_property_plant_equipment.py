#!/usr/bin/env python3
"""
Module: psak_16_property_plant_equipment.py
Layer: 7 - Policy Engine & Standards / PSAK
Responsibility: PSAK 16: Aset Tetap.
               Mendefinisikan aturan untuk pengakuan, pengukuran, depresiasi,
               dan penghentian aset tetap sesuai PSAK 16 / IAS 16.

Dependencies:
- standard library (decimal, datetime, logging, dataclass)
- domain.fixed_asset.depreciation_schedule_engine (DepreciationMethod)

Audit: Setiap pelanggaran PSAK 16 dictat.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class DepreciationMethodPSAK(Enum):
    """Metode depresiasi yang diizinkan PSAK 16."""

    STRAIGHT_LINE = "straight_line"  # Garis lurus
    DECLINING_BALANCE = "declining_balance"  # Saldo menurun
    UNITS_OF_PRODUCTION = "units_of_production"  # Unit produksi


class RevaluationModel(Enum):
    """Model revaluasi aset tetap."""

    COST_MODEL = "cost_model"  # Model biaya
    REVALUATION_MODEL = "revaluation_model"  # Model revaluasi


# === 2. ASSET VALUATION ===


@dataclass
class AssetValuation:
    """Hasil penilaian aset tetap."""

    asset_id: UUID
    asset_code: str
    asset_name: str
    cost: Decimal
    accumulated_depreciation: Decimal
    carrying_amount: Decimal
    revaluation_surplus: Decimal = Decimal(0)
    fair_value: Decimal | None = None

    @property
    def nbv(self) -> Decimal:
        return self.carrying_amount

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "cost": str(self.cost),
            "accumulated_depreciation": str(self.accumulated_depreciation),
            "carrying_amount": str(self.carrying_amount),
            "revaluation_surplus": str(self.revaluation_surplus),
            "fair_value": str(self.fair_value) if self.fair_value else None,
        }


# === 3. DEPRECIATION SCHEDULE ===


@dataclass
class DepreciationSchedule:
    """Jadwal depresiasi aset."""

    asset_id: UUID
    asset_code: str
    asset_name: str
    useful_life_years: int
    salvage_value: Decimal
    depreciation_method: DepreciationMethodPSAK
    annual_depreciation: Decimal
    total_depreciable_amount: Decimal
    remaining_useful_life: int
    entries: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "useful_life_years": self.useful_life_years,
            "salvage_value": str(self.salvage_value),
            "depreciation_method": self.depreciation_method.value,
            "annual_depreciation": str(self.annual_depreciation),
            "total_depreciable_amount": str(self.total_depreciable_amount),
            "remaining_useful_life": self.remaining_useful_life,
            "entries": self.entries,
        }


# === 4. PSAK 16 VALIDATION RESULT ===


@dataclass
class PSAK16ValidationResult:
    """Hasil validasi PSAK 16."""

    is_compliant: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_compliant = False

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)

    def merge(self, other: PSAK16ValidationResult) -> PSAK16ValidationResult:
        return PSAK16ValidationResult(
            is_compliant=self.is_compliant and other.is_compliant,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
        )


# === 5. PSAK 16 RULES ===


class PSAK16Rules:
    """
    Aturan-aturan sesuai PSAK 16.

    PSAK 16 mengatur tentang perlakuan akuntansi untuk aset tetap,
    termasuk pengakuan, penentuan jumlah tercatat, depresiasi, dan
    penurunan nilai.
    """

    # Komponen biaya perolehan aset tetap
    COST_COMPONENTS = [
        "purchase_price",
        "import_duties",
        "non_refundable_taxes",
        "delivery_costs",
        "installation_costs",
        "professional_fees",
    ]

    # Metode depresiasi yang diizinkan
    ALLOWED_DEPRECIATION_METHODS = [
        DepreciationMethodPSAK.STRAIGHT_LINE,
        DepreciationMethodPSAK.DECLINING_BALANCE,
        DepreciationMethodPSAK.UNITS_OF_PRODUCTION,
    ]

    @staticmethod
    def validate_depreciation_method(method: DepreciationMethodPSAK) -> PSAK16ValidationResult:
        """
        Memvalidasi metode depresiasi.

        Aturan: Metode harus sesuai dengan pola manfaat ekonomi aset.
        """
        result = PSAK16ValidationResult(is_compliant=True)

        if method not in PSAK16Rules.ALLOWED_DEPRECIATION_METHODS:
            result.add_error(f"Depreciation method '{method.value}' not recognized")

        return result

    @staticmethod
    def calculate_depreciation(
        cost: Decimal,
        salvage_value: Decimal,
        useful_life_years: int,
        method: DepreciationMethodPSAK,
        current_year: int,
    ) -> Decimal:
        """
        Menghitung depresiasi tahunan.

        Returns:
            Depresiasi tahunan
        """
        depreciable_amount = cost - salvage_value

        if method == DepreciationMethodPSAK.STRAIGHT_LINE:
            return depreciable_amount / Decimal(useful_life_years)
        elif method == DepreciationMethodPSAK.DECLINING_BALANCE:
            rate = Decimal(2) / Decimal(useful_life_years)
            # Simplified: assume first year full rate
            return cost * rate
        else:  # UNITS_OF_PRODUCTION
            # Requires total units estimate
            return Decimal(0)

    @staticmethod
    def validate_useful_life(
        useful_life_years: int,
        asset_category: str,
    ) -> PSAK16ValidationResult:
        """
        Memvalidasi estimasi masa manfaat.

        Aturan: Masa manfaat harus realistis berdasarkan ekspektasi penggunaan.
        """
        result = PSAK16ValidationResult(is_compliant=True)

        if useful_life_years <= 0:
            result.add_error(f"Useful life must be positive: {useful_life_years}")

        # Minimum useful life untuk kategori tertentu (contoh)
        min_life = {
            "building": 20,
            "machinery": 5,
            "vehicle": 4,
            "computer": 2,
        }

        min_required = min_life.get(asset_category, 1)
        if useful_life_years < min_required:
            result.add_warning(
                f"Useful life of {useful_life_years} years for {asset_category} is shorter than typical range"
            )

        return result

    @staticmethod
    def validate_salvage_value(salvage_value: Decimal, cost: Decimal) -> PSAK16ValidationResult:
        """
        Memvalidasi nilai residu.

        Aturan: Nilai residu tidak boleh melebihi biaya perolehan.
        """
        result = PSAK16ValidationResult(is_compliant=True)

        if salvage_value < 0:
            result.add_error(f"Salvage value cannot be negative: {salvage_value}")

        if salvage_value > cost:
            result.add_error(f"Salvage value {salvage_value} exceeds cost {cost}")

        return result

    @staticmethod
    def validate_revaluation_model(
        fair_value: Decimal,
        carrying_amount: Decimal,
        has_appraisal: bool,
    ) -> PSAK16ValidationResult:
        """
        Memvalidasi revaluasi aset.

        Aturan: Revaluasi harus dilakukan dengan frekuensi yang teratur
        dan berdasarkan nilai wajar.
        """
        result = PSAK16ValidationResult(is_compliant=True)

        if not has_appraisal:
            result.add_error("Revaluation requires independent appraisal")

        if fair_value <= 0:
            result.add_error(f"Fair value must be positive: {fair_value}")

        return result

    @staticmethod
    def validate_impairment(
        carrying_amount: Decimal,
        recoverable_amount: Decimal,
    ) -> tuple[Decimal, bool]:
        """
        Memvalidasi penurunan nilai aset.

        Returns:
            (impairment_loss, has_impairment)
        """
        if carrying_amount > recoverable_amount:
            loss = carrying_amount - recoverable_amount
            return loss, True
        return Decimal(0), False


# === 6. PSAK 16 VALIDATOR ===


class PSAK16Validator:
    """
    Validator untuk PSAK 16.

    Business context: Memastikan aset tetap diakui, diukur, dan
    disajikan sesuai dengan persyaratan PSAK 16.
    """

    def __init__(self):
        self._rules = PSAK16Rules()

    def validate_asset_recognition(
        self,
        cost: Decimal,
        useful_life_years: int,
        asset_category: str,
        salvage_value: Decimal = Decimal(0),
        depreciation_method: DepreciationMethodPSAK = DepreciationMethodPSAK.STRAIGHT_LINE,
    ) -> PSAK16ValidationResult:
        """
        Memvalidasi pengakuan aset tetap baru.

        Returns:
            PSAK16ValidationResult
        """
        result = PSAK16ValidationResult(is_compliant=True)

        # 1. Validasi masa manfaat
        result.merge(self._rules.validate_useful_life(useful_life_years, asset_category))

        # 2. Validasi nilai residu
        result.merge(self._rules.validate_salvage_value(salvage_value, cost))

        # 3. Validasi metode depresiasi
        result.merge(self._rules.validate_depreciation_method(depreciation_method))

        return result

    def calculate_asset_valuation(
        self,
        asset_id: UUID,
        asset_code: str,
        asset_name: str,
        cost: Decimal,
        accumulated_depreciation: Decimal,
        fair_value: Decimal | None = None,
        revaluation_surplus: Decimal = Decimal(0),
    ) -> AssetValuation:
        """
        Menghitung nilai tercatat aset.

        Returns:
            AssetValuation
        """
        carrying_amount = cost - accumulated_depreciation

        if fair_value and revaluation_surplus:
            carrying_amount = fair_value

        return AssetValuation(
            asset_id=asset_id,
            asset_code=asset_code,
            asset_name=asset_name,
            cost=cost,
            accumulated_depreciation=accumulated_depreciation,
            carrying_amount=carrying_amount,
            revaluation_surplus=revaluation_surplus,
            fair_value=fair_value,
        )

    def generate_depreciation_schedule(
        self,
        asset_id: UUID,
        asset_code: str,
        asset_name: str,
        cost: Decimal,
        salvage_value: Decimal,
        useful_life_years: int,
        depreciation_method: DepreciationMethodPSAK,
        acquisition_date: datetime,
    ) -> DepreciationSchedule:
        """
        Menghasilkan jadwal depresiasi aset.

        Returns:
            DepreciationSchedule
        """
        depreciable_amount = cost - salvage_value
        annual_depreciation = depreciable_amount / Decimal(useful_life_years)

        entries = []
        current_date = acquisition_date
        remaining_nbv = cost
        current_year = 1

        while current_year <= useful_life_years and remaining_nbv > salvage_value:
            year_end = current_date.replace(year=current_date.year + 1)
            depreciation = annual_depreciation

            if remaining_nbv - depreciation < salvage_value:
                depreciation = remaining_nbv - salvage_value

            entries.append(
                {
                    "year": current_year,
                    "period_start": current_date.isoformat(),
                    "period_end": year_end.isoformat(),
                    "depreciation_amount": str(depreciation),
                    "accumulated_depreciation": str(annual_depreciation * current_year),
                    "ending_nbv": str(remaining_nbv - depreciation),
                }
            )

            remaining_nbv -= depreciation
            current_date = year_end
            current_year += 1

        return DepreciationSchedule(
            asset_id=asset_id,
            asset_code=asset_code,
            asset_name=asset_name,
            useful_life_years=useful_life_years,
            salvage_value=salvage_value,
            depreciation_method=depreciation_method,
            annual_depreciation=annual_depreciation,
            total_depreciable_amount=depreciable_amount,
            remaining_useful_life=useful_life_years,
            entries=entries,
        )

    def validate_derecognition(
        self,
        asset: AssetValuation,
        proceeds: Decimal,
        disposal_cost: Decimal = Decimal(0),
    ) -> PSAK16ValidationResult:
        """
        Memvalidasi penghentian pengakuan aset.

        Returns:
            PSAK16ValidationResult
        """
        result = PSAK16ValidationResult(is_compliant=True)

        net_proceeds = proceeds - disposal_cost
        gain_loss = net_proceeds - asset.carrying_amount

        if gain_loss > 0:
            result.add_warning(f"Gain on disposal: {gain_loss}")
        elif gain_loss < 0:
            result.add_warning(f"Loss on disposal: {abs(gain_loss)}")

        return result

    def get_requirements_summary(self) -> dict[str, Any]:
        """Mendapatkan ringkasan persyaratan PSAK 16."""
        return {
            "cost_components": self._rules.COST_COMPONENTS,
            "allowed_depreciation_methods": [
                m.value for m in self._rules.ALLOWED_DEPRECIATION_METHODS
            ],
            "revaluation_models": [m.value for m in RevaluationModel],
        }


# === 7. SINGLETON ACCESSOR ===

_psak16_validator_instance: PSAK16Validator | None = None


def get_psak16_validator() -> PSAK16Validator:
    """Mendapatkan instance singleton PSAK16Validator."""
    global _psak16_validator_instance
    if _psak16_validator_instance is None:
        _psak16_validator_instance = PSAK16Validator()
    return _psak16_validator_instance


# === 8. EXPORTS ===

__all__ = [
    "AssetValuation",
    "DepreciationMethodPSAK",
    "DepreciationSchedule",
    "PSAK16Rules",
    "PSAK16ValidationResult",
    "PSAK16Validator",
    "RevaluationModel",
    "get_psak16_validator",
]
